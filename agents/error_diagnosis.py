import uuid
import os
from typing import Optional
import json
from core.schema import RunReport, DiagnosisReport, FlowSchema
from core.llm import call_llm
from agents.rag_context import retrieve_relevant_dom

SYSTEM_PROMPT = """
You are the Error Diagnosis Agent. Your job is to analyze browser automation script failures.
You will be given the original FlowSchema, the generated script, the run log, and a DOM snapshot (HTML) at the time of failure.

Determine the type of error. The allowed error types are:
- broken_selector
- timeout
- navigation_failure
- assertion_failure
- server_error
- auth_failure
- unknown

Identify the affected step number (1-indexed), the selector that caused the issue (if any), and provide a confidence rating (0.0 to 1.0).
If the error is a `broken_selector`, suggest alternative selectors that are present in the DOM snapshot. Check the attributes like id, data-testid, class, or text.
Classify whether the repair is eligible (we only attempt repair for `broken_selector` and `timeout`).

Format the response strictly as a JSON object matching this schema:
{
  "error_type": "broken_selector | timeout | navigation_failure | assertion_failure | server_error | auth_failure | unknown",
  "confidence": 0.9,
  "affected_step": 2,
  "affected_selector": "#selector-that-failed",
  "suggested_alternatives": [".suggested-class", "[data-testid='btn']"],
  "repair_eligible": true,
  "explanation": "Brief explanation of why it failed and how to fix it."
}

Do not wrap response in markdown code blocks. Return raw JSON.
"""

def diagnose_run(
    run: RunReport,
    flow: FlowSchema,
    script_content: str,
    api_key: str,
    provider: str = "openai",
    base_url: Optional[str] = None
) -> DiagnosisReport:
    # Read the log
    log_content = ""
    if run.artifacts.log and os.path.exists(run.artifacts.log):
        with open(run.artifacts.log, "r", encoding="utf-8") as f:
            log_content = f.read()
            
    # Read DOM snapshot — use RAG retrieval to send only the most relevant chunks
    dom_content = ""
    if run.artifacts.dom_snapshot and os.path.exists(run.artifacts.dom_snapshot):
        with open(run.artifacts.dom_snapshot, "r", encoding="utf-8") as f:
            raw_dom = f.read()
        # Build a query from the error context for targeted chunk retrieval
        error_query = ""
        if run.error:
            error_query = f"{run.error.error_type} {run.error.message} step {run.error.step_id}"
        dom_content = retrieve_relevant_dom(raw_dom, query=error_query or "error selector failed")
            
    user_prompt = f"""
    Flow Name: {flow.flow_name}
    Steps: {json.dumps([step.model_dump() for step in flow.steps], indent=2)}
    
    Original Generated Script:
    {script_content}
    
    Execution Run Error:
    {json.dumps(run.error.model_dump() if run.error else {}, indent=2)}
    
    Run Logs:
    {log_content}
    
    DOM Snapshot (Truncated if large):
    {dom_content}
    """
    
    response_text = call_llm(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        api_key=api_key,
        provider=provider,
        base_url=base_url,
        response_format={"type": "json_object"}
    )

    diag_data = json.loads(response_text.strip())
    
    return DiagnosisReport(
        diagnosis_id=str(uuid.uuid4()),
        run_id=run.run_id,
        error_type=diag_data.get("error_type", "unknown"),
        confidence=diag_data.get("confidence", 0.5),
        affected_step=diag_data.get("affected_step", 1),
        affected_selector=diag_data.get("affected_selector"),
        suggested_alternatives=diag_data.get("suggested_alternatives", []),
        repair_eligible=diag_data.get("repair_eligible", False),
        explanation=diag_data.get("explanation", "Unknown error")
    )
