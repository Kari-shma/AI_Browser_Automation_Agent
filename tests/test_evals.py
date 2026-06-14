"""
Structured eval harness for the Browser Automation AI Agent.

Evaluates the deterministic (non-LLM) components of the pipeline:
  1. Intent detection accuracy
  2. Script generator output correctness (scrape flows)
  3. RAG context retrieval relevance
  4. Regression monitor diff accuracy (NumPy path)
  5. Run analytics DataFrame shape and content

Each eval case reports:
  - pass / fail
  - score (0.0 – 1.0) where applicable

Final results are saved to tests/eval_results.json.
"""
import os
import sys
import json
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.schema import FlowSchema, FlowStep
from agents.flow_discovery import detect_intent
from agents.script_generator import generate_script, _build_scrape_step_code
from agents.rag_context import retrieve_relevant_dom, _chunk_html
from agents import regression_monitor


# ── Helpers ───────────────────────────────────────────────────────────────────

RESULTS_PATH = os.path.join(os.path.dirname(__file__), "eval_results.json")

def _score(passed: int, total: int) -> float:
    return round(passed / total, 3) if total else 0.0


# ── Eval 1: Intent Detection ──────────────────────────────────────────────────

class EvalIntentDetection(unittest.TestCase):
    """Score how accurately detect_intent() classifies user goals."""

    CASES = [
        ("scrape all book titles from the page",        "scrape"),
        ("extract product prices and ratings",          "scrape"),
        ("collect data from the listing page",          "scrape"),
        ("monitor the homepage and check it loads",     "monitor"),
        ("verify the login button is visible",          "monitor"),
        ("login with username admin and password 123",  "automate"),
        ("click the submit button after filling form",  "automate"),
        ("go to checkout and enter card details",       "automate"),
    ]

    def test_intent_accuracy(self):
        passed = sum(
            1 for goal, expected in self.CASES
            if detect_intent(goal) == expected
        )
        score = _score(passed, len(self.CASES))
        print(f"\n[Eval 1] Intent detection — {passed}/{len(self.CASES)} correct | score={score}")
        _append_result("intent_detection", score, passed, len(self.CASES))
        self.assertGreaterEqual(score, 0.75, "Intent detection score below 75%")


# ── Eval 2: Script Generator (scrape steps) ───────────────────────────────────

class EvalScriptGenerator(unittest.TestCase):
    """Check that generated scrape code contains the expected Playwright calls."""

    def _make_scrape_step(self, container: str, fields: dict) -> FlowStep:
        return FlowStep(
            step_id=2,
            action="scrape",
            selector=container,
            value=json.dumps(fields),
            description="Scrape items",
            timeout_ms=15000
        )

    CASES = [
        {
            "container": "article.product_pod",
            "fields": {"title": "h3 > a@title", "price": "p.price_color", "rating": "p.star-rating@class"},
            "must_contain": [
                "page.locator('article.product_pod')",
                "get_attribute('title')",
                "text_content()",
                "get_attribute(\"class\")",
                'split()[1:]',
            ],
        },
        {
            "container": "li.result-item",
            "fields": {"name": "h2.name", "url": "a@href"},
            "must_contain": [
                "page.locator('li.result-item')",
                "get_attribute('href')",
            ],
        },
    ]

    def test_scrape_codegen(self):
        passed = 0
        total_checks = 0
        for case in self.CASES:
            step = self._make_scrape_step(case["container"], case["fields"])
            code = _build_scrape_step_code(step)
            for expected in case["must_contain"]:
                total_checks += 1
                if expected in code:
                    passed += 1
                else:
                    print(f"  MISSING in generated code: {expected!r}")

        score = _score(passed, total_checks)
        print(f"\n[Eval 2] Script codegen — {passed}/{total_checks} checks passed | score={score}")
        _append_result("script_codegen", score, passed, total_checks)
        self.assertGreaterEqual(score, 0.9, "Script codegen score below 90%")


# ── Eval 3: RAG Context Retrieval ─────────────────────────────────────────────

class EvalRagRetrieval(unittest.TestCase):
    """Verify that RAG retrieval returns relevant chunks and reduces context size."""

    FAKE_DOM = """
    <html><body>
    <nav><a href="/home">Home</a><a href="/about">About</a></nav>
    <main>
      <article class="product_pod">
        <h3><a href="/book/1" title="A Light in the Attic">A Light in the Attic</a></h3>
        <p class="price_color">£51.77</p>
        <p class="star-rating Three"></p>
      </article>
      <article class="product_pod">
        <h3><a href="/book/2" title="Tipping the Velvet">Tipping the Velvet</a></h3>
        <p class="price_color">£53.74</p>
        <p class="star-rating One"></p>
      </article>
    </main>
    <footer><p>Copyright 2024</p></footer>
    </html>
    """

    def test_chunking_produces_chunks(self):
        chunks = list(_chunk_html(self.FAKE_DOM, chunk_size=200, overlap=50))
        self.assertGreater(len(chunks), 0, "Chunking produced no output")
        print(f"\n[Eval 3a] Chunking — {len(chunks)} chunks produced")

    def test_retrieval_reduces_size(self):
        query = "star-rating class broken selector"
        result = retrieve_relevant_dom(self.FAKE_DOM, query=query, top_k=2)
        self.assertLess(len(result), len(self.FAKE_DOM),
                        "RAG output is not smaller than the full DOM")
        print(f"\n[Eval 3b] RAG retrieval — input={len(self.FAKE_DOM)} chars, output={len(result)} chars")
        _append_result("rag_retrieval_size_reduction", 1.0, 1, 1)

    def test_retrieval_relevance(self):
        query = "price_color selector"
        result = retrieve_relevant_dom(self.FAKE_DOM, query=query, top_k=2)
        # Result should contain book price data (£51.77 or 51.77) from the DOM
        has_price_data = "51.77" in result or "53.74" in result or "price" in result.lower()
        self.assertTrue(has_price_data, f"Retrieved chunks don't contain expected price data. Got: {result[:200]}")
        print(f"\n[Eval 3c] RAG relevance — price data found in retrieved context ✓")
        _append_result("rag_retrieval_relevance", 1.0, 1, 1)


# ── Eval 4: Regression Monitor (NumPy path) ───────────────────────────────────

class EvalRegressionMonitor(unittest.TestCase):
    """Verify the NumPy-based diff gives correct percentages."""

    def _make_img(self, color, path):
        from PIL import Image
        img = Image.new("RGB", (100, 100), color=color)
        img.save(path)

    def test_identical_images_zero_diff(self):
        from PIL import Image
        p1 = os.path.join(os.path.dirname(__file__), "_eval_base.png")
        p2 = os.path.join(os.path.dirname(__file__), "_eval_curr.png")
        diff_dir = os.path.join(os.path.dirname(__file__), "_eval_diff")
        try:
            self._make_img("black", p1)
            self._make_img("black", p2)
            report = regression_monitor.compare_screenshots(p1, p2, diff_dir)
            self.assertEqual(report["diff_percentage"], 0.0)
            self.assertEqual(report["status"], "pass")
            print(f"\n[Eval 4a] Identical images — diff={report['diff_percentage']}% ✓")
            _append_result("regression_identical", 1.0, 1, 1)
        finally:
            for f in [p1, p2, os.path.join(diff_dir, "visual_diff.png")]:
                if os.path.exists(f): os.remove(f)

    def test_different_images_nonzero_diff(self):
        p1 = os.path.join(os.path.dirname(__file__), "_eval_base2.png")
        p2 = os.path.join(os.path.dirname(__file__), "_eval_curr2.png")
        diff_dir = os.path.join(os.path.dirname(__file__), "_eval_diff2")
        try:
            self._make_img("black", p1)
            self._make_img("white", p2)
            report = regression_monitor.compare_screenshots(p1, p2, diff_dir, threshold=0.5)
            self.assertGreater(report["diff_percentage"], 0.0)
            self.assertEqual(report["status"], "fail")
            print(f"\n[Eval 4b] Different images — diff={report['diff_percentage']}%, status={report['status']} ✓")
            _append_result("regression_different", 1.0, 1, 1)
        finally:
            for f in [p1, p2, os.path.join(diff_dir, "visual_diff.png")]:
                if os.path.exists(f): os.remove(f)


# ── Eval 5: Run Analytics ─────────────────────────────────────────────────────

class EvalRunAnalytics(unittest.TestCase):
    """Verify run_analytics returns a properly shaped summary."""

    def test_analytics_summary_shape(self):
        from agents import run_analytics
        summary = run_analytics.get_run_summary()
        self.assertIn("total_runs", summary)
        self.assertIn("pass_rate_pct" if summary["total_runs"] > 0 else "message", summary)
        print(f"\n[Eval 5] Analytics summary keys: {list(summary.keys())} ✓")
        _append_result("analytics_shape", 1.0, 1, 1)


# ── Result writer ─────────────────────────────────────────────────────────────

def _append_result(name: str, score: float, passed: int, total: int):
    results = []
    if os.path.exists(RESULTS_PATH):
        with open(RESULTS_PATH, "r") as f:
            results = json.load(f)
    results.append({
        "eval": name,
        "score": score,
        "passed": passed,
        "total": total,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    })
    with open(RESULTS_PATH, "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
