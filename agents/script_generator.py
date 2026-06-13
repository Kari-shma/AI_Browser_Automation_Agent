import os
import json
from typing import Optional
from core.schema import FlowSchema
from core.llm import call_llm

SYSTEM_PROMPT = """
You are the Script Generator Agent. Your task is to output a fully executable, standalone Playwright Python script based on a given FlowSchema.

Requirements for the generated Python script:
1. Use the sync Playwright API (`from playwright.sync_api import sync_playwright`).
2. Implement argument parsing to support `--headless` (flag), `--screenshot` (path to save screenshot on completion/failure), and `--snapshot` (path to save HTML DOM snapshot on completion/failure).
3. The script must execute the steps sequentially:
   - navigate: `page.goto(value, timeout=timeout_ms)`
   - click: `page.click(selector, timeout=timeout_ms)`
   - fill: `page.fill(selector, value, timeout=timeout_ms)`
   - select: `page.select_option(selector, value, timeout=timeout_ms)`
   - hover: `page.hover(selector, timeout=timeout_ms)`
   - assert: Perform standard assertions (e.g. check current URL or content) and throw `AssertionError` if condition fails.
4. Annotate each step with a comment: `# STEP {step_id}: {description}`
5. Wrap the execution in a try-except block. If ANY step fails:
   - Capture a screenshot if the `--screenshot` arg is provided.
   - Capture a DOM snapshot (HTML file) if the `--snapshot` arg is provided.
   - Print a structured JSON error string to standard error or standard output on a single line starting with "ERROR_REPORT:" followed by the JSON block:
     `ERROR_REPORT: {"type": "type of error", "message": "error description", "step_id": failed_step_id, "selector": "selector_used_or_null"}`
   - Exit with code 1.
6. If the script succeeds, exit with code 0.

Output ONLY valid, compilable Python code. Do not include markdown blocks (like ```python) or extra explanation text.
"""

def generate_script(flow: FlowSchema, api_key: str, provider: str = "openai", base_url: Optional[str] = None) -> str:
    user_prompt = f"""
    Generate a Playwright Python script for the following flow:
    
    Flow ID: {flow.flow_id}
    Flow Name: {flow.flow_name}
    Flow Steps:
    {json.dumps([step.dict() for step in flow.steps], indent=2)}
    """
    
    code = call_llm(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        api_key=api_key,
        provider=provider,
        base_url=base_url
    )
    
    # Strip markdown if any
    code = code.strip()
    if code.startswith("```python"):
        code = code[9:]
    elif code.startswith("```"):
        code = code[3:]
        
    if code.endswith("```"):
        code = code[:-3]
        
    return code.strip()
