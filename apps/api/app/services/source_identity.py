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


def disambiguated_source_id(source_id: str, identity_key: str) -> str:
    """Keep legacy IDs stable and suffix only an intra-thread collision."""

    return f"{source_id}-{sha256(identity_key.encode()).hexdigest()[:10]}"
