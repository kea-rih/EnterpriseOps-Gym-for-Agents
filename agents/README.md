# ADK+A2A Agents for EnterpriseOps-Gym

Vertical-specific Google ADK agents that connect to OpsGym MCP servers, execute enterprise IT tasks autonomously, and return results. Each agent has a focused domain skill and exposes two interfaces: an OpsGym benchmark adapter and an A2A (Agent-to-Agent) protocol endpoint.

## What is an Agent?

An **agent** here is a Google ADK `LlmAgent` backed by Gemini that:

1. Receives a task description (natural language prompt)
2. Discovers available tools from an MCP server
3. Reasons about which tools to call and in what order
4. Executes multi-step tool chains against a live database
5. Returns a final response summarizing what it did

Each agent is specialized for one enterprise domain via a `SKILL.md` file that provides domain expertise, operational policies, and workflow patterns.

## Architecture

```
                          EnterpriseOps-Gym Benchmark
                                    |
                          evaluate.py --orchestrator external
                                    |
                    ExternalAgentOrchestrator (POST /task)
                                    |
                    +---------------+---------------+
                    |               |               |
              ITSM Agent      CSM Agent      Calendar Agent
              (port 9101)    (port 9102)     (port 9103)
                    |               |               |
              FastAPI + ADK   FastAPI + ADK   FastAPI + ADK
                    |               |               |
              MCP Toolset     MCP Toolset     MCP Toolset
              (dynamic)       (dynamic)       (dynamic)
                    |               |               |
              gym-itsm-mcp   gym-csm-mcp    gym-calendar-mcp
              (port 8006)    (port 8001)     (port 8003)
                    |               |               |
              SQLite DB       SQLite DB       SQLite DB
              (per task)      (per task)      (per task)
```

### Two Exposure Modes

Each agent server exposes two interfaces:

| Mode | Endpoint | Purpose |
|------|----------|---------|
| **OpsGym Adapter** | `POST /task` | Benchmark evaluation — receives task payload, runs agent, returns results |
| **A2A Protocol** | `/a2a/` | Agent-to-agent communication — standard A2A JSON-RPC protocol |

## How the ADK Agent Orchestration Works

### Request Flow (OpsGym Mode)

```
1. Benchmark creates a fresh SQLite database from a SQL seed file
2. ExternalAgentOrchestrator POSTs to agent's /task endpoint:
   {
     "system_prompt": "ITSM policy document...",
     "user_prompt": "Resolve incident INC_005...",
     "mcp_servers": [{
       "url": "http://localhost:8006",
       "endpoint": "/mcp",
       "database_id": "db_123_abc",
       "context": {"x-itsm-user-token": "..."}
     }],
     "selected_tools": ["get_incident", "update_incident", ...],
   }

3. Agent server (opsgym_adapter.py) handles the request:
   a. Creates a McpToolset with dynamic connection params per request
      (database_id + auth context are passed as HTTP headers)
   b. Constructs an LlmAgent with:
      - SKILL.md domain instruction + system_prompt from benchmark
      - MCP tools discovered from the server
      - Gemini model (configurable via GOOGLE_MODEL env var)
   c. Creates an InMemorySession and Runner
   d. Sends the user_prompt as a message and iterates over events

4. ADK Runner orchestration loop:
   a. Sends prompt + tool definitions to Gemini
   b. Gemini returns either:
      - A text response (final answer) → loop ends
      - Tool call requests → ADK executes them via MCP
   c. Tool results are sent back to Gemini
   d. Repeat until Gemini produces a final text response

5. Agent returns OpsGymResponse:
   {
     "final_response": "I have resolved incident INC_005...",
     "tools_used": ["get_incident", "update_incident"],
     "tool_results": [...]
   }

6. Benchmark runs SQL verifiers against the database to check
   if the agent achieved the correct outcome
```

### Key Design: Dynamic MCP Connections

OpsGym creates a **fresh database per task**. The agent server creates a new `McpToolset` for each request with the task-specific `database_id` and auth context passed as HTTP headers. This ensures complete isolation between benchmark tasks.

```python
# Each request gets its own MCP connection
McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url="http://localhost:8006/mcp",
        headers={
            "x-database-id": "db_123_abc",          # Task-specific DB
            "x-itsm-user-token": "admin_token_...",  # Auth context
        },
    ),
    tool_filter=["get_incident", "update_incident"],  # Oracle tool set
)
```

## Project Structure

```
agents/
├── common/
│   ├── __init__.py
│   └── opsgym_adapter.py    # Shared: FastAPI adapter + A2A mount helper
├── itsm_agent/
│   ├── __init__.py
│   ├── agent.py              # ITSM agent: dual OpsGym + A2A exposure
│   └── SKILL.md              # ITSM domain expertise & policies
├── csm_agent/
│   ├── __init__.py
│   ├── agent.py              # CSM agent
│   └── SKILL.md              # CSM domain expertise
├── calendar_agent/
│   ├── __init__.py
│   ├── agent.py              # Calendar agent
│   └── SKILL.md              # Calendar domain expertise
├── __init__.py
├── .env                      # GOOGLE_API_KEY, GOOGLE_MODEL
└── requirements.txt          # google-adk[a2a], fastapi, uvicorn, etc.
```

## Agent Verticals

| Agent | Domain | MCP Port | Agent Port | Description |
|-------|--------|----------|------------|-------------|
| **ITSM** | IT Service Management | 8006 | 9101 | Incident, change, problem management |
| **CSM** | Customer Service | 8001 | 9102 | Case lifecycle, SLA monitoring |
| **Calendar** | Scheduling | 8003 | 9103 | Event management, availability |

## Setup & Running

### Prerequisites

- Docker Desktop (with **Resource Saver disabled**)
- Python 3.11+
- Google API key with Generative Language API enabled

### 1. Install Dependencies

```bash
pip install -r agents/requirements.txt
```

### 2. Configure API Key

Edit `agents/.env`:
```
GOOGLE_API_KEY=your-gemini-api-key
GOOGLE_MODEL=gemini-3-flash-preview
```

Available models: `gemini-3-flash-preview` (fast), `gemini-3-pro-preview` (capable)

### 3. Extract Seed Databases

```bash
unzip gym_dbs.zip   # Creates "Domain Wise DBs and Task-DB Mappings/"
```

### 4. Start MCP Servers

```bash
docker compose up -d gym-itsm    # Port 8006
docker compose up -d gym-csm     # Port 8001
docker compose up -d gym-calendar # Port 8003
```

### 5. Start Agent Servers

```bash
# Each in a separate terminal (or background)
uvicorn agents.itsm_agent.agent:app --host 0.0.0.0 --port 9101
uvicorn agents.csm_agent.agent:app --host 0.0.0.0 --port 9102
uvicorn agents.calendar_agent.agent:app --host 0.0.0.0 --port 9103
```

### 6. Run Benchmarks

```bash
python evaluate.py \
  --hf_dataset ServiceNow-AI/EnterpriseOps-Gym \
  --domain itsm \
  --mode oracle \
  --orchestrator external \
  --agent_url http://localhost:9101/task \
  --output_folder results/itsm-adk-agent \
  --concurrency 3 \
  --num_runs 1
```

### 7. Score Results

```bash
python compute_score.py --results_folder results/itsm-adk-agent
```

## Example: Task Execution

### Prompt

> After identifying that incident INC0000011 is still pending in our workspace which recently was again brought to our notice by Carlos Rodriguez as it's highly impacting his Wi-Fi networks, indicating a high business impact that should be updated accordingly. Progress the work on this incident so as to get it quickly resolved, check if there are any SLAs already linked, if not provide a valid and appropriate SLA and align it to the incident. Also notify Carlos regarding the same.

### Agent Response

> I have processed the request for incident **INC0000011** regarding the Wi-Fi network issues reported by Carlos Rodriguez.
>
> **Actions Taken:**
> 1. **Incident Status Update:** Updated Impact to High. Set Urgency to Medium. Recalculated Priority to High (High Impact x Medium Urgency). Moved Status to In Progress.
> 2. **SLA Check & Link:** Verified no existing SLA was linked. Created and aligned an appropriate SLA based on the High priority.
> 3. **Notification:** Sent notification to Carlos Rodriguez regarding the incident update and priority escalation.

### Verification Results

| Verifier | Result |
|----------|--------|
| Incident update | PASS |
| SLA link | PASS |
| Notification sent | PASS |

## Benchmark Results

Model: `gemini-3-flash-preview` | Mode: Oracle

| Domain | Tasks | Errors | Success Rate | Verifier Pass Rate |
|--------|-------|--------|-------------|-------------------|
| **ITSM** | 103 | 7 | **28.16%** | **56.65%** |
| **Calendar** | 61 | 5 | **13.11%** | **60.11%** |
| **CSM** | 103 | 0 | **0.97%** | **6.24%** |

**Notes:**
- ITSM performed best overall with strong policy compliance and multi-step tool execution
- Calendar achieved the highest verifier pass rate (60%) despite lower task success — individual steps often pass but full task completion is harder
- CSM scored low due to ADK tool schema compatibility issues with certain MCP tools (e.g. `find_product` output schema validation). The agent returns error messages instead of completing tasks when these tools are involved

## API Reference

### POST /task — OpsGym Adapter

**Request:**
```json
{
  "system_prompt": "Domain policy and instructions...",
  "user_prompt": "The task to perform...",
  "mcp_servers": [
    {
      "name": "gym-itsm-mcp",
      "url": "http://localhost:8006",
      "endpoint": "/mcp",
      "database_id": "db_123_abc",
      "context": {"x-itsm-user-token": "token_value"}
    }
  ],
  "selected_tools": ["get_incident", "update_incident"],
  "restricted_tools": [],
  "task_id": "task_001"
}
```

**Response:**
```json
{
  "final_response": "I have completed the requested actions...",
  "tools_used": ["get_incident", "update_incident", "send_notification"],
  "tool_results": [
    {
      "tool_name": "get_incident",
      "arguments": {},
      "result": {}
    }
  ],
  "conversation_flow": []
}
```

### GET /a2a/.well-known/agent.json — A2A Agent Card

Returns the agent's A2A protocol card with capabilities, skills, and protocol version.

```json
{
  "name": "itsm_agent",
  "description": "IT Service Management agent for incident, change, and problem management",
  "url": "http://localhost:9101",
  "protocolVersion": "0.2.6",
  "skills": [...]
}
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Docker keeps stopping | Disable **Resource Saver** in Docker Desktop Settings > Resources |
| Port conflict crashes Docker | Use ports 9101-9103 for agents (avoid 9001 which conflicts with Docker's internal proxy) |
| `INVALID_ARGUMENT` on tool schemas | Ensure `selected_tools` is provided (oracle mode) — loading all 90+ tools can hit Gemini schema limits |
| `models/gemini-3.0-flash-preview not found` | Use `gemini-3-flash-preview` (no `.0`) |
| `No API key` | Set `GOOGLE_API_KEY` in `agents/.env` |
| `Generative Language API not enabled` | Enable at https://console.developers.google.com/apis/api/generativelanguage.googleapis.com |
