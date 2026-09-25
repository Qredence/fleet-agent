from httpx import ASGITransport, AsyncClient

from tests.conftest import make_test_app


async def get_catalog(app):
    """
    Request the tools catalog from the test application.

    Parameters:
        app: ASGI application to serve the request.

    Returns:
        Response: HTTP response from the `/api/tools` endpoint.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get("/api/tools")


async def test_tool_catalog_without_a_web_key():
    app = make_test_app(tavily_api_key=None)
    response = await get_catalog(app)
    assert response.status_code == 200
    tools = response.json()["tools"]
    assert [tool["name"] for tool in tools] == [
        "search_docs",
        "write_report",
        "get_current_time",
        "ls",
        "find",
        "grep",
        "read",
    ]
    assert all(tool["description"] for tool in tools)
    report = next(tool for tool in tools if tool["name"] == "write_report")
    assert report["read_only"] is False
    assert report["parallelizable"] is False
    assert report["capability"] == "artifact"
    workspace_read = next(tool for tool in tools if tool["name"] == "read")
    assert workspace_read["capability"] == "workspace_read"
    assert workspace_read["read_only"] is True


async def test_tool_catalog_includes_web_tools_with_a_key():
    app = make_test_app(tavily_api_key="tvly-test-key")
    response = await get_catalog(app)
    assert response.status_code == 200
    tools = response.json()["tools"]
    assert [tool["name"] for tool in tools] == [
        "web_search",
        "fetch_page",
        "search_docs",
        "write_report",
        "get_current_time",
        "ls",
        "find",
        "grep",
        "read",
    ]
    assert all(tool["description"] for tool in tools)
    web_search = next(tool for tool in tools if tool["name"] == "web_search")
    assert web_search["read_only"] is True
    assert web_search["parallelizable"] is True


async def test_tool_catalog_omits_workspace_tools_without_a_production_root():
    app = make_test_app(environment="production", workspace_root=None)
    response = await get_catalog(app)
    assert response.status_code == 200
    assert not {tool["name"] for tool in response.json()["tools"]} & {
        "ls",
        "find",
        "grep",
        "read",
        "write",
        "edit",
        "bash",
    }
