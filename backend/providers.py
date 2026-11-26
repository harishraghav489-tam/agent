import os
from urllib.parse import urlparse, urlunparse

import httpx
from langchain_openai import ChatOpenAI


def llm():
    options = {
        "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        "api_key": os.getenv("OPENAI_API_KEY"),
        "temperature": 0.2,
        "timeout": 45,
        "max_retries": 1,
        "max_tokens": 4000,
    }
    if os.getenv("OPENAI_BASE_URL"):
        options["base_url"] = os.environ["OPENAI_BASE_URL"]
    if "generativelanguage.googleapis.com" in options.get("base_url", "") and options["model"].startswith("gemini-3"):
        # Career extraction/ranking needs concise tool arguments, not long deliberation.
        options["reasoning_effort"] = "low"
    return ChatOpenAI(**options)


def canonical_url(url: str, domain: str) -> str | None:
    """Only return HTTPS URLs on the requested provider's domain."""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if (
            parsed.scheme != "https"
            or not (host == domain or host.endswith("." + domain))
            or parsed.username or parsed.password or parsed.port
        ):
            return None
        # Listing paths carry the identity on all supported boards.
        return urlunparse(("https", host, parsed.path.rstrip("/"), "", "", ""))
    except ValueError:
        return None


async def tavily(endpoint: str, payload: dict) -> dict:
    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.post(
            f"https://api.tavily.com/{endpoint}",
            headers={"Authorization": f"Bearer {os.environ['TAVILY_API_KEY']}"},
            json=payload,
        )
        response.raise_for_status()
        return response.json()


async def search(query: str, domain: str, count: int = 6, recent: bool = False):
    payload = {
        "query": query[:400],
        "include_domains": [domain],
        "max_results": count,
        "search_depth": "advanced",
        "include_raw_content": False,
    }
    if recent:
        payload["time_range"] = "month"
    return (await tavily("search", payload)).get("results", [])
