import re
import json
from typing import Optional
from core.schema import FlowSchema
from core.llm import call_llm, call_llm_langchain

STEPS_SYSTEM_PROMPT = """
You are a Playwright automation expert. Given a list of flow steps, output ONLY the Python statements that execute those steps — nothing else.

Rules:
- Output raw Python lines only. No imports, no functions, no try/except, no argparse, no browser setup.
- Use the variable `page` (already available in scope).
- Precede each step with a comment: # STEP {step_id}: {description}
- Action mappings:
    navigate  -> page.goto("{value}", timeout={timeout_ms})
    fill      -> page.fill("{selector}", "{value}", timeout={timeout_ms})
    click     -> page.click("{selector}", timeout={timeout_ms})
    select    -> page.select_option("{selector}", "{value}", timeout={timeout_ms})
    hover     -> page.hover("{selector}", timeout={timeout_ms})
    assert    -> use page.locator("{selector}").text_content().strip() or page.url
                 ALWAYS use `in` for text checks, never `==`
                 e.g.: assert "expected text" in page.locator("{selector}").text_content().strip()
    scrape    -> The step's value field is a JSON string describing fields.
                 Generate a loop using page.locator("{selector}").all(), extract each field,
                 build a list of dicts, and print as JSON.
                 For "@attr" fields use .get_attribute("attr"), for plain selectors use .text_content()
                 e.g.:
                   items = []
                   for item in page.locator("{selector}").all():
                       items.append({
                           "title": (item.locator("h3 > a").get_attribute("title") or "").strip(),
                           "price": (item.locator("p.price_color").text_content() or "").strip(),
                       })
                   print(json.dumps({"total": len(items), "items": items}, indent=2, ensure_ascii=False))

Output ONLY the step lines. No markdown, no explanation.
"""

POSTPROCESS_SYSTEM_PROMPT = """
You are a Python data processing expert. You will be given:
1. A user goal describing what they want extracted or computed
2. A variable `items` — a list of dicts already extracted from the correct page

Your job: write 3-10 lines of pure Python that transform `items` into the final result.

Rules:
- You may sort, slice, deduplicate, compute, or reshape `items`.
- The final result must be stored back in `items`.
- IMPORTANT: The browser already navigated to the correct category/section page before scraping.
  Do NOT filter by category name — the items are already from the right page.
  Only sort, slice, or rank as the goal requires.
- Do NOT re-scrape, use Playwright, import anything, or define functions.
- End with exactly: print(json.dumps({"total": len(items), "items": items}, indent=2, ensure_ascii=False))
- If the goal needs numeric comparison (e.g. highest price), parse the value to float first.
- Output raw Python lines only. No markdown, no explanation.

Example — goal "top 3 highest priced books from Fiction":
# Parse price to float for sorting (browser is already on the Fiction page)
for item in items:
    item['_price_num'] = float(item.get('price', '0').replace('£', '').replace('$', '').strip() or 0)
# Sort descending by price, keep top 3
items = sorted(items, key=lambda x: x['_price_num'], reverse=True)[:3]
# Remove helper field by rebuilding each dict (do NOT reassign loop variable)
items = [{k: v for k, v in item.items() if not k.startswith('_')} for item in items]
print(json.dumps({"total": len(items), "items": items}, indent=2, ensure_ascii=False))
"""

SCRIPT_TEMPLATE = '''\
import sys
import json
import argparse
from playwright.sync_api import sync_playwright

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--watch-live", action="store_true")
    parser.add_argument("--screenshot", type=str)
    parser.add_argument("--snapshot", type=str)
    args = parser.parse_args()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        page = browser.new_context().new_page()
        current_step_id = None
        _watch = args.watch_live

        def _highlight(selector):
            if _watch and selector:
                try:
                    page.evaluate(
                        """(sel) => {{
                            const el = document.querySelector(sel);
                            if (!el) return;
                            const prev = el.style.cssText;
                            el.style.outline = '3px solid #FFD700';
                            el.style.boxShadow = '0 0 12px 4px rgba(255,215,0,0.7)';
                            el.style.transition = 'all 0.2s';
                            setTimeout(() => {{ el.style.cssText = prev; }}, 900);
                        }}""",
                        selector
                    )
                    page.wait_for_timeout(600)
                except Exception:
                    pass

        def _pause(ms=1200):
            if _watch:
                page.wait_for_timeout(ms)

        try:
{steps}

            # Save artifacts on success
            if args.screenshot:
                page.screenshot(path=args.screenshot, full_page=True)
            if args.snapshot:
                with open(args.snapshot, "w", encoding="utf-8") as f:
                    f.write(page.content())

            if _watch:
                page.evaluate("""() => {{
                    const div = document.createElement('div');
                    div.style.cssText = (
                        'position:fixed;top:20px;right:20px;z-index:999999;'
                        + 'background:#22c55e;color:#fff;font-size:18px;font-weight:bold;'
                        + 'padding:16px 28px;border-radius:10px;'
                        + 'box-shadow:0 4px 24px rgba(0,0,0,0.35);'
                        + 'font-family:sans-serif;letter-spacing:0.5px;'
                    );
                    div.innerText = '\\u2713 Run Complete — Screenshot Saved';
                    document.body.appendChild(div);
                }}""")
                page.wait_for_timeout(3500)

            sys.exit(0)

        except Exception as e:
            if args.screenshot:
                try:
                    page.screenshot(path=args.screenshot)
                except Exception:
                    pass
            if args.snapshot:
                try:
                    with open(args.snapshot, "w", encoding="utf-8") as f:
                        f.write(page.content())
                except Exception:
                    pass
            print(
                "ERROR_REPORT: " + json.dumps({{
                    "type": type(e).__name__,
                    "message": str(e),
                    "step_id": current_step_id,
                    "selector": None
                }}),
                file=sys.stderr
            )
            sys.exit(1)

        finally:
            if not _watch:
                browser.close()

if __name__ == "__main__":
    main()
'''


def _inject_step_tracker(steps_block: str) -> str:
    lines = steps_block.splitlines()
    result = []
    for line in lines:
        match = re.match(r'(\s*)# STEP (\d+):', line)
        if match:
            indent = match.group(1)
            step_num = match.group(2)
            result.append(f"{indent}current_step_id = {step_num}")
        result.append(line)
    return "\n".join(result)


def _needs_postprocessing(goal: str) -> bool:
    """Return True if the goal implies sort/filter/slice beyond raw extraction."""
    keywords = [
        "top ", "highest", "lowest", "most", "least", "cheapest", "expensive",
        "best", "worst", "first ", "last ", "only ", "filter", "sort", "rank",
        "maximum", "minimum", "average", "unique", "distinct", "limit"
    ]
    g = goal.lower()
    return any(kw in g for kw in keywords)


def _build_postprocess_code(goal: str, api_key: str, provider: str, base_url) -> str:
    """
    Ask the LLM to generate a Python post-processing block that transforms
    the extracted `items` list according to the user goal.
    Returns indented lines (4 spaces) ready to drop after the extraction loop.
    """
    user_prompt = f"""
User Goal: {goal}

The variable `items` is a list of dicts already populated by the extraction loop above.
Write the Python lines to transform `items` to match exactly what the user wants.
End with: print(json.dumps({{"total": len(items), "items": items}}, indent=2, ensure_ascii=False))
"""
    try:
        raw = call_llm(
            system_prompt=POSTPROCESS_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            api_key=api_key,
            provider=provider,
            base_url=base_url
        )
        raw = raw.strip()
        if raw.startswith("```python"):
            raw = raw[9:]
        elif raw.startswith("```"):
            raw = raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        return raw.strip()
    except Exception as e:
        print(f"[script_generator] Post-process codegen failed: {e}")
        return 'print(json.dumps({"total": len(items), "items": items}, indent=2, ensure_ascii=False))'


def _build_scrape_step_code(
    step,
    goal: str = "",
    api_key: str = "",
    provider: str = "openai",
    base_url=None
) -> str:
    """
    Deterministically generate a scraping loop from a scrape-action step,
    followed by an LLM-generated post-processing block when the goal
    requires sorting, filtering, or slicing.
    Returns unindented lines — the caller handles indentation.
    """
    container = step.selector or "article"
    try:
        fields = json.loads(step.value or "{}")
    except (json.JSONDecodeError, TypeError):
        fields = {}

    lines = [
        f"# STEP {step.step_id}: {step.description or 'Scrape data'}",
        f"page.wait_for_selector({repr(container)}, timeout={step.timeout_ms})",
        "items = []",
        f"for item in page.locator({repr(container)}).all():",
        "    items.append({"
    ]

    for field_name, selector_str in fields.items():
        selector_str = str(selector_str)
        if "@" in selector_str:
            css, attr = selector_str.rsplit("@", 1)
            css = css.strip()
            if attr == "class":
                # Strip the element's own base class (e.g. "star-rating Three" -> "Three")
                lines.append(
                    f'        {repr(field_name)}: " ".join('
                    f'(item.locator({repr(css)}).get_attribute("class") or "").split()[1:]),'
                )
            else:
                lines.append(
                    f'        {repr(field_name)}: (item.locator({repr(css)}).get_attribute({repr(attr)}) or "").strip(),'
                )
        else:
            lines.append(f'        {repr(field_name)}: (item.locator({repr(selector_str)}).text_content() or "").strip(),')

    lines.append("    })")

    # Generate post-processing block if goal requires sort/filter/slice
    if goal and api_key and _needs_postprocessing(goal):
        print(f"[script_generator] Goal requires post-processing: {goal!r}")
        postprocess = _build_postprocess_code(goal, api_key, provider, base_url)
        lines.append("")
        lines.append("# Post-processing: sort/filter/slice per user goal")
        lines.extend(postprocess.splitlines())
    else:
        lines.append('print(json.dumps({"total": len(items), "items": items}, indent=2, ensure_ascii=False))')

    return "\n".join(lines)


def generate_script(flow: FlowSchema, api_key: str, provider: str = "openai", base_url: Optional[str] = None) -> str:
    # Check if any step uses the scrape action
    has_scrape = any(s.action == "scrape" for s in flow.steps)

    if has_scrape:
        # Build steps deterministically — no LLM needed for scrape steps
        step_blocks = []
        for step in flow.steps:
            if step.action == "navigate":
                block = (
                    f"# STEP {step.step_id}: {step.description or 'Navigate'}\n"
                    f"_pause(800)\n"
                    f"page.goto({repr(step.value or flow.url)}, timeout={step.timeout_ms})\n"
                    f"_pause(1500)"
                )
            elif step.action == "scrape":
                scrape_code = _build_scrape_step_code(
                    step,
                    goal=flow.goal or flow.flow_name,
                    api_key=api_key,
                    provider=provider,
                    base_url=base_url
                )
                # Wrap scrape block with a pre-pause and post-pause so the viewer
                # can see the page before and after data extraction
                block = f"_pause(1000)\n{scrape_code}\n_pause(1500)"
            elif step.action == "assert":
                sel = step.selector or ""
                val = step.value or ""
                block = (
                    f"# STEP {step.step_id}: {step.description or 'Assert'}\n"
                    f"_highlight({repr(sel)})\n"
                    f"assert {repr(val)} in page.locator({repr(sel)}).text_content().strip()\n"
                    f"_pause(800)"
                )
            elif step.action == "click":
                sel = step.selector or ""
                block = (
                    f"# STEP {step.step_id}: {step.description or 'Click'}\n"
                    f"_highlight({repr(sel)})\n"
                    f"page.click({repr(sel)}, timeout={step.timeout_ms})\n"
                    f"page.wait_for_load_state('networkidle', timeout=15000)\n"
                    f"_pause(1200)"
                )
            elif step.action == "fill":
                sel = step.selector or ""
                val = step.value or ""
                block = (
                    f"# STEP {step.step_id}: {step.description or 'Fill'}\n"
                    f"_highlight({repr(sel)})\n"
                    f"page.fill({repr(sel)}, {repr(val)}, timeout={step.timeout_ms})\n"
                    f"_pause(800)"
                )
            elif step.action == "select":
                sel = step.selector or ""
                val = step.value or ""
                block = (
                    f"# STEP {step.step_id}: {step.description or 'Select'}\n"
                    f"_highlight({repr(sel)})\n"
                    f"page.select_option({repr(sel)}, {repr(val)}, timeout={step.timeout_ms})\n"
                    f"_pause(800)"
                )
            elif step.action == "hover":
                sel = step.selector or ""
                block = (
                    f"# STEP {step.step_id}: {step.description or 'Hover'}\n"
                    f"_highlight({repr(sel)})\n"
                    f"page.hover({repr(sel)}, timeout={step.timeout_ms})\n"
                    f"_pause(600)"
                )
            else:
                block = f"# STEP {step.step_id}: {step.description or step.action}"

            step_blocks.append(block)

        raw_steps = "\n\n".join(step_blocks)
    else:
        # Standard automation/monitor flow — use LangChain when provider is openai, else httpx
        user_prompt = f"""
Flow Name: {flow.flow_name}
Steps:
{json.dumps([step.model_dump() for step in flow.steps], indent=2)}

Output only the step execution lines (no imports, no functions, no boilerplate).
"""
        if provider == "openai" and not base_url:
            raw_steps = call_llm_langchain(
                system_prompt=STEPS_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                api_key=api_key
            )
        else:
            raw_steps = call_llm(
                system_prompt=STEPS_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                api_key=api_key,
                provider=provider,
                base_url=base_url
            )

        # Strip markdown fences
        raw_steps = raw_steps.strip()
        if raw_steps.startswith("```python"):
            raw_steps = raw_steps[9:]
        elif raw_steps.startswith("```"):
            raw_steps = raw_steps[3:]
        if raw_steps.endswith("```"):
            raw_steps = raw_steps[:-3]
        raw_steps = raw_steps.strip()

    # Indent to sit inside the try block (12 spaces)
    indented_steps = "\n".join(
        "            " + line if line.strip() else ""
        for line in raw_steps.splitlines()
    )

    indented_steps = _inject_step_tracker(indented_steps)

    return SCRIPT_TEMPLATE.format(steps=indented_steps)
