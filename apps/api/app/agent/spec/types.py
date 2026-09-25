"""The closed set of declarative module types, as real DSPy classes.

Every type in ``schema.MODULE_TYPES`` has exactly one class here, and
``MODULE_REGISTRY`` is the only place a YAML type name becomes executable code:
adding a module type is a code change in this file and in the schema rules.

A node carries the contract its parent wires it by: ``declared_inputs``,
``produced``, and the optimizer-facing ``dump_state`` / ``apply_state`` pair
keyed by ``named_predictors()`` paths. Constructors take the keyword names the
YAML declares (``n``, ``reward``, ``threshold``, ``max_iters``). One signature
class is built per step, never shared, because ``Signature.instructions`` lives
on the class itself.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

import dspy

from app.agent.spec.schema import MODULE_TYPES, fail

if TYPE_CHECKING:
    from app.agent.spec.schema import AgentSpec

type SignatureClass = type[dspy.Signature]

STATE_KEYS: frozenset[str] = frozenset({"metadata", "structure_hash"})
"""Keys of a dumped state that hold state identity, not predictor paths."""

CONTRACT_ATTRIBUTES: frozenset[str] = frozenset(
    {"agent_spec", "child_names", "declared_inputs", "produced", "structure_hash"}
)
"""Attributes every node carries; a child module name must not shadow them."""

type RewardFn = Callable[[dict[str, Any], Any], float]


def _bind(module: Node, namespace: Mapping[str, Any], name: str) -> dict[str, Any]:
    """Select one child's declared inputs out of the shared namespace."""
    missing = [key for key in module.declared_inputs if key not in namespace]
    if missing:
        fail(f"module {name!r} needs {missing}, namespace has {sorted(namespace)}")
    return {key: namespace[key] for key in module.declared_inputs}


def _declare(node: Node, signature: SignatureClass) -> None:
    """Record one leaf node's field contract from its own signature class."""
    node.declared_inputs = list(signature.input_fields)
    node.produced = list(signature.output_fields)


def _check_child_names(node: Node, children: Mapping[str, Node]) -> None:
    """Refuse a child name that would shadow a DSPy or contract attribute.

    Children are real module attributes, so their optimizer paths read like the
    YAML; checking the live instance is what makes those names safe.
    """
    shadowed = CONTRACT_ATTRIBUTES | STATE_KEYS | frozenset(dir(node))
    for name in children:
        if not name.isidentifier() or name.startswith("_"):
            fail(f"module name {name!r} must be a public python identifier")
        if name in shadowed:
            fail(f"module name {name!r} collides with a dspy.Module attribute")


class Node(dspy.Module):  # type: ignore[misc]  # dspy is untyped
    """Base class of every node: the declarative contract and its state."""

    declared_inputs: list[str]
    produced: list[str]
    agent_spec: AgentSpec
    structure_hash: str

    def dump_state(self, json_mode: bool = True) -> dict[str, Any]:
        """Return dspy-native state per predictor path plus the fingerprint."""
        from app.agent.spec.loader import dump_state  # deferred: loader builds nodes

        return dump_state(self, json_mode=json_mode)

    def apply_state(self, state: dict[str, Any]) -> list[str]:
        """Write saved state into this program and return the rewritten paths."""
        from app.agent.spec.loader import apply_state  # deferred: loader builds nodes

        return apply_state(self, state)


class Predict(Node, dspy.Predict):  # type: ignore[misc]  # dspy is untyped
    """One LM call over the declared signature."""

    def __init__(self, signature: SignatureClass) -> None:
        super().__init__(signature)
        _declare(self, signature)


class ChainOfThought(Node, dspy.ChainOfThought):  # type: ignore[misc]  # dspy is untyped
    """One reasoning step, then one LM call for the declared outputs."""

    def __init__(self, signature: SignatureClass) -> None:
        super().__init__(signature)
        _declare(self, signature)


class React(Node, dspy.ReActV2):  # type: ignore[misc]  # dspy is untyped
    """A bounded reason-act loop over the tools the spec bound by name."""

    def __init__(
        self, signature: SignatureClass, *, tools: list[dspy.Tool], max_iters: int
    ) -> None:
        super().__init__(signature, tools=tools, max_iters=max_iters)
        _declare(self, signature)


class Refine(Node, dspy.Refine):  # type: ignore[misc]  # dspy is untyped
    """Re-run one predict step until the reward passes or n attempts are spent."""

    def __init__(
        self, signature: SignatureClass, *, n: int, reward: RewardFn, threshold: float
    ) -> None:
        super().__init__(Predict(signature), N=n, reward_fn=reward, threshold=threshold)
        _declare(self, signature)


class BestOfN(Node, dspy.BestOfN):  # type: ignore[misc]  # dspy is untyped
    """Run one predict step up to n times and keep the best rewarded output."""

    def __init__(
        self, signature: SignatureClass, *, n: int, reward: RewardFn, threshold: float
    ) -> None:
        super().__init__(Predict(signature), N=n, reward_fn=reward, threshold=threshold)
        _declare(self, signature)


class Composite(Node):
    """Base class for nodes whose children run against one namespace.

    Children are real attributes, so optimizer paths read like the YAML
    (``route``, ``reviews.risk``) instead of ``steps['route']``; the loader
    rejects child names that would shadow a node or DSPy attribute.
    """

    def __init__(self, children: Mapping[str, Node], *, sequential: bool) -> None:
        super().__init__()
        _check_child_names(self, children)
        self.child_names = tuple(children)
        declared: list[str] = []
        produced: list[str] = []
        for name, child in children.items():
            setattr(self, name, child)
            for key in child.declared_inputs:
                if key not in declared and not (sequential and key in produced):
                    declared.append(key)
            for key in child.produced:
                if key not in produced:
                    produced.append(key)
        self.declared_inputs = declared
        self.produced = produced

    def child(self, name: str) -> Node:
        """Return the child module declared under ``name``."""
        child = getattr(self, name)
        if not isinstance(child, Node):
            fail(f"child module {name!r} is not a spec node")
        return child


class Sequential(Composite):
    """Run child modules in order, merging each output into the namespace."""

    def __init__(self, steps: Mapping[str, Node]) -> None:
        super().__init__(steps, sequential=True)

    def forward(self, **inputs: Any) -> dspy.Prediction:
        namespace: dict[str, Any] = dict(inputs)
        for name in self.child_names:
            child = self.child(name)
            namespace.update(child(**_bind(child, namespace, name)).toDict())
        return dspy.Prediction(**namespace)


class Fanout(Composite):
    """Run child modules concurrently over one namespace, then merge them.

    ``dspy.Parallel`` is created per call so it reads the current
    ``settings.num_threads``. Its straggler timeout is disabled on purpose:
    dspy would otherwise resubmit a slow branch and duplicate its LM calls and
    tool side effects.
    """

    def __init__(self, branches: Mapping[str, Node]) -> None:
        super().__init__(branches, sequential=False)

    def forward(self, **inputs: Any) -> dspy.Prediction:
        namespace: dict[str, Any] = dict(inputs)
        children = [(name, self.child(name)) for name in self.child_names]
        pairs = [(child, _bind(child, namespace, name)) for name, child in children]
        if len(pairs) == 1:
            results: list[Any] = [pairs[0][0](**pairs[0][1])]
        else:
            run = dspy.Parallel(
                disable_progress_bar=True, timeout=0, return_failed_examples=True
            )
            results, _, failures = run(pairs)
            if failures:
                raise failures[0]
        for (name, child), result in zip(children, results, strict=True):
            if result is None:
                fail(f"branch {name!r} produced no prediction")
            pred_dict = result.toDict()
            for key in child.produced:
                if key not in pred_dict:
                    fail(f"branch {name!r} did not produce declared field {key!r}")
                if key in namespace:
                    fail(f"branch {name!r} would overwrite field {key!r}")
                namespace[key] = pred_dict[key]
        return dspy.Prediction(**namespace)


MODULE_REGISTRY: dict[str, type[Node]] = {
    "predict": Predict,
    "chain_of_thought": ChainOfThought,
    "react": React,
    "refine": Refine,
    "best_of_n": BestOfN,
    "sequential": Sequential,
    "fanout": Fanout,
}
"""One class per type in ``schema.MODULE_TYPES``; the loader builds only these."""

if set(MODULE_REGISTRY) != set(MODULE_TYPES):  # import-time drift guard
    raise RuntimeError("MODULE_REGISTRY and schema.MODULE_TYPES disagree")
