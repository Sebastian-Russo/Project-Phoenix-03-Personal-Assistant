"""
Tool registry — the master directory of everything the system can do.
Think of it as a staffing agency: connectors register their skills here,
and when the orchestrator needs something done, it consults the registry
to find out what's available and hands the list to Claude.

Claude reads the tool definitions and decides which ones to call.
The registry then routes those calls to the right connector.
"""

from typing import Any
from src.connectors.base_connector import BaseConnector


class ToolRegistry:

    def __init__(self):
        # Maps connector_name → connector instance
        self._connectors: dict[str, BaseConnector] = {}

        # Maps tool_name → connector_name (for routing execute calls)
        self._tool_index: dict[str, str] = {}

    def register(self, name: str, connector: BaseConnector) -> None:
        """
        Register a connector and index all its tools.
        Called at startup for each connector that successfully authenticates.
        """
        if not connector.health_check():
            print(f"[registry] Skipping {name} — health check failed.")
            return

        self._connectors[name] = connector

        for tool in connector.get_tools():
            tool_name = tool["name"]
            self._tool_index[tool_name] = name
            print(f"[registry] Registered tool: {tool_name} → {name}")

    def get_all_tools(self) -> list[dict]:
        """
        Return all tool definitions from all registered connectors.
        This is what gets passed to Claude in every API call —
        Claude uses this list to know what actions are available.
        """
        tools = []
        for connector in self._connectors.values():
            tools.extend(connector.get_tools())
        return tools

    def get_tools_for(self, connector_names: list[str]) -> list[dict]:
        """
        Return tool definitions for a specific subset of connectors.
        Used when the orchestrator already knows which connectors are relevant
        and wants to limit Claude's options to reduce noise.
        """
        tools = []
        for name in connector_names:
            if name in self._connectors:
                tools.extend(self._connectors[name].get_tools())
        return tools

    def execute(self, tool_name: str, parameters: dict) -> Any:
        """
        Route a tool call to the correct connector and execute it.
        Called by the orchestrator after Claude decides which tool to use.

        Flow:
            Claude says "call slack_read_messages with {channel: 'general'}"
            Orchestrator calls registry.execute("slack_read_messages", {...})
            Registry looks up which connector owns slack_read_messages
            Registry calls that connector's execute_tool() method
            Result flows back up to the orchestrator
        """
        connector_name = self._tool_index.get(tool_name)

        if not connector_name:
            raise ValueError(f"[registry] Unknown tool: {tool_name}")

        connector = self._connectors[connector_name]

        if not connector.health_check():
            raise RuntimeError(
                f"[registry] Connector '{connector_name}' failed health check "
                f"before executing '{tool_name}'"
            )

        print(f"[registry] Executing {tool_name} via {connector_name}")
        return connector.execute_tool(tool_name, parameters)

    def list_registered(self) -> dict[str, list[str]]:
        """
        Return a summary of registered connectors and their tools.
        Useful for debugging and the /health endpoint.
        """
        return {
            name: [t["name"] for t in connector.get_tools()]
            for name, connector in self._connectors.items()
        }

    @property
    def is_empty(self) -> bool:
        return len(self._connectors) == 0

# The _tool_index is the key piece — it's a flat map of every tool name to its connector.
# When Claude says "call slack_read_messages", the registry doesn't need to know anything about Slack specifically —
# it just looks up the tool name, finds the right connector, and routes the call.
# Adding a new connector with new tools requires zero changes to the registry.
