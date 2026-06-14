"""
Run analytics using pandas.
Reads all RunReports from storage and produces summary statistics:
pass rate, average duration, per-flow breakdown, failure type counts.
"""
import pandas as pd
from typing import List, Dict, Any
from core import storage


def get_run_summary() -> Dict[str, Any]:
    """
    Build a pandas DataFrame from all run history and return summary stats.
    Returns a dict ready to be serialised as JSON.
    """
    runs = storage.get_all_runs()

    if not runs:
        return {"total_runs": 0, "message": "No runs recorded yet."}

    # Build flat records for DataFrame
    records = [
        {
            "run_id":     r.run_id,
            "flow_id":    r.flow_id,
            "status":     r.status,
            "duration_ms": r.duration_ms,
            "browser":    r.browser,
            "timestamp":  r.timestamp,
            "error_type": r.error.type if r.error else None,
        }
        for r in runs
    ]

    df = pd.DataFrame(records)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df["duration_s"] = df["duration_ms"] / 1000.0

    # ── Overall stats ──────────────────────────────────────────────────────────
    total = len(df)
    pass_count = int((df["status"] == "pass").sum())
    fail_count = int((df["status"] == "fail").sum())
    pass_rate = round(pass_count / total * 100, 1)
    avg_duration_s = round(df["duration_s"].mean(), 2)

    # ── Per-flow breakdown ─────────────────────────────────────────────────────
    per_flow = (
        df.groupby("flow_id")
        .agg(
            total_runs=("run_id", "count"),
            passes=("status", lambda s: (s == "pass").sum()),
            failures=("status", lambda s: (s == "fail").sum()),
            avg_duration_s=("duration_s", "mean"),
        )
        .reset_index()
    )
    per_flow["pass_rate_pct"] = (per_flow["passes"] / per_flow["total_runs"] * 100).round(1)
    per_flow["avg_duration_s"] = per_flow["avg_duration_s"].round(2)
    per_flow_records = per_flow.to_dict(orient="records")

    # ── Failure type breakdown ─────────────────────────────────────────────────
    error_counts = (
        df[df["error_type"].notna()]
        .groupby("error_type")["run_id"]
        .count()
        .reset_index()
        .rename(columns={"run_id": "count"})
        .to_dict(orient="records")
    )

    return {
        "total_runs":     total,
        "pass_count":     pass_count,
        "fail_count":     fail_count,
        "pass_rate_pct":  pass_rate,
        "avg_duration_s": avg_duration_s,
        "per_flow":       per_flow_records,
        "error_breakdown": error_counts,
    }
