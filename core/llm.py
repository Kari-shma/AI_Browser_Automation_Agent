import httpx
from typing import Optional, Dict

def call_llm(
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    provider: str = "openai",
    base_url: Optional[str] = None,
    response_format: Optional[Dict] = None
) -> str:
    """
    Calls the LLM using the provided api_key and provider details.
    """
    if not api_key:
        raise ValueError("API Key is required to call the LLM agent.")
    
    # Determine base URL
    if not base_url:
        if provider == "openrouter":
            base_url = "https://openrouter.ai/api/v1"
        else:
            base_url = "https://api.openai.com/v1"
            
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    # OpenRouter requires additional headers
    if provider == "openrouter":
        headers["HTTP-Referer"] = "http://localhost:8000"
        headers["X-Title"] = "Browser Automation AI Agent"
        model = "meta-llama/llama-3.1-70b-instruct"  # default standard model for OpenRouter
    else:
        model = "gpt-4o"  # default OpenAI model

    url = f"{base_url.rstrip('/')}/chat/completions"
    
    data = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.1
    }
    
    if response_format:
        data["response_format"] = response_format

    try:
        response = httpx.post(url, headers=headers, json=data, timeout=60.0)
        response.raise_for_status()
        res_json = response.json()
        return res_json["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"Error calling LLM: {str(e)}")
        if 'response' in locals() and response is not None:
            print(f"Response status: {response.status_code}, Body: {response.text}")
        raise e
