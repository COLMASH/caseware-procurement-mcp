"""Evidence that the MCP server speaks the protocol to an MCP client.

Spawns the server over stdio with the official MCP Python client, initializes
the session, lists the tools, and calls a few — printing the structured output.

    uv run python scripts/mcp_client_test.py
"""
from __future__ import annotations

import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = StdioServerParameters(command=sys.executable, args=["-m", "procurement_kb.server.mcp_server"])


def show(title, result):
    print(f"\n>>> {title}")
    payload = getattr(result, "structuredContent", None)
    if payload is None and result.content:
        payload = result.content[0].text
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str)[:900])


async def main() -> None:
    async with stdio_client(SERVER) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("Connected. Tools exposed by the MCP server:")
            for t in tools.tools:
                print(f"  • {t.name}")

            show("reconcile(order_id=10687)  — three-way match",
                 await session.call_tool("reconcile", {"order_id": 10687}))
            show("search_contract('termination of the contract', k=2)",
                 await session.call_tool("search_contract", {"query": "termination of the contract", "k": 2}))
            show("get_order_dossier(10248)",
                 await session.call_tool("get_order_dossier", {"order_id": 10248}))
            show("search('Queso Cabrales', limit=2)",
                 await session.call_tool("search", {"query": "Queso Cabrales", "limit": 2}))
            show("get_document('batch2-0998')  — headerless image invoice",
                 await session.call_tool("get_document", {"doc_id": "batch2-0998"}))
            show("list_inventory_reports()",
                 await session.call_tool("list_inventory_reports", {}))
    print("\nAll 6 tools exercised over MCP. Protocol round-trip OK. ✓")


if __name__ == "__main__":
    asyncio.run(main())
