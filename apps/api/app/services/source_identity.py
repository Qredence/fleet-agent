"""Canonical source identity shared by the public reducer and persistence."""

from hashlib import sha256
from urllib.parse import urlsplit, urlunsplit

from app.contracts.domain import SourceResult


def canonical_source_key(source: SourceResult | dict[str, object]) -> str:
    uri = source.get("uri") if isinstance(source, dict) else source.uri
    source_id = source.get("id") if isinstance(source, dict) else source.id
    if isinstance(uri, str) and uri.strip():
        parts = urlsplit(uri.strip())
        scheme = (parts.scheme or "https").lower()
        netloc = parts.netloc.lower()
        path = parts.path.rstrip("/")
        return urlunsplit((scheme, netloc, path, parts.query, ""))
    return f"id:{source_id}"


def public_source_id(
    source: SourceResult | dict[str, object], *, thread_id: str
) -> str:
    """Return a stable, thread-scoped identifier without exposing a hash key."""

    raw_id = source.get("id") if isinstance(source, dict) else source.id
    key = canonical_source_key(source)
    digest = sha256(f"{thread_id}\x00{key}".encode()).hexdigest()[:12]
    if isinstance(raw_id, str) and raw_id:
        return f"{raw_id}-{digest}"
    return f"source-{digest}"


def disambiguated_source_id(source_id: str, identity_key: str) -> str:
    """Keep legacy IDs stable and suffix only an intra-thread collision."""

    return f"{source_id}-{sha256(identity_key.encode()).hexdigest()[:10]}"
