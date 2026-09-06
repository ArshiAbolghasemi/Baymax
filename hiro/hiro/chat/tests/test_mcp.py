"""Tool discovery: the tools are the MCP server's, and they are fetched once."""

import pytest

from hiro.chat.agent import mcp


class FakeClient:
    def __init__(self, tools=None, error=None):
        self.tools = tools or []
        self.error = error
        self.calls = 0

    async def get_tools(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.tools


@pytest.fixture(autouse=True)
def forget_discovered_tools():
    mcp._tools = []
    yield
    mcp._tools = []


class Tool:
    def __init__(self, name):
        self.name = name


async def test_tools_are_discovered_from_the_server(monkeypatch, config):
    client = FakeClient([Tool("search_drug_label")])
    monkeypatch.setattr(mcp, "MultiServerMCPClient", lambda connections: client)

    tools = await mcp.get_mcp_tools()
    assert [tool.name for tool in tools] == ["search_drug_label"]


async def test_discovery_happens_once_per_process(monkeypatch):
    client = FakeClient([Tool("search_genetics")])
    monkeypatch.setattr(mcp, "MultiServerMCPClient", lambda connections: client)

    await mcp.get_mcp_tools()
    await mcp.get_mcp_tools()
    assert client.calls == 1


async def test_the_server_address_comes_from_configuration(monkeypatch, config):
    seen = {}

    def capture(connections):
        seen.update(connections)
        return FakeClient([])

    monkeypatch.setattr(mcp, "MultiServerMCPClient", capture)
    await mcp.get_mcp_tools()

    connection = seen[mcp.SERVER_NAME]
    assert connection["url"] == config.mcp.url
    assert connection["transport"] == "streamable_http"
    assert connection["timeout"] == config.mcp.timeout


async def test_a_failed_discovery_is_retried_next_time(monkeypatch):
    """A server that is not up yet must not disable tools for the whole process."""
    failing = FakeClient(error=RuntimeError("connection refused"))
    monkeypatch.setattr(mcp, "MultiServerMCPClient", lambda connections: failing)
    with pytest.raises(RuntimeError):
        await mcp.get_mcp_tools()

    working = FakeClient([Tool("search_health_info")])
    monkeypatch.setattr(mcp, "MultiServerMCPClient", lambda connections: working)
    assert [t.name for t in await mcp.get_mcp_tools()] == ["search_health_info"]
