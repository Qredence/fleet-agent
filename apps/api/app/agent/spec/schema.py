"""Strict declarative models for one agent spec.

The pydantic models describe shape and types only (``extra="forbid"``).
``validate_spec`` checks meaning and raises ``SpecError`` naming the offender:
an unknown module type, an unknown signature or child, a cycle, a field type
that is not registered, and so on. Nothing here executes the spec.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Never

import dspy
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

# Closed sets; every module type has exactly one class in ``types``.
FIELD_TYPES: dict[str, Any] = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "list[str]": list[str],
    "list[int]": list[int],
    "list[float]": list[float],
    "History": dspy.History,
    "dspy.History": dspy.History,
}
COMPOSITE_TYPES: tuple[str, ...] = ("sequential", "fanout")

SIGNATURE_ONLY = frozenset({"signature"})
SCORED = SIGNATURE_ONLY | {"reward", "n", "threshold"}
MODULE_PARAMETERS: dict[str, frozenset[str]] = {
    **dict.fromkeys(("predict", "chain_of_thought"), SIGNATURE_ONLY),
    "react": SIGNATURE_ONLY | {"tools", "max_iters"},
    **dict.fromkeys(("refine", "best_of_n"), SCORED),
    "sequential": frozenset({"steps"}),
    "fanout": frozenset({"branches"}),
}
MODULE_TYPES: tuple[str, ...] = tuple(MODULE_PARAMETERS)
OUTPUT_TYPES: frozenset[str] = frozenset(MODULE_TYPES).difference(
    {"react", *COMPOSITE_TYPES}
)
"""Leaf types whose signature must declare output fields.

An LM call with no outputs produces nothing, so the schema refuses it. ``react``
is excluded: an evidence-only loop is a real DSPy pattern, and refusing it would
push that loop back into hand-written Python."""
MODULE_FIELD_NAMES = frozenset().union(*MODULE_PARAMETERS.values())


class SpecError(ValueError):
    """A declarative definition that cannot compile into DSPy objects."""


def fail(message: str) -> Never:
    """Raise ``SpecError``; keeps validation messages short and findable."""
    raise SpecError(message)


class FieldSpec(BaseModel):
    """One declared input or output field of a signature."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    type: str = "str"
    description: str = ""


class SignatureSpec(BaseModel):
    """One named signature: typed fields plus the prompt that owns its text."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    inputs: list[FieldSpec]
    outputs: list[FieldSpec]
    instructions_file: str | None = None
    instructions: str | None = None
    inherit_policy: bool = False


class ModuleSpec(BaseModel):
    """One node of the module tree: a registered type plus its parameters."""

    model_config = ConfigDict(extra="forbid")

    type: str
    signature: str | None = None
    tools: list[str] = Field(default_factory=list)
    max_iters: int = Field(default=8, ge=1)
    n: int = Field(default=2, ge=1)
    threshold: float = 1.0
    reward: str | None = None
    steps: list[str] = Field(default_factory=list)
    branches: list[str] = Field(default_factory=list)

    @property
    def children(self) -> list[str]:
        """Names of the child modules this node runs, in declaration order."""
        return self.steps if self.type == "sequential" else self.branches


class AgentSpec(BaseModel):
    """One declarative agent definition: named signatures over a module tree."""

    model_config = ConfigDict(extra="forbid")

    agent: str = Field(min_length=1)
    root: str
    version: int = 1
    policy_file: str | None = None
    signatures: list[SignatureSpec]
    modules: dict[str, ModuleSpec]

    _source_dir: Path = PrivateAttr(default=Path("."))

    @property
    def source_dir(self) -> Path:
        """Directory the spec was loaded from; prompt files resolve against it."""
        return self._source_dir


def validate_spec(spec: AgentSpec) -> None:
    """Raise ``SpecError`` unless every part of ``spec`` is consistent."""
    _check_signatures(spec)
    _check_modules(spec)
    _check_references(spec)
    _check_acyclic(spec)


def _check_signatures(spec: AgentSpec) -> None:
    """Validate every signature's fields and instruction source."""
    seen: set[str] = set()
    for sig in spec.signatures:
        if sig.name in seen:
            fail(f"duplicate signature {sig.name!r}")
        seen.add(sig.name)
        if sig.instructions_file is None and not (sig.instructions or "").strip():
            fail(f"signature {sig.name!r} needs instructions or instructions_file")
        if not sig.inputs:
            fail(f"signature {sig.name!r} needs input fields")
        # ``outputs`` may legitimately be empty. A ReAct evidence loop runs a
        # signature that declares none, so the loop ends when the model stops
        # asking for tools rather than being forced to submit a result. Leaf
        # types that genuinely need outputs are checked in ``_check_modules``.
        for field in (*sig.inputs, *sig.outputs):
            if field.type not in FIELD_TYPES:
                fail(f"field {field.name!r} uses unregistered type {field.type!r}")
            if not field.name.isidentifier():
                fail(f"field name {field.name!r} is not a python identifier")
        for kind, group in (("input", sig.inputs), ("output", sig.outputs)):
            names = [field.name for field in group]
            duplicates = sorted({name for name in names if names.count(name) > 1})
            if duplicates:
                fail(f"signature {sig.name!r} repeats {kind} fields {duplicates}")
        clash = sorted({f.name for f in sig.inputs} & {f.name for f in sig.outputs})
        if clash:
            fail(f"signature {sig.name!r} lists {clash} as input and output")


def _check_modules(spec: AgentSpec) -> None:
    """Validate every module's type, parameters, and required wiring."""
    declared = {signature.name: signature for signature in spec.signatures}
    for module in spec.modules.values():
        if module.type not in MODULE_TYPES:
            fail(f"module type {module.type!r} not in {list(MODULE_TYPES)}")
        provided = module.model_fields_set & MODULE_FIELD_NAMES
        unused = sorted(provided - MODULE_PARAMETERS[module.type])
        if unused:
            fail(f"module type {module.type!r} does not accept {unused}")
        if module.type in COMPOSITE_TYPES:
            if not module.children:
                fail(f"module type {module.type!r} needs a child module")
            duplicates = sorted(
                {name for name in module.children if module.children.count(name) > 1}
            )
            if duplicates:
                fail(f"composite module repeats children {duplicates}")
        elif module.signature is None:
            fail(f"module type {module.type!r} needs a signature name")
        if module.type in ("refine", "best_of_n") and module.reward is None:
            fail(f"module type {module.type!r} needs a reward function name")
        if module.type == "react" and not module.tools:
            fail("module type 'react' needs at least one tool")
        # ``declared`` may not hold the name yet: _check_references reports an
        # unknown signature, so only a known one is inspected here.
        referenced = declared.get(module.signature) if module.signature else None
        if (
            module.type in OUTPUT_TYPES
            and referenced is not None
            and not referenced.outputs
        ):
            fail(
                f"signature {module.signature!r} needs output fields for "
                f"module type {module.type!r}"
            )


def _check_references(spec: AgentSpec) -> None:
    """Validate that every declared name resolves."""
    known = {signature.name for signature in spec.signatures}
    if not spec.modules:
        fail("spec declares no modules")
    if spec.root not in spec.modules:
        fail(f"root module {spec.root!r} is not defined")
    for name, module in spec.modules.items():
        if module.signature is not None and module.signature not in known:
            fail(f"module {name!r} references signature {module.signature!r}")
        for child in module.children:
            if child not in spec.modules:
                fail(f"module {name!r} references unknown child {child!r}")


def _check_acyclic(spec: AgentSpec) -> None:
    """Raise ``SpecError`` when the module tree contains a cycle."""
    path: list[str] = []
    done: set[str] = set()

    def visit(name: str) -> None:
        if name in path:
            fail(f"module cycle: {' -> '.join([*path, name])}")
        if name in done:
            return
        path.append(name)
        for child in spec.modules[name].children:
            visit(child)
        path.pop()
        done.add(name)

    for name in spec.modules:
        visit(name)
