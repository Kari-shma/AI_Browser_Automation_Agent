from fastapi import APIRouter, Header, HTTPException, Body, Query
from typing import Optional, List
from core import storage, orchestrator
from core.schema import RunReport, DiagnosisReport
from agents import adaptive_repair, execution_agent, parallel_runner
import os

router = APIRouter()
GENERATED_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "scripts", "generated")

@router.post("", response_model=RunReport)
def run_flow_endpoint(
    flow_id: str = Body(..., embed=True),
    browser: str = Body("chromium", embed=True),
    headless: bool = Body(True, embed=True),
    max_repair_attempts: int = Body(3, embed=True),
    x_api_key: Optional[str] = Header(None),
    x_api_provider: Optional[str] = Header("openai"),
    x_api_base_url: Optional[str] = Header(None)
):
    if not x_api_key:
        raise HTTPException(status_code=400, detail="Missing API Key in headers (X-API-Key)")
        
    try:
        report = orchestrator.run_orchestrated_flow(
            flow_id=flow_id,
            api_key=x_api_key,
            provider=x_api_provider,
            base_url=x_api_base_url,
            browser=browser,
            headless=headless,
            max_repair_attempts=max_repair_attempts
        )
        return report
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Execution orchestration failed: {str(e)}")

@router.post("/batch", response_model=List[RunReport])
def run_flows_batch(
    flow_ids: List[str] = Body(..., embed=True),
    browser: str = Body("chromium", embed=True),
    headless: bool = Body(True, embed=True),
    max_repair_attempts: int = Body(3, embed=True),
    max_workers: int = Body(4, embed=True),
    x_api_key: Optional[str] = Header(None),
    x_api_provider: Optional[str] = Header("openai"),
    x_api_base_url: Optional[str] = Header(None)
):
    """Run multiple flows in parallel using a thread pool."""
    if not x_api_key:
        raise HTTPException(status_code=400, detail="Missing API Key in headers (X-API-Key)")
    if not flow_ids:
        raise HTTPException(status_code=400, detail="flow_ids list must not be empty")
    try:
        reports = parallel_runner.run_flows_in_parallel(
            flow_ids=flow_ids,
            api_key=x_api_key,
            provider=x_api_provider,
            base_url=x_api_base_url,
            browser=browser,
            headless=headless,
            max_repair_attempts=max_repair_attempts,
            max_workers=max_workers
        )
        return reports
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch execution failed: {str(e)}")

@router.get("", response_model=List[RunReport])
def list_runs(flow_id: Optional[str] = Query(None)):
    if flow_id:
        return storage.get_runs_by_flow(flow_id)
    return storage.get_all_runs()

@router.get("/{run_id}", response_model=RunReport)
def get_run(run_id: str):
    run = storage.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run

@router.get("/{run_id}/diagnosis", response_model=Optional[DiagnosisReport])
def get_run_diagnosis(run_id: str):
    return storage.get_diagnosis(run_id)

@router.get("/{run_id}/artifacts")
def get_artifacts(run_id: str):
    run = storage.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
        
    artifact_details = {}
    if run.artifacts.screenshot and os.path.exists(run.artifacts.screenshot):
        artifact_details["screenshot"] = f"/artifacts/{run_id}/screenshot.png"
    if run.artifacts.dom_snapshot and os.path.exists(run.artifacts.dom_snapshot):
        artifact_details["dom_snapshot"] = f"/artifacts/{run_id}/dom_snapshot.html"
    if run.artifacts.log and os.path.exists(run.artifacts.log):
        artifact_details["log"] = f"/artifacts/{run_id}/run.log"
        
    # Check if a visual diff exists
    run_dir = os.path.dirname(run.artifacts.log)
    diff_path = os.path.join(run_dir, "visual_diff.png")
    if os.path.exists(diff_path):
        artifact_details["visual_diff"] = f"/artifacts/{run_id}/visual_diff.png"
        
    return artifact_details
