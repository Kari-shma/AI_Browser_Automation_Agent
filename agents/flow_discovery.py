import uuid
from datetime import datetime
from typing import List, Optional
import json
from playwright.sync_api import sync_playwright
from core.schema import FlowSchema, FlowStep
from core.llm import call_llm

SYSTEM_PROMPT = """
You are the Flow Discovery Agent for a browser automation tool.
Given a list of interactive DOM elements from a web page and a user goal or sitemap, identify the structured steps needed to complete the flow.
Classify each step's action as: 'click', 'fill', 'navigate', 'select', 'hover', or 'assert'.

Format the response strictly as a JSON object matching this schema:
{
  "flow_name": "Name of the flow",
  "steps": [
    {
      "step_id": 1,
      "action": "click | fill | navigate | select | hover | assert",
      "selector": "CSS selector or XPath targeting the element",
      "selector_strategy": "css | xpath | text | role | testid",
      "value": "Value to input/select or assertion statement, or null",
      "description": "Short description of what the step does",
      "timeout_ms": 5000
    }
  ]
}

Only suggest selectors that exist in the input. Prioritize id, data-testid, name, or role-based attributes.
Do not wrap response in markdown code blocks. Return raw JSON.
"""

def extract_elements(url: str) -> List[dict]:
    elements = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
            
            # Simple element extractor JavaScript code
            extracted = page.evaluate("""
                () => {
                    const interactives = [];
                    const selectors = 'button, input, a, select, textarea, [role="button"], [role="link"]';
                    const nodes = document.querySelectorAll(selectors);
                    nodes.forEach((node, index) => {
                        const style = window.getComputedStyle(node);
                        if (style.display === 'none' || style.visibility === 'hidden') return;
                        
                        interactives.push({
                            tag: node.tagName.toLowerCase(),
                            id: node.getAttribute('id') || '',
                            name: node.getAttribute('name') || '',
                            type: node.getAttribute('type') || '',
                            placeholder: node.getAttribute('placeholder') || '',
                            aria_label: node.getAttribute('aria-label') || '',
                            role: node.getAttribute('role') || '',
                            testid: node.getAttribute('data-testid') || '',
                            classes: node.className || '',
                            text: (node.innerText || node.value || '').trim().substring(0, 50)
                        });
                    });
                    return interactives;
                }
            """)
            elements.extend(extracted)
        except Exception as e:
            print(f"Error extracting DOM elements: {str(e)}")
        finally:
            browser.close()
    return elements

def discover_flow(url: str, goal: str, api_key: str, provider: str = "openai", base_url: Optional[str] = None) -> FlowSchema:
    elements = extract_elements(url)
    
    user_prompt = f"""
    Target URL: {url}
    User Goal: {goal}
    
    Extracted Elements on Page:
    {json.dumps(elements, indent=2)}
    
    Please build the step-by-step flow to complete the goal. The first step should usually navigate to the URL:
    Action: "navigate", selector: null, value: "{url}".
    """
    
    response_text = call_llm(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        api_key=api_key,
        provider=provider,
        base_url=base_url
    )
    
    # Strip markdown if LLM wrapped it
    clean_text = response_text.strip()
    if clean_text.startswith("```json"):
        clean_text = clean_text[7:]
    if clean_text.endswith("```"):
        clean_text = clean_text[:-3]
    clean_text = clean_text.strip()
    
    flow_data = json.loads(clean_text)
    
    # Map steps
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
