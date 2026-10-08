"""Native gateway wire behavior, without a provider or paid inference."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import dspy
import pytest
from dspy.lm15 import Config, FunctionTool, Message, Request, Response, StreamDeltaEvent
from pydantic import SecretStr

from app.agent.factory import _build_lm
from app.agent.gateway import close_lm
from app.agent.provider import ProviderOverride
from app.settings import Settings


@pytest.fixture
def gateway():
    requests = []
    response = {"status": 200, "redirect": None}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, dict(self.headers), body))
            reply = response.get("sequence", [])
            reply = reply.pop(0) if reply else response
            self.send_response(reply.get("status", 200))
            if reply.get("redirect"):
                self.send_header("Location", reply.get("redirect"))
            streaming = body.get("stream")
            self.send_header(
                "Content-Type", "text/event-stream" if streaming else "application/json"
            )
            self.end_headers()
            if reply.get("status", 200) != 200:
                self.wfile.write(
                    json.dumps(
                        reply.get(
                            "error",
                            {
                                "error": {
                                    "message": "fixture failure",
                                    "type": "fixture",
                                }
                            },
                        )
                    ).encode()
                )
            elif streaming and reply.get("stream_error"):
                self.wfile.write(
                    f"data: {json.dumps(reply['stream_error'])}\n\n".encode()
                )
            elif streaming:
                for delta in reply.get(
                    "deltas",
                    [
                        {"role": "assistant", "content": "fixture "},
                        {"content": "answer"},
                    ],
                ):
                    chunk = {
                        "id": "fixture",
                        "model": body["model"],
                        "choices": [{"index": 0, "delta": delta}],
                    }
                    self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                chunk = {
                    "id": "fixture",
                    "model": body["model"],
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                    },
                }
                self.wfile.write(
                    f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode()
                )
            else:
                self.wfile.write(
                    json.dumps(
                        {
                            "id": "fixture",
                            "model": body["model"],
                            "choices": [
                                {
                                    "index": 0,
                                    "message": reply.get(
                                        "message",
                                        {
                                            "role": "assistant",
                                            "content": "fixture answer",
                                        },
                                    ),
                                    "finish_reason": "stop",
                                }
                            ],
                            "usage": {
                                "prompt_tokens": 10,
                                "completion_tokens": 5,
                                "total_tokens": 15,
                            },
                        }
                    ).encode()
                )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", requests, response
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


@pytest.mark.parametrize("role", ["system_role", "developer_role"])
def test_gateway_preserves_model_credentials_and_message_role(gateway, role):
    base, requests, _ = gateway
    lm = _build_lm(
        Settings(llm_model="openai/verbatim-model"),
        ProviderOverride(
            api_key="fixture-key",
            api_base=base,
            messages_format=role,
        ),
    )
    try:
        response = lm(
            Request(
                model=lm.model,
                system="fixture instruction",
                messages=(Message.user("fixture request"),),
            )
        )
        assert response.message.text == "fixture answer"
        path, headers, body = requests[0]
        assert path == "/v1/chat/completions"
        assert headers["Authorization"] == "Bearer fixture-key"
        assert body["model"] == "openai/verbatim-model"
        assert body["messages"][0]["role"] == role.removesuffix("_role")
        assert lm.history[-1]["usage"]["total_tokens"] == 15
    finally:
        close_lm(lm)


def test_native_gateway_stream_returns_canonical_events(gateway):
    base, _, _ = gateway
    lm = _build_lm(
        Settings(
            llm_model="vendor/model",
            llm_base_url=base,
            llm_api_key=SecretStr("fixture-key"),
        )
    )
    try:
        request = Request(model=lm.model, messages=(Message.user("fixture"),))
        events = list(lm.engine.stream(request))
        assert any(isinstance(event, StreamDeltaEvent) for event in events)
        response = lm.engine.complete(request)
        assert isinstance(response, Response)
        assert response.usage.total_tokens == 15
    finally:
        close_lm(lm)


@pytest.mark.parametrize(
    "status,error",
    [
        (401, dspy.LMAuthError),
        (429, dspy.LMRateLimitError),
        (500, dspy.LMServerError),
    ],
)
def test_native_gateway_maps_provider_errors(gateway, status, error):
    base, _, response = gateway
    response["status"] = status
    lm = _build_lm(
        Settings(
            llm_model="fixture", llm_base_url=base, llm_api_key=SecretStr("fixture-key")
        )
    )
    lm.num_retries = 0
    try:
        with pytest.raises(error):
            lm(prompt="fixture")
    finally:
        close_lm(lm)


def test_gateway_does_not_follow_redirects(gateway):
    base, requests, response = gateway
    response.update(status=307, redirect=base + "/redirected")
    lm = _build_lm(
        Settings(
            llm_model="fixture", llm_base_url=base, llm_api_key=SecretStr("fixture-key")
        )
    )
    lm.num_retries = 0
    try:
        with pytest.raises(dspy.LMError):
            lm(prompt="fixture")
        assert len(requests) == 1
    finally:
        close_lm(lm)


def test_native_tool_and_schema_wire_contract(gateway):
    base, requests, response = gateway
    response["message"] = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "fixture-call",
                "type": "function",
                "function": {"name": "lookup", "arguments": '{"query":"fixture"}'},
            }
        ],
    }
    lm = _build_lm(
        Settings(
            llm_model="fixture", llm_base_url=base, llm_api_key=SecretStr("fixture-key")
        )
    )
    try:
        result = lm(
            Request(
                model=lm.model,
                messages=(Message.user("fixture"),),
                tools=(
                    FunctionTool(
                        name="lookup",
                        parameters={
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                            "required": ["query"],
                        },
                    ),
                ),
                config=Config(response_format={"type": "json_object"}),
            )
        )
        body = requests[0][2]
        assert body["tools"][0]["function"]["name"] == "lookup"
        assert body["response_format"] == {"type": "json_object"}
        from dspy.lm15 import ToolCallPart

        call = result.message.first(ToolCallPart)
        assert call.name == "lookup"
        assert call.input == {"query": "fixture"}
    finally:
        close_lm(lm)


def test_openrouter_headers_are_trusted_and_scoped():
    from app.agent.provider import OPENROUTER_API_BASE_URL

    settings = Settings(
        llm_model="vendor/model",
        llm_base_url=OPENROUTER_API_BASE_URL,
        llm_api_key=SecretStr("fixture-key"),
        openrouter_http_referer="https://fleet.example",
    )
    lm = _build_lm(settings)
    other = _build_lm(
        settings,
        ProviderOverride(api_key="fixture-key", api_base="https://other.example/v1"),
    )
    try:
        assert lm.engine.config.providers[0].access.headers == (
            ("HTTP-Referer", "https://fleet.example"),
            ("X-Title", "Fleet Agent"),
        )
        assert other.engine.config.providers[0].access.headers == ()
    finally:
        close_lm(lm)
        close_lm(other)


@pytest.mark.parametrize("streaming", [False, True])
def test_parallel_multi_iteration_reasoning_replay_and_cleanup(gateway, streaming):
    from dspy.lm15 import ResponseStream, ToolCallPart, tool_result

    base, requests, replies = gateway
    calls = [
        {
            "id": f"call-{i}",
            "type": "function",
            "function": {
                "name": "lookup",
                "arguments": '{"query":"fixture"}',
            },
        }
        for i in range(3)
    ]
    replies["sequence"] = [
        {
            "message": {
                "role": "assistant",
                "content": None,
                "reasoning_content": "first private thinking",
                "tool_calls": calls[:2],
            },
            "deltas": [
                {"role": "assistant", "reasoning_content": "first private thinking"},
                {
                    "tool_calls": [
                        {"index": i, **call} for i, call in enumerate(calls[:2])
                    ]
                },
            ],
        },
        {
            "message": {
                "role": "assistant",
                "content": None,
                "reasoning_content": "second private thinking",
                "tool_calls": calls[2:],
            },
            "deltas": [
                {"role": "assistant", "reasoning_content": "second private thinking"},
                {"tool_calls": [{"index": 0, **calls[2]}]},
            ],
        },
        {
            "message": {"role": "assistant", "content": "fixture answer"},
            "deltas": [{"role": "assistant", "content": "fixture answer"}],
        },
    ]
    lm = _build_lm(
        Settings(
            llm_model="deepseek/deepseek-v4.1-flash",
            llm_base_url=base,
            llm_api_key=SecretStr("fixture-key"),
        )
    )
    messages = [Message.user("private fixture prompt")]
    try:
        for _turn in range(3):
            request = Request(
                model=lm.model,
                messages=tuple(messages),
                tools=(
                    FunctionTool(
                        name="lookup",
                        parameters={
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                        },
                    ),
                ),
            )
            if streaming:
                with ResponseStream(lm.engine.stream(request), request) as stream:
                    list(stream.events())
                    result = stream.response
            else:
                result = lm.engine.complete(request)
            assert result.usage.total_tokens == 15
            tool_calls = result.message.parts_of(ToolCallPart)
            if tool_calls:
                # ReAct history drops thinking; the run-owned boundary restores it.
                messages.append(Message.assistant(tool_calls))
                messages.append(
                    Message.tool(
                        tuple(
                            tool_result(
                                call.id, "private fixture result", name=call.name
                            )
                            for call in tool_calls
                        )
                    )
                )
        final_wire = requests[-1][2]["messages"]
        assistants = [m for m in final_wire if m["role"] == "assistant"]
        assert [m["reasoning_content"] for m in assistants] == [
            "first private thinking",
            "second private thinking",
        ]
        ids = [c["id"] for m in assistants for c in m["tool_calls"]]
        assert [m["tool_call_id"] for m in final_wire if m["role"] == "tool"] == ids
        assert len(lm.engine._tool_thinking) == 2
    finally:
        close_lm(lm)
    assert lm.engine._tool_thinking == {}
