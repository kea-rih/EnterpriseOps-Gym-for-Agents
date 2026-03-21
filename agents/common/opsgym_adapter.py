"""Adapter: receives OpsGym ExternalAgentOrchestrator payload, runs an ADK agent, returns results."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
from google.genai import types

# Load .env from agents/ directory
load_dotenv(Path(__file__).parent.parent / ".env")

logger = logging.getLogger(__name__)


class OpsGymRequest(BaseModel):
    system_prompt: str
    user_prompt: str
    mcp_servers: list[dict]
    selected_tools: list[str] = []
    restricted_tools: list[str] = []
    task_id: str | None = None


class OpsGymResponse(BaseModel):
    final_response: str
    tools_used: list[str] = []
    tool_results: list[dict] = []
    conversation_flow: list = []


def create_app(agent_name: str, skill_instruction: str, model: str = "gemini-2.0-flash") -> FastAPI:
    """Create a FastAPI app that bridges OpsGym payloads to an ADK agent."""
    app = FastAPI(title=f"{agent_name} OpsGym Agent")

    @app.post("/task")
    async def handle_task(req: OpsGymRequest) -> OpsGymResponse:
        # 1. Build MCP toolsets from payload (dynamic per-request)
        toolsets = []
        for srv in req.mcp_servers:
            headers = {"x-database-id": srv["database_id"]}
            for k, v in (srv.get("context") or {}).items():
                hdr = k if k.lower().startswith("x-") else f"x-{k.lower().replace('_', '-')}"
                headers[hdr] = str(v)
            toolsets.append(McpToolset(
                connection_params=StreamableHTTPConnectionParams(
                    url=f"{srv['url']}{srv['endpoint']}",
                    headers=headers,
                ),
                tool_filter=req.selected_tools if req.selected_tools else None,
            ))

        # 2. Create ADK agent with domain skill + dynamic tools
        instruction = f"{skill_instruction}\n\n{req.system_prompt}"
        agent = LlmAgent(
            model=model,
            name=agent_name,
            instruction=instruction,
            tools=toolsets,
        )

        # 3. Run agent
        session_service = InMemorySessionService()
        runner = Runner(agent=agent, app_name=agent_name, session_service=session_service)
        session = await session_service.create_session(app_name=agent_name, user_id="opsgym")

        user_msg = types.Content(role="user", parts=[types.Part(text=req.user_prompt)])

        tools_used = []
        tool_results = []
        final_text = ""

        async for event in runner.run_async(user_id="opsgym", session_id=session.id, new_message=user_msg):
            if event.is_final_response() and event.content and event.content.parts:
                final_text = "".join(p.text for p in event.content.parts if p.text)
            # Track tool calls from events
            if hasattr(event, "function_calls") and event.function_calls:
                for fc in event.function_calls:
                    tools_used.append(fc.name)
            if hasattr(event, "function_responses") and event.function_responses:
                for fr in event.function_responses:
                    tool_results.append({
                        "tool_name": fr.name,
                        "arguments": {},
                        "result": fr.response if hasattr(fr, "response") else {},
                    })

        # 4. Cleanup MCP connections
        for ts in toolsets:
            await ts.close()

        return OpsGymResponse(
            final_response=final_text,
            tools_used=list(set(tools_used)),
            tool_results=tool_results,
        )

    return app


def mount_a2a(app: FastAPI, agent: LlmAgent, port: int):
    """Mount A2A protocol alongside the OpsGym adapter.

    Mounts at /a2a to avoid intercepting FastAPI routes like /task.
    Agent card: /a2a/.well-known/agent.json
    JSON-RPC:   POST /a2a/
    """
    from google.adk.a2a.utils.agent_to_a2a import to_a2a

    a2a_app = to_a2a(agent, port=port)

    @app.on_event("startup")
    async def _init_a2a():
        for handler in a2a_app.router.on_startup:
            await handler()

    app.mount("/a2a", a2a_app)
