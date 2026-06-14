"""
Parallel batch execution of multiple flows using ThreadPoolExecutor.
Demonstrates Python threading / parallelism concepts.
"""
import concurrent.futures
from typing import List, Optional, Tuple
from core import orchestrator, storage
from core.schema import RunReport


def _run_single(args: Tuple) -> RunReport:
    """Worker function executed in each thread."""
    flow_id, api_key, provider, base_url, browser, headless, max_repair_attempts = args
    return orchestrator.run_orchestrated_flow(
        flow_id=flow_id,
        api_key=api_key,
        provider=provider,
        base_url=base_url,
        browser=browser,
        headless=headless,
        max_repair_attempts=max_repair_attempts
    )


def run_flows_in_parallel(
    flow_ids: List[str],
    api_key: str,
    provider: str = "openai",
    base_url: Optional[str] = None,
    browser: str = "chromium",
    headless: bool = True,
    max_repair_attempts: int = 3,
    max_workers: int = 4
) -> List[RunReport]:
    """
    Runs multiple flows concurrently using a thread pool.
    Returns a list of RunReports in the same order as flow_ids.
    Flows that don't exist are silently skipped.
    """
    valid_ids = [fid for fid in flow_ids if storage.get_flow(fid) is not None]

    if not valid_ids:
        return []

    task_args = [
        (fid, api_key, provider, base_url, browser, headless, max_repair_attempts)
        for fid in valid_ids
    ]

    results: List[RunReport] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(max_workers, len(valid_ids))) as pool:
        futures = {pool.submit(_run_single, args): args[0] for args in task_args}
        for future in concurrent.futures.as_completed(futures):
            flow_id = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                print(f"[parallel_runner] flow {flow_id} raised: {exc}")

    return results
