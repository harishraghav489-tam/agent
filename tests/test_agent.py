import asyncio
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

import agent


def test_profile_validation_and_prompt_extraction():
    request = agent.SearchRequest(prompt="Find roles for https://www.linkedin.com/in/alex-dev/")
    assert request.linkedin_url == "https://www.linkedin.com/in/alex-dev/"
    for url in ["http://localhost/in/a", "https://linkedin.com.evil.org/in/a", "https://www.linkedin.com/jobs/view/123"]:
        with pytest.raises(ValidationError):
            agent.SearchRequest(linkedin_url=url)
    with pytest.raises(ValidationError):
        agent.SearchRequest()


def test_listing_validation():
    assert agent.is_listing("https://www.linkedin.com/jobs/view/12345", "LinkedIn")
    assert agent.is_listing("https://internshala.com/internship/detail/python-intern123", "Internshala")
    assert agent.is_listing("https://unstop.com/internships/ai-intern-company-12345", "Unstop")
    assert not agent.is_listing("https://evil.com/jobs/view/12345", "LinkedIn")
    assert not agent.is_listing("https://www.linkedin.com/jobs/search", "LinkedIn")
    assert agent.canonical_url("javascript:alert(1)") is None


def test_partial_sources_and_duplicate_removal(monkeypatch):
    async def fake_search(query, domains, limit=5):
        if domains == ["unstop.com"]:
            raise RuntimeError("provider failure")
        if domains == ["linkedin.com"]:
            return [{"url": "https://www.linkedin.com/jobs/view/123", "title": "Developer", "content": "Python"}] * 2
        return []
    monkeypatch.setattr(agent, "search_web", fake_search)
    result = asyncio.run(agent.find_jobs({"profile": {"roles": ["Python"], "kind": "Jobs", "location": "Remote"}, "warnings": []}))
    assert len(result["candidates"]) == 1
    assert any("Unstop" in w for w in result["warnings"])
    assert len(result["sources"]) == 4


def test_ranking_cannot_invent_urls_or_ids(monkeypatch):
    class FakeLLM:
        def with_structured_output(self, schema):
            return self
        async def ainvoke(self, messages):
            return agent.Ranking(matches=[
                agent.Match(evidence_id=0, title="Engineer", reason="Python"),
                agent.Match(evidence_id=999, title="Fabricated", reason="No evidence"),
                agent.Match(evidence_id=0, title="Duplicate", reason="Duplicate"),
            ])
    monkeypatch.setattr(agent, "llm", FakeLLM)
    result = asyncio.run(agent.rank_jobs({"request": {}, "profile": {}, "candidates": [
        {"evidence_id": 0, "url": "https://www.linkedin.com/jobs/view/123", "source": "LinkedIn", "content": "Python"}
    ]}))
    assert len(result["jobs"]) == 1
    assert result["jobs"][0]["url"].endswith("/123")


def test_compiled_graph_empty_search(monkeypatch):
    monkeypatch.setattr(agent, "search_web", AsyncMock(return_value=[]))
    class FakeLLM:
        def with_structured_output(self, schema):
            return self
        async def ainvoke(self, messages):
            if "Analyze career evidence" in messages[0][1]:
                return agent.Profile(summary="Python developer", skills=["Python"], roles=["Developer"])
            class Response:
                content = "No matches found. Try a broader location."
            return Response()
    monkeypatch.setattr(agent, "llm", FakeLLM)
    request = agent.SearchRequest(profile_text="I know Python", domain="Data engineering").model_dump()
    result = asyncio.run(agent.graph.ainvoke({"request": request}))
    assert result["profile"]["roles"] == ["Data engineering"]
    assert result["jobs"] == []
    assert "No matches" in result["summary"]
