"""Opt-in structural receipts around the native DSPy HTTP transport.

The native transport owns sockets and streaming. No response conversion occurs
here; error bytes are inspected in memory before being passed back unchanged.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from importlib import import_module
from typing import Any, cast

from dspy.lm15 import ConfigurationError
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


def _request_id(
    value: Any, secrets: tuple[str, ...] = (), *, body: dict[str, Any] | None = None
) -> str | None:
    """Only recognizable opaque IDs, never request-derived identifiers."""
    if not isinstance(value, str) or not re.fullmatch(
        r"(?:req[-_][A-Fa-f0-9]{5,64}|(?:req[-_])?[A-Fa-f0-9]{8}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{12})",
        value,
    ):
        return None
    sensitive = (
        json.dumps(body or {}, ensure_ascii=False).lower() + " ".join(secrets).lower()
    )
    tokens = re.findall(r"[a-f0-9]{4,}", value.lower())
    if any(token in sensitive for token in tokens) or any(
        secret and (secret.lower() in value.lower() or value.lower() in secret.lower())
        for secret in secrets
    ):
        return None
    return value


class ProviderDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    run_id: str
    stage: str
    call_index: int
    status: int
    request_id: str | None = None
    structure: dict[str, Any]
    rejection: dict[str, Any] = Field(default_factory=dict)


def request_structure(body: dict[str, Any]) -> dict[str, Any]:
    messages = body.get("messages", [])
    tools = body.get("tools", [])
    schema = body.get("response_format", {})
    properties = schema.get("json_schema", {}).get("schema", {}).get("properties", {})
    tool_names = [t.get("function", {}).get("name") for t in tools]
    choice = body.get("tool_choice")
    forced_submit = (
        isinstance(choice, dict)
        and choice.get("type") == "function"
        and choice.get("function", {}).get("name") == "submit"
    )
    stage = (
        "forced_submission"
        if tool_names == ["submit"] or forced_submit
        else "evidence_gathering"
        if tools or "next_thought" in properties
        else "routing"
        if "route" in properties
        else "synthesis"
        if "answer" in properties
        else "unknown"
    )
    return {
        "stage": stage,
        "parameters": sorted(body)[:64],
        "message_count": len(messages),
        "structure_truncated": len(messages) > 128,
        "roles": [m.get("role") for m in messages[:128]],
        "messages": [
            {
                "role": m.get("role"),
                "content_type": type(m.get("content")).__name__,
                "content_present": bool(m.get("content")),
                "reasoning_present": "reasoning_content" in m,
                "reasoning_nonempty": bool(m.get("reasoning_content")),
                "call_count": len(m.get("tool_calls", [])),
                "call_ids": [
                    hashlib.sha256(str(c.get("id")).encode()).hexdigest()[:12]
                    for c in m.get("tool_calls", [])[:32]
                ],
                "result_id": hashlib.sha256(
                    str(m["tool_call_id"]).encode()
                ).hexdigest()[:12]
                if m.get("tool_call_id")
                else None,
            }
            for m in messages[:128]
        ],
        "tool_count": len(tools),
        "tool_choice": (
            choice
            if choice in ("auto", "none", "required")
            else "named_submit"
            if forced_submit
            else "named_function"
            if isinstance(choice, dict) and choice.get("type") == "function"
            else "other"
            if choice is not None
            else None
        ),
        "response_format": schema.get("type"),
        "schema_fields": sorted(properties)[:32],
        "stream": bool(body.get("stream")),
    }


_ERROR_CODES = frozenset(
    {
        "invalid_request_error",
        "authentication_error",
        "rate_limit_error",
        "permission_error",
        "not_found_error",
        "server_error",
        "api_error",
        "context_length_exceeded",
        "invalid_api_key",
        "insufficient_quota",
        "validation_error",
        "invalid_request",
        "unauthorized",
        "rate_limited",
    }
)
_FIELDS = frozenset(
    {
        "body",
        "messages",
        "content",
        "tools",
        "tool_calls",
        "tool_call_id",
        "function",
        "arguments",
        "response_format",
        "json_schema",
        "reasoning_content",
        "tool_choice",
        "thinking",
    }
)
_RULES = frozenset(
    {
        "not supported",
        "does not support",
        "required",
        "missing",
        "invalid",
        "must be",
        "not allowed",
        "thinking mode",
    }
)


def rejection_facts(
    raw: bytes, body: dict[str, Any], secrets: tuple[str, ...]
) -> dict[str, Any]:
    """Retain fixed-vocabulary facts only; provider prose is never retained."""
    facts: dict[str, Any] = {
        "envelope": "non_json",
        "bytes": len(raw),
        "truncated": False,
        "codes": [],
        "locations": [],
        "mentioned_fields": [],
        "mentioned_rules": [],
        "request_ids": [],
    }
    if len(raw) > 262_144:
        facts["truncated"] = True
        return facts
    try:
        parsed = json.loads(raw)
    except (ValueError, RecursionError):
        return facts
    facts["envelope"] = "json"
    fields: set[str] = set()
    rules: set[str] = set()
    visited = 0

    def visit(value: Any, depth: int = 0) -> None:
        nonlocal visited
        visited += 1
        if depth > 8 or visited > 256:
            facts["truncated"] = True
            return
        if isinstance(value, dict):
            for key in ("request_id", "requestId"):
                identifier = _request_id(value.get(key), secrets, body=body)
                if identifier and len(facts["request_ids"]) < 8:
                    facts["request_ids"].append(identifier)
            for key in ("code", "type"):
                code = value.get(key)
                if (
                    isinstance(code, str)
                    and code in _ERROR_CODES
                    and len(facts["codes"]) < 8
                ):
                    facts["codes"].append(code)
            loc = value.get("loc")
            if isinstance(loc, list) and len(facts["locations"]) < 8:
                location = ".".join(
                    str(item)
                    for item in loc[:16]
                    if isinstance(item, str)
                    and item in _FIELDS
                    or type(item) is int
                    and 0 <= item < 128
                )
                if location:
                    facts["locations"].append(location)
            for key in (
                "error",
                "errors",
                "message",
                "detail",
                "details",
                "cause",
                "responseBody",
                "response",
                "data",
                "body",
                "validation_errors",
            ):
                if key in value:
                    visit(value[key], depth + 1)
        elif isinstance(value, list):
            if len(value) > 8:
                facts["truncated"] = True
            for item in value[:8]:
                visit(item, depth + 1)
        elif isinstance(value, str):
            fields.update(
                field for field in _FIELDS if re.search(rf"\b{field}\b", value)
            )
            rules.update(rule for rule in _RULES if rule in value.lower())
            try:
                nested, _ = json.JSONDecoder().raw_decode(value.lstrip())
            except (ValueError, RecursionError):
                return
            if isinstance(nested, (dict, list, str)) and nested != value:
                visit(nested, depth + 1)

    visit(parsed)
    facts["mentioned_fields"] = sorted(fields)
    facts["mentioned_rules"] = sorted(rules)
    return facts


class DiagnosticTransport:
    def __init__(self, *, enabled: bool, limit: int | None = None) -> None:
        # DSPy does not re-export its transport constructor through dspy.lm15.
        # Isolate the native dependency here; do not copy its HTTP implementation.
        self.native = import_module("dspy._vendor.lm15.transports").StdlibTransport()
        self.enabled = enabled
        self.limit = limit
        self.run_id = "unassigned"
        self.calls = 0
        self._lock = threading.Lock()
        self.records: list[ProviderDiagnostic] = []

    def stream(self, request: Any) -> Any:
        with self._lock:
            if self.limit is not None and self.calls >= self.limit:
                raise ConfigurationError("Provider request budget exhausted")
            self.calls += 1
            call_index = self.calls
        response = self.native.stream(request)
        if not self.enabled:
            return response
        body = json.loads(request.body or b"{}")
        secrets = tuple(
            value.removeprefix("Bearer ")
            for key, value in request.headers
            if key.lower() in {"authorization", "x-api-key"}
        )
        owner = self

        class ReceiptResponse:
            def __getattr__(self, name: str) -> Any:
                return getattr(response, name)

            def read(self) -> bytes:
                raw = cast(bytes, response.read())
                if response.status >= 400:
                    self.record(raw)
                return raw

            def iter_lines(self) -> Any:
                for line in response.iter_lines():
                    if line.startswith(b"data:"):
                        try:
                            chunk = json.loads(line[5:].strip())
                        except ValueError:
                            chunk = None
                        if isinstance(chunk, dict) and (
                            "error" in chunk or chunk.get("type") == "error"
                        ):
                            self.record(line[5:].strip(), stream_error=True)
                    yield line

            def record(self, raw: bytes = b"", *, stream_error: bool = False) -> None:
                structure = request_structure(body)
                receipt = ProviderDiagnostic(
                    run_id=owner.run_id,
                    stage=structure.pop("stage"),
                    call_index=call_index,
                    status=response.status,
                    request_id=_request_id(
                        response.header("x-request-id"), secrets, body=body
                    ),
                    structure=structure,
                    rejection=rejection_facts(raw, body, secrets)
                    if response.status >= 400 or stream_error
                    else {},
                )
                owner.records.append(receipt)
                owner.records[:] = owner.records[-32:]
                logger.warning("provider diagnostic %s", receipt.model_dump_json())

            def __enter__(self) -> Any:
                response.__enter__()
                if response.status < 400:
                    self.record()
                return self

            def __exit__(self, *args: Any) -> Any:
                return response.__exit__(*args)

        return ReceiptResponse()

    def close(self) -> None:
        self.native.close()
