import importlib
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.main import app, provider_error_message
from backend.models import Assessment, Assessments, Profile, SearchRequest
from backend.providers import canonical_url

workflow = importlib.import_module("backend.graph")


class InputTests(unittest.TestCase):
    def test_extracts_profile_from_prompt(self):
        request = SearchRequest(prompt="Find AI internships for https://www.linkedin.com/in/alex-morgan/")
        self.assertEqual(request.linkedin_url, "https://www.linkedin.com/in/alex-morgan/")

    def test_rejects_non_profile_urls(self):
        for url in ["http://linkedin.com/in/alex", "https://linkedin.com.attacker.test/in/alex",
                    "https://localhost/in/alex", "https://user@linkedin.com/in/alex",
                    "https://linkedin.com/jobs/123"]:
            with self.subTest(url=url), self.assertRaises(ValidationError):
                SearchRequest(linkedin_url=url)

    def test_rejects_empty_inputs_and_sources(self):
        with self.assertRaises(ValidationError):
            SearchRequest()
        with self.assertRaises(ValidationError):
            SearchRequest(demo=True, sources=[])

    def test_urls_are_validated_and_deduplicated(self):
        self.assertEqual(canonical_url("https://www.linkedin.com/jobs/view/123/?tracking=abc", "linkedin.com"),
                         "https://www.linkedin.com/jobs/view/123")
        self.assertIsNone(canonical_url("javascript:alert(1)", "linkedin.com"))
        self.assertIsNone(canonical_url("https://linkedin.com.evil.test/job", "linkedin.com"))


class GraphTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_post_themes_without_post_evidence(self):
        model = MagicMock()
        model.with_structured_output.return_value.ainvoke = AsyncMock(
            return_value=Profile(post_themes=["Invented theme"]))
        with patch.object(workflow, "llm", return_value=model):
            result = await workflow.analyze_profile({
                "request": SearchRequest(domain="AI").model_dump(), "evidence": [],
            })
        self.assertEqual(result["profile"]["post_themes"], [])

    async def test_partial_ranking_timeout_preserves_completed_batch(self):
        candidates = [{"id":str(i), "source":"Unstop",
                       "url":f"https://unstop.com/internships/{i}", "content":"Python"} for i in range(7)]
        model = MagicMock()
        model.with_structured_output.return_value.ainvoke = AsyncMock(side_effect=[
            Assessments(jobs=[Assessment(candidate_id="0", is_job_listing=True,
                title="Python Intern", kind="Internship", match_score=90, reason="Python")]),
            TimeoutError("provider timeout"),
        ])
        with patch.object(workflow, "llm", return_value=model):
            result = await workflow.rank_jobs({
                "request":{"demo":False}, "profile":{"kind":"Internships"},
                "candidates":candidates, "warnings":[],
            })
        self.assertEqual([j["id"] for j in result["jobs"]], ["0"])
        self.assertIn("ranking batch", result["warnings"][0])
        self.assertEqual(model.with_structured_output.return_value.ainvoke.await_count, 2)

    async def test_all_ranking_failures_remain_actionable_errors(self):
        model = MagicMock()
        model.with_structured_output.return_value.ainvoke = AsyncMock(side_effect=TimeoutError("timeout"))
        with patch.object(workflow, "llm", return_value=model), self.assertRaises(TimeoutError):
            await workflow.rank_jobs({
                "request":{"demo":False}, "profile":{"kind":"Both"},
                "candidates":[{"id":"1", "source":"Unstop", "url":"https://unstop.com/jobs/1", "content":"role"}],
            })

    async def test_summary_timeout_keeps_real_results(self):
        model = MagicMock()
        model.with_structured_output.return_value.ainvoke = AsyncMock(side_effect=TimeoutError("timeout"))
        state = {
            "request":{"demo":False}, "profile":{}, "warnings":[], "source_status":[],
            "jobs":[{"title":"Python Intern", "company":"A real listing company"}],
        }
        with patch.object(workflow, "llm", return_value=model):
            result = await workflow.summarize(state)
        self.assertIn("Python Intern", result["summary"]["message"])
        self.assertIn("basic overview", result["warnings"][0])
        self.assertEqual(len(state["jobs"]), 1)

    async def test_demo_runs_entire_graph_without_providers(self):
        with patch.object(workflow, "llm", side_effect=AssertionError("Demo must not call an LLM")), \
             patch.object(workflow, "search", side_effect=AssertionError("Demo must not call search")):
            result = await workflow.graph.ainvoke({"request": SearchRequest(
                demo=True, kind="Internships", sources=["Unstop"]).model_dump()})
        self.assertEqual(len(result["jobs"]), 1)
        self.assertEqual(result["jobs"][0]["source"], "Unstop")
        self.assertIn("Demo", result["warnings"][0])
        self.assertIn("summary", result)

    async def test_profile_excludes_unrelated_people_and_posts(self):
        request = SearchRequest(linkedin_url="https://www.linkedin.com/in/alex-morgan/").model_dump()
        async def fake_search(query, *_args, **_kwargs):
            if "posts/" in query:
                return [
                    {"url":"https://www.linkedin.com/posts/alex-morgan_building-ai-123", "content":"My Python project"},
                    {"url":"https://www.linkedin.com/posts/other-person_news-123", "content":"Other person's skills"},
                ]
            return [
                {"url":"https://www.linkedin.com/in/alex-morgan/", "content":"Python developer"},
                {"url":"https://www.linkedin.com/in/someone-else/", "content":"Unrelated profile"},
            ]
        with patch.object(workflow, "tavily", AsyncMock(return_value={"results": []})), \
             patch.object(workflow, "search", side_effect=fake_search):
            result = await workflow.collect_profile({"request": request})
        self.assertEqual(len(result["evidence"]), 2)
        self.assertNotIn("Unrelated", str(result["evidence"]))
        self.assertEqual(result["warnings"], [])

    async def test_source_failure_preserves_other_results_and_domain(self):
        queries = []
        async def fake_search(query, domain, *_args, **_kwargs):
            queries.append(query)
            if domain == "linkedin.com":
                raise RuntimeError("provider unavailable")
            return [{"url":"https://unstop.com/internships/123?utm_source=a","title":"Design intern","content":"UI internship"},
                    {"url":"https://unstop.com/internships/123?utm_source=b","title":"Design intern","content":"UI internship"}]
        state = {
            "request": SearchRequest(domain="UX Design", sources=["LinkedIn", "Unstop"]).model_dump(),
            "profile":{"domain":"UX Design","suggested_roles":["Product designer"],"location":"Remote","kind":"Internships"},
            "warnings":[],
        }
        with patch.object(workflow, "search", side_effect=fake_search):
            result = await workflow.find_jobs(state)
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["source_status"][0]["status"], "error")
        self.assertTrue(all("UX Design" in q for q in queries))
        self.assertTrue(result["warnings"])

    async def test_ranking_rejects_fabricated_ids_categories_and_wrong_type(self):
        candidates = [{"id":str(i),"source":"Unstop","url":f"https://unstop.com/internships/{i}","content":"Python"} for i in range(4)]
        assessments = Assessments(jobs=[
            Assessment(candidate_id="0", is_job_listing=True, title="Python Intern",kind="Internship",match_score=90,reason="Python experience"),
            Assessment(candidate_id="1", is_job_listing=False, title="Search page",match_score=99,reason="Category"),
            Assessment(candidate_id="2", is_job_listing=True, title="Full-time",kind="Job",match_score=95,reason="Wrong type"),
            Assessment(candidate_id="3", is_job_listing=True, matches_preferences=False,title="Marketing intern",kind="Internship",match_score=80,reason="Wrong domain"),
            Assessment(candidate_id="invented", is_job_listing=True, title="Fake job",kind="Internship",match_score=100,reason="Fake"),
        ])
        from unittest.mock import MagicMock
        model = MagicMock()
        model.with_structured_output.return_value.ainvoke = AsyncMock(return_value=assessments)
        with patch.object(workflow, "llm", return_value=model):
            result = await workflow.rank_jobs({"request":{"demo":False},"profile":{"kind":"Internships"},"candidates":candidates})
        self.assertEqual([j["id"] for j in result["jobs"]], ["0"])
        self.assertEqual(result["jobs"][0]["url"], candidates[0]["url"])


class APITests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_home_and_demo_stream(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        response = self.client.post("/api/search", json={"demo":True})
        self.assertEqual(response.status_code, 200)
        import json
        events = [json.loads(line) for line in response.text.splitlines()]
        self.assertEqual([e["event"] for e in events].count("progress"), 5)
        self.assertEqual(events[-1]["event"], "result")
        self.assertTrue(events[-1]["data"]["demo"])

    def test_live_requires_keys(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY":"", "TAVILY_API_KEY":""}):
            self.assertEqual(self.client.post("/api/search", json={"domain":"AI"}).status_code, 503)
        self.assertEqual(self.client.post("/api/search", json={}).status_code, 422)

    def test_credit_error_is_actionable_without_exposing_provider_payload(self):
        error = RuntimeError("sensitive provider payload")
        error.code = "credit_balance_exhausted"
        message = provider_error_message(error)
        self.assertIn("credit", message)
        self.assertIn("Demo", message)
        self.assertNotIn("sensitive", message)

    def test_provider_timeout_and_overload_have_specific_messages(self):
        import httpx
        from openai import APITimeoutError
        error = APITimeoutError(request=httpx.Request("POST", "https://provider.example"))
        self.assertIn("too long", provider_error_message(error))
        error = RuntimeError("private provider response")
        error.status_code = 503
        self.assertIn("overloaded", provider_error_message(error))
        self.assertNotIn("private", provider_error_message(error))


if __name__ == "__main__":
    unittest.main()
