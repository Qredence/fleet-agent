"""Compile a validated spec (YAML + Markdown) into a live DSPy program.

The YAML owns structure and tool names; the Markdown owns prompt text. No
control flow exists beyond the module types in ``types``, and no tool
description or prompt text is duplicated between the two.

``dump_state`` / ``apply_state`` are the optimizer write-back contract: state is
keyed by ``named_predictors()`` paths, carries ``metadata.dependency_versions``
like DSPy's own saves, and is refused unless its fingerprint matches the
program, because ``Signature.load_state`` matches fields positionally.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import dspy
import yaml  # type: ignore[import-untyped]  # PyYAML ships no stubs
from dspy.utils.saving import get_dependency_versions
from pydantic import ValidationError

from app.agent.spec.fingerprint import structure_hash, verify_state
from app.agent.spec.registry import (
    RewardInput,
    RewardRegistry,
    ToolInput,
    ToolRegistry,
)
from app.agent.spec.schema import (
    COMPOSITE_TYPES,
    FIELD_TYPES,
    AgentSpec,
    ModuleSpec,
    SignatureSpec,
    fail,
    validate_spec,
)
from app.agent.spec.types import MODULE_REGISTRY, STATE_KEYS, Node, SignatureClass

FRONT_MATTER = re.compile(r"\A---\r?\n(?P<meta>.*?)\r?\n---[ \t]*\r?\n?", re.DOTALL)
"""Optional YAML front matter at the very start of a prompt file."""


def read_markdown(path: Path) -> tuple[dict[str, Any], str]:
    """Split one Markdown prompt file into front matter and body text."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        fail(f"cannot read prompt file {path}: {error}")
    match = FRONT_MATTER.match(text)
    if match is None:
        return {}, text.strip()
    try:
        meta = yaml.safe_load(match.group("meta")) or {}
    except yaml.YAMLError as error:
        fail(f"{path.name}: invalid prompt front matter: {error}")
    if not isinstance(meta, dict):
        fail(f"{path.name}: prompt front matter must be a YAML mapping")
    return {str(key): value for key, value in meta.items()}, text[match.end() :].strip()


def check_prompt_files(spec: AgentSpec) -> None:
    """Raise ``SpecError`` when a prompt file the spec names is missing."""
    for signature in spec.signatures:
        named = signature.instructions_file
        if named is not None and not (spec.source_dir / named).is_file():
            fail(f"signature {signature.name!r} prompt file not found: {named}")
    policy = spec.policy_file
    if policy is not None and not (spec.source_dir / policy).is_file():
        fail(f"policy file not found: {policy}")


def check_names(spec: AgentSpec, tools: ToolRegistry, rewards: RewardRegistry) -> None:
    """Raise ``SpecError`` for a tool or reward the registries do not know."""
    for name, module in spec.modules.items():
        unknown = [tool for tool in module.tools if tool not in tools]
        if unknown:
            fail(f"module {name!r} binds unknown python tool {unknown}")
        if module.reward is not None and module.reward not in rewards:
            fail(f"module {name!r} binds unknown reward {module.reward!r}")


def load_spec(
    path: str | Path,
    *,
    tools: ToolRegistry | ToolInput | None = None,
    rewards: RewardRegistry | RewardInput | None = None,
) -> AgentSpec:
    """Read and validate the agent spec at ``path``; raises ``SpecError``.

    The optional registries make tool and reward names fail here, at load time,
    instead of when the program is built.
    """
    spec_path = Path(path)
    if not spec_path.is_file():
        fail(f"spec file not found: {spec_path}")
    try:
        document = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        fail(f"{spec_path.name}: invalid YAML: {error}")
    if not isinstance(document, dict):
        fail(f"{spec_path.name}: a spec must be a YAML mapping")
    try:
        spec = AgentSpec(**document)
    except ValidationError as error:
        fail(f"{spec_path.name}: {_first_error(error)}")
    spec._source_dir = spec_path.parent.resolve()
    validate_spec(spec)
    check_prompt_files(spec)
    if tools is not None or rewards is not None:
        check_names(spec, ToolRegistry.coerce(tools), RewardRegistry.coerce(rewards))
    return spec


def build_program(
    spec: AgentSpec,
    *,
    tools: ToolRegistry | ToolInput | None = None,
    rewards: RewardRegistry | RewardInput | None = None,
) -> Node:
    """Compile a validated spec into a live DSPy program.

    Every tool and reward the spec binds must be registered: an empty registry
    is an empty allowlist, never a silently tool-less program.
    """
    validate_spec(spec)
    tool_registry = ToolRegistry.coerce(tools)
    reward_registry = RewardRegistry.coerce(rewards)
    check_prompt_files(spec)
    check_names(spec, tool_registry, reward_registry)
    base = spec.source_dir
    policy = read_markdown(base / spec.policy_file)[1] if spec.policy_file else ""
    by_name = {signature.name: signature for signature in spec.signatures}
    signatures: dict[str, SignatureClass] = {}
    for name, module in spec.modules.items():
        if module.signature is None:
            continue
        declared = by_name[module.signature]
        signatures[name] = build_signature(declared, policy=policy, base=base)
    program = build_node(spec.root, spec, signatures, tool_registry, reward_registry)
    program.agent_spec = spec
    program.structure_hash = structure_hash(spec)
    return program


def build_signature(spec: SignatureSpec, *, policy: str, base: Path) -> SignatureClass:
    """Compile one declarative signature into a class of its own.

    The Markdown body is the instruction text and reaches the model verbatim
    apart from DSPy's own ``inspect.cleandoc`` normalisation. Front matter may
    override field descriptions; the shared policy is appended only when the
    signature opts in with ``inherit_policy: true``.
    """
    meta: dict[str, Any] = {}
    text = spec.instructions or ""
    if spec.instructions_file is not None:
        meta, text = read_markdown(base / spec.instructions_file)
    if spec.inherit_policy and policy:
        text = f"{text}\n\n{policy}"
    if not text.strip():
        fail(f"signature {spec.name!r} has no instruction text")
    overrides = meta.get("fields") or {}
    if not isinstance(overrides, dict):
        fail(f"signature {spec.name!r} front matter 'fields' must be a mapping")
    declared = [field.name for field in (*spec.inputs, *spec.outputs)]
    unknown = sorted(set(overrides) - set(declared))
    if unknown:
        fail(f"signature {spec.name!r} front matter overrides unknown fields {unknown}")
    fields: dict[str, tuple[Any, Any]] = {}
    groups = ((dspy.InputField, spec.inputs), (dspy.OutputField, spec.outputs))
    for kind, group in groups:
        for field in group:
            description = str(overrides.get(field.name, field.description))
            fields[field.name] = (FIELD_TYPES[field.type], kind(desc=description))
    signature = dspy.make_signature(fields, instructions=text, signature_name=spec.name)
    return cast("SignatureClass", signature)


def build_node(
    name: str,
    spec: AgentSpec,
    signatures: Mapping[str, SignatureClass],
    tools: ToolRegistry,
    rewards: RewardRegistry,
) -> Node:
    """Build one node of the module tree; the schema already refused cycles."""
    module = spec.modules[name]
    node_class = MODULE_REGISTRY[module.type]
    if module.type not in COMPOSITE_TYPES:
        return _build_leaf(module, node_class, signatures[name], tools, rewards)
    children = {
        child: build_node(child, spec, signatures, tools, rewards)
        for child in module.children
    }
    return node_class(children)


def dump_state(program: Node, json_mode: bool = True) -> dict[str, Any]:
    """Return dspy-native state per predictor path plus the fingerprint."""
    state: dict[str, Any] = {
        # dspy's own predictor state, not this module's override, per path.
        name: dspy.Predict.dump_state(predictor, json_mode=json_mode)
        for name, predictor in program.named_predictors()
    }
    state["structure_hash"] = program.structure_hash
    state["metadata"] = {
        "dependency_versions": get_dependency_versions(),
        "agent": program.agent_spec.agent,
        "spec_version": program.agent_spec.version,
    }
    return state


def apply_state(program: Node, state: dict[str, Any]) -> list[str]:
    """Write saved state into ``program``; returns the rewritten paths.

    Refuses state written for another structure, since ``Signature.load_state``
    matches fields positionally. Each payload is either instructions text or a
    full dspy-native predictor state as produced by :func:`dump_state`.
    """
    verify_state(state, program.structure_hash)
    predictors = dict(program.named_predictors())
    unknown = sorted(set(state) - STATE_KEYS - set(predictors))
    if unknown:
        fail(f"state holds paths this program does not declare: {unknown}")
    applied: list[str] = []
    for name, predictor in predictors.items():
        payload = state.get(name)
        if payload is None:
            continue
        if isinstance(payload, str):
            predictor.signature.instructions = payload
        elif isinstance(payload, dict):
            declared = predictor.signature.__name__
            predictor.load_state(payload)
            predictor.signature.__name__ = declared
        else:
            fail(f"state for {name!r} must be instructions or a predictor state")
        applied.append(name)
    return applied


def _first_error(error: ValidationError) -> str:
    """Return the first pydantic error as one short line."""
    first = error.errors()[0]
    location = ".".join(str(part) for part in first["loc"])
    message = str(first["msg"]).removeprefix("Value error, ")
    return f"{location}: {message}" if location else message


def _build_leaf(
    module: ModuleSpec,
    node_class: type[Node],
    signature: SignatureClass,
    tools: ToolRegistry,
    rewards: RewardRegistry,
) -> Node:
    """Build one leaf node from its type, its signature, and bound names."""
    if module.type in ("refine", "best_of_n"):
        scored = {"n": module.n, "reward": rewards.resolve(cast("str", module.reward))}
        return node_class(signature, threshold=module.threshold, **scored)
    if module.type == "react":
        bound = [tools.resolve(tool) for tool in module.tools]
        return node_class(signature, tools=bound, max_iters=module.max_iters)
    return node_class(signature)
