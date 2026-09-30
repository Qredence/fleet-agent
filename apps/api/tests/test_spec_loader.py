"""End-to-end tests for the declarative spec layer.

Every test is deterministic and offline: LMs are DummyLM subclasses with
scripted per-signature answers, and specs are written into ``tmp_path``.
"""

from __future__ import annotations

import json
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

import dspy
import pytest
from dspy.utils.dummies import DummyLM

from app.agent.spec import (
    AgentSpec,
    Fanout,
    SpecError,
    ToolRegistry,
    load_spec,
)
from app.agent.spec.fingerprint import canonical_spec, structure_hash, verify_state
from app.agent.spec.loader import build_program, build_signature, read_markdown
from app.agent.spec.schema import SignatureSpec
from app.agent.spec.types import (
    BestOfN,
    ChainOfThought,
    Predict,
    React,
    Refine,
    Sequential,
)

POLICY_BODY = """# Researcher policy

Answer from evidence, not from memory.

## Evidence discipline

- Gather evidence with tools before you make a factual claim.
- Name the document ids you used.
"""

ROUTE_BODY = """# Route request

Choose the narrowest profile that can answer the request."""

BRIEF_BODY = """# Evidence brief

Search the corpus with a tool, then read at most one document.

Report only what a tool observation returned."""

RISK_BODY = """# Risk review

Review the evidence for risk and name one flag per risk."""

MARKET_BODY = """# Market review

Describe the user-facing impact in two sentences."""

COST_BODY = """# Cost review

Name the largest cost driver visible in the evidence."""

FINAL_BODY = """# Final answer

Answer the request from the evidence and cite a document id."""

FILES = {
    "policy.md": f"---\nagent: researcher\nrole: shared policy\n---\n{POLICY_BODY}",
    "prompts/route.md": ROUTE_BODY,
    "prompts/brief.md": (
        "---\nfields:\n"
        '  evidence: "One bounded evidence line per tool observation."\n'
        "---\n" + BRIEF_BODY
    ),
    "prompts/risk.md": RISK_BODY,
    "prompts/market.md": MARKET_BODY,
    "prompts/cost.md": COST_BODY,
    "prompts/final.md": FINAL_BODY,
}

SPEC_YAML = """agent: researcher
version: 1
root: researcher
policy_file: policy.md

signatures:
  - name: route_request
    instructions_file: prompts/route.md
    inputs:
      - {name: user_request, type: str, description: "The user's request."}
    outputs:
      - {name: route, type: str, description: "One of: corpus, mixed."}
      - {name: rationale, type: str, description: "One line justification."}

  - name: evidence_brief
    instructions_file: prompts/brief.md
    inherit_policy: true
    inputs:
      - {name: user_request, type: str, description: "The user's request."}
      - {name: route, type: str, description: "Route chosen by the router step."}
    outputs:
      - {name: evidence, type: "list[str]", description: "Evidence lines."}
      - {name: gaps, type: "list[str]", description: "What evidence cannot answer."}

  - name: risk_review
    instructions_file: prompts/risk.md
    inputs:
      - {name: evidence, type: "list[str]", description: "The evidence to review."}
      - {name: gaps, type: "list[str]", description: "Known holes in the evidence."}
    outputs:
      - {name: risk_view, type: str, description: "Risk assessment."}
      - {name: risk_flags, type: "list[str]", description: "Short flag names."}

  - name: market_review
    instructions_file: prompts/market.md
    inputs:
      - {name: evidence, type: "list[str]", description: "The evidence to review."}
    outputs:
      - {name: market_view, type: str, description: "User-facing impact."}

  - name: cost_review
    instructions_file: prompts/cost.md
    inputs:
      - {name: evidence, type: "list[str]", description: "The evidence to review."}
    outputs:
      - {name: cost_view, type: str, description: "Largest cost driver."}

  - name: final_answer
    instructions_file: prompts/final.md
    inputs:
      - {name: user_request, type: str, description: "The user's request."}
      - {name: evidence, type: "list[str]", description: "Gathered evidence."}
      - {name: risk_view, type: str, description: "Risk reviewer output."}
      - {name: market_view, type: str, description: "Market reviewer output."}
      - {name: cost_view, type: str, description: "Cost reviewer output."}
    outputs:
      - {name: answer, type: str, description: "Direct final answer."}
      - {name: process_summary, type: str, description: "Summary of the approach."}

modules:
  researcher: {type: sequential, steps: [route, gather, reviews, synthesize]}
  route: {type: predict, signature: route_request}
  gather:
    type: react
    signature: evidence_brief
    tools: [corpus_search, read_doc]
    max_iters: 3
  reviews: {type: fanout, branches: [risk, market, cost]}
  risk: {type: chain_of_thought, signature: risk_review}
  market: {type: predict, signature: market_review}
  cost: {type: refine, signature: cost_review, n: 2, reward: evidence_reward}
  synthesize:
    type: best_of_n
    signature: final_answer
    n: 2
    reward: evidence_reward
"""

CORPUS = {
    "doc://gepa": "GEPA rewrites the instructions of each named predictor path.",
    "doc://react": "ReActV2 interleaves a reasoning trace with tool calls.",
}


def corpus_search(query: str, k: int = 3) -> list[str]:
    """Search the evidence corpus and return matching document ids, best first."""
    words = {word.strip(".,:;").lower() for word in query.split() if len(word) > 3}
    scored = []
    for doc, text in CORPUS.items():
        hits = sum(1 for word in words if word in text.lower())
        scored.append((hits, doc))
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [doc for hits, doc in scored[:k] if hits > 0]


def read_doc(doc_id: str) -> str:
    """Return the full text of one corpus document, selected by document id."""
    if doc_id not in CORPUS:
        raise KeyError(f"unknown doc id: {doc_id}")
    return CORPUS[doc_id]


def nonempty_reward(args: dict[str, Any], pred: Any) -> float:
    """1.0 when the prediction has at least one non-empty output."""
    values = [
        value for value in pred.toDict().values() if value not in (None, "", [], {})
    ]
    return 1.0 if values else 0.0


def evidence_reward(args: dict[str, Any], pred: Any) -> float:
    """1.0 when an output names a corpus document id."""
    text = " ".join(str(value) for value in pred.toDict().values())
    return 1.0 if "doc://" in text else 0.0


TOOLS = {"corpus_search": corpus_search, "read_doc": read_doc}
REWARDS = {"evidence_reward": evidence_reward, "nonempty_reward": nonempty_reward}


def load(path: Path) -> AgentSpec:
    """Validate one spec path against the fixture tools and rewards."""
    return load_spec(path, tools=TOOLS, rewards=REWARDS)


def build(spec_path: Path, yaml_text: str = SPEC_YAML) -> Predict:
    """Write ``yaml_text`` next to ``spec_path`` and build its DSPy program."""
    spec = load(write_spec(spec_path.parent, yaml_text))
    return build_program(spec, tools=TOOLS, rewards=REWARDS)


def write_spec(root: Path, yaml_text: str = SPEC_YAML) -> Path:
    """Write the researcher spec and its prompt files under ``root``."""
    for name, body in FILES.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    path = root / "researcher.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    return path


@pytest.fixture()
def spec_path(tmp_path: Path) -> Path:
    return write_spec(tmp_path)


@pytest.fixture()
def spec(spec_path: Path) -> AgentSpec:
    return load(spec_path)


@pytest.fixture()
def program(spec: AgentSpec) -> Predict:
    return build_program(spec, tools=TOOLS, rewards=REWARDS)


HEADER = re.compile(r"\[\[ ## ([a-z_][a-z0-9_]*) ## \]\]")


def prompt_key(messages: list[dict[str, Any]]) -> str | None:
    """Read a signature's output fields back out of the rendered prompt."""
    content = messages[-1]["content"]
    tail = content.rsplit("starting with the field", 1)[-1]
    names = [name for name in HEADER.findall(tail or content) if name != "completed"]
    return "|".join(names) or None


class ScriptedLM(DummyLM):
    """DummyLM with one answer queue per signature output-field set."""

    def __init__(self, script: dict[str, list[dict[str, Any]]]) -> None:
        super().__init__({})
        self.script = {key: list(answers) for key, answers in script.items()}
        self.lock = threading.Lock()
        self.calls: list[dict[str, Any]] = []

        self._engine_spec = SignatureEngine(self, self._engine_spec)

    def copy(self, **kwargs):
        copied = super().copy(**kwargs)
        copied._engine_spec = SignatureEngine(copied, copied._engine_spec)
        return copied


class SignatureEngine:
    """Select scripted answers at the canonical engine boundary."""

    supports_function_calling = False
    supports_response_schema = False
    supports_reasoning = False
    supported_params: set[str] = set()

    def __init__(self, lm, delegate):
        self.lm = lm
        self.delegate = delegate

    def complete(self, request):
        if isinstance(self.lm, SlowLM):
            time.sleep(0.2)
        messages = [
            {"role": message.role, "content": message.text}
            for message in request.messages
        ]
        if request.system is not None:
            messages.insert(0, {"role": "system", "content": str(request.system)})
        with self.lm.lock:
            key = prompt_key(messages)
            queue = self.lm.script.get(key or "", [])
            answer = queue.pop(0) if queue else {}
            self.lm.answers = iter([answer])
            self.lm.calls.append(
                {
                    "key": key,
                    "thread": threading.current_thread().name,
                    "system": messages[0]["content"],
                }
            )
            return self.delegate.complete(request)

    def close(self):
        self.delegate.close()


class SlowLM(ScriptedLM):
    """Each engine call costs 0.2s to make branch concurrency observable."""


SCRIPT: dict[str, list[dict[str, Any]]] = {
    "next_thought|tool_calls": [
        {
            "next_thought": "Search the corpus.",
            "tool_calls": {
                "tool_calls": [
                    {
                        "id": "c1",
                        "name": "corpus_search",
                        "args": {"query": "gepa instructions"},
                    }
                ]
            },
        },
        {
            "next_thought": "Read the best document.",
            "tool_calls": {
                "tool_calls": [
                    {"id": "c2", "name": "read_doc", "args": {"doc_id": "doc://gepa"}}
                ]
            },
        },
        {
            "next_thought": "Submit the evidence.",
            "tool_calls": {
                "tool_calls": [
                    {
                        "id": "c3",
                        "name": "submit",
                        "args": {
                            "evidence": ["doc://gepa: GEPA rewrites instructions."],
                            "gaps": ["No evidence about the optimizer budget."],
                        },
                    }
                ]
            },
        },
    ],
    "route|rationale": [
        {"route": "corpus", "rationale": "The request is about the corpus."}
    ],
    "reasoning|risk_view|risk_flags": [
        {
            "reasoning": "One coupling is visible.",
            "risk_view": "Risk is instruction drift.",
            "risk_flags": ["instruction-drift"],
        }
    ],
    "market_view": [{"market_view": "Reviewers read Markdown instead of Python."}],
    "cost_view": [{"cost_view": "One extra call per branch (doc://gepa)."}] * 2,
    "answer|process_summary": [
        {
            "answer": "YAML plus Markdown compiles to DSPy objects (doc://gepa).",
            "process_summary": "Routed, gathered, reviewed, synthesized.",
        }
    ]
    * 2,
}


def fresh_script() -> dict[str, list[dict[str, Any]]]:
    """Return a copy of the script with fresh answer queues."""
    script = {
        key: [json.loads(json.dumps(answer)) for answer in answers]
        for key, answers in SCRIPT.items()
    }
    return script


def run(program: dspy.Module, lm: DummyLM, **inputs: Any):
    with dspy.context(lm=lm):
        return program(**inputs)


def test_load_spec_reads_yaml_and_markdown_files(
    spec: AgentSpec, spec_path: Path
) -> None:
    assert spec.agent == "researcher"
    assert spec.root == "researcher"
    assert spec.version == 1
    assert spec.source_dir == spec_path.parent.resolve()
    assert [signature.name for signature in spec.signatures][0] == "route_request"
    assert spec.modules["reviews"].children == ["risk", "market", "cost"]


def test_build_program_maps_every_type_onto_a_dspy_class(program: Predict) -> None:
    assert isinstance(program, dspy.Module)
    assert type(program) is Sequential
    assert type(program.route) is Predict
    assert type(program.gather) is React
    assert isinstance(program.gather, dspy.ReActV2)
    assert isinstance(program.reviews, Fanout)
    assert type(program.reviews.risk) is ChainOfThought
    assert type(program.reviews.market) is Predict
    assert type(program.reviews.cost) is Refine
    assert type(program.synthesize) is BestOfN
    assert isinstance(program.synthesize, dspy.BestOfN)


def test_predictor_paths_are_named_like_the_yaml(program: Predict) -> None:
    assert [name for name, _ in program.named_predictors()] == [
        "route",
        "gather.react",
        "reviews.risk.predict",
        "reviews.market",
        "reviews.cost.module",
        "synthesize.module",
    ]


def test_signatures_keep_declared_field_order_and_types(program: Predict) -> None:
    final = program.synthesize.module.signature
    assert final.__name__ == "final_answer"
    assert list(final.input_fields) == [
        "user_request",
        "evidence",
        "risk_view",
        "market_view",
        "cost_view",
    ]
    assert list(final.output_fields) == ["answer", "process_summary"]
    brief = program.gather.signature
    assert brief.input_fields["user_request"].annotation is str
    assert brief.output_fields["evidence"].annotation == list[str]


def test_one_signature_class_per_step_is_never_shared(
    program: Predict, spec_path: Path
) -> None:
    classes = [predictor.signature for _, predictor in program.named_predictors()]
    assert len(classes) == len({id(signature) for signature in classes})
    shared = SPEC_YAML.replace(
        "  market: {type: predict, signature: market_review}",
        "  market: {type: predict, signature: cost_review}",
    )
    built = build(spec_path, shared)
    assert built.reviews.market.signature is not built.reviews.cost.module.signature
    assert built.reviews.market.signature.__name__ == "cost_review"


def flatten(text: str) -> str:
    """Drop the prompt template's per-line indentation, keep line breaks."""
    return "\n".join(line.strip() for line in text.splitlines())


def test_markdown_body_reaches_the_lm_verbatim(program: Predict) -> None:
    lm = ScriptedLM(fresh_script())
    run(program, lm, user_request="How does a declarative spec reach an optimizer?")
    market = next(call["system"] for call in lm.calls if call["key"] == "market_view")
    assert flatten(MARKET_BODY) in flatten(market)
    calls = [call for call in lm.calls if call["key"] == "next_thought|tool_calls"]
    assert flatten(BRIEF_BODY) in flatten(calls[0]["system"])
    # internal line breaks and the blank line survive verbatim
    assert "read at most one document.\n\nReport only what a tool" in flatten(
        calls[0]["system"]
    )


def test_front_matter_overrides_field_descriptions(program: Predict) -> None:
    evidence = program.gather.signature.output_fields["evidence"]
    assert evidence.json_schema_extra["desc"].startswith("One bounded evidence line")
    gaps = program.gather.signature.output_fields["gaps"]
    assert gaps.json_schema_extra["desc"] == "What evidence cannot answer."


def test_policy_is_attached_only_to_opt_in_signatures(program: Predict) -> None:
    assert "Researcher policy" in program.gather.signature.instructions
    assert "Evidence discipline" in program.gather.signature.instructions
    assert "Researcher policy" not in program.route.signature.instructions
    risk = program.reviews.risk.predict.signature.instructions
    assert "Researcher policy" not in risk


def test_tools_are_bound_by_python_name_and_docstring(program: Predict) -> None:
    tools = program.gather.tools
    assert set(tools) == {"corpus_search", "read_doc", "submit"}
    assert tools["corpus_search"].desc == corpus_search.__doc__
    assert tools["read_doc"].args["doc_id"]["type"] == "string"
    assert tools["corpus_search"].func is corpus_search


def test_scored_types_resolve_the_reward_by_name(spec_path: Path) -> None:
    seen: list[tuple[dict[str, Any], Any]] = []

    def counting(args: dict[str, Any], pred: Any) -> float:
        """1.0, and record the dspy reward-call convention."""
        seen.append((args, pred))
        return 1.0

    registry = {"evidence_reward": counting}
    validated = load_spec(spec_path, tools=TOOLS, rewards=registry)
    program = build_program(validated, tools=TOOLS, rewards=registry)
    assert type(program.reviews.cost) is Refine
    assert type(program.synthesize) is BestOfN
    assert (program.reviews.cost.N, program.reviews.cost.threshold) == (2, 1.0)
    lm = ScriptedLM(fresh_script())
    run(program, lm, user_request="question")
    assert seen, "the reward function never ran"
    args, pred = seen[0]
    assert isinstance(args, dict)
    assert pred.toDict()


def test_declared_inputs_are_wired_by_field_name(program: Predict) -> None:
    assert program.declared_inputs == ["user_request"]
    assert program.reviews.declared_inputs == ["evidence", "gaps"]
    assert {"answer", "process_summary"} <= set(program.produced)
    with pytest.raises(SpecError, match=r"needs \['gaps'\]"):
        program.reviews(evidence=["doc://gepa"])


def test_end_to_end_run_under_dummy_lm(program: Predict) -> None:
    lm = ScriptedLM(fresh_script())
    prediction = run(program, lm, user_request="How does a spec reach an optimizer?")
    assert prediction.route == "corpus"
    assert prediction.risk_flags == ["instruction-drift"]
    assert prediction.evidence[0].startswith("doc://gepa")
    assert prediction.answer.endswith("(doc://gepa).")
    keys = [call["key"] for call in lm.calls]
    assert keys[0] == "route|rationale"
    assert keys[1:4] == ["next_thought|tool_calls"] * 3
    assert keys[-1] == "answer|process_summary"
    assert len(keys) == 8


def test_end_to_end_under_plain_dummylm(spec_path: Path) -> None:
    single = SPEC_YAML.replace(
        "  researcher: {type: sequential, steps: [route, gather, reviews, synthesize]}",
        "  researcher: {type: predict, signature: route_request}",
    )
    program = build(spec_path, single)
    lm = DummyLM([{"route": "corpus", "rationale": "The request is about the corpus."}])
    prediction = run(program, lm, user_request="Which route?")
    assert prediction.route == "corpus"
    assert lm.history
    assert "Which route?" in json.dumps(lm.history[0], default=str)


def test_fanout_runs_branches_on_several_threads(program: Predict) -> None:
    def reviews(num_threads: int) -> tuple[float, set[str], Any]:
        lm = SlowLM(fresh_script())
        started = time.perf_counter()
        with dspy.context(lm=lm, num_threads=num_threads):
            result = program.reviews(evidence=["doc://gepa"], gaps=[])
        threads = {call["thread"] for call in lm.calls}
        return time.perf_counter() - started, threads, result

    parallel, threads, result = reviews(3)
    sequential, sequential_threads, _ = reviews(1)
    assert result.risk_view and result.market_view and result.cost_view
    assert sequential_threads == {"MainThread"}
    assert len(threads) == 3
    assert parallel == pytest.approx(0.2, abs=0.15)
    assert sequential == pytest.approx(0.6, abs=0.3)
    assert parallel < sequential


def test_fanout_runs_each_branch_exactly_once(program: Predict) -> None:
    lm = ScriptedLM(fresh_script())
    with dspy.context(lm=lm, num_threads=3):
        program.reviews(evidence=["doc://gepa"], gaps=[])
    assert sorted(call["key"] for call in lm.calls) == [
        "cost_view",
        "market_view",
        "reasoning|risk_view|risk_flags",
    ]


def test_fanout_refuses_a_branch_that_overwrites_a_field(spec_path: Path) -> None:
    clashing = SPEC_YAML.replace(
        "  market: {type: predict, signature: market_review}",
        "  market: {type: predict, signature: risk_review}",
    )
    program = build(spec_path, clashing)
    script = fresh_script()
    script["risk_view|risk_flags"] = [{"risk_view": "Direct.", "risk_flags": ["drift"]}]
    lm = ScriptedLM(script)
    with dspy.context(lm=lm, num_threads=1):
        with pytest.raises(SpecError, match="overwrite"):
            program.reviews(evidence=["doc://gepa"], gaps=[])


def test_state_round_trip_is_the_optimizer_writeback_contract(
    program: Predict, spec_path: Path
) -> None:
    state = program.dump_state()
    paths = [name for name, _ in program.named_predictors()]
    assert set(state) == {*paths, "metadata", "structure_hash"}
    metadata = state["metadata"]
    assert metadata["dependency_versions"]["dspy"] == dspy.__version__
    assert metadata["agent"] == "researcher"
    assert json.dumps(state)

    optimized = dict(state)
    optimized["route"] = "# Route request\n\nAlways route to the corpus profile."
    fresh = build_program(load(spec_path), tools=TOOLS, rewards=REWARDS)
    assert sorted(fresh.apply_state(optimized)) == sorted(paths)
    assert fresh.route.signature.instructions.startswith("# Route request\n\nAlways")
    lm = ScriptedLM(fresh_script())
    run(fresh, lm, user_request="question")
    routed = [call for call in lm.calls if call["key"] == "route|rationale"]
    assert "Always route to the corpus profile." in routed[0]["system"]


def test_apply_state_accepts_full_predictor_state(program: Predict) -> None:
    state = program.dump_state()
    market = state["reviews.market"]
    assert market["signature"]["instructions"] == MARKET_BODY
    market["signature"]["instructions"] = "# Market review\n\nReplaced."
    paths = [name for name, _ in program.named_predictors()]
    assert program.apply_state(state) == paths
    assert program.reviews.market.signature.instructions.startswith("# Market review")
    assert program.reviews.market.signature.__name__ == "market_review"


def test_apply_state_refuses_another_structure(program: Predict) -> None:
    before = {name: p.signature.instructions for name, p in program.named_predictors()}
    state = program.dump_state()
    state["structure_hash"] = "sha256:" + "0" * 64
    state["route"] = "tampered"
    with pytest.raises(SpecError, match="different spec"):
        program.apply_state(state)
    after = {name: p.signature.instructions for name, p in program.named_predictors()}
    assert after == before


def test_apply_state_refuses_state_without_metadata(program: Predict) -> None:
    state = program.dump_state()
    del state["metadata"]
    with pytest.raises(SpecError, match="dependency_versions"):
        program.apply_state(state)


def test_apply_state_refuses_unknown_paths_and_payloads(program: Predict) -> None:
    ghost = dict(program.dump_state())
    ghost["ghost.module"] = "instructions"
    with pytest.raises(SpecError, match="does not declare"):
        program.apply_state(ghost)
    wrong_type = dict(program.dump_state())
    wrong_type["route"] = 7
    with pytest.raises(SpecError, match="instructions or a predictor state"):
        program.apply_state(wrong_type)


def test_structure_hash_covers_structure_but_not_prompt_text(
    spec_path: Path,
) -> None:
    spec = load(spec_path)
    first = structure_hash(spec)
    assert first == structure_hash(load(spec_path))
    assert canonical_spec(spec) == json.dumps(
        spec.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )
    (spec_path.parent / "prompts/market.md").write_text("# Market review\n\nRewritten.")
    assert structure_hash(load(spec_path)) == first
    changed = SPEC_YAML.replace('type: "list[str]"', "type: str")
    assert structure_hash(load(write_spec(spec_path.parent, changed))) != first
    envelope = {"structure_hash": first, "metadata": {"dependency_versions": {}}}
    verify_state(envelope, first)
    with pytest.raises(SpecError, match="different spec"):
        verify_state({**envelope, "structure_hash": "sha256:0"}, first)


def test_root_leaf_program_keeps_the_state_contract(spec_path: Path) -> None:
    leaf_yaml = SPEC_YAML.replace(
        "  researcher: {type: sequential, steps: [route, gather, reviews, synthesize]}",
        "  researcher: {type: best_of_n, signature: route_request, n: 2,"
        " reward: nonempty_reward}",
    )
    leaf = build(spec_path, leaf_yaml)
    assert type(leaf) is BestOfN
    state = leaf.dump_state()
    assert state["structure_hash"] == leaf.structure_hash
    assert (
        state["metadata"]["dependency_versions"]["python"]
        == f"{sys.version_info.major}.{sys.version_info.minor}"
    )
    assert leaf.apply_state(state) == ["module"]


def test_dspy_native_save_and_load_still_work(program: Predict, tmp_path: Path) -> None:
    """The declared state stays compatible with dspy's own save/load pair."""
    path = tmp_path / "state.json"
    program.save(path)
    saved = json.loads(path.read_text())
    paths = [name for name, _ in program.named_predictors()]
    assert set(saved) == {*paths, "metadata", "structure_hash"}
    assert saved["metadata"]["dependency_versions"]["dspy"] == dspy.__version__
    source = program.agent_spec.source_dir / "researcher.yaml"
    fresh = build_program(load(source), tools=TOOLS, rewards=REWARDS)
    fresh.load_state(saved)  # dspy's own loader ignores the extra keys
    live = fresh.named_predictors()
    instructions = {name: pred.signature.instructions for name, pred in live}
    assert instructions["reviews.market"] == MARKET_BODY


def test_tool_building_falls_back_to_plain_dspy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without the app package the registry still builds real dspy tools."""
    monkeypatch.setitem(sys.modules, "app.agent.tooling", None)
    tool = ToolRegistry({"corpus_search": corpus_search}).resolve("corpus_search")
    assert isinstance(tool, dspy.Tool)
    assert tool.desc == corpus_search.__doc__


def test_build_program_requires_registered_tools_and_rewards(spec: AgentSpec) -> None:
    with pytest.raises(SpecError, match="unknown python tool"):
        build_program(spec)
    with pytest.raises(SpecError, match="unknown reward"):
        build_program(spec, tools=TOOLS)


def test_module_names_that_shadow_attributes_are_refused(spec_path: Path) -> None:
    for name in ("forward", "metadata", "declared_inputs", "callbacks"):
        declared = "  route: {type: predict"
        shadowing = SPEC_YAML.replace(declared, f"  {name}: {{type: predict")
        shadowing = shadowing.replace("steps: [route,", f"steps: [{name},")
        with pytest.raises(SpecError, match="collides with a dspy.Module attribute"):
            build(spec_path, shadowing)


def test_read_markdown_splits_front_matter(tmp_path: Path) -> None:
    plain = tmp_path / "plain.md"
    plain.write_text("# Title\n\nBody line.\n")
    assert read_markdown(plain) == ({}, "# Title\n\nBody line.")
    front = tmp_path / "front.md"
    front.write_text('---\nfields:\n  answer: "Answer text."\n---\n# Title\n\nBody.\n')
    meta, body = read_markdown(front)
    assert meta["fields"] == {"answer": "Answer text."}
    assert body == "# Title\n\nBody."
    broken = tmp_path / "broken.md"
    broken.write_text("---\n- a\n- b\n---\nBody.\n")
    with pytest.raises(SpecError, match="front matter"):
        read_markdown(broken)
    malformed_yaml = tmp_path / "malformed.md"
    malformed_yaml.write_text("---\nfields: [unclosed\n---\nBody.\n")
    with pytest.raises(SpecError, match="invalid prompt front matter"):
        read_markdown(malformed_yaml)


def test_build_signature_refuses_unknown_front_matter_fields(tmp_path: Path) -> None:
    (tmp_path / "prompt.md").write_text('---\nfields:\n  ghost: "x"\n---\n# Title\n')
    declared = SignatureSpec.model_validate(
        {
            "name": "one",
            "instructions_file": "prompt.md",
            "inputs": [{"name": "question", "type": "str"}],
            "outputs": [{"name": "answer", "type": "str"}],
        }
    )
    with pytest.raises(SpecError, match="unknown fields"):
        build_signature(declared, policy="", base=tmp_path)
