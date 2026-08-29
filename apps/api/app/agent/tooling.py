"""Pure DSPy tool construction and schema validation.

This module intentionally has no AG-UI, persistence, or execution-policy
imports. It is safe for the FleetAgent program, registries, tests, and future
optimizer tooling to share.
"""

from __future__ import annotations

import copy
import inspect
import re
from collections.abc import Callable, Mapping
from typing import Any, get_type_hints

import dspy

type ToolSource = Callable[..., Any] | dspy.Tool

TOOL_NAME_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
"""Canonical model-visible tool name rule shared by all layers."""

RESERVED_TOOL_NAMES = frozenset({"submit"})
"""Tool names owned by ReActV2 internals; user tools must not use them."""

_TOOL_NAME_RE = re.compile(TOOL_NAME_PATTERN)


def create_dspy_tool(
    source: ToolSource,
    *,
    name: str | None = None,
    description: str | None = None,
    arg_descriptions: Mapping[str, str] | None = None,
) -> dspy.Tool:
    """
    Create and validate a DSPy tool from a callable or existing tool.
    
    Parameters:
    	source (ToolSource): Callable or DSPy tool to wrap or reuse.
    	name (str | None): Optional public name for the tool.
    	description (str | None): Optional description for the tool.
    	arg_descriptions (Mapping[str, str] | None): Optional descriptions for the tool's arguments.
    
    Returns:
    	dspy.Tool: The constructed or validated DSPy tool.
    """
    if name is not None:
        name = _validate_tool_name(name)

    if isinstance(source, dspy.Tool):
        if name is None and description is None and arg_descriptions is None:
            tool = source
        else:
            args = copy.deepcopy(source.args or {})
            descriptions = (
                dict(arg_descriptions)
                if arg_descriptions is not None
                else dict(source.arg_desc or {})
            )
            _apply_arg_descriptions(args, descriptions)
            tool = dspy.Tool(
                source.func,
                name=name or source.name,
                desc=description or source.desc,
                args=args,
                arg_types=dict(source.arg_types or {}),
                arg_desc=descriptions,
            )
    else:
        tool = dspy.Tool(
            source,
            name=name,
            desc=description,
            arg_desc=(dict(arg_descriptions) if arg_descriptions else None),
        )

    if arg_descriptions is not None:
        _apply_arg_descriptions(tool.args or {}, dict(arg_descriptions))
    _validate_dspy_tool(tool)
    return tool


def clone_dspy_tool(
    tool: dspy.Tool,
    function: Callable[..., Any],
) -> dspy.Tool:
    """Create a validated tool around a replacement callable while preserving the source tool's schema and metadata.
    
    Parameters:
    	tool (dspy.Tool): Tool whose name, description, argument schema, types, and descriptions are preserved.
    	function (Callable[..., Any]): Callable used by the cloned tool.
    
    Returns:
    	dspy.Tool: The validated tool wrapping the replacement callable.
    """
    cloned = dspy.Tool(
        function,
        name=tool.name,
        desc=tool.desc,
        args=copy.deepcopy(tool.args or {}),
        arg_types=dict(tool.arg_types or {}),
        arg_desc=dict(tool.arg_desc or {}),
    )
    _validate_dspy_tool(cloned)
    return cloned


def is_async_tool(tool: dspy.Tool) -> bool:
    """Return whether a Tool wraps an async callable."""
    return inspect.iscoroutinefunction(_callable_target(tool.func))


def _validate_dspy_tool(tool: dspy.Tool) -> None:
    """
    Validate that a DSPy tool has a valid name, description, callable signature, return annotation, and concrete argument types.
    
    Parameters:
        tool (dspy.Tool): The tool to validate.
    """
    if not isinstance(tool.name, str):
        raise TypeError("dspy.Tool name must be a string")
    name = _validate_tool_name(tool.name)
    if name in RESERVED_TOOL_NAMES:
        raise ValueError(f"tool name {name!r} is reserved by ReActV2")
    if not str(tool.desc or "").strip():
        raise ValueError(f"tool {name!r} must have a description or docstring")
    unsupported = _unsupported_parameters(tool.func)
    if unsupported:
        parameters = ", ".join(unsupported)
        raise TypeError(
            f"tool {name!r} has unsupported parameter(s): {parameters}; "
            "DSPy tools must expose explicit keyword-callable parameters"
        )

    target = _callable_target(tool.func)
    return_type = get_type_hints(target).get("return", Any)
    if return_type is Any:
        raise TypeError(f"tool {name!r} must declare a concrete return annotation")

    args = tool.args or {}
    arg_types = tool.arg_types or {}
    untyped = [
        argument
        for argument in args
        if argument not in arg_types or arg_types[argument] is Any
    ]
    if untyped:
        arguments = ", ".join(sorted(untyped))
        raise TypeError(
            f"tool {name!r} has untyped argument(s): {arguments}; "
            "add concrete Python annotations so DSPy can build a real schema"
        )


def _validate_tool_name(name: str) -> str:
    """
    Validate and return a tool name.
    
    Parameters:
        name (str): The tool name to validate.
    
    Returns:
        str: The validated tool name.
    
    Raises:
        ValueError: If the name contains surrounding whitespace or uses invalid characters or length.
    """
    normalized = name.strip()
    if normalized != name:
        raise ValueError("tool names must not contain surrounding whitespace")
    if not _TOOL_NAME_RE.fullmatch(normalized):
        raise ValueError(
            "tool names must be 1-64 characters using only letters, numbers, "
            "underscores, or hyphens"
        )
    return normalized


def _callable_target(function: Callable[..., Any]) -> Callable[..., Any]:
    """
    Resolve the callable used for signature and annotation inspection.
    
    Parameters:
    	function (Callable[..., Any]): A function, bound method, or callable object.
    
    Returns:
    	Callable[..., Any]: The function or method itself, or the callable object's class-level ``__call__`` method.
    """
    if inspect.isfunction(function) or inspect.ismethod(function):
        return function
    return type(function).__call__


def _unsupported_parameters(function: Callable[..., Any]) -> list[str]:
    """Identify parameter names with unsupported calling conventions.
    
    Returns:
    	list[str]: Names of positional-only, variadic positional, or variadic keyword parameters.
    """
    signature = inspect.signature(_callable_target(function))
    unsupported_kinds = {
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.VAR_POSITIONAL,
        inspect.Parameter.VAR_KEYWORD,
    }
    return [
        parameter.name
        for parameter in signature.parameters.values()
        if parameter.kind in unsupported_kinds
    ]


def _apply_arg_descriptions(
    args: dict[str, Any],
    descriptions: Mapping[str, str],
) -> None:
    """
    Apply validated descriptions to the corresponding argument definitions.
    
    Parameters:
    	args (dict[str, Any]): Argument definitions to update.
    	descriptions (Mapping[str, str]): Descriptions keyed by argument name.
    
    Raises:
    	ValueError: If a description references an unknown argument or contains only whitespace.
    """
    unknown = set(descriptions).difference(args)
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ValueError(f"argument description refers to unknown argument(s): {names}")

    for argument, description in descriptions.items():
        normalized = description.strip()
        if not normalized:
            raise ValueError(f"argument description for {argument!r} must not be empty")
        args[argument]["description"] = normalized
