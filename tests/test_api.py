import json

from fastapi.testclient import TestClient

import app as server


def test_setup_and_static_pages(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    with TestClient(server.app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/static/style.css").status_code == 200
        assert client.get("/api/health").json()["ready"] is False
        assert client.post("/api/search", json={"domain": "Design"}).status_code == 503
        assert client.post("/api/search", json={}).status_code == 422


def test_progress_and_result_stream(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    class Graph:
        async def astream(self, state, stream_mode):
            yield {"collect_profile": {"evidence": [], "warnings": []}}
            yield {"summarize": {"profile": {}, "jobs": [], "sources": [], "summary": "No matches."}}
    monkeypatch.setattr(server, "graph", Graph())
    with TestClient(server.app) as client:
        response = client.post("/api/search", json={"domain": "Design"})
        events = [json.loads(line) for line in response.text.splitlines()]
        assert [e["type"] for e in events] == ["progress", "progress", "result"]
        assert events[-1]["summary"] == "No matches."


def test_provider_failure_is_actionable(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    class Graph:
        async def astream(self, state, stream_mode):
            raise RuntimeError("sensitive provider detail")
            yield {}
    monkeypatch.setattr(server, "graph", Graph())
    with TestClient(server.app) as client:
        response = client.post("/api/search", json={"domain": "Design"})
        event = response.json()
        assert event["type"] == "error"
        assert "credentials" in event["message"]
        assert "sensitive" not in response.text
