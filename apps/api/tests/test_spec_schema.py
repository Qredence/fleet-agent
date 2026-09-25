"""Validation tests for the declarative spec schema and its name registries."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import dspy
import pytest
import yaml
from pydantic import ValidationError

from app.agent.spec import AgentSpec, RewardRegistry, SpecError, ToolRegistry, load_spec
from app.agent.spec.schema import FIELD_TYPES, MODULE_TYPES, validate_spec
from app.agent.spec.types import MODULE_REGISTRY


def field(name: str, kind: str = "str") -> dict[str, str]:
    """Return one minimal field declaration."""
    return {"name": name, "type": kind, "description": f"The {name}."}


def signature(name: str, **overrides: Any) -> dict[str, Any]:
    """Return one minimal signature declaration."""
    data: dict[str, Any] = {
        "name": name,
        "instructions": f"# {name}\n\nDo the {name} step.",
        "inputs": [field("user_request")],
        "outputs": [field(f"{name}_view")],
    }
    data.update(overrides)
    return data


def spec_data(**overrides: Any) -> dict[str, Any]:
    """Return one minimal valid spec document."""
    data: dict[str, Any] = {
        "agent": "mini",
        "root": "step",
        "signatures": [signature("route"), signature("answer")],
        "modules": {
            "step": {"type": "sequential", "steps": ["route", "answer"]},
            "route": {"type": "predict", "signature": "route"},
            "answer": {"type": "chain_of_thought", "signature": "answer"},
        },
    }
    data.update(overrides)
    return data


def write_document(root: Path, document: Any, name: str = "mini.yaml") -> Path:
    """Write one YAML document under ``root`` and return its path."""
    path = root / name
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return path


def validated(document: dict[str, Any]) -> AgentSpec:
    """Build one spec document, then run the semantic validation over it."""
    spec = AgentSpec(**document)
    validate_spec(spec)
    return spec


def with_module(name: str, module: dict[str, Any]) -> dict[str, Any]:
    """Return spec data with one extra module appended."""
    data = spec_data()
    data["modules"][name] = module
    return data


def tool_source(query: str) -> list[str]:
    """Return matching document ids for a query, best first."""
    return [query]


def reward(args: dict[str, Any], pred: Any) -> float:
    """1.0 when the prediction has an output."""
    return 1.0 if pred.toDict() else 0.0


def test_minimal_spec_validates() -> None:
    spec = AgentSpec(**spec_data())
    assert spec.agent == "mini"
    assert spec.root == "step"
    assert spec.version == 1
    assert spec.policy_file is None
    assert list(spec.modules) == ["step", "route", "answer"]
    assert spec.modules["answer"].max_iters == 8
    assert spec.modules["answer"].threshold == 1.0
    assert spec.source_dir == Path(".")


def test_spec_error_is_a_value_error() -> None:
    assert issubclass(SpecError, ValueError)


def test_module_type_is_closed_and_registered() -> None:
    assert MODULE_TYPES == (
        "predict",
        "chain_of_thought",
        "react",
        "refine",
        "best_of_n",
        "sequential",
        "fanout",
    )
    assert set(MODULE_REGISTRY) == set(MODULE_TYPES)
    assert set(FIELD_TYPES) == {
        "str",
        "int",
        "float",
        "bool",
        "list[str]",
        "list[int]",
        "list[float]",
        "History",
        "dspy.History",
    }


@pytest.mark.parametrize(
    ("document", "message"),
    [
        (
            with_module("extra", {"type": "self_reflect", "signature": "answer"}),
            "module type 'self_reflect' not in",
        ),
        (
            spec_data(
                modules={
                    "step": {"type": "sequential", "steps": ["route", "ghost"]},
                    "route": {"type": "predict", "signature": "route"},
                }
            ),
            "references unknown child 'ghost'",
        ),
        (
            spec_data(
                modules={
                    "step": {"type": "predict", "signature": "ghost"},
                }
            ),
            "references signature 'ghost'",
        ),
        (spec_data(root="missing"), "root module 'missing' is not defined"),
        (
            spec_data(signatures=[signature("route"), signature("route")]),
            "duplicate signature 'route'",
        ),
        (
            spec_data(modules={"step": {"type": "sequential", "steps": []}}),
            "needs a child module",
        ),
    ],
)
def test_invalid_specs_are_refused(document: dict[str, Any], message: str) -> None:
    with pytest.raises(SpecError, match=message):
        validated(document)


def test_module_cycle_is_refused() -> None:
    document = spec_data(
        modules={
            "step": {"type": "fanout", "branches": ["route", "answer"]},
            "route": {"type": "sequential", "steps": ["answer"]},
            "answer": {"type": "sequential", "steps": ["route"]},
        }
    )
    cycle = "module cycle: step -> route -> answer -> route"
    with pytest.raises(SpecError, match=cycle):
        validated(document)


def test_unregistered_field_type_is_refused() -> None:
    document = spec_data(
        signatures=[signature("route", inputs=[field("user_request", "DataFrame")])]
    )
    with pytest.raises(SpecError, match="uses unregistered type 'DataFrame'"):
        validated(document)


def test_field_names_and_shapes_are_validated() -> None:
    with pytest.raises(SpecError, match="is not a python identifier"):
        validated(spec_data(signatures=[signature("route", inputs=[field("2bad")])]))
    with pytest.raises(SpecError, match="repeats input fields"):
        validated(
            spec_data(
                signatures=[
                    signature("route", inputs=[field("question"), field("question")])
                ]
            )
        )
    with pytest.raises(SpecError, match=r"lists \['same'\] as input and output"):
        validated(
            spec_data(
                signatures=[
                    signature("route", inputs=[field("same")], outputs=[field("same")])
                ]
            )
        )
    # An LM-call leaf with no declared outputs produces nothing, so it is
    # still refused - with a message that names the module type.
    with pytest.raises(SpecError, match="needs output fields for module type"):
        validated(spec_data(signatures=[signature("route", outputs=[])]))
    with pytest.raises(SpecError, match="needs instructions or instructions_file"):
        validated(spec_data(signatures=[signature("route", instructions=None)]))


def test_module_types_reject_foreign_parameters() -> None:
    plain = with_module("plain", {"type": "predict", "signature": "route", "n": 3})
    with pytest.raises(SpecError, match=r"does not accept \['n'\]"):
        validated(plain)
    seq = {"type": "sequential", "steps": ["route"], "reward": "r"}
    with pytest.raises(SpecError, match=r"does not accept \['reward'\]"):
        validated(with_module("loop", seq))
    refine = {"step": {"type": "refine", "signature": "route", "n": 2}}
    with pytest.raises(SpecError, match="needs a reward function name"):
        validated(spec_data(modules=refine))
    react = {"step": {"type": "react", "signature": "route", "tools": []}}
    with pytest.raises(SpecError, match="needs at least one tool"):
        validated(spec_data(modules=react))


def test_extra_keys_are_refused(tmp_path: Path) -> None:
    document = spec_data()
    document["extra"] = "nope"
    with pytest.raises(ValidationError):
        AgentSpec(**document)
    path = write_document(tmp_path, document)
    with pytest.raises(SpecError, match="Extra inputs are not permitted"):
        load_spec(path)


def test_load_spec_reports_file_and_yaml_problems(tmp_path: Path) -> None:
    with pytest.raises(SpecError, match="spec file not found"):
        load_spec(tmp_path / "ghost.yaml")
    broken = tmp_path / "broken.yaml"
    broken.write_text("agent: [", encoding="utf-8")
    with pytest.raises(SpecError, match="invalid YAML"):
        load_spec(broken)
    listing = tmp_path / "list.yaml"
    listing.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(SpecError, match="must be a YAML mapping"):
        load_spec(listing)


def test_missing_prompt_file_is_refused(tmp_path: Path) -> None:
    document = spec_data(
        signatures=[signature("route", instructions_file="prompts/ghost.md")],
        modules={"step": {"type": "predict", "signature": "route"}},
    )
    path = write_document(tmp_path, document)
    with pytest.raises(SpecError, match="signature 'route' prompt file not found"):
        load_spec(path)
    document = spec_data(
        policy_file="policy.md",
        modules={"step": {"type": "predict", "signature": "route"}},
    )
    path = write_document(tmp_path, document)
    with pytest.raises(SpecError, match="policy file not found"):
        load_spec(path)


def test_unknown_tool_and_reward_names_are_refused(tmp_path: Path) -> None:
    document = spec_data(
        modules={
            "step": {
                "type": "react",
                "signature": "route",
                "tools": ["corpus_search"],
            },
        }
    )
    path = write_document(tmp_path, document)
    spec = load_spec(path, tools={"corpus_search": tool_source})
    assert spec.modules["step"].tools == ["corpus_search"]
    missing = r"binds unknown python tool \['corpus_search'\]"
    with pytest.raises(SpecError, match=missing):
        load_spec(path, tools={"other": tool_source})
    scored = spec_data(
        modules={
            "step": {
                "type": "refine",
                "signature": "route",
                "n": 2,
                "reward": "ghost_reward",
            },
        }
    )
    with pytest.raises(SpecError, match="binds unknown reward 'ghost_reward'"):
        load_spec(write_document(tmp_path, scored), rewards={"real": reward})


def test_tool_registry_resolves_names_to_dspy_tools() -> None:
    registry = ToolRegistry({"corpus_search": tool_source})
    assert "corpus_search" in registry
    assert registry.names() == ("corpus_search",)
    tool = registry.resolve("corpus_search")
    assert isinstance(tool, dspy.Tool)
    assert tool.name == "corpus_search"
    assert tool.desc == tool_source.__doc__
    assert tool.args["query"]["type"] == "string"
    assert tool.func is tool_source
    with pytest.raises(SpecError, match="unknown python tool"):
        registry.resolve("ghost")
    with pytest.raises(SpecError, match="already registered"):
        registry.register("corpus_search", tool_source)
    with pytest.raises(SpecError, match="invalid tool name"):
        registry.register(" spaced", tool_source)


def test_registries_coerce_the_accepted_inputs() -> None:
    from_mapping = ToolRegistry.coerce({"corpus_search": tool_source})
    from_iterable = ToolRegistry.coerce([tool_source])
    from_nothing = ToolRegistry.coerce(None)
    assert from_mapping.names() == ("corpus_search",)
    assert from_iterable.names() == ("tool_source",)
    assert from_nothing.names() == ()
    assert ToolRegistry.coerce(from_mapping) is from_mapping
    rewards = RewardRegistry.coerce({"reward": reward})
    assert rewards.names() == ("reward",)
    assert rewards.resolve("reward") is reward
    assert RewardRegistry.coerce([reward]).names() == ("reward",)
    assert RewardRegistry.coerce(None).names() == ()
    assert RewardRegistry.coerce(rewards) is rewards
    with pytest.raises(SpecError, match="unknown reward function"):
        rewards.resolve("ghost")
    with pytest.raises(SpecError, match="already registered"):
        rewards.register("reward", reward)
    with pytest.raises(SpecError, match="invalid reward name"):
        rewards.register("", reward)


def test_helper_tool_construction_matches_the_app_contract() -> None:
    """A tool whose docstring is empty cannot reach the model with a desc."""

    def undocumented(query: str) -> list[str]:
        return [query]

    with pytest.raises(ValueError):
        ToolRegistry({"undocumented": undocumented}).resolve("undocumented")


def test_react_may_run_a_signature_with_no_output_fields() -> None:
    """An evidence-only ReAct loop is declarable.

    The loop ends when the model stops asking for tools, so it needs no output
    fields. Refusing that shape would push the loop back into hand-written
    Python, which is exactly what this layer exists to avoid.
    """
    from app.agent.spec.schema import AgentSpec, validate_spec

    spec = AgentSpec(
        agent="evidence",
        root="gather",
        signatures=[
            {
                "name": "Evidence",
                "instructions": "Gather tool evidence.",
                "inputs": [{"name": "user_request", "type": "str"}],
                "outputs": [],
            }
        ],
        modules={
            "gather": {
                "type": "react",
                "signature": "Evidence",
                "tools": ["search_docs"],
            }
        },
    )
    validate_spec(spec)  # must not raise


def test_predict_may_not_run_a_signature_with_no_output_fields() -> None:
    from app.agent.spec.schema import AgentSpec, SpecError, validate_spec

    spec = AgentSpec(
        agent="empty",
        root="answer",
        signatures=[
            {
                "name": "Nothing",
                "instructions": "Produces nothing.",
                "inputs": [{"name": "user_request", "type": "str"}],
                "outputs": [],
            }
        ],
        modules={"answer": {"type": "predict", "signature": "Nothing"}},
    )
    with pytest.raises(SpecError, match="needs output fields for module type"):
        validate_spec(spec)


def test_composite_module_rejects_duplicate_children() -> None:
    document = spec_data()
    document["modules"]["step"]["steps"] = ["route", "answer", "route"]
    with pytest.raises(SpecError, match="composite module repeats children"):
        validated(document)


def test_composite_module_rejects_child_names_shadowing() -> None:
    from app.agent.spec.loader import build_program

    document = spec_data()
    document["signatures"].append(signature("child_names"))
    document["modules"]["child_names"] = {
        "type": "predict",
        "signature": "child_names",
    }
    document["modules"]["step"]["steps"] = ["route", "child_names"]
    spec = validated(document)
    with pytest.raises(SpecError, match="collides with a dspy.Module attribute"):
        build_program(spec)
