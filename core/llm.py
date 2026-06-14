import time
import httpx
from typing import Optional, Dict


def call_llm_langchain(
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    model: str = "gpt-4o",
    temperature: float = 0.1
) -> str:
    """
    LangChain-based LLM call using ChatOpenAI + ChatPromptTemplate.
    Demonstrates LangChain's chain composition pattern:
      prompt_template | llm | output_parser
    Falls back to the httpx call_llm() if langchain is not installed.
    """
    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.output_parsers import StrOutputParser

        prompt = ChatPromptTemplate.from_messages([
            ("system", "{system_prompt}"),
            ("human", "{user_prompt}"),
        ])
        llm = ChatOpenAI(model=model, temperature=temperature, api_key=api_key)
        chain = prompt | llm | StrOutputParser()
        return chain.invoke({"system_prompt": system_prompt, "user_prompt": user_prompt})
    except ImportError:
        print("[llm] langchain_openai not installed — falling back to httpx call_llm()")
        return call_llm(system_prompt=system_prompt, user_prompt=user_prompt,
                        api_key=api_key, provider="openai")


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
    
    # JSON mode is only supported by OpenAI; strip it for other providers
    if response_format and provider != "openai":
        response_format = None
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


def call_llm_with_retry(
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    provider: str = "openai",
    base_url: Optional[str] = None,
    response_format: Optional[Dict] = None,
    max_retries: int = 2
) -> str:
    """Calls call_llm with automatic retry on transient failures."""
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return call_llm(system_prompt, user_prompt, api_key, provider, base_url, response_format)
        except Exception as e:
            last_exc = e
            if attempt < max_retries:
                print(f"[llm] Attempt {attempt + 1} failed ({e}). Retrying in 2s...")
                time.sleep(2)
    raise last_exc
