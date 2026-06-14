import uuid
import re
from datetime import datetime
from typing import List, Optional
import json
from playwright.sync_api import sync_playwright
from core.schema import FlowSchema, FlowStep
from core.llm import call_llm

# ── Intent detection ──────────────────────────────────────────────────────────

SCRAPE_KEYWORDS   = ["scrape", "extract", "collect", "harvest", "pull", "gather",
                     "list all", "get all", "print", "data", "export"]
MONITOR_KEYWORDS  = ["monitor", "check", "verify", "watch", "alert", "detect",
                     "assert", "confirm", "validate", "ensure"]
# Anything not matching the above is treated as an automation/interaction flow

def detect_intent(goal: str) -> str:
    g = goal.lower()
    if any(kw in g for kw in SCRAPE_KEYWORDS):
        return "scrape"
    if any(kw in g for kw in MONITOR_KEYWORDS):
        return "monitor"
    return "automate"

# ── DOM extractors ────────────────────────────────────────────────────────────

def extract_interactive_elements(page) -> List[dict]:
    """For automation/monitor flows: extract buttons, inputs, links."""
    return page.evaluate(r"""
        () => {
            const results = [];
            const nodes = document.querySelectorAll(
                'button, input, a, select, textarea, [role="button"], [role="link"]'
            );
            nodes.forEach(node => {
                const style = window.getComputedStyle(node);
                if (style.display === 'none' || style.visibility === 'hidden') return;
                results.push({
                    tag: node.tagName.toLowerCase(),
                    id: node.getAttribute('id') || '',
                    name: node.getAttribute('name') || '',
                    type: node.getAttribute('type') || '',
                    placeholder: node.getAttribute('placeholder') || '',
                    aria_label: node.getAttribute('aria-label') || '',
                    role: node.getAttribute('role') || '',
                    testid: node.getAttribute('data-testid') || '',
                    classes: node.className || '',
                    text: (node.innerText || node.value || '').trim().substring(0, 60)
                });
            });
            return results;
        }
    """)

def extract_data_elements(page) -> dict:
    """For scraping flows: extract repeating data structures and their content."""
    return page.evaluate(r"""
        () => {
            // Find repeating container elements (lists, grids, tables, articles)
            const candidates = document.querySelectorAll(
                'article, li, tr, .card, .item, .product, .result, ' +
                '[class*="card"], [class*="item"], [class*="product"], [class*="result"], ' +
                '[class*="listing"], [class*="entry"], [class*="row"]'
            );

            // Group by tag+class to find repeating patterns
            const groups = {};
            candidates.forEach(el => {
                const key = el.tagName + '.' + (el.className || '').trim().split(/\s+/).join('.');
                if (!groups[key]) groups[key] = [];
                groups[key].push(el);
            });

            // Pick the group with the most repetitions (most likely the data list)
            let bestKey = null, bestCount = 0;
            for (const [key, els] of Object.entries(groups)) {
                if (els.length > bestCount) { bestCount = els.length; bestKey = key; }
            }

            if (!bestKey || bestCount < 2) {
                // Fallback: sample text/price/heading nodes
                return {
                    container: null,
                    sample_count: 0,
                    text_nodes: Array.from(document.querySelectorAll('h1,h2,h3,p,span,td'))
                        .slice(0, 30)
                        .map(el => ({
                            tag: el.tagName.toLowerCase(),
                            classes: el.className || '',
                            text: (el.innerText || '').trim().substring(0, 80)
                        }))
                };
            }

            const containerEls = groups[bestKey];
            const containerSelector = bestKey.replace(/\./g, ' .').replace(' ', '');

            // Sample first 3 containers to discover child field selectors
            const fieldSamples = [];
            containerEls.slice(0, 3).forEach(container => {
                const fields = [];
                container.querySelectorAll('*').forEach(child => {
                    const text = (child.innerText || '').trim();
                    if (text && child.children.length === 0) {
                        fields.push({
                            tag: child.tagName.toLowerCase(),
                            classes: child.className || '',
                            text: text.substring(0, 60),
                            title_attr: child.getAttribute('title') || '',
                            href: child.getAttribute('href') || ''
                        });
                    }
                });
                fieldSamples.push(fields);
            });

            return {
                container: containerSelector,
                sample_count: containerEls.length,
                field_samples: fieldSamples
            };
        }
    """)

# ── System prompts ────────────────────────────────────────────────────────────

AUTOMATE_SYSTEM_PROMPT = """
You are the Flow Discovery Agent for a browser automation tool.
Given interactive DOM elements from a web page and a user goal, identify the structured steps to complete the flow.

Allowed actions: navigate, click, fill, select, hover, assert
- assert: check page URL or visible text confirms the action succeeded. Use partial text match.

Return strictly this JSON (no markdown):
{
  "flow_name": "string",
  "steps": [
    {
      "step_id": 1,
      "action": "navigate|click|fill|select|hover|assert",
      "selector": "CSS selector or null",
      "selector_strategy": "css|xpath|text|role|testid",
      "value": "input value, assertion text, or URL — or null",
      "description": "what this step does",
      "timeout_ms": 5000
    }
  ]
}

Rules:
- First step is always navigate to the URL.
- Prefer id, data-testid, name, aria-label selectors over class-based ones.
- Only use selectors that exist in the provided element list.
- Return raw JSON only.
"""

SCRAPE_SYSTEM_PROMPT = """
You are the Flow Discovery Agent for a browser automation tool.
Given data elements sampled from a web page and a scraping goal, produce flow steps that EXTRACT and PRINT data.

Allowed actions: navigate, scrape, assert
- scrape: extract a list of items from repeating elements and print as JSON.

Return strictly this JSON (no markdown):
{
  "flow_name": "string",
  "steps": [
    {
      "step_id": 1,
      "action": "navigate|scrape|assert",
      "selector": "CSS selector for the repeating container, or null",
      "selector_strategy": "css",
      "value": "comma-separated field descriptors for scrape action, or null",
      "description": "what this step extracts",
      "timeout_ms": 15000
    }
  ]
}

For a scrape step, set:
- selector: the repeating container CSS selector (e.g. "article.product_pod")
- value: field descriptors as JSON string: {"field_name": "child_css_selector_or_@attr"}
  e.g. {"title": "h3 > a@title", "price": "p.price_color", "rating": "p.star-rating@class"}

Return raw JSON only.
"""

MONITOR_SYSTEM_PROMPT = """
You are the Flow Discovery Agent for a browser automation tool.
Given DOM elements from a web page and a monitoring goal, produce steps that navigate to the page and assert key conditions.

Allowed actions: navigate, assert
- assert: verify a value, text, or URL condition is true.

Return strictly this JSON (no markdown):
{
  "flow_name": "string",
  "steps": [
    {
      "step_id": 1,
      "action": "navigate|assert",
      "selector": "CSS selector or null",
      "selector_strategy": "css|xpath|text|role|testid",
      "value": "expected text or URL fragment to assert",
      "description": "what this step checks",
      "timeout_ms": 10000
    }
  ]
}

Return raw JSON only.
"""

# ── Script generator system prompt for scrape steps ──────────────────────────

SCRAPE_STEP_PROMPT_HINT = """
When you see action = "scrape":
- selector is the container CSS selector
- value is a JSON string describing fields: {"field_name": "child_css@attr_or_text"}
- Generate a loop:
    items = []
    for item in page.locator("{selector}").all():
        items.append({
            "field_name": (item.locator("child_css").get_attribute("attr") or "").strip(),
            ...
        })
    print(json.dumps({"total": len(items), "items": items}, indent=2, ensure_ascii=False))
"""

# ── Main discovery function ───────────────────────────────────────────────────

def discover_flow(url: str, goal: str, api_key: str, provider: str = "openai", base_url: Optional[str] = None) -> FlowSchema:
    intent = detect_intent(goal)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(url, wait_until="networkidle", timeout=30000)

            if intent == "scrape":
                dom_data = extract_data_elements(page)
                system_prompt = SCRAPE_SYSTEM_PROMPT
                user_prompt = f"""
Target URL: {url}
User Goal: {goal}

Sampled repeating data elements from the page:
{json.dumps(dom_data, indent=2)}

Build scrape steps to extract the requested data. First step: navigate to {url}.
"""
            elif intent == "monitor":
                dom_data = extract_interactive_elements(page)
                system_prompt = MONITOR_SYSTEM_PROMPT
                user_prompt = f"""
Target URL: {url}
User Goal: {goal}

Page elements:
{json.dumps(dom_data, indent=2)}

Build monitoring steps to assert the conditions described in the goal. First step: navigate to {url}.
"""
            else:
                dom_data = extract_interactive_elements(page)
                system_prompt = AUTOMATE_SYSTEM_PROMPT
                user_prompt = f"""
Target URL: {url}
User Goal: {goal}

Interactive elements on the page:
{json.dumps(dom_data, indent=2)}

Build automation steps to complete the goal. First step: navigate to {url}.
"""
        except Exception as e:
            print(f"Error extracting DOM: {e}")
            dom_data = []
            system_prompt = AUTOMATE_SYSTEM_PROMPT
            user_prompt = f"Target URL: {url}\nUser Goal: {goal}\nNo DOM data available."
        finally:
            browser.close()

    response_text = call_llm(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        api_key=api_key,
        provider=provider,
        base_url=base_url
    )

    # Strip markdown fences
    clean_text = response_text.strip()
    if clean_text.startswith("```json"):
        clean_text = clean_text[7:]
    elif clean_text.startswith("```"):
        clean_text = clean_text[3:]
    if clean_text.endswith("```"):
        clean_text = clean_text[:-3]
    clean_text = clean_text.strip()

    flow_data = json.loads(clean_text)

    steps = []
    for idx, s in enumerate(flow_data.get("steps", [])):
        steps.append(FlowStep(
            step_id=s.get("step_id", idx + 1),
            action=s.get("action"),
            selector=s.get("selector"),
            selector_strategy=s.get("selector_strategy", "css"),
            value=s.get("value"),
            description=s.get("description"),
            timeout_ms=s.get("timeout_ms", 5000)
        ))

    return FlowSchema(
        flow_id=str(uuid.uuid4()),
        flow_name=flow_data.get("flow_name", "Discovered Flow"),
        url=url,
        steps=steps,
        created_at=datetime.utcnow().isoformat() + "Z",
        target_framework="playwright"
    )
