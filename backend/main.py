import asyncio
import json
import logging
import os
from pathlib import Path

import httpx
from openai import APIConnectionError, APITimeoutError
from langchain_core.exceptions import OutputParserException
from pydantic import ValidationError
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .graph import graph
from .models import SearchRequest

app = FastAPI(title="CareerGlass", version="1.0.0")
app.mount("/static", StaticFiles(directory=ROOT / "frontend"), name="static")
logger = logging.getLogger(__name__)
slots = asyncio.Semaphore(3)


def provider_error_message(error: Exception) -> str:
    if isinstance(error, (APITimeoutError, httpx.TimeoutException, TimeoutError)):
        return "The AI provider took too long to respond. Please retry; choosing fewer platforms can help. Your profile is not the problem."
    if isinstance(error, APIConnectionError):
        return "Could not connect to the AI provider. Check your internet connection and retry."
    if isinstance(error, (OutputParserException, ValidationError)):
        return "The AI provider returned an incomplete or invalid response. Please retry the search."
    code = getattr(error, "code", None)
    if code in {"credit_balance_exhausted", "insufficient_quota"}:
        return "Your LLM provider account has no available credit. Add API billing credit or configure a funded OPENAI_API_KEY in .env and restart. Demo mode is available now."
    if getattr(error, "status_code", None) == 401:
        return "The LLM provider rejected the API key. Update OPENAI_API_KEY in .env and restart."
    if getattr(error, "status_code", None) == 429:
        return "The LLM provider's rate limit was reached. Wait a moment and retry, or check your account limits."
    if getattr(error, "status_code", None) in {500, 502, 503, 504}:
        return "The AI provider is temporarily overloaded or unavailable. Please retry in a moment."
    if getattr(error, "status_code", None) == 404:
        return "The configured AI model is unavailable to this account. Update OPENAI_MODEL in .env and restart."
    if getattr(error, "status_code", None) == 400:
        return "The AI provider rejected the request format. Check that the configured model supports structured function calling."
    return "A provider request failed. Check server logs, API keys, model support, and quota, then retry."


@app.get("/")
async def index():
    return FileResponse(ROOT / "frontend" / "index.html")


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "live_ready": bool(os.getenv("OPENAI_API_KEY") and os.getenv("TAVILY_API_KEY")),
        "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
    }


@app.post("/api/search")
async def run_search(request: SearchRequest):
    if not request.demo and not (os.getenv("OPENAI_API_KEY") and os.getenv("TAVILY_API_KEY")):
        raise HTTPException(503, "Live search needs OPENAI_API_KEY and TAVILY_API_KEY in .env. You can explore Demo mode now.")
    if slots.locked():
        raise HTTPException(429, "All search slots are busy. Please try again shortly.")

    async def events():
        def encode(event, data):
            return json.dumps({"event": event, "data": data}) + "\n"

        state = {"request": request.model_dump()}
        stages = {
            "collect_profile": "reading your public profile",
            "analyze_profile": "analyzing your skills",
            "find_jobs": "searching job boards",
            "rank_jobs": "assessing job matches",
            "summarize": "writing your overview",
        }
        stage_names = list(stages)
        active_stage = stage_names[0]
        async with slots:
            try:
                async with asyncio.timeout(240):
                    yield encode("started", {"message": "Your career agent is getting started."})
                    async for update in graph.astream(state, stream_mode="updates"):
                        for node, values in update.items():
                            state.update(values)
                            yield encode("progress", {"step": node})
                            active_stage = stage_names[min(stage_names.index(node) + 1, len(stage_names) - 1)]
                    yield encode("result", {
                        "demo": request.demo,
                        **{key: state[key] for key in ("profile", "jobs", "summary", "warnings", "source_status")},
                    })
            except TimeoutError:
                yield encode("error", {"message": "The search timed out. Try fewer sources or a more specific domain."})
            except asyncio.CancelledError:
                raise
            except Exception as error:
                # Log metadata, not raw exceptions that may contain profile data or key fragments.
                logger.error("Career search failed at %s: %s (status=%s, code=%s)",
                             active_stage, type(error).__name__, getattr(error, "status_code", None),
                             getattr(error, "code", None))
                yield encode("error", {"message": f"While {stages[active_stage]}: {provider_error_message(error)}"})

    return StreamingResponse(events(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
