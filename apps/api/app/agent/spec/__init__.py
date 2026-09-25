"""Declarative YAML + Markdown agent definitions, compiled into DSPy programs."""

from app.agent.spec.fingerprint import canonical_spec, structure_hash, verify_state
from app.agent.spec.loader import (
    apply_state,
    build_program,
    build_signature,
    check_names,
    check_prompt_files,
    dump_state,
    load_spec,
    read_markdown,
)
from app.agent.spec.registry import RewardRegistry, ToolRegistry
from app.agent.spec.schema import (
    AgentSpec,
    FieldSpec,
    ModuleSpec,
    SignatureSpec,
    SpecError,
)
from app.agent.spec.types import MODULE_REGISTRY, Fanout, Node, Sequential

__all__ = [
    "MODULE_REGISTRY",
    "AgentSpec",
    "Fanout",
    "FieldSpec",
    "ModuleSpec",
    "Node",
    "RewardRegistry",
    "Sequential",
    "SignatureSpec",
    "SpecError",
    "ToolRegistry",
    "apply_state",
    "build_program",
    "build_signature",
    "canonical_spec",
    "check_names",
    "check_prompt_files",
    "dump_state",
    "load_spec",
    "read_markdown",
    "structure_hash",
    "verify_state",
]
