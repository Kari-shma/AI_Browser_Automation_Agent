import os
import shutil
from typing import Optional
from core.schema import DiagnosisReport, FlowSchema
from core.llm import call_llm

SYSTEM_PROMPT = """
You are the Adaptive Repair Agent. Your task is to auto-patch a broken Playwright Python script based on a DiagnosisReport.

Guidelines:
1. ONLY modify the line(s) causing the failure (e.g., replace the incorrect selector with one of the suggested alternatives, or increase a timeout).
2. NEVER modify assertion logic, test flow ordering, or other steps that are passing.
3. Keep the overall script structure, import statements, try-except harness, and argument parsing exactly the same.
4. Ensure the output is a valid, compilable Python script.

Output ONLY the fully patched Python script code. Do not wrap the response in markdown code blocks (like ```python) or include extra text.
"""

def repair_script(
    flow_id: str,
    original_script: str,
    diagnosis: DiagnosisReport,
    api_key: str,
    provider: str = "openai",
    base_url: Optional[str] = None
) -> str:
    # Backup the original script
    generated_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "generated")
    original_path = os.path.join(generated_dir, f"{flow_id}.py")
    if os.path.exists(original_path):
        backup_path = os.path.join(generated_dir, f"{flow_id}_backup.py")
        shutil.copy2(original_path, backup_path)
        print(f"Backed up original script to {backup_path}")
        
    user_prompt = f"""
    Original Script content:
    {original_script}
    
    Diagnosis Report:
    - Error Type: {diagnosis.error_type}
    - Affected Step: {diagnosis.affected_step}
    - Affected Selector: {diagnosis.affected_selector}
    - Suggested Selector/Wait Alternatives: {diagnosis.suggested_alternatives}
    - Explanation: {diagnosis.explanation}
    
    Please provide the corrected script content.
    """
    
    patched_code = call_llm(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        api_key=api_key,
        provider=provider,
        base_url=base_url
    )
    
    # Strip markdown if any
    patched_code = patched_code.strip()
    if patched_code.startswith("```python"):
        patched_code = patched_code[9:]
    elif patched_code.startswith("```"):
        patched_code = patched_code[3:]
        
    if patched_code.endswith("```"):
        patched_code = patched_code[:-3]
        
    return patched_code.strip()
