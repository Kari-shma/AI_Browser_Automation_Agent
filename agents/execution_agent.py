import os
import sys
import time
import subprocess
import json
import uuid
from datetime import datetime, timezone
from typing import Tuple, Optional
from core.schema import RunReport, RunArtifacts, RunError

GENERATED_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "generated")
ARTIFACTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "artifacts")

os.makedirs(GENERATED_DIR, exist_ok=True)
os.makedirs(ARTIFACTS_DIR, exist_ok=True)

def execute_run(flow_id: str, script_content: str, browser: str = "chromium", headless: bool = True) -> RunReport:
    run_id = str(uuid.uuid4())
    run_dir = os.path.join(ARTIFACTS_DIR, run_id)
    os.makedirs(run_dir, exist_ok=True)
    
    script_path = os.path.join(GENERATED_DIR, f"{flow_id}.py")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script_content)
        
    screenshot_path = os.path.join(run_dir, "screenshot.png")
    snapshot_path = os.path.join(run_dir, "dom_snapshot.html")
    log_path = os.path.join(run_dir, "run.log")
    
    cmd = [
        sys.executable,
        script_path,
        "--screenshot", screenshot_path,
        "--snapshot", snapshot_path
    ]
    if headless:
        cmd.append("--headless")
    else:
        cmd.append("--watch-live")
        
    start_time = time.time()
    
    # Run the subprocess
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    duration_ms = int((time.time() - start_time) * 1000)
    
    # Write to run.log
    with open(log_path, "w", encoding="utf-8") as lf:
        lf.write(f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n")
        
    status = "pass" if result.returncode == 0 else "fail"
    
    # Check if files exist
    saved_screenshot = screenshot_path if os.path.exists(screenshot_path) else None
    saved_snapshot = snapshot_path if os.path.exists(snapshot_path) else None
    
    artifacts = RunArtifacts(
        log=log_path,
        screenshot=saved_screenshot,
        dom_snapshot=saved_snapshot
    )
    
    error = None
    if status == "fail":
        # Look for ERROR_REPORT: in output
        error_type = "unknown"
        error_msg = "Script exited with non-zero status code."
        step_id = None
        selector = None
        
        combined_output = result.stdout + "\n" + result.stderr
        for line in combined_output.split("\n"):
            if "ERROR_REPORT:" in line:
                try:
                    report_str = line.split("ERROR_REPORT:", 1)[1].strip()
                    report_data = json.loads(report_str)
                    error_type = report_data.get("type", "unknown")
                    error_msg = report_data.get("message", "Script execution failed.")
                    step_id = report_data.get("step_id")
                    selector = report_data.get("selector")
                    break
                except Exception as e:
                    print(f"Error parsing error report line: {e}")
                    
        error = RunError(
            type=error_type,
            message=error_msg,
            step_id=step_id,
            selector=selector
        )
        
    return RunReport(
        run_id=run_id,
        flow_id=flow_id,
        status=status,
        duration_ms=duration_ms,
        browser=browser,
        artifacts=artifacts,
        error=error,
        timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
