"""Typed tools exposed to ReActV2.

Rules (plan 6.4): synchronous, simple domain returns, bounded strings,
controlled failures (raise -> ReActV2 converts to an error observation).
"""

from datetime import UTC, datetime

from app.agent.tools.corpus import CORPUS
from app.contracts.domain import SourceResult

_MAX_SECONDS_RETURNED = 3
_MAX_EXCERPT_CHARS = 300
_MAX_RESULT_CHARS = 1200


class SearchDocsTool:
    """search_docs as a callable object so the instrumented wrapper can read
    the sources it produced (per-run instance — no cross-run leakage).

    `__name__`/`__doc__` are set explicitly: ReActV2 and the instrumented
    wrapper introspect plain functions, and callable objects don't carry
    those attributes by default.
    """

    def __init__(self) -> None:
        self.__name__ = "search_docs"
        self.__doc__ = SearchDocsTool.__call__.__doc__
        self.last_sources: list[SourceResult] = []

    def __call__(self, query: str) -> str:
        """Search the bundled documentation corpus for a short query.

        Returns up to three brief excerpts (title plus text), best matches first.
        """
        query_terms = {term.strip(".,;:!?").lower() for term in query.split() if term}
        scored: list[tuple[int, dict[str, str | None]]] = []
        for chunk in CORPUS:
            haystack = f"{chunk['title']} {chunk['text']}".lower()
            score = sum(1 for term in query_terms if term in haystack)
            if score:
                scored.append((score, chunk))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        top = scored[:_MAX_SECONDS_RETURNED]

        self.last_sources = [
            SourceResult(
                id=str(chunk["id"]),
                title=str(chunk["title"]),
                source_type=str(chunk["source_type"]),
                uri=chunk["uri"] if isinstance(chunk["uri"], str) else None,
                excerpt=str(chunk["text"])[:_MAX_EXCERPT_CHARS],
                metadata={},
            )
            for _, chunk in top
        ]

        if not top:
            return "No documentation matched the query."

        parts = [
            f"* {chunk['title']}: {str(chunk['text'])[:_MAX_EXCERPT_CHARS]}"
            for _, chunk in top
        ]
        return "\n".join(parts)[:_MAX_RESULT_CHARS]


_search_docs_default = SearchDocsTool()


def search_docs(query: str) -> str:
    """Search the bundled documentation corpus for a short query.

    Returns up to three brief excerpts (title plus text), best matches first.
    """
    return _search_docs_default(query)


def get_current_time() -> str:
    """Return the current UTC date and time in ISO 8601 format."""
    return datetime.now(UTC).isoformat(timespec="seconds")
