from fastapi import APIRouter, HTTPException
from agents import run_analytics

router = APIRouter()

@router.get("/summary")
def get_analytics_summary():
    """Return pandas-generated summary of all run history."""
    try:
        return run_analytics.get_run_summary()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analytics failed: {str(e)}")
