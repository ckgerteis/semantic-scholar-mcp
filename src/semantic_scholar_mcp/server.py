"""
Semantic Scholar MCP Server (v2.0.1)
====================================
An MCP server for the Semantic Scholar Academic Graph API: paper search,
citation and reference traversal, author lookup, and recommendations.

v2.0.0 — clean replacement of the response format. Every tool now emits the
unified response envelope shared across the server family (see mediation.py /
response-schema.json): typed query/script, matching_mode, graduated breadth,
per-item matched_in, typed diagnostics, a loggable receipt, and attribution.
This is a breaking change from v1.x, which returned formatted markdown text.

Data source: Semantic Scholar API (https://api.semanticscholar.org)
API key (free): https://www.semanticscholar.org/product/api#api-key-form
Set via environment variable SEMANTIC_SCHOLAR_API_KEY. The key is sent as a
header and never as a query parameter.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
try:  # mcp SDK 1.x
    from mcp.server.fastmcp import FastMCP as _MCPServer
except ModuleNotFoundError:  # mcp SDK 2.x removed mcp.server.fastmcp
    from mcp.server.mcpserver import MCPServer as _MCPServer

from . import mediation as M

__version__ = "2.0.1"

# ==============================================================================
# Configuration
# ==============================================================================

API_BASE = "https://api.semanticscholar.org/graph/v1"
RECOMMENDATIONS_URL = "https://api.semanticscholar.org/recommendations/v1"
API_KEY = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")
TIMEOUT = 30.0
# Semantic Scholar allows 1 request per second to keyed users and a smaller
# shared pool to everyone else. The interval is enforced for both: without a
# key the pool is stricter, not looser, so nothing is gained by skipping it.
RATE_LIMIT_DELAY = 1.1
ATTRIBUTION = "Data via the Semantic Scholar Academic Graph API, Allen Institute for AI."

# Paper search is relevance-ranked over title, abstract and venue: neither a
# catalogued conjunction nor a plain full-text hit, and the total is an
# estimate the API revises as it pages. The mode name says so.
MODE_SEARCH = "relevance_ranked"
MODE_FILTER = "filter_exact"
MODE_LOOKUP = "identifier_lookup"
MODE_RECOMMEND = "similarity_ranked"

DEFAULT_PAPER_FIELDS = (
    "paperId,title,year,authors,abstract,citationCount,"
    "referenceCount,influentialCitationCount,isOpenAccess,"
    "openAccessPdf,fieldsOfStudy,publicationDate,journal,"
    "externalIds,url,tldr,publicationVenue"
)
BRIEF_PAPER_FIELDS = "paperId,title,year,authors,citationCount,abstract,url,externalIds"
DEFAULT_AUTHOR_FIELDS = "authorId,name,affiliations,paperCount,citationCount,hIndex,url"


def _silence_http_logging() -> None:
    """This is a stdio server: stdout carries JSON-RPC and nothing else, and
    httpx logs every request URL at INFO. The key travels in a header rather
    than the URL, so nothing secret would leak — but a search term would, onto
    the stderr Claude Desktop captures. Mute it, as the rest of the family does."""
    for name in ("httpx", "httpcore", "httpx._client"):
        lg = logging.getLogger(name)
        lg.setLevel(logging.WARNING)
        lg.propagate = False
    root = logging.getLogger()
    for h in list(root.handlers):
        if getattr(h, "stream", None) is sys.stdout:
            root.removeHandler(h)
    if not root.handlers:
        root.addHandler(logging.StreamHandler(sys.stderr))


_silence_http_logging()

# mcp 1.x's FastMCP takes no `version`; 2.x's MCPServer does. Passed where it is
# accepted, because a server that answers `initialize` with an empty version
# string cannot be cited by the disclosure that has to name the build it ran.
try:
    mcp = _MCPServer("semantic_scholar_mcp", version=__version__)
except TypeError:  # mcp SDK 1.x
    mcp = _MCPServer("semantic_scholar_mcp")


# ==============================================================================
# HTTP client
# ==============================================================================

_last_request_time = 0.0
_rate_lock: Optional[asyncio.Lock] = None


def _lock() -> asyncio.Lock:
    """Created lazily so the lock binds to the running loop, not import time."""
    global _rate_lock
    if _rate_lock is None:
        _rate_lock = asyncio.Lock()
    return _rate_lock


def _redact(text: str) -> str:
    if API_KEY and API_KEY in text:
        text = text.replace(API_KEY, "[redacted]")
    return text


async def _api_request(
    method: str,
    url: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Any] = None,
) -> tuple[Optional[Any], Optional[dict]]:
    """Call one endpoint under the rate limit.

    Returns (data, error_diag); exactly one is non-None. The lock is held
    across check, sleep and request so that two concurrent tool calls cannot
    both read the same last-request time and fire together.
    """
    global _last_request_time
    headers = {"Accept": "application/json"}
    if API_KEY:
        headers["x-api-key"] = API_KEY

    try:
        async with _lock():
            elapsed = time.monotonic() - _last_request_time
            if elapsed < RATE_LIMIT_DELAY:
                await asyncio.sleep(RATE_LIMIT_DELAY - elapsed)
            _last_request_time = time.monotonic()
            async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
                if method == "GET":
                    resp = await client.get(url, params=params, headers=headers)
                else:
                    resp = await client.post(url, params=params, json=json_body, headers=headers)
    except httpx.HTTPError as exc:
        return None, M.diag(
            "error", "TRANSPORT_ERROR",
            f"Could not reach Semantic Scholar: {_redact(type(exc).__name__ + ': ' + str(exc))[:300]}",
            "The result of this search is unknown, not empty. Retry before "
            "concluding anything about the literature.",
        )

    if resp.status_code == 404:
        return None, M.diag(
            "warning", "NOT_FOUND",
            "Semantic Scholar has no record for this identifier.",
            "Accepted forms: an S2 paper ID, DOI:10.…, ARXIV:…, PMID:…, CorpusId:…, or a semanticscholar.org URL.",
        )
    if resp.status_code == 429:
        return None, M.diag(
            "error", "RATE_LIMITED",
            "Semantic Scholar answered 429: the request rate was exceeded.",
            "Wait and retry. Keyless access shares one pool across all callers and "
            "search endpoints are throttled first; a free key gives 1 request/second.",
        )
    if resp.status_code >= 400:
        return None, M.diag(
            "error", "API_ERROR",
            f"Semantic Scholar answered {resp.status_code}: {_redact(resp.text[:300])}",
            None,
        )
    try:
        return resp.json(), None
    except ValueError:
        return None, M.diag(
            "error", "API_ERROR",
            "Semantic Scholar answered 200 with a body that is not JSON.",
            "Retry; if it persists the API or an intermediary is misbehaving.",
        )


# ==============================================================================
# Record builders
# ==============================================================================


def _place_title(text: Optional[str]) -> dict:
    """Semantic Scholar reports no language, so script decides. Kana or Hangul
    is decisive; a han-only title could be Chinese or Japanese and is left
    untyped rather than guessed, with the text kept in extra.title."""
    out = {"title_ja": None, "title_ko": None, "title_en": None}
    if not text:
        return out
    script = M.detect_script(text)
    if script in ("kana", "han_kana"):
        out["title_ja"] = text
    elif script in ("hangul", "han_hangul"):
        out["title_ko"] = text
    elif script == "latin":
        out["title_en"] = text
    return out


def _item_from_paper(p: dict, matched_in: str) -> dict:
    ext = p.get("externalIds") or {}
    venue = p.get("publicationVenue") or {}
    journal = p.get("journal") or {}
    oa_pdf = p.get("openAccessPdf") or {}
    tldr = p.get("tldr") or {}
    abstract = p.get("abstract")
    authors = [
        {"name": a.get("name"), "s2_author_id": a.get("authorId")}
        for a in (p.get("authors") or [])[:12]
    ]
    return M.make_item(
        **_place_title(p.get("title")),
        authors=authors,
        journal_en=journal.get("name") or venue.get("name"),
        volume=journal.get("volume"),
        pages=journal.get("pages"),
        year=p.get("year"),
        doi=ext.get("DOI"),
        issn=venue.get("issn"),
        url_en=p.get("url"),
        fulltext_url=oa_pdf.get("url") or None,
        matched_in=matched_in,
        record_type="article",
        extra={
            "title": p.get("title"),
            "s2_paper_id": p.get("paperId"),
            "corpus_id": ext.get("CorpusId"),
            "arxiv": ext.get("ArXiv"),
            "pmid": ext.get("PubMed"),
            "venue_type": venue.get("type"),
            "publication_date": p.get("publicationDate"),
            "citation_count": p.get("citationCount"),
            "influential_citation_count": p.get("influentialCitationCount"),
            "reference_count": p.get("referenceCount"),
            "is_open_access": p.get("isOpenAccess"),
            "open_access_status": oa_pdf.get("status"),
            "fields_of_study": p.get("fieldsOfStudy"),
            "tldr": tldr.get("text"),
            "abstract": (abstract[:400] + "…") if abstract and len(abstract) > 400 else abstract,
        },
    )


def _item_from_author(a: dict, matched_in: str) -> dict:
    return M.make_item(
        title_en=a.get("name"),
        url_en=a.get("url"),
        matched_in=matched_in,
        record_type="author",
        extra={
            "s2_author_id": a.get("authorId"),
            "affiliations": a.get("affiliations") or [],
            "paper_count": a.get("paperCount"),
            "citation_count": a.get("citationCount"),
            "h_index": a.get("hIndex"),
        },
    )


# ==============================================================================
# Envelope assembly
# ==============================================================================


def _envelope(
    *,
    operation: str,
    term: str,
    params: dict,
    matching_mode: str,
    data: Optional[Any],
    err: Optional[dict],
    records: list,
    total: Optional[int],
    start: int = 1,
    matched_in: str,
    build=_item_from_paper,
    extra_diags: Optional[list] = None,
    coverage_note: Optional[str] = None,
) -> str:
    """Assemble and emit one envelope.

    `total` is what the API reported, or None where the endpoint reports no
    corpus total (citations, references, an author's papers, batch, and
    recommendations). Then result.total is the returned count and a
    TOTAL_NOT_REPORTED diagnostic says so, so that a returned count is never
    mistaken for a corpus count.
    """
    items = [build(r, matched_in) for r in records if isinstance(r, dict)]
    ds: list[dict] = []
    if err:
        ds.append(err)
    ds.extend(extra_diags or [])
    if not err and total is None:
        more = isinstance(data, dict) and data.get("next") is not None
        total = len(items)
        ds.append(M.diag(
            "info", "TOTAL_NOT_REPORTED",
            "This endpoint reports no corpus total; result.total is the number of "
            "records returned" + (", and the API offers a further page." if more else "."),
            "Page with offset to enumerate the set." if more else None,
        ))
    if not err and not items:
        ds.append(M.diag(
            "warning", "ZERO_RESULTS",
            "No records for this query.",
            "Semantic Scholar's coverage of non-English humanities scholarship is "
            "thin; try the sibling servers (CiNii, J-STAGE, NDL, KCI) before "
            "concluding the literature is absent.",
        ))
    if not ds:
        ds.append(M.diag("info", "OK", f"{total} record(s) reported.", None))

    env = M.build_envelope(
        server="semantic_scholar", operation=operation,
        input_terms=term, normalized=term,
        params={k: v for k, v in params.items() if v is not None},
        matching_mode=matching_mode, total=total or 0, start=start,
        items=items, diagnostics=ds, attribution=ATTRIBUTION,
        coverage_note=coverage_note,
    )
    return M.emit(env)


def _page(data: Any) -> tuple[list, Optional[int]]:
    """(records, total-or-None) from a {total?, offset, next, data} page."""
    if not isinstance(data, dict):
        return [], None
    records = data.get("data") or []
    total = data.get("total")
    try:
        return records, (int(total) if total is not None else None)
    except (TypeError, ValueError):
        return records, None


# ==============================================================================
# Input Models
# ==============================================================================


class PaperSearchInput(BaseModel):
    """Input for searching papers by keyword."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: str = Field(..., description="Search query (e.g., 'bōsōzoku motorcycle gangs Japan')", min_length=1)
    year_start: Optional[int] = Field(default=None, description="Filter: earliest publication year (e.g. 1970)")
    year_end: Optional[int] = Field(default=None, description="Filter: latest publication year (e.g. 2024)")
    fields_of_study: Optional[str] = Field(default=None, description="Comma-separated fields (e.g., 'History,Sociology')")
    min_citations: Optional[int] = Field(default=None, description="Minimum citation count", ge=0)
    open_access_only: bool = Field(default=False, description="Only return open access papers")
    limit: int = Field(default=10, description="Number of results (1-100)", ge=1, le=100)
    offset: int = Field(default=0, description="Pagination offset", ge=0)


class PaperLookupInput(BaseModel):
    """Input for looking up a specific paper."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    paper_id: str = Field(
        ...,
        description="Paper identifier: S2 Paper ID, DOI (e.g. '10.1234/xyz'), ArXiv ID (e.g. 'ArXiv:2106.15928'), or URL",
        min_length=1,
    )


class BatchPaperInput(BaseModel):
    """Input for batch paper lookup."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    paper_ids: List[str] = Field(
        ..., description="List of paper IDs (S2 IDs, DOIs, ArXiv IDs)", min_length=1, max_length=500
    )


class CitationInput(BaseModel):
    """Input for citation/reference traversal."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    paper_id: str = Field(..., description="Paper identifier", min_length=1)
    direction: str = Field(
        default="citations",
        description="'citations' (papers citing this) or 'references' (papers this cites)",
    )
    limit: int = Field(default=20, description="Number of results (1-1000)", ge=1, le=1000)
    offset: int = Field(default=0, description="Pagination offset", ge=0)

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, v: str) -> str:
        if v not in ("citations", "references"):
            raise ValueError("direction must be 'citations' or 'references'")
        return v


class AuthorSearchInput(BaseModel):
    """Input for searching authors."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: str = Field(..., description="Author name to search", min_length=1)
    limit: int = Field(default=10, description="Number of results (1-100)", ge=1, le=100)
    offset: int = Field(default=0, description="Pagination offset", ge=0)


class AuthorLookupInput(BaseModel):
    """Input for looking up a specific author."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    author_id: str = Field(..., description="Semantic Scholar Author ID", min_length=1)


class AuthorPapersInput(BaseModel):
    """Input for getting an author's papers."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    author_id: str = Field(..., description="Semantic Scholar Author ID", min_length=1)
    limit: int = Field(default=20, description="Number of results (1-100)", ge=1, le=100)
    offset: int = Field(default=0, description="Pagination offset", ge=0)


class RecommendInput(BaseModel):
    """Input for paper recommendations from a single seed paper."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    paper_id: str = Field(..., description="Seed paper identifier", min_length=1)
    limit: int = Field(default=10, description="Number of recommendations (1-100)", ge=1, le=100)


class MultiRecommendInput(BaseModel):
    """Input for recommendations from multiple seed papers."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    positive_paper_ids: List[str] = Field(
        ..., description="Papers to recommend similar to (1-100)", min_length=1, max_length=100
    )
    negative_paper_ids: Optional[List[str]] = Field(
        default=None, description="Papers to recommend UNLIKE (optional)"
    )
    limit: int = Field(default=10, description="Number of recommendations (1-100)", ge=1, le=100)


# ==============================================================================
# Tools
# ==============================================================================

_ANN = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}


@mcp.tool(name="s2_search_papers", annotations=_ANN)
async def s2_search_papers(params: PaperSearchInput) -> str:
    """Search Semantic Scholar for papers by keyword, with year, field-of-study, citation-count and open-access filters. Returns the unified envelope.

    Matching is relevance-ranked over title, abstract and venue
    (matching_mode relevance_ranked); result.total is the API's estimate.
    Titles are typed by script: kana or Hangul decide ja or ko, Latin goes to
    en, and a han-only title stays untyped in extra.title. Coverage of
    non-English humanities work is thin — a ZERO_RESULTS here is weak
    evidence; consult the CiNii, J-STAGE, NDL and KCI servers.
    """
    qp: Dict[str, Any] = {"query": params.query, "fields": DEFAULT_PAPER_FIELDS,
                          "limit": params.limit, "offset": params.offset}
    if params.year_start or params.year_end:
        qp["year"] = f"{params.year_start or ''}-{params.year_end or ''}"
    if params.fields_of_study:
        qp["fieldsOfStudy"] = params.fields_of_study
    if params.min_citations is not None:
        qp["minCitationCount"] = params.min_citations
    if params.open_access_only:
        qp["openAccessPdf"] = ""
    data, err = await _api_request("GET", f"{API_BASE}/paper/search", params=qp)
    records, total = _page(data)
    return _envelope(operation="search_papers", term=params.query,
                     params={k: v for k, v in qp.items() if k != "fields"},
                     matching_mode=MODE_SEARCH, data=data, err=err,
                     records=records, total=total, start=params.offset + 1,
                     matched_in="title_abstract_venue")


@mcp.tool(name="s2_get_paper", annotations=_ANN)
async def s2_get_paper(params: PaperLookupInput) -> str:
    """Look up one paper by S2 ID, DOI, ArXiv ID, or URL. Returns the unified envelope with a single item, or NOT_FOUND."""
    data, err = await _api_request("GET", f"{API_BASE}/paper/{params.paper_id}",
                                   params={"fields": DEFAULT_PAPER_FIELDS})
    return _envelope(operation="get_paper", term=params.paper_id, params={"paper_id": params.paper_id},
                     matching_mode=MODE_LOOKUP, data=data, err=err,
                     records=[data] if isinstance(data, dict) else [], total=1 if isinstance(data, dict) else 0,
                     matched_in="identifier")


@mcp.tool(name="s2_batch_papers", annotations=_ANN)
async def s2_batch_papers(params: BatchPaperInput) -> str:
    """Look up up to 500 papers at once by ID. Returns the unified envelope; identifiers the API could not resolve are counted in a PARTIAL_NOT_FOUND diagnostic and listed in coverage_note."""
    data, err = await _api_request("POST", f"{API_BASE}/paper/batch",
                                   params={"fields": BRIEF_PAPER_FIELDS},
                                   json_body={"ids": params.paper_ids})
    records = [p for p in data if isinstance(p, dict)] if isinstance(data, list) else []
    extra: list[dict] = []
    note = None
    if isinstance(data, list):
        missing = [pid for pid, p in zip(params.paper_ids, data) if p is None]
        if missing:
            extra.append(M.diag(
                "warning", "PARTIAL_NOT_FOUND",
                f"{len(missing)} of {len(params.paper_ids)} identifier(s) resolved to no record.",
                "The unresolved identifiers are listed in coverage_note.",
            ))
            note = "Unresolved: " + ", ".join(missing[:50]) + (" …" if len(missing) > 50 else "")
    elif err is None:
        err = M.diag("error", "API_ERROR", "Batch endpoint returned a body that is not a list.", None)
    # The identifiers are the query here; they go into params so the receipt
    # hash fixes which papers were asked for, not only which came back.
    return _envelope(operation="batch_papers", term=" ".join(params.paper_ids)[:500],
                     params={"ids": params.paper_ids},
                     matching_mode=MODE_LOOKUP, data=data, err=err,
                     records=records, total=len(records) if err is None else 0,
                     matched_in="identifier", extra_diags=extra, coverage_note=note)


@mcp.tool(name="s2_citations", annotations=_ANN)
async def s2_citations(params: CitationInput) -> str:
    """Papers citing a given paper (citations) or cited by it (references). Returns the unified envelope. The API reports no total for this endpoint, so result.total is the returned count (TOTAL_NOT_REPORTED)."""
    qp = {"fields": BRIEF_PAPER_FIELDS, "limit": params.limit, "offset": params.offset}
    data, err = await _api_request("GET", f"{API_BASE}/paper/{params.paper_id}/{params.direction}", params=qp)
    records, _ = _page(data)
    key = "citingPaper" if params.direction == "citations" else "citedPaper"
    papers = [r.get(key) for r in records if isinstance(r, dict) and isinstance(r.get(key), dict)]
    return _envelope(operation=params.direction, term=params.paper_id,
                     params={"paper_id": params.paper_id, "direction": params.direction,
                             "limit": params.limit, "offset": params.offset},
                     matching_mode=MODE_FILTER, data=data, err=err,
                     records=papers, total=None, start=params.offset + 1,
                     matched_in="citation_graph")


@mcp.tool(name="s2_search_authors", annotations=_ANN)
async def s2_search_authors(params: AuthorSearchInput) -> str:
    """Search for authors by name. Returns the unified envelope; each item is an author record (record_type author) with affiliations, paper count, citation count and h-index in extra."""
    qp = {"query": params.query, "fields": DEFAULT_AUTHOR_FIELDS, "limit": params.limit, "offset": params.offset}
    data, err = await _api_request("GET", f"{API_BASE}/author/search", params=qp)
    records, total = _page(data)
    return _envelope(operation="search_authors", term=params.query,
                     params={k: v for k, v in qp.items() if k != "fields"},
                     matching_mode=MODE_SEARCH, data=data, err=err,
                     records=records, total=total, start=params.offset + 1,
                     matched_in="name", build=_item_from_author)


@mcp.tool(name="s2_get_author", annotations=_ANN)
async def s2_get_author(params: AuthorLookupInput) -> str:
    """Look up one author by Semantic Scholar Author ID. Returns the unified envelope with a single author item, or NOT_FOUND."""
    data, err = await _api_request("GET", f"{API_BASE}/author/{params.author_id}",
                                   params={"fields": DEFAULT_AUTHOR_FIELDS})
    return _envelope(operation="get_author", term=params.author_id, params={"author_id": params.author_id},
                     matching_mode=MODE_LOOKUP, data=data, err=err,
                     records=[data] if isinstance(data, dict) else [], total=1 if isinstance(data, dict) else 0,
                     matched_in="identifier", build=_item_from_author)


@mcp.tool(name="s2_author_papers", annotations=_ANN)
async def s2_author_papers(params: AuthorPapersInput) -> str:
    """Papers by one author, paginated. Returns the unified envelope; result.total is the returned count (TOTAL_NOT_REPORTED)."""
    qp = {"fields": BRIEF_PAPER_FIELDS, "limit": params.limit, "offset": params.offset}
    data, err = await _api_request("GET", f"{API_BASE}/author/{params.author_id}/papers", params=qp)
    records, _ = _page(data)
    return _envelope(operation="author_papers", term=params.author_id,
                     params={"author_id": params.author_id, "limit": params.limit, "offset": params.offset},
                     matching_mode=MODE_FILTER, data=data, err=err,
                     records=records, total=None, start=params.offset + 1,
                     matched_in="authorship")


@mcp.tool(name="s2_recommend_single", annotations=_ANN)
async def s2_recommend_single(params: RecommendInput) -> str:
    """Papers similar to one seed paper, by Semantic Scholar's recommender. Returns the unified envelope (matching_mode similarity_ranked)."""
    data, err = await _api_request("GET", f"{RECOMMENDATIONS_URL}/papers/forpaper/{params.paper_id}",
                                   params={"fields": BRIEF_PAPER_FIELDS, "limit": params.limit})
    records = (data.get("recommendedPapers") or []) if isinstance(data, dict) else []
    return _envelope(operation="recommend_single", term=params.paper_id,
                     params={"paper_id": params.paper_id, "limit": params.limit},
                     matching_mode=MODE_RECOMMEND, data=data, err=err,
                     records=records, total=None, matched_in="recommender")


@mcp.tool(name="s2_recommend_multi", annotations=_ANN)
async def s2_recommend_multi(params: MultiRecommendInput) -> str:
    """Papers similar to a set of positive seed papers and unlike optional negative ones. Returns the unified envelope (matching_mode similarity_ranked); the seed IDs are in query.params so the receipt fixes them."""
    body: Dict[str, Any] = {"positivePaperIds": params.positive_paper_ids}
    if params.negative_paper_ids:
        body["negativePaperIds"] = params.negative_paper_ids
    data, err = await _api_request("POST", f"{RECOMMENDATIONS_URL}/papers/",
                                   params={"fields": BRIEF_PAPER_FIELDS, "limit": params.limit},
                                   json_body=body)
    records = (data.get("recommendedPapers") or []) if isinstance(data, dict) else []
    return _envelope(operation="recommend_multi", term=" ".join(params.positive_paper_ids)[:500],
                     params={"positive_paper_ids": params.positive_paper_ids,
                             "negative_paper_ids": params.negative_paper_ids, "limit": params.limit},
                     matching_mode=MODE_RECOMMEND, data=data, err=err,
                     records=records, total=None, matched_in="recommender")


# ==============================================================================
# Entry point
# ==============================================================================

def main() -> None:
    """Console-script entry point (`semantic-scholar-mcp`)."""
    mcp.run()


if __name__ == "__main__":
    main()
