"""A 200 body that is not the shape asked for is an error, not zero.

Stress test, 12 October 2026: a 200 whose body was null, [], a string, {},
{"error": ...} or {"message": ...} came back from every list tool as
ZERO_RESULTS (with a hint to try the sibling servers before concluding the
literature is absent), and from s2_get_paper and s2_get_author as an empty
record marked OK with total 1.
"""
import asyncio
import json

import pytest

from semantic_scholar_mcp import server as S

BAD = [None, [], "x", {}, {"error": "Not found"}, {"message": "Too Many Requests"},
       {"data": "x"}]


@pytest.fixture
def answer(monkeypatch):
    box = {}

    async def fake(method, url, params=None, json_body=None):
        return box["data"], None
    monkeypatch.setattr(S, "_api_request", fake)
    return box


def _codes(out):
    env = json.loads(out)
    return env, [d["code"] for d in env["diagnostics"]]


CALLS = [
    lambda: S.s2_search_papers(S.PaperSearchInput(query="q")),
    lambda: S.s2_search_authors(S.AuthorSearchInput(query="q")),
    lambda: S.s2_citations(S.CitationInput(paper_id="abc")),
    lambda: S.s2_author_papers(S.AuthorPapersInput(author_id="1")),
    lambda: S.s2_recommend_single(S.RecommendInput(paper_id="abc")),
    lambda: S.s2_recommend_multi(S.MultiRecommendInput(positive_paper_ids=["abc"])),
    lambda: S.s2_get_paper(S.PaperLookupInput(paper_id="abc")),
    lambda: S.s2_get_author(S.AuthorLookupInput(author_id="1")),
]


@pytest.mark.parametrize("call", CALLS)
@pytest.mark.parametrize("data", BAD)
def test_wrong_shape_is_api_error(answer, call, data):
    answer["data"] = data
    env, codes = _codes(asyncio.run(call()))
    assert codes[0] == "API_ERROR", codes
    assert "ZERO_RESULTS" not in codes and "OK" not in codes
    assert env["items"] == [] and env["result"]["total"] == 0


def test_upstream_message_is_quoted(answer):
    answer["data"] = {"message": "Too Many Requests"}
    env, _ = _codes(asyncio.run(S.s2_search_papers(S.PaperSearchInput(query="q"))))
    assert "Too Many Requests" in env["diagnostics"][0]["message"]


@pytest.mark.parametrize("data", [
    {"total": 0, "offset": 0},              # a search page with nothing to list
    {"total": 0, "offset": 0, "data": []},
])
def test_empty_search_page_is_still_zero_results(answer, data):
    answer["data"] = data
    _, codes = _codes(asyncio.run(S.s2_search_papers(S.PaperSearchInput(query="q"))))
    assert "ZERO_RESULTS" in codes and "API_ERROR" not in codes


def test_empty_recommendations_are_still_zero_results(answer):
    answer["data"] = {"recommendedPapers": []}
    _, codes = _codes(asyncio.run(S.s2_recommend_single(S.RecommendInput(paper_id="abc"))))
    assert "ZERO_RESULTS" in codes and "API_ERROR" not in codes
