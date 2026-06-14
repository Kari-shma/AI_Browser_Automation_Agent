import re
import json
from typing import Optional
from core.schema import FlowSchema
from core.llm import call_llm

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

SCRIPT_TEMPLATE = '''\
import sys
import json
import argparse
from playwright.sync_api import sync_playwright

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--screenshot", type=str)
    parser.add_argument("--snapshot", type=str)
    args = parser.parse_args()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        page = browser.new_context().new_page()
        current_step_id = None

        try:
{steps}

            # Save artifacts on success
            if args.screenshot:
                page.screenshot(path=args.screenshot, full_page=True)
            if args.snapshot:
                with open(args.snapshot, "w", encoding="utf-8") as f:
                    f.write(page.content())
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


def _build_scrape_step_code(step) -> str:
    """
    Deterministically generate a scraping loop from a scrape-action step.
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

    lines += [
        "    })",
        'print(json.dumps({"total": len(items), "items": items}, indent=2, ensure_ascii=False))',
    ]

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
                    f"page.goto({repr(step.value or flow.url)}, timeout={step.timeout_ms})"
                )
            elif step.action == "scrape":
                block = _build_scrape_step_code(step)
            elif step.action == "assert":
                sel = step.selector or ""
                val = step.value or ""
                block = (
                    f"# STEP {step.step_id}: {step.description or 'Assert'}\n"
                    f"assert {repr(val)} in page.locator({repr(sel)}).text_content().strip()"
                )
            else:
                # click, fill, hover, select — delegate to LLM for this single step
                block = f"# STEP {step.step_id}: {step.description or step.action}"

            step_blocks.append(block)

        raw_steps = "\n\n".join(step_blocks)
    else:
        # Standard automation/monitor flow — ask LLM for step lines only
        user_prompt = f"""
Flow Name: {flow.flow_name}
Steps:
{json.dumps([step.model_dump() for step in flow.steps], indent=2)}

Output only the step execution lines (no imports, no functions, no boilerplate).
"""
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
