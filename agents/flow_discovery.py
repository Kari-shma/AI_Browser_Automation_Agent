import uuid
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urljoin
import json
from playwright.sync_api import sync_playwright
from core.schema import FlowSchema, FlowStep
from core.llm import call_llm, call_llm_langchain, call_llm_with_retry

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
The browser has ALREADY navigated to the correct page. Your only job is to describe how to extract data.

Allowed actions: scrape, assert
IMPORTANT: Do NOT include any navigate steps. Navigation is handled separately by the system.

Return strictly this JSON (no markdown):
{
  "flow_name": "string",
  "steps": [
    {
      "step_id": 1,
      "action": "scrape|assert",
      "selector": "CSS selector for the repeating container, or null",
      "selector_strategy": "css",
      "value": "field descriptors JSON string for scrape action, or null",
      "description": "what this step extracts",
      "timeout_ms": 15000
    }
  ]
}

For a scrape step, set:
- selector: the repeating container CSS selector (e.g. "article.product_pod")
- value: field descriptors as JSON string: {"field_name": "child_css_selector_or_@attr"}
  e.g. {"title": "h3 > a@title", "price": "p.price_color", "rating": "p.star-rating@class"}

Example:
DOM sample from a books listing page:
  container: "article.product_pod"
  field_samples: [{"tag":"a","classes":"","text":"A Light in the Attic","title_attr":"A Light in the Attic"},
                  {"tag":"p","classes":"price_color","text":"£51.77"},
                  {"tag":"p","classes":"star-rating Three","text":""}]

Correct output:
{
  "flow_name": "Scrape book listings",
  "steps": [{
    "step_id": 1,
    "action": "scrape",
    "selector": "article.product_pod",
    "selector_strategy": "css",
    "value": "{\\"title\\": \\"h3 > a@title\\", \\"price\\": \\"p.price_color\\", \\"rating\\": \\"p.star-rating@class\\"}",
    "description": "Extract title, price, rating from each book card",
    "timeout_ms": 15000
  }]
}

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

# ── Goal-driven navigation ────────────────────────────────────────────────────

NAV_RESOLUTION_PROMPT = """
You are a browser navigation assistant. Given a list of links on a page and a user goal,
decide whether the user needs to navigate to a different page before scraping.

If the goal mentions a specific category, section, filter, or sub-page that is NOT the current page,
return the href of the single link the user should navigate to.

If the user can scrape directly from the current page, return null.

Respond with ONLY a JSON object — no markdown:
{"nav_href": "/path/to/subpage" | null, "reason": "brief explanation"}

Example:
Goal: "Scrape the top 3 highest priced books from the Fiction category"
Links include: {"text": "Fiction", "href": "/catalogue/category/books/fiction_10/index.html"}
→ {"nav_href": "/catalogue/category/books/fiction_10/index.html", "reason": "Goal specifies Fiction category; Fiction link leads to that page"}

If scraping from the current page is sufficient:
→ {"nav_href": null, "reason": "Current page already shows the required data"}
"""

def _resolve_navigation(page, url: str, goal: str, api_key: str, provider: str, base_url) -> Optional[str]:
    """
    Ask the LLM whether the goal requires navigating to a sub-page first.
    Returns an absolute URL to navigate to, or None if already on the right page.
    Uses page.goto instead of page.click to avoid selector / special-character failures.
    """
    links = page.evaluate("""
        () => Array.from(document.querySelectorAll('a[href]'))
            .filter(a => a.innerText.trim())
            .slice(0, 80)
            .map(a => ({
                text: a.innerText.trim().substring(0, 60),
                href: a.getAttribute('href')
            }))
    """)

    user_prompt = f"""
User Goal: {goal}

Links available on the current page:
{json.dumps(links, indent=2)}

Does the goal require navigating to a sub-page (e.g. a category, filter, or section)?
If yes, return the href of the correct link. If no, return null for nav_href.
"""
    try:
        response = call_llm_with_retry(
            system_prompt=NAV_RESOLUTION_PROMPT,
            user_prompt=user_prompt,
            api_key=api_key,
            provider=provider,
            base_url=base_url,
            response_format={"type": "json_object"}
        )
        data = json.loads(response.strip())
        nav_href = data.get("nav_href")
        reason = data.get("reason", "")
        print(f"[flow_discovery] Nav resolution: nav_href={nav_href!r} reason={reason!r}")
        if nav_href:
            return urljoin(url, nav_href)
        return None
    except Exception as e:
        print(f"[flow_discovery] Nav resolution failed: {e}")
        return None


# ── Main discovery function ───────────────────────────────────────────────────

def discover_flow(url: str, goal: str, api_key: str, provider: str = "openai", base_url: Optional[str] = None) -> FlowSchema:
    intent = detect_intent(goal)
    landed_url = url  # tracks where we actually ended up during discovery
    dom_data = {}
    flow_data = {"flow_name": "Discovered Flow"}
    steps = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(url, wait_until="networkidle", timeout=30000)

            if intent == "scrape":
                # Ask LLM if we need to navigate to a sub-page — use goto, not click
                abs_nav_url = _resolve_navigation(page, url, goal, api_key, provider, base_url)
                if abs_nav_url:
                    try:
                        page.goto(abs_nav_url, wait_until="networkidle", timeout=20000)
                        landed_url = page.url
                        print(f"[flow_discovery] Navigated to: {landed_url}")
                    except Exception as e:
                        print(f"[flow_discovery] Could not navigate to {abs_nav_url!r}: {e}")

                # Extract DOM from the page we actually landed on
                dom_data = extract_data_elements(page)
                system_prompt = SCRAPE_SYSTEM_PROMPT
                user_prompt = f"""
Target URL: {url}
User Goal: {goal}
Current page (data extracted from): {landed_url}

Sampled repeating data elements from the page:
{json.dumps(dom_data, indent=2)}

Build scrape steps to extract the requested data from the elements above.
Remember: do NOT include navigate steps — they are handled automatically.
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

            # Call LLM with retry and JSON mode enforcement
            response_text = call_llm_with_retry(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                api_key=api_key,
                provider=provider,
                base_url=base_url,
                response_format={"type": "json_object"}
            )
            flow_data = json.loads(response_text.strip())

            def _iter_steps(raw_steps):
                """Generator that yields FlowStep objects from raw LLM step dicts."""
                for idx, s in enumerate(raw_steps):
                    yield FlowStep(
                        step_id=s.get("step_id", idx + 1),
                        action=s.get("action"),
                        selector=s.get("selector"),
                        selector_strategy=s.get("selector_strategy", "css"),
                        value=s.get("value"),
                        description=s.get("description"),
                        timeout_ms=s.get("timeout_ms", 5000)
                    )

            steps = list(_iter_steps(flow_data.get("steps", [])))

            # For scrape flows: always inject navigation steps deterministically.
            # The LLM is forbidden from generating navigate steps; this is the only
            # source of navigation — guaranteeing correct URLs from the live browser.
            if intent == "scrape":
                non_nav_steps = [s for s in steps if s.action not in ("navigate", "click")]
                fixed_steps = [
                    FlowStep(step_id=1, action="navigate", value=url,
                             description=f"Navigate to {url}", timeout_ms=15000),
                ]
                if landed_url != url:
                    fixed_steps.append(
                        FlowStep(step_id=2, action="navigate", value=landed_url,
                                 description=f"Navigate to target page: {landed_url}", timeout_ms=15000)
                    )
                for i, s in enumerate(non_nav_steps, start=len(fixed_steps) + 1):
                    s.step_id = i
                    fixed_steps.append(s)
                steps = fixed_steps

                # Validate that the scrape selector actually matches elements on the live page
                for step in steps:
                    if step.action == "scrape" and step.selector:
                        try:
                            count = page.locator(step.selector).count()
                            print(f"[flow_discovery] Selector {step.selector!r} matched {count} elements")
                            if count == 0:
                                fallback = dom_data.get("container") if isinstance(dom_data, dict) else None
                                if fallback and fallback != step.selector:
                                    print(f"[flow_discovery] Falling back to DOM container: {fallback!r}")
                                    step.selector = fallback
                        except Exception as e:
                            print(f"[flow_discovery] Selector validation error: {e}")

        except Exception as e:
            print(f"[flow_discovery] Error during discovery: {e}")
            steps = [FlowStep(step_id=1, action="navigate", value=url,
                              description=f"Navigate to {url}", timeout_ms=15000)]
        finally:
            browser.close()

    return FlowSchema(
        flow_id=str(uuid.uuid4()),
        flow_name=flow_data.get("flow_name", "Discovered Flow"),
        url=url,
        goal=goal,
        steps=steps,
        created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        target_framework="playwright"
    )
