"""Evidence rendering: the synthesizer's ``evidence_json`` must stay parseable.

The synthesis predictor's evidence input is a JSON document, so an
over-budget payload has to shorten or drop whole entries instead of slicing
the serialized text. These tests pin that contract for both DSPy programs.
"""

from __future__ import annotations

import json

import dspy
import pytest

from app.agent.evidence import (
    DEFAULT_MAX_CHARS,
    _dump,
    _fit_entry,
    bounded_json,
    cap_strings,
)


def _entry(index: int, size: int = 900) -> dict[str, object]:
    return {"tool": f"read_file_{index}", "result": "x" * size, "is_error": False}


class TestBoundedJson:
    def test_returns_the_full_document_when_it_fits(self) -> None:
        entries = [_entry(0, 10), _entry(1, 10)]

        assert json.loads(bounded_json(entries)) == entries

    def test_empty_evidence_is_an_empty_array(self) -> None:
        assert bounded_json([]) == "[]"

    @pytest.mark.parametrize(
        ("count", "size"),
        [(0, 0), (1, 1), (1, 500_000), (2, 12_000), (20, 900), (200, 3), (50, 400)],
    )
    def test_the_document_is_always_valid_and_within_budget(
        self, count: int, size: int
    ) -> None:
        text = bounded_json([_entry(index, size) for index in range(count)])

        assert len(text) <= DEFAULT_MAX_CHARS
        assert isinstance(json.loads(text), list)

    def test_keeps_whole_entries_and_shortens_only_the_overflowing_one(self) -> None:
        text = bounded_json([_entry(index) for index in range(20)])

        parsed = json.loads(text)
        # Entries are kept in order from the front, and only the entry that
        # ran into the budget is shortened.
        assert len(parsed) > 1
        assert [entry["tool"] for entry in parsed] == [
            f"read_file_{index}" for index in range(len(parsed))
        ]
        assert all(len(entry["result"]) == 900 for entry in parsed[:-1])
        assert len(parsed[-1]["result"]) < 900

    def test_one_oversized_value_fills_the_budget_instead_of_a_fraction(self) -> None:
        text = bounded_json([_entry(0, 500_000)])

        parsed = json.loads(text)
        assert parsed[0]["tool"] == "read_file_0"
        # The point of shortening rather than capping at a fixed size: the
        # model still gets nearly the whole evidence budget.
        assert len(parsed[0]["result"]) > DEFAULT_MAX_CHARS * 0.9
        assert parsed[0]["result"].endswith("…")

    def test_shrinks_one_entry_that_cannot_fit_on_its_own(self) -> None:
        wide = {f"field_{index}": "w" * 400 for index in range(40)}

        text = bounded_json([wide])

        assert len(text) <= DEFAULT_MAX_CHARS
        assert set(json.loads(text)[0]) == set(wide)

    def test_the_fitted_entry_uses_the_room_that_is_left(self) -> None:
        """The overflow entry stops only when one more character cannot fit."""

        item = {"tool": "read_file_0", "result": "x" * 400, "is_error": False}
        budget = 120

        fitted = _fit_entry(item, budget=budget)

        assert fitted is not None
        used = len(_dump([fitted])) - 2
        assert used <= budget
        longer = cap_strings(item, len(str(fitted["result"])) + 1)
        assert len(_dump([longer])) - 2 > budget

    def test_caps_strings_inside_nested_containers(self) -> None:
        text = bounded_json(
            [{"tool": "search", "result": {"hits": ["q" * 50_000]}, "is_error": False}]
        )

        assert len(text) <= DEFAULT_MAX_CHARS
        assert len(json.loads(text)[0]["result"]["hits"][0]) < 50_000

    def test_rejects_a_budget_too_small_for_an_array(self) -> None:
        with pytest.raises(ValueError, match="max_chars"):
            bounded_json([_entry(0)], max_chars=3)

    def test_honors_a_custom_budget(self) -> None:
        text = bounded_json([_entry(index) for index in range(20)], max_chars=500)

        assert len(text) <= 500
        assert json.loads(text)

    def test_preserves_non_ascii_evidence(self) -> None:
        assert bounded_json([{"tool": "t", "result": "café ✓"}]) == (
            '[{"tool":"t","result":"café ✓"}]'
        )

    def test_the_budget_and_validity_invariant_holds_across_random_shapes(self) -> None:
        """Whatever the entry shapes and budget, the document stays parseable."""
        import random

        rng = random.Random(7)
        for _ in range(300):
            items = []
            for _ in range(rng.randint(0, 8)):
                item: dict[str, object] = {}
                for index in range(rng.randint(1, 4)):
                    key = f"field_{index}"
                    match rng.randint(0, 2):
                        case 0:
                            item[key] = "v" * rng.choice([0, 3, 900, 12_000])
                        case 1:
                            item[key] = [{"inner": "d" * rng.choice([0, 400])}]
                        case _:
                            item[key] = rng.randint(-5, 5)
                items.append(item)
            for max_chars in (17, 100, 999, DEFAULT_MAX_CHARS, 20_000):
                text = bounded_json(items, max_chars=max_chars)
                assert len(text) <= max_chars
                assert isinstance(json.loads(text), list)


class TestCapStrings:
    def test_truncates_and_marks_strings(self) -> None:
        assert cap_strings("abcdef", 3) == "abc…"
        assert cap_strings("abc", 3) == "abc"

    def test_leaves_non_strings_alone(self) -> None:
        assert cap_strings({"n": 1, "f": 1.5, "b": True, "z": None}, 1) == {
            "n": 1,
            "f": 1.5,
            "b": True,
            "z": None,
        }


class TestRoutedEvidenceJson:
    """``FleetAgent`` hands the synthesizer tool results, never broken JSON."""

    def test_oversized_history_still_reaches_the_synthesizer_as_json(self) -> None:
        from app.agent.program import _evidence_json

        history = dspy.History(
            messages=[
                {
                    "tool_calls": {
                        "tool_call_results": [
                            {
                                "name": f"read_file_{index}",
                                "value": "x" * 900,
                                "is_error": False,
                            }
                        ]
                    }
                }
                for index in range(12)
            ]
        )

        text = _evidence_json(history)

        assert len(text) <= 8000
        parsed = json.loads(text)
        assert parsed
        assert parsed[0] == {
            "tool": "read_file_0",
            "result": "x" * 900,
            "is_error": False,
        }

    def test_none_history_is_an_empty_array(self) -> None:
        from app.agent.program import _evidence_json

        assert _evidence_json(None) == "[]"


class TestStagedEvidenceJson:
    def test_oversized_outcomes_still_reach_the_synthesizer_as_json(self) -> None:
        from app.agent.staged import ResearchTask, _evidence_json, _WorkerOutcome

        outcomes = [
            _WorkerOutcome(
                task=ResearchTask(title=f"task {index}", task="gather"),
                status="completed",
                answer="a" * 5000,
            )
            for index in range(4)
        ]

        text = _evidence_json(outcomes)

        assert len(text) <= 8000
        assert json.loads(text)


def _evidence_section(prompt: str) -> str:
    """Pull the rendered ``evidence_json`` field out of a synthesis prompt.

    ``bounded_json`` emits a single-line document, so the field's value is the
    line following the marker; the adapter's trailing instructions come after
    a blank line.
    """
    marker = "[[ ## evidence_json ## ]]\n"
    start = prompt.index(marker) + len(marker)
    return prompt[start:].split("\n", 1)[0].strip()


class TestSynthesizerPrompt:
    """End to end: the model's own prompt carries parseable evidence."""

    def test_a_30k_tool_result_reaches_the_synthesis_prompt_as_valid_json(self) -> None:
        import asyncio

        from app.agent.engine import AgentRunContext, DspyAgentEngine
        from app.agent.factory import build_tool_profiles
        from app.agent.program import FleetAgent
        from app.agent.tool_registry import ToolMetadata, ToolRegistry
        from tests.helpers.scripted_lm import ScriptedLM, router_call, synthesis_call

        prompts: list[str] = []

        class RecordingLM(ScriptedLM):
            def forward(self, prompt=None, messages=None, **kwargs):  # noqa: ANN001, ANN201
                for message in messages or []:
                    content = message.get("content")
                    if isinstance(content, str) and "evidence_json" in content:
                        prompts.append(content)
                return super().forward(prompt=prompt, messages=messages, **kwargs)

        def big(query: str) -> str:
            """Return a large payload."""
            return "B" * 30_000

        registry = ToolRegistry(
            [(big, ToolMetadata(name="big", capability="retrieval"))]
        )
        engine = DspyAgentEngine(
            program_factory=lambda: FleetAgent(
                tool_profiles=build_tool_profiles(registry), max_iters=3
            ),
            lm=RecordingLM(
                [
                    router_call("research"),
                    [{"name": "big", "args": {"query": "x"}}],
                    {"calls": [], "content": '{"next_thought": "done"}'},
                    synthesis_call(answer="ok", summary="Gathered."),
                ]
            ),  # type: ignore[arg-type]
            adapter=dspy.JSONAdapter(use_native_function_calling=True),
        )

        result = asyncio.run(
            engine.run(
                user_request="go",
                history=None,
                context=AgentRunContext(
                    thread_id="t-evidence",
                    run_id="r-evidence",
                    assistant_message_id="m",
                ),
            )
        )

        assert result.status == "completed"
        rendered = _evidence_section(prompts[-1])
        assert len(rendered) <= 8000
        parsed = json.loads(rendered)
        assert parsed[0]["tool"] == "big"
        assert len(parsed[0]["result"]) > 8000 * 0.9
