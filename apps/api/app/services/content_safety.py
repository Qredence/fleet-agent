"""Emission-time secret scrubbing for public agent text.

Structural companion to ``history_safety``: the contract layer guarantees
that no reasoning-shaped *payload* crosses the API boundary, and this module
adds a content-level guarantee for the free text the model writes
(``answer``, ``process_summary``, ``key_decisions``, ``caveats``), for
tool-argument/result previews, and for artifact content.

Behavior-preserving by design: model observations and DSPy history stay
untouched — only text on its way to the browser or to persistent public
state is scrubbed. High-precision provider-token patterns only: there are
deliberately no generic base64/hex guesses, because false positives would
corrupt legitimate answers. Source titles/excerpts (external web content,
already bounded) are displayed as-is, like a browser rendering a page.
"""

from __future__ import annotations

import re
from typing import Any

# Ordered high-precision patterns. The generic assignment pattern runs last
# so named-format tokens (sk-/AKIA/...) are fully masked before value
# detection sees their remnants.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    # PEM private key blocks (any algorithm), including the envelope lines.
    re.compile(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
        re.DOTALL,
    ),
    # OpenAI / OpenRouter / Anthropic-style keys. The leading \b keeps the
    # pattern from firing inside ordinary words ("task-oriented-...").
    re.compile(r"\bsk-(?:ant-|or-)?[A-Za-z0-9_-]{16,}"),
    # AWS access key ids.
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    # Google API keys.
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    # GitHub tokens (classic and fine-grained).
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    # Slack tokens.
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    # JWTs: two base64url eyJ-prefixed segments plus the signature.
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    # Bearer credentials in Authorization-style text.
    re.compile(r"\bBearer[ \t]+[A-Za-z0-9._~+/-]{20,}={0,2}", re.IGNORECASE),
    # Explicit credential assignments: a credential-shaped key name followed
    # by a long secret-shaped value. Spaces inside the value break the match,
    # which keeps ordinary sentences intact.
    re.compile(
        r"\b(?:api[_-]?key|apikey|secret|access[_-]?token|auth[_-]?token|"
        r"password|passwd|pwd)\b['\"]?[ \t]*[:=][ \t]*['\"]?[A-Za-z0-9_+/=-]{16,}",
        re.IGNORECASE,
    ),
)

_MASK = "[redacted]"


def scrub_public_text(value: str) -> str:
    """Mask high-precision secret patterns in text bound for the browser.

    The mask contains no quotes, backslashes, or control characters, so
    scrubbing a JSON-encoded string keeps it valid JSON.
    """
    scrubbed = value
    for pattern in _SECRET_PATTERNS:
        scrubbed = pattern.sub(_MASK, scrubbed)
    return scrubbed


def scrub_public_lines(values: list[str]) -> list[str]:
    """Scrub every line (model-written decisions, caveats)."""
    return [scrub_public_text(value) for value in values]


def scrub_json_strings(value: Any) -> Any:
    """Scrub every string in a JSON-like structure (used on legacy state).

    The container shape is preserved: dicts keep their keys, lists keep
    their length, scalars pass through untouched.
    """
    if isinstance(value, str):
        return scrub_public_text(value)
    if isinstance(value, list):
        return [scrub_json_strings(item) for item in value]
    if isinstance(value, dict):
        return {key: scrub_json_strings(item) for key, item in value.items()}
    return value


# Hold-back window for streamed text: no text is emitted until at least this
# many characters are confirmed complete, so a secret split across deltas is
# caught before any of its fragments reach the browser.
_STREAM_HOLDBACK_CHARS = 80

# Anchor prefixes that could still complete into a secret pattern.  While any
# unresolved anchor is pending (the scrubber has not masked it away), the
# stream holds back from its position: prefix-closed patterns like
# ``sk-<unbounded>`` cannot be disproved until more text arrives or the field
# ends.  Every pattern in ``_SECRET_PATTERNS`` must start with one of these
# anchors, which is what makes the emitted prefix stable.  Benign anchors
# (``Bearer of...``, ``the password field``) simply lag until flush instead
# of leaking a partial secret.
_STREAM_ANCHORS = (
    "-----begin",
    "sk-",
    "akia",
    "aiza",
    "ghp_",
    "gho_",
    "ghu_",
    "ghs_",
    "ghr_",
    "github_pat_",
    "xox",
    "eyj",
    "bearer",
    "apikey",
    "api_key",
    "api-key",
    "secret",
    "accesstoken",
    "access_token",
    "access-token",
    "authtoken",
    "auth_token",
    "auth-token",
    "password",
    "passwd",
    "pwd",
)


class StreamingScrubber:
    """Emission-time scrubbing for token streams.

    Token deltas arrive before the full field text is known, so a secret can
    be split across deltas.  The scrubber emits only stable prefixes of the
    scrubbed text: up to the first secret anchor the scrubber has not yet
    masked away (masked secrets leave no anchor text), minus a partial-anchor
    prefix at the boundary and a small holdback window.  When a growing
    secret completes, its mask is emitted in place without ever emitting the
    secret itself.  ``flush`` returns the final remainder with the same
    semantics as a full-text scrub, so the concatenation of everything
    emitted always equals ``scrub_public_text(full_text)``.  Benign anchors
    (``Bearer of...``, ``the password field``) merely lag until flush.
    """

    def __init__(self, *, holdback_chars: int = _STREAM_HOLDBACK_CHARS) -> None:
        if holdback_chars < 0:
            raise ValueError("holdback_chars must not be negative")
        self._holdback = holdback_chars
        self._pending = ""
        self._emitted = 0

    def push(self, delta: str) -> str:
        """Accept one delta and return the text that is now safe to emit."""
        self._pending += delta
        return self._release_locked()

    def flush(self) -> str:
        """Emit everything still held back (end of the field's stream)."""
        scrubbed = scrub_public_text(self._pending)
        remainder = scrubbed[self._emitted :]
        self._emitted = len(scrubbed)
        return remainder

    def _release_locked(self) -> str:
        scrubbed = scrub_public_text(self._pending)
        stable = len(scrubbed) - self._holdback
        if stable <= 0:
            return ""
        # An anchor still visible in the scrubbed text is benign or a secret
        # still being received; either way nothing from it onward is stable.
        scrubbed_lower = scrubbed.lower()
        for anchor in _STREAM_ANCHORS:
            index = scrubbed_lower.find(anchor)
            if index != -1:
                stable = min(stable, index)
        if stable <= 0:
            return ""
        stable = self._partial_anchor_hold(scrubbed_lower, stable)
        if stable <= self._emitted:
            return ""
        remainder = scrubbed[self._emitted : stable]
        self._emitted = stable
        return remainder

    @staticmethod
    def _partial_anchor_hold(scrubbed_lower: str, stable: int) -> int:
        """Hold back anchor or mask prefixes that straddle the emit boundary.

        ``...the pass`` could continue into ``password = <secret>`` with the
        next delta, so a fragment ending at the boundary that is a proper
        prefix of an anchor must not be emitted yet.  A boundary inside the
        ``[redacted]`` mask would split it across emissions, so mask
        prefixes hold too.  Retreating exposes a new boundary, so this
        repeats to a fixpoint.  Together with the anchor scan this makes the
        emitted concatenation equal the batch scrub of the full text for
        every possible delta split.
        """
        window = (
            max(
                max(len(anchor) for anchor in _STREAM_ANCHORS),
                len(_MASK),
            )
            - 1
        )
        while stable > 0:
            retreat = 0
            for length in range(min(window, stable), 0, -1):
                fragment = scrubbed_lower[stable - length : stable]
                if any(anchor.startswith(fragment) for anchor in _STREAM_ANCHORS):
                    retreat = length
                    break
                if _MASK.startswith(fragment):
                    retreat = length
                    break
            if retreat == 0:
                return stable
            stable -= retreat
        return stable
