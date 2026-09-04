"""The external medical tools, loaded from the dobby MCP server.

Nothing about the tools lives here: their names, arguments, limits and
disclaimers are the server's, and are discovered at runtime. This module only
knows where the server is.
"""

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from hiro.common.logging import get_logger
from hiro.config import get_config

logger = get_logger(__name__)

SERVER_NAME = "dobby"

_tools: list[BaseTool] = []


async def get_mcp_tools() -> list[BaseTool]:
    """Discover the server's tools once per process.

    A failed discovery is not cached, so a server that is not up yet is
    retried on the next question rather than disabling tools for the life of
    the process.
    """
    global _tools
    if not _tools:
        config = get_config().mcp
        client = MultiServerMCPClient(
            {
                SERVER_NAME: {
                    "transport": "streamable_http",
                    "url": config.url,
                    "timeout": config.timeout,
                    "sse_read_timeout": config.read_timeout,
                }
            }
        )
        _tools = await client.get_tools()
        logger.info(
            "mcp tools discovered server=%s url=%s count=%d tools=%s",
            SERVER_NAME,
            config.url,
            len(_tools),
            [tool.name for tool in _tools],
        )
    return _tools
