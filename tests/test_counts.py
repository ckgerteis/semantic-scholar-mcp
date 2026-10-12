"""A total that is not a finite, non-negative integer is not a total (stress
test, 12 October 2026).

"total": 1e309 parses as infinity and int() raised OverflowError out of the
tool; a negative total was reported as the corpus size.
"""
import asyncio
import json

import httpx
import pytest

BAD = ["1e309", "-1e309", "-7", "-7.0", "12.5", "true", "\"abc\"", "{}", "[]"]


@pytest.fixture
def body(monkeypatch):
    box = {"text": ""}

    def handler(req):
        return httpx.Response(200, text=box["text"], headers={"content-type": "application/json"})
    orig = httpx.AsyncClient.__init__

    def init(self, *a, **k):
        k["transport"] = httpx.MockTransport(handler)
        orig(self, *a, **k)
    monkeypatch.setattr(httpx.AsyncClient, "__init__", init)
    return box


def _total(out):
    env = json.loads(out)
    t = env["result"]["total"]
    assert isinstance(t, int) and not isinstance(t, bool) and t >= 0, t
    return env

from semantic_scholar_mcp import server as S


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(S, "API_KEY", "")
    monkeypatch.setattr(S, "RATE_LIMIT_DELAY", 0)


@pytest.mark.parametrize("bad", BAD)
def test_bad_total_is_reported_as_not_reported(body, bad):
    body["text"] = '{"total": %s, "offset": 0, "data": [{"paperId": "p1"}, {"paperId": "p2"}]}' % bad
    env = _total(asyncio.run(S.s2_search_papers(S.PaperSearchInput(query="x"))))
    codes = [d["code"] for d in env["diagnostics"]]
    assert env["result"]["total"] == 2 and "TOTAL_NOT_REPORTED" in codes


@pytest.mark.parametrize("good", ["94", '"94"', "94.0"])
def test_a_good_total_passes_through(body, good):
    body["text"] = '{"total": %s, "offset": 0, "data": [{"paperId": "p1", "title": "x"}]}' % good
    assert _total(asyncio.run(S.s2_search_papers(S.PaperSearchInput(query="x"))))["result"]["total"] == 94
