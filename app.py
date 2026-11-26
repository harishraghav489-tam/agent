import asyncio
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")
from agent import SearchRequest, graph

app = FastAPI(title="Jobseeker", version="1.0.0")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/")
async def index():
    return FileResponse(ROOT / "static/index.html")


@app.get("/api/health")
async def health():
    missing = [key for key in ("OPENAI_API_KEY", "TAVILY_API_KEY") if not os.getenv(key)]
    return {"ready": not missing, "missing": missing, "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini")}


@app.post("/api/search")
async def search(request: SearchRequest):
    config = await health()
    if not config["ready"]:
        raise HTTPException(503, "Set " + ", ".join(config["missing"]) + " in .env, then restart the server.")

    async def events():
        state = {"request": request.model_dump()}
        try:
            async with asyncio.timeout(240):
                async for update in graph.astream(state, stream_mode="updates"):
                    for node, values in update.items():
                        state.update(values)
                        yield json.dumps({"type": "progress", "node": node}) + "\n"
                yield json.dumps({"type": "result", "profile": state["profile"], "jobs": state["jobs"],
                                  "summary": state["summary"], "warnings": state["warnings"],
                                  "sources": state["sources"], "evidence": state["evidence"]}) + "\n"
        except TimeoutError:
            yield json.dumps({"type": "error", "message": "Search timed out. Try a more specific domain or fewer profile details."}) + "\n"
        except Exception:
            logging.exception("Job search failed")
            yield json.dumps({"type": "error", "message": "The search could not finish. Check provider credentials, model availability and quota, then retry."}) + "\n"
    return StreamingResponse(events(), media_type="application/x-ndjson", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
