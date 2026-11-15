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
from dataclasses import dataclass
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
    # Explicit credential assignments: preserve the key name, delimiter, and
    # optional opening quote (group 1) while redacting the secret value so
    # JSON payloads (e.g. ``{"api_key": "..."}``) stay valid JSON.
    re.compile(
        r"(\b(?:api[_-]?key|apikey|secret|access[_-]?token|auth[_-]?token|"
        r"password|passwd|pwd)\b['\"]?[ \t]*[:=][ \t]*['\"]?)[A-Za-z0-9_+/=-]{16,}",
        re.IGNORECASE,
    ),
)

_MASK = "[redacted]"


def _redact_match(match: re.Match[str]) -> str:
    if match.lastindex:
        return f"{match.group(1)}{_MASK}"
    return _MASK


def scrub_public_text(value: str) -> str:
    """Mask high-precision secret patterns in text bound for the browser.

    The mask contains no quotes, backslashes, or control characters, so
    scrubbing a JSON-encoded string keeps it valid JSON.
    """
    scrubbed = value
    for pattern in _SECRET_PATTERNS:
        scrubbed = pattern.sub(_redact_match, scrubbed)
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


# Anchor prefixes that could still complete into a secret pattern.  While an
# unresolved candidate anchor is still a valid open prefix of a secret pattern,
# the stream holds back from its position.  Once subsequent characters disprove
# it (e.g. ``Bearer of `` or ``the password policy``) or a word-boundary check
# rejects it upfront (e.g. ``task-oriented``), it expires and streaming resumes
# without waiting for flush.
@dataclass(frozen=True, slots=True)
class _AnchorPrefix:
    text: str
    word_start: bool = True
    ignore_case: bool = False


@dataclass(frozen=True, slots=True)
class _CandidateSpec:
    start: re.Pattern[str]
    live_prefix: re.Pattern[str]


_STREAM_ANCHOR_PREFIXES: tuple[_AnchorPrefix, ...] = (
    _AnchorPrefix("-----BEGIN", word_start=False),
    _AnchorPrefix("sk-"),
    _AnchorPrefix("AKIA"),
    _AnchorPrefix("AIza"),
    _AnchorPrefix("ghp_"),
    _AnchorPrefix("gho_"),
    _AnchorPrefix("ghu_"),
    _AnchorPrefix("ghs_"),
    _AnchorPrefix("ghr_"),
    _AnchorPrefix("github_pat_"),
    _AnchorPrefix("xox"),
    _AnchorPrefix("eyJ"),
    _AnchorPrefix("bearer", ignore_case=True),
    _AnchorPrefix("apikey", ignore_case=True),
    _AnchorPrefix("api_key", ignore_case=True),
    _AnchorPrefix("api-key", ignore_case=True),
    _AnchorPrefix("secret", ignore_case=True),
    _AnchorPrefix("accesstoken", ignore_case=True),
    _AnchorPrefix("access_token", ignore_case=True),
    _AnchorPrefix("access-token", ignore_case=True),
    _AnchorPrefix("authtoken", ignore_case=True),
    _AnchorPrefix("auth_token", ignore_case=True),
    _AnchorPrefix("auth-token", ignore_case=True),
    _AnchorPrefix("password", ignore_case=True),
    _AnchorPrefix("passwd", ignore_case=True),
    _AnchorPrefix("pwd", ignore_case=True),
)

_MAX_ANCHOR_PREFIX_LEN = (
    max(
        max(len(anchor.text) for anchor in _STREAM_ANCHOR_PREFIXES),
        len(_MASK),
    )
    - 1
)

_CANDIDATE_SPECS: tuple[_CandidateSpec, ...] = (
    _CandidateSpec(
        re.compile(r"-----BEGIN"),
        re.compile(
            r"(?:-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*"
            r"|-----BEGIN(?: [A-Z0-9 ]*(?:PRIVATE KEY-{1,4})?)?)",
            re.DOTALL,
        ),
    ),
    _CandidateSpec(
        re.compile(r"\bsk-"),
        re.compile(r"sk-[A-Za-z0-9_-]*"),
    ),
    _CandidateSpec(
        re.compile(r"\bAKIA"),
        re.compile(r"AKIA[0-9A-Z]{0,16}"),
    ),
    _CandidateSpec(
        re.compile(r"\bAIza"),
        re.compile(r"AIza[0-9A-Za-z_-]{0,35}"),
    ),
    _CandidateSpec(
        re.compile(r"\bgh[pousr]_"),
        re.compile(r"gh[pousr]_[A-Za-z0-9]*"),
    ),
    _CandidateSpec(
        re.compile(r"\bgithub_pat_"),
        re.compile(r"github_pat_[A-Za-z0-9_]*"),
    ),
    _CandidateSpec(
        re.compile(r"\bxox"),
        re.compile(r"xox(?:[abprs](?:-[A-Za-z0-9-]*)?)?"),
    ),
    _CandidateSpec(
        re.compile(r"\beyJ"),
        re.compile(
            r"eyJ[A-Za-z0-9_-]*(?:\.(?:e(?:y(?:J[A-Za-z0-9_-]*(?:\.[A-Za-z0-9_-]*)?)?)?)?)?"
        ),
    ),
    _CandidateSpec(
        re.compile(r"\bBearer", re.IGNORECASE),
        re.compile(
            r"Bearer(?:[ \t]+(?:[A-Za-z0-9._~+/-]+={0,2})?)?",
            re.IGNORECASE,
        ),
    ),
    _CandidateSpec(
        re.compile(
            r"\b(?:api[_-]?key|apikey|secret|access[_-]?token|auth[_-]?token|"
            r"password|passwd|pwd)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:api[_-]?key|apikey|secret|access[_-]?token|auth[_-]?token|"
            r"password|passwd|pwd)"
            r"(?:['\"]?[ \t]*(?:[:=][ \t]*['\"]?[A-Za-z0-9_+/=-]*)?)?",
            re.IGNORECASE,
        ),
    ),
)

# Patterns whose trailing \b allows a match at EOF to un-match if a word
# character arrives in the next delta (relevant for small holdbacks).
_BOUNDED_TRAILING_PATTERNS: tuple[re.Pattern[str], ...] = (
    _SECRET_PATTERNS[2],
    _SECRET_PATTERNS[3],
    _SECRET_PATTERNS[4],
    _SECRET_PATTERNS[5],
    _SECRET_PATTERNS[6],
    _SECRET_PATTERNS[7],
)

_WORD_CHAR_RE = re.compile(r"\w")


class StreamingScrubber:
    """Emission-time scrubbing for token streams.

    Token deltas arrive before the full field text is known, so a secret can
    be split across deltas.  The scrubber emits only stable prefixes of the
    scrubbed text: up to the first unresolved candidate secret anchor, minus a
    partial-anchor prefix at the end of the pending buffer and a small holdback
    window.  When a growing secret completes, its mask is emitted in place
    without ever emitting the secret itself.  When an anchor is disproved by
    subsequent characters (e.g. ``Bearer of `` or ``password policy``), it
    expires and streaming resumes without waiting for flush.
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
        if stable <= self._emitted:
            return ""
        # A bounded-token match touching EOF could still un-match if the next
        # delta appends a word character; hold the trailing mask until resolved.
        for pattern in _BOUNDED_TRAILING_PATTERNS:
            for match in pattern.finditer(self._pending):
                if match.end() == len(self._pending):
                    stable = min(stable, len(scrubbed) - len(_MASK))
                    break
        if stable <= self._emitted:
            return ""
        for spec in _CANDIDATE_SPECS:
            for match in spec.start.finditer(scrubbed, self._emitted):
                idx = match.start()
                if idx >= stable:
                    break
                if spec.live_prefix.fullmatch(scrubbed, idx) is not None:
                    stable = idx
                    break
        if stable <= self._emitted:
            return ""
        stable = self._partial_anchor_hold(scrubbed, stable, self._emitted)
        if stable <= self._emitted:
            return ""
        remainder = scrubbed[self._emitted : stable]
        self._emitted = stable
        return remainder

    @staticmethod
    def _partial_anchor_hold(scrubbed: str, stable: int, start_floor: int) -> int:
        """Hold back partial anchor prefixes at EOF and unsplit masks."""
        # Do not split an already-materialized ``[redacted]`` mask across deltas.
        search_from = max(start_floor, stable - len(_MASK) + 1)
        search_to = min(len(scrubbed), stable + len(_MASK) - 1)
        idx = scrubbed.find(_MASK, search_from, search_to)
        if idx != -1 and idx < stable < idx + len(_MASK):
            stable = idx

        tail_start = max(start_floor, len(scrubbed) - _MAX_ANCHOR_PREFIX_LEN)
        for pos in range(tail_start, min(stable, len(scrubbed))):
            tail = scrubbed[pos:]
            at_word_boundary = (
                pos == 0 or _WORD_CHAR_RE.match(scrubbed[pos - 1]) is None
            )
            for anchor in _STREAM_ANCHOR_PREFIXES:
                if len(tail) >= len(anchor.text):
                    continue
                if anchor.word_start and not at_word_boundary:
                    continue
                if anchor.ignore_case:
                    if anchor.text.startswith(tail.lower()):
                        return pos
                elif anchor.text.startswith(tail):
                    return pos
        return stable
