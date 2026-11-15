"""Validated message-scoped projections of authoritative public state."""

import json
import logging
import re
from collections.abc import Mapping
from typing import Any, cast
from urllib.parse import urlsplit

from pydantic import ValidationError

from app.contracts.inline_card import InlineCard
from app.kernel.content_safety import scrub_json_strings

logger = logging.getLogger(__name__)
_QUERY_KEY_PATTERN = re.compile(r'"query"\s*:\s*')


def _clamp_card_ids(value: Any) -> Any:
    if isinstance(value, Mapping):
        clamped: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"id", "sourceId"} and isinstance(item, str):
                clamped[key] = item[:128]
            else:
                clamped[key] = _clamp_card_ids(item)
        return clamped
    if isinstance(value, list):
        return [_clamp_card_ids(item) for item in value]
    return value


def _safe_hostname(uri: Any) -> str:
    if not isinstance(uri, str) or not uri:
        return ""
    try:
        return urlsplit(uri).hostname or ""
    except ValueError:
        return ""


def _card_source(
    source: Mapping[str, Any], *, include_source_type: bool
) -> dict[str, str]:
    fallback_domain = (
        str(source.get("sourceType") or "source") if include_source_type else "source"
    )
    projected = {
        "title": (str(source.get("title") or "Source").strip() or "Source")[:240],
        "domain": (_safe_hostname(source.get("uri")) or fallback_domain)[:120],
    }
    source_id = source.get("id")
    if source_id is not None:
        projected["sourceId"] = str(source_id)[:128]
    return projected


def _normalize_web_search_query(raw_query: Any) -> str | dict[str, Any]:
    if isinstance(raw_query, str):
        cleaned = raw_query.strip()
        return cleaned[:240] if cleaned else "Restored web search"
    if isinstance(raw_query, Mapping) and isinstance(raw_query.get("type"), str):
        normalized: dict[str, Any] = {"type": raw_query["type"][:32]}
        chars = raw_query.get("chars")
        if isinstance(chars, int) and not isinstance(chars, bool) and chars >= 0:
            normalized["chars"] = chars
        return normalized
    return "Restored web search"


def _extract_web_search_query(input_preview: Any) -> str | dict[str, Any]:
    if not isinstance(input_preview, str) or not input_preview.strip():
        return "Restored web search"
    try:
        parsed = json.loads(input_preview)
        if isinstance(parsed, Mapping) and "query" in parsed:
            return _normalize_web_search_query(parsed["query"])
        return "Restored web search"
    except ValueError:
        match = _QUERY_KEY_PATTERN.search(input_preview)
        if match is None:
            return "Restored web search"
        try:
            decoded, _ = json.JSONDecoder().raw_decode(input_preview, match.end())
        except ValueError:
            tail = input_preview[match.end() :]
            if tail.startswith('"'):
                partial = tail[1:].rstrip("…\"'")
                return _normalize_web_search_query(partial)
            return "Restored web search"
        return _normalize_web_search_query(decoded)


def make_card(
    kind: str, data: dict[str, Any], *, run_id: str, message_id: str
) -> dict[str, Any] | None:
    payload = {key: value for key, value in data.items() if key != "schemaVersion"}
    envelope = scrub_json_strings(
        {
            "schemaVersion": 2,
            "kind": kind,
            "runId": run_id[:128],
            "messageId": message_id[:128],
            "data": _clamp_card_ids(payload),
        }
    )
    try:
        return cast(
            dict[str, Any],
            InlineCard.model_validate(envelope).model_dump(
                mode="json", exclude_none=True
            ),
        )
    except ValidationError as exc:
        fields = ",".join(
            ".".join(str(part) for part in err["loc"]) for err in exc.errors()[:5]
        )
        logger.warning(
            "Dropped invalid inline card kind=%s fields=%s",
            kind,
            fields or "unknown",
        )
        return None
    except ValueError:
        logger.warning("Dropped invalid inline card kind=%s", kind)
        return None


def settled_cards(
    state: dict[str, Any], *, run_id: str, message_id: str
) -> list[dict[str, Any]]:
    result = []
    raw_sources = [
        source for source in state.get("sources", []) if isinstance(source, Mapping)
    ]
    sources = [
        _card_source(source, include_source_type=True) for source in raw_sources[-12:]
    ]
    for cycle, tool in enumerate(state.get("toolCalls", [])):
        if not isinstance(tool, Mapping) or tool.get("name") != "web_search":
            continue
        matching = [
            source
            for source in raw_sources
            if source.get("toolCallId") == tool.get("id")
        ][:12]
        query = _extract_web_search_query(tool.get("inputPreview"))
        card = make_card(
            "web-search",
            {
                "query": query,
                "results": [
                    _card_source(source, include_source_type=False)
                    for source in matching
                ],
                "searching": False,
                "visibleResults": len(matching),
                "cycle": cycle,
            },
            run_id=run_id,
            message_id=message_id,
        )
        if card:
            result.append(card)
    if sources:
        card = make_card(
            "sources", {"sources": sources}, run_id=run_id, message_id=message_id
        )
        if card:
            result.append(card)
    for artifact in state.get("artifacts", []):
        if not isinstance(artifact, Mapping) or artifact.get("status") != "ready":
            continue
        artifact_limits = {
            "id": 128,
            "name": 240,
            "mediaType": 128,
            "downloadUrl": 256,
        }
        artifact_payload = {
            key: (
                artifact[key][:limit]
                if isinstance(artifact[key], str)
                else artifact[key]
            )
            for key, limit in artifact_limits.items()
            if key in artifact
        }
        card = make_card(
            "artifact",
            artifact_payload,
            run_id=run_id,
            message_id=message_id,
        )
        if card:
            result.append(card)
    return result[:32]
