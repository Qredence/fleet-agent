"""Name-based registries for python tools and reward functions.

The spec binds a tool by NAME only: the description always comes from the
python docstring, so tool metadata is never duplicated in YAML. Tools are built
through the project's validated ``app.agent.tooling.create_dspy_tool`` when it
is importable; plain ``dspy.Tool`` keeps this package usable on its own.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

import dspy

from app.agent.spec.schema import fail

type ToolSource = Callable[..., Any] | dspy.Tool
type ToolInput = Mapping[str, ToolSource] | Iterable[ToolSource]
type RewardFn = Callable[[dict[str, Any], Any], float]
type RewardInput = Mapping[str, RewardFn] | Iterable[RewardFn]


def _name_of(source: object) -> str:
    """Return the registry name one python source is keyed by."""
    if isinstance(source, dspy.Tool):
        return str(source.name)
    return str(getattr(source, "__name__", type(source).__name__))


def _entries[T](sources: Mapping[str, T] | Iterable[T]) -> Iterable[tuple[str, T]]:
    """Yield ``(name, value)`` pairs for a mapping or a plain iterable."""
    if isinstance(sources, Mapping):
        return sources.items()
    return ((_name_of(source), source) for source in sources)


def build_dspy_tool(source: ToolSource, name: str) -> dspy.Tool:
    """Build the real ``dspy.Tool`` for one registered python source."""
    try:
        from app.agent.tooling import create_dspy_tool
    except ImportError:  # standalone use: no app package on the path
        return dspy.Tool(source, name=name)
    return create_dspy_tool(source, name=name)


class ToolRegistry:
    """Resolve a declared tool name to a python callable and a ``dspy.Tool``."""

    def __init__(self, tools: ToolInput = ()) -> None:
        self._sources: dict[str, ToolSource] = {}
        for name, source in _entries(tools):
            self.register(name, source)

    @classmethod
    def coerce(cls, tools: ToolRegistry | ToolInput | None) -> ToolRegistry:
        """Return a registry for any accepted tool input; ``None`` is empty."""
        if isinstance(tools, ToolRegistry):
            return tools
        return cls(() if tools is None else tools)

    def register(self, name: str, source: ToolSource) -> None:
        """Register one trusted python callable under its model-visible name."""
        if not name or name.strip() != name:
            fail(f"invalid tool name {name!r}")
        if name in self._sources:
            fail(f"python tool {name!r} is already registered")
        self._sources[name] = source

    def names(self) -> tuple[str, ...]:
        """Return the registered tool names, in registration order."""
        return tuple(self._sources)

    def __contains__(self, name: object) -> bool:
        return name in self._sources

    def resolve(self, name: str) -> dspy.Tool:
        """Return the tool for ``name``; an unknown name raises SpecError."""
        source = self._sources.get(name)
        if source is None:
            fail(f"unknown python tool {name!r}")
        return build_dspy_tool(source, name)


class RewardRegistry:
    """Resolve a declared reward name to the function Refine/BestOfN call."""

    def __init__(self, rewards: RewardInput = ()) -> None:
        self._rewards: dict[str, RewardFn] = {}
        for name, reward in _entries(rewards):
            self.register(name, reward)

    @classmethod
    def coerce(cls, rewards: RewardRegistry | RewardInput | None) -> RewardRegistry:
        """Return a registry for any accepted reward input; ``None`` is empty."""
        if isinstance(rewards, RewardRegistry):
            return rewards
        return cls(() if rewards is None else rewards)

    def register(self, name: str, reward: RewardFn) -> None:
        """Register one reward function under the name the spec binds."""
        if not name or name.strip() != name:
            fail(f"invalid reward name {name!r}")
        if name in self._rewards:
            fail(f"reward function {name!r} is already registered")
        self._rewards[name] = reward

    def names(self) -> tuple[str, ...]:
        """Return the registered reward names, in registration order."""
        return tuple(self._rewards)

    def __contains__(self, name: object) -> bool:
        return name in self._rewards

    def resolve(self, name: str) -> RewardFn:
        """Return the reward function; an unknown name raises SpecError."""
        reward = self._rewards.get(name)
        if reward is None:
            fail(f"unknown reward function {name!r}")
        return reward
