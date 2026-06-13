# AI Browser Automation Agent

A self-healing browser automation agent architecture utilizing Playwright, FastAPI, SQLite, and LLM orchestration (OpenAI / OpenRouter). It discovers user flows, generates script files, executes tests, classifies errors, automatically patches code scripts, and diffs visual regressions.

## Directory Structure

```
browser-automation-agent/
├── agents/
│   ├── flow_discovery.py        # Flow Discovery Agent
│   ├── script_generator.py      # Script Generator Agent
│   ├── execution_agent.py       # Execution Agent
│   ├── error_diagnosis.py       # Error Diagnosis Agent
│   ├── adaptive_repair.py       # Adaptive Repair Agent
│   └── regression_monitor.py    # Regression Monitor Agent
├── api/
│   ├── routes/
│   │   ├── flows.py
│   │   ├── runs.py
│   │   └── regression.py
│   └── main.py                  # FastAPI server entrypoint
├── core/
│   ├── orchestrator.py          # E2E self-healing workflow coordinations
│   ├── schema.py                # Pydantic schemas (FlowSchema, etc.)
│   ├── storage.py               # SQLite storage manager
│   └── llm.py                   # Dynamic LLM API completion router
├── static/
│   ├── index.html               # Premium Dashboard UI
│   ├── style.css                # Visual themes and layouts
│   └── app.js                   # State, API calls, and modals handler
├── tests/
│   └── test_agents.py           # Verification suite
├── db.sqlite                    # Automatically initialized DB
├── requirements.txt             # Project requirements
└── README.md
```

## Features

- **End-to-End Self Healing:** Automatically diagnoses errors (e.g. broken selectors or timeouts), extracts DOM snapshot elements, patches Playwright scripts, and retries.
- **Dynamic API Keys Settings:** Configure API Key, Provider (OpenAI/OpenRouter), and Custom Endpoint directly in the UI dashboard (stored securely in local storage).
- **Visual Regression Diffs:** Promote test screenshots to flow baselines and view highlighted pixel-level diff reports side-by-side.

## Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
python -m playwright install chromium
```

### 2. Run the application
```bash
python api/main.py
```
Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser.

### 3. Run automated tests
```bash
python -m unittest tests/test_agents.py
```
