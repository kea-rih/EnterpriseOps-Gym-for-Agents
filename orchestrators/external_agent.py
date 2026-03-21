"""External Agent Orchestrator: delegates task execution to an external HTTP agent."""

import logging
from typing import Any, Dict

import httpx

from orchestrators.base import AgentOrchestrator

logger = logging.getLogger(__name__)


class ExternalAgentOrchestrator(AgentOrchestrator):
    """Orchestrator that POSTs task info to an external agent (e.g. A2A/ADK)
    and returns its response. The external agent handles tool discovery,
    reasoning, and tool execution independently."""

    def __init__(self, *args, agent_url: str, timeout: int = 600, **kwargs):
        super().__init__(*args, **kwargs)
        self.agent_url = agent_url
        self.timeout = timeout

    async def execute(self) -> Dict[str, Any]:
        # Build MCP server info from self.mcp_clients
        mcp_servers = []
        for gym_name, client in self.mcp_clients.items():
            mcp_servers.append({
                "name": gym_name,
                "url": client.base_url,
                "endpoint": client.mcp_endpoint,
                "database_id": client.database_id,
                "context": client.context,
            })

        payload = {
            "system_prompt": self.config.system_prompt,
            "user_prompt": self.config.user_prompt,
            "mcp_servers": mcp_servers,
            "selected_tools": self.config.selected_tools or [],
            "restricted_tools": self.config.restricted_tools or [],
            "task_id": getattr(self.config, "task_id", None),
        }

        logger.info(f"Sending task to external agent at {self.agent_url}")
        logger.info(f"  MCP servers: {[s['name'] for s in mcp_servers]}")
        logger.info(f"  Selected tools: {len(payload['selected_tools'])}")

        async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout)) as http_client:
            resp = await http_client.post(self.agent_url, json=payload)
            resp.raise_for_status()
            result = resp.json()

        logger.info(f"External agent returned response ({len(result.get('final_response', ''))} chars)")

        return {
            "final_response": result.get("final_response", ""),
            "conversation_flow": result.get("conversation_flow", []),
            "tools_used": result.get("tools_used", []),
            "tool_results": result.get("tool_results", []),
            "messages": [],
        }
