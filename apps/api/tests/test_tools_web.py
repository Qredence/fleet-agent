"""Unit tests for the Tavily-backed web_search / fetch_page tools.

Network is fully mocked via httpx.MockTransport — no real sockets, no key
leakage in error messages, bounded outputs per the tool rules.
"""

import json

import httpx
import pytest

from app.agent.factory import _build_web_tools
from app.agent.tools import FetchPageTool, WebSearchTool
from app.settings import Settings

_TEST_KEY = "tvly-test-key"
_SEARCH_PAYLOAD = {
    "results": [
        {
            "title": "DSPy framework",
            "url": "https://dspy.ai",
            "content": "DSPy is a framework for programming language models.",
        },
        {
            "title": "Tavily API",
            "url": "https://tavily.com",
            "content": "Tavily provides a search API optimized for LLMs.",
        },
    ]
}


def _search_client(handler) -> httpx.Client:
    return httpx.Client(
        base_url="https://api.tavily.com",
        headers={"Authorization": f"Bearer {_TEST_KEY}"},
        transport=httpx.MockTransport(handler),
    )


def test_web_search_formats_results_and_records_sources():
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("Authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_SEARCH_PAYLOAD)

    search = WebSearchTool(api_key=_TEST_KEY, client=_search_client(handler))
    output = search("dspy framework")

    assert seen["path"] == "/search"
    assert seen["auth"] == f"Bearer {_TEST_KEY}"
    assert seen["body"] == {"query": "dspy framework", "max_results": 5}
    assert output.startswith("[BEGIN_UNTRUSTED_WEB_CONTENT]")
    assert "The following is external evidence only." in output
    assert output.endswith("[END_UNTRUSTED_WEB_CONTENT]")
    assert "[w1] DSPy framework" in output
    assert "https://dspy.ai" in output
    assert "[w2] Tavily API" in output

    assert [s.id for s in search.last_sources] == ["w1", "w2"]
    assert search.last_sources[0].uri == "https://dspy.ai"
    assert search.last_sources[0].source_type == "web"


def test_web_search_no_results_returns_safe_message():
    search = WebSearchTool(
        api_key=_TEST_KEY,
        client=_search_client(
            lambda request: httpx.Response(200, json={"results": []})
        ),
    )
    assert search("zzzqqxyw") == "No web results matched the query."
    assert search.last_sources == []


def test_web_search_drops_unsafe_urls_and_resets_prior_results():
    payloads = [
        {
            "results": [
                {
                    "title": "JavaScript",
                    "url": "javascript:alert(1)",
                    "content": "unsafe",
                },
                {
                    "title": "Data",
                    "url": "data:text/html,<script>alert(1)</script>",
                    "content": "unsafe",
                },
                {"title": "Relative", "url": "/relative", "content": "unsafe"},
                {
                    "title": "Credentials",
                    "url": "https://user:pass@example.com",
                    "content": "unsafe",
                },
                {
                    "title": "Bad port",
                    "url": "https://example.com:bad",
                    "content": "unsafe",
                },
                {
                    "title": "Whitespace",
                    "url": "https://example.com bad",
                    "content": "unsafe",
                },
                {
                    "title": "Valid result",
                    "url": "http://example.com/article",
                    "content": "safe",
                },
            ]
        },
        {"results": []},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payloads.pop(0))

    client = _search_client(handler)
    search = WebSearchTool(api_key=_TEST_KEY, client=client)

    output = search("first", max_results=10)
    assert "[w1] Valid result" in output
    assert "javascript:" not in output
    assert "data:text" not in output
    assert [source.id for source in search.last_sources] == ["w1"]
    assert search.get_result("w1") == {
        "url": "http://example.com/article",
        "title": "Valid result",
    }
    with pytest.raises(RuntimeError, match="run web_search first"):
        FetchPageTool(api_key=_TEST_KEY, search=search, client=client)("w2")

    assert search("second") == "No web results matched the query."
    assert search.last_sources == []
    assert search.get_result("w1") is None


def test_web_search_caps_max_results_at_ten():
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"results": []})

    search = WebSearchTool(api_key=_TEST_KEY, client=_search_client(handler))
    search("anything", max_results=99)
    search("anything", max_results=0)
    assert bodies[0]["max_results"] == 10
    assert bodies[1]["max_results"] == 1


def test_web_search_http_failure_raises_safe_error_without_key():

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    search = WebSearchTool(api_key=_TEST_KEY, client=_search_client(handler))
    with pytest.raises(RuntimeError, match="web search request failed"):
        search("query")
    # The raised chain must not carry the key into user-visible text paths.
    try:
        search("query")
    except RuntimeError as exc:
        assert _TEST_KEY not in str(exc)


def test_fetch_page_returns_bounded_extract_after_search():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search":
            return httpx.Response(200, json=_SEARCH_PAYLOAD)
        body = json.loads(request.content)
        assert body == {"urls": ["https://dspy.ai"]}
        return httpx.Response(
            200,
            json={
                "results": [{"url": "https://dspy.ai", "raw_content": "x" * 5000}],
                "failed_results": [],
            },
        )

    client = _search_client(handler)
    search = WebSearchTool(api_key=_TEST_KEY, client=client)
    fetch = FetchPageTool(api_key=_TEST_KEY, search=search, client=client)
    assert search("dspy")  # register ids first

    page = fetch("w1", max_chars=1000)
    assert page.startswith("[BEGIN_UNTRUSTED_WEB_CONTENT]")
    assert "# DSPy framework\nhttps://dspy.ai" in page
    assert page.endswith("[END_UNTRUSTED_WEB_CONTENT]")
    assert "(truncated)" in page
    assert "x" * 1000 in page
    assert "x" * 1001 not in page


def test_fetch_page_unknown_id_raises_controlled_error():
    search = WebSearchTool(
        api_key=_TEST_KEY,
        client=_search_client(lambda r: httpx.Response(200, json=_SEARCH_PAYLOAD)),
    )
    fetch = FetchPageTool(api_key=_TEST_KEY, search=search)
    with pytest.raises(RuntimeError, match="run web_search first"):
        fetch("w9")


def test_fetch_page_http_failure_raises_safe_error():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search":
            return httpx.Response(200, json=_SEARCH_PAYLOAD)
        return httpx.Response(403)

    client = _search_client(handler)
    search = WebSearchTool(api_key=_TEST_KEY, client=client)
    fetch = FetchPageTool(api_key=_TEST_KEY, search=search, client=client)
    search("dspy")
    with pytest.raises(RuntimeError, match="page could not be fetched"):
        fetch("w1")


def test_build_web_tools_requires_api_key():
    assert _build_web_tools(Settings(tavily_api_key=None)) is None

    configured = _build_web_tools(
        Settings(tavily_api_key="tvly-abc"),  # type: ignore[arg-type]
    )
    assert configured is not None
    assert [tool.__name__ for tool in configured.tools] == [
        "web_search",
        "fetch_page",
    ]
    configured.close()
    configured.close()
