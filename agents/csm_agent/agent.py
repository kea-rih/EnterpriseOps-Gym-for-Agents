"""CSM Agent — ADK agent for Customer Service Management OpsGym tasks."""

import os
from pathlib import Path

from google.adk.agents import LlmAgent

from agents.common.opsgym_adapter import create_app, mount_a2a

MODEL = os.environ.get("GOOGLE_MODEL", "gemini-3-flash-preview")
SKILL_MD = (Path(__file__).parent / "SKILL.md").read_text()

# OpsGym adapter (POST /task)
app = create_app(agent_name="csm_agent", skill_instruction=SKILL_MD, model=MODEL)

# A2A exposure (agent card at /a2a/.well-known/agent-card.json)
a2a_agent = LlmAgent(
    model=MODEL,
    name="csm_agent",
    description="Customer Service Management agent for case lifecycle, SLA monitoring, and knowledge base",
    instruction=SKILL_MD,
)
mount_a2a(app, a2a_agent, port=9102)
