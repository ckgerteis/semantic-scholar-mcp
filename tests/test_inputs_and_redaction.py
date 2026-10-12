"""Identifiers cannot rewrite the request path; the key does not survive into
diagnostics (stress test, 12 October 2026).

- IDs went into the URL path unencoded: paper_id "../../author/1" fetched an
  author as a paper, and "abc?x=1" or "abc#" in s2_citations dropped the
  /citations suffix, so the paper itself was read as an empty citation list.
- A query over ~65,000 characters, or a control character in an ID, raised
  httpx.InvalidURL out of the tool.
- The error text was cut to 300 characters before redaction, so a key
  straddling the cut leaked a prefix.
"""
import asyncio
from urllib.parse import quote

import httpx
import pytest
from pydantic import ValidationError

from semantic_scholar_mcp import server as S

ID_MODELS = [(S.PaperLookupInput, "paper_id"), (S.CitationInput, "paper_id"),
             (S.AuthorLookupInput, "author_id"), (S.AuthorPapersInput, "author_id"),
             (S.RecommendInput, "paper_id")]


@pytest.mark.parametrize("model,field", ID_MODELS)
@pytest.mark.parametrize("bad", ["../../author/1", "1/../../paper/zzz", "./x", "a\x00b", "a\nb"])
def test_id_cannot_walk_the_path(model, field, bad):
    with pytest.raises(ValidationError):
        model(**{field: bad})


@pytest.mark.parametrize("model,field", ID_MODELS)
def test_real_id_forms_are_accepted(model, field):
    for ok in ("649def34f8be52c8b66281af98ae884c09aef38b", "DOI:10.1093/mind/LIX.236.433",
               "ARXIV:2106.15928", "CorpusId:215416146", "URL:https://arxiv.org/abs/2106.15928v1"):
        model(**{field: ok})


@pytest.fixture
def requested(monkeypatch):
    urls, box = [], {"status": 200, "body": '{"data": []}'}

    def handler(req):
        urls.append(req.url)
        return httpx.Response(box["status"], text=box["body"])
    orig = httpx.AsyncClient.__init__

    def init(self, *a, **k):
        k["transport"] = httpx.MockTransport(handler)
        orig(self, *a, **k)
    monkeypatch.setattr(httpx.AsyncClient, "__init__", init)
    monkeypatch.setattr(S, "RATE_LIMIT_DELAY", 0)
    monkeypatch.setattr(S, "API_KEY", "")
    return urls, box


@pytest.mark.parametrize("pid", ["abc?x=1", "abc#", "DOI:10.1002/a#b"])
def test_citations_keep_their_suffix(requested, pid):
    urls, _ = requested
    asyncio.run(S.s2_citations(S.CitationInput(paper_id=pid)))
    path = urls[0].raw_path.decode().split("?")[0]
    assert path.endswith(quote(pid, safe=":/") + "/citations"), path


def test_overlong_query_is_refused_before_sending():
    with pytest.raises(ValidationError):
        S.PaperSearchInput(query="x" * 70_000)
    with pytest.raises(ValidationError):
        S.AuthorSearchInput(query="x" * 70_000)


def test_unsendable_request_is_a_diagnostic_not_a_crash(requested):
    data, err = asyncio.run(S._api_request("GET", f"{S.API_BASE}/paper/a\x00b"))
    assert data is None and err["code"] == "TRANSPORT_ERROR"


def test_key_straddling_the_cut_is_not_leaked(requested, monkeypatch):
    urls, box = requested
    monkeypatch.setattr(S, "API_KEY", "SENTINELKEY123")
    box.update(status=400, body="x" * 290 + "SENTINELKEY123")
    _, err = asyncio.run(S._api_request("GET", f"{S.API_BASE}/paper/search", params={"query": "q"}))
    assert "SENTIN" not in err["message"]


@pytest.mark.parametrize("form", [quote("k/y+z=", safe=""), "k%2Fy%2Bz%3D".replace("%2F", "/"), "k%2Fy%2Bz%3D"])
def test_key_is_redacted_in_encoded_forms(monkeypatch, form):
    monkeypatch.setattr(S, "API_KEY", "k/y+z=")
    assert "[redacted]" in S._redact(f"url?key={form}&x") and form not in S._redact(f"url?key={form}&x")
