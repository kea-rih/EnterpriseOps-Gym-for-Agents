"""ITSM Agent — ADK agent for IT Service Management OpsGym tasks."""

import os
from pathlib import Path

from google.adk.agents import LlmAgent

from agents.common.opsgym_adapter import create_app, mount_a2a

MODEL = os.environ.get("GOOGLE_MODEL", "gemini-3-flash-preview")
SKILL_MD = (Path(__file__).parent / "SKILL.md").read_text()

# OpsGym adapter (POST /task)
app = create_app(agent_name="itsm_agent", skill_instruction=SKILL_MD, model=MODEL)

# A2A exposure (agent card at /a2a/.well-known/agent-card.json)
a2a_agent = LlmAgent(
    model=MODEL,
    name="itsm_agent",
    description="IT Service Management agent for incident, change, and problem management",
    instruction=SKILL_MD,
)
mount_a2a(app, a2a_agent, port=9101)
