"""Calendar Agent — ADK agent for Calendar/Scheduling OpsGym tasks."""

import os
from pathlib import Path

from google.adk.agents import LlmAgent

from agents.common.opsgym_adapter import create_app, mount_a2a

MODEL = os.environ.get("GOOGLE_MODEL", "gemini-3-flash-preview")
SKILL_MD = (Path(__file__).parent / "SKILL.md").read_text()

# OpsGym adapter (POST /task)
app = create_app(agent_name="calendar_agent", skill_instruction=SKILL_MD, model=MODEL)

# A2A exposure (agent card at /a2a/.well-known/agent-card.json)
a2a_agent = LlmAgent(
    model=MODEL,
    name="calendar_agent",
    description="Calendar and Scheduling agent for event management, availability queries, and timezone handling",
    instruction=SKILL_MD,
)
mount_a2a(app, a2a_agent, port=9103)
