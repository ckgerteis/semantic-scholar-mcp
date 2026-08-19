"""
Semantic Scholar MCP Server
===========================
An MCP server providing access to the Semantic Scholar Academic Graph API
for searching papers, exploring citation networks, looking up authors,
and getting paper recommendations.

Data source: Semantic Scholar API (https://api.semanticscholar.org)
Requires: API key from https://www.semanticscholar.org/product/api#api-key-form
Set via environment variable SEMANTIC_SCHOLAR_API_KEY.
"""

import json
import asyncio
import os
import time
from typing import Optional, List, Dict, Any
from enum import Enum

import httpx
from pydantic import BaseModel, Field, ConfigDict, field_validator
try:  # mcp SDK 1.x
    from mcp.server.fastmcp import FastMCP as _MCPServer
except ModuleNotFoundError:  # mcp SDK 2.x removed mcp.server.fastmcp
    from mcp.server.mcpserver import MCPServer as _MCPServer

import ledger

# ==============================================================================
# Configuration
# ==============================================================================

API_BASE = "https://api.semanticscholar.org/graph/v1"
RECOMMENDATIONS_URL = "https://api.semanticscholar.org/recommendations/v1"
API_KEY = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")
TIMEOUT = 30
RATE_LIMIT_DELAY = 1.1  # slightly over 1s to respect 1 RPS limit for keyed users

DEFAULT_PAPER_FIELDS = (
    "paperId,title,year,authors,abstract,citationCount,"
    "referenceCount,influentialCitationCount,isOpenAccess,"
    "openAccessPdf,fieldsOfStudy,publicationDate,journal,"
    "externalIds,url,tldr,publicationVenue"
)

BRIEF_PAPER_FIELDS = (
    "paperId,title,year,authors,citationCount,abstract,url,externalIds"
)

DEFAULT_AUTHOR_FIELDS = (
    "authorId,name,affiliations,paperCount,citationCount,hIndex,url"
)

# ==============================================================================
# HTTP Client
# ==============================================================================

_last_request_time = 0.0


async def _api_request(
    method: str,
    url: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Any] = None,
) -> Dict[str, Any]:
    """Make a rate-limited request to the Semantic Scholar API."""
    global _last_request_time

    # Rate limiting
    now = time.monotonic()
    elapsed = now - _last_request_time
    if elapsed < RATE_LIMIT_DELAY:
        await asyncio.sleep(RATE_LIMIT_DELAY - elapsed)

    headers = {"Accept": "application/json"}
    if API_KEY:
        headers["x-api-key"] = API_KEY

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        _last_request_time = time.monotonic()
        if method == "GET":
            resp = await client.get(url, params=params, headers=headers)
        else:
            resp = await client.post(url, params=params, json=json_body, headers=headers)

    if resp.status_code == 404:
        out = {"error": "Not found. Check the ID or query."}
    elif resp.status_code == 429:
        out = {"error": "Rate limit exceeded. Wait a moment and retry."}
    elif resp.status_code >= 400:
        out = {"error": f"API error {resp.status_code}: {resp.text[:500]}"}
    else:
        out = resp.json()

    # Query receipt. Records what was sent to Semantic Scholar, not what was displayed.
    ledger.record_request(
        server="semantic_scholar", operation=url.split("/v1/")[-1],
        endpoint=url, params=params, response=out,
    )
    return out


def _format_paper(p: Dict) -> str:
    """Format a single paper record as readable text."""
    parts = []
    title = p.get("title", "Untitled")
    year = p.get("year", "n.d.")
    parts.append(f"**{title}** ({year})")

    authors = p.get("authors", [])
    if authors:
        names = ", ".join(a.get("name", "?") for a in authors[:5])
        if len(authors) > 5:
            names += f" … +{len(authors)-5} more"
        parts.append(f"  Authors: {names}")

    cites = p.get("citationCount")
    if cites is not None:
        parts.append(f"  Citations: {cites}")

    doi = (p.get("externalIds") or {}).get("DOI")
    if doi:
        parts.append(f"  DOI: {doi}")

    oa_pdf = p.get("openAccessPdf")
    if oa_pdf and oa_pdf.get("url"):
        parts.append(f"  Open Access PDF: {oa_pdf['url']}")

    url = p.get("url")
    if url:
        parts.append(f"  URL: {url}")

    tldr = p.get("tldr")
    if tldr and tldr.get("text"):
        parts.append(f"  TL;DR: {tldr['text']}")

    abstract = p.get("abstract")
    if abstract:
        parts.append(f"  Abstract: {abstract[:400]}{'…' if len(abstract)>400 else ''}")

    return "\n".join(parts)


# ==============================================================================
# Server Initialization
# ==============================================================================

__version__ = "1.0.0"

mcp = _MCPServer("semantic_scholar_mcp")

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


@mcp.tool(
    name="s2_search_papers",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def s2_search_papers(params: PaperSearchInput) -> str:
    """Search Semantic Scholar for papers by keyword, with optional filters for year, field of study, citation count, and open access status. Returns titles, authors, abstracts, citation counts, DOIs, and links."""
    query_params: Dict[str, Any] = {
        "query": params.query,
        "fields": DEFAULT_PAPER_FIELDS,
        "limit": params.limit,
        "offset": params.offset,
    }

    if params.year_start or params.year_end:
        yr = f"{params.year_start or ''}-{params.year_end or ''}"
        query_params["year"] = yr

    if params.fields_of_study:
        query_params["fieldsOfStudy"] = params.fields_of_study

    if params.min_citations is not None:
        query_params["minCitationCount"] = params.min_citations

    if params.open_access_only:
        query_params["openAccessPdf"] = ""

    data = await _api_request("GET", f"{API_BASE}/paper/search", params=query_params)

    if "error" in data:
        return f"Error: {data['error']}"

    total = data.get("total", 0)
    papers = data.get("data", [])

    if not papers:
        return f"No results found for '{params.query}'."

    lines = [f"**Search results for '{params.query}'** — {total} total, showing {len(papers)}\n"]
    for i, p in enumerate(papers, 1):
        lines.append(f"---\n{i}. {_format_paper(p)}")

    if total > params.offset + len(papers):
        lines.append(f"\n→ More results available. Use offset={params.offset + len(papers)} to paginate.")

    return "\n".join(lines)


@mcp.tool(
    name="s2_get_paper",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def s2_get_paper(params: PaperLookupInput) -> str:
    """Look up a specific paper by its Semantic Scholar ID, DOI, ArXiv ID, or URL. Returns full metadata including abstract, citation counts, open access links, and TL;DR summary."""
    data = await _api_request(
        "GET", f"{API_BASE}/paper/{params.paper_id}", params={"fields": DEFAULT_PAPER_FIELDS}
    )
    if "error" in data:
        return f"Error: {data['error']}"
    return _format_paper(data)


@mcp.tool(
    name="s2_batch_papers",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def s2_batch_papers(params: BatchPaperInput) -> str:
    """Look up multiple papers at once by their IDs (S2 IDs, DOIs, ArXiv IDs). Up to 500 papers per request."""
    data = await _api_request(
        "POST",
        f"{API_BASE}/paper/batch",
        params={"fields": BRIEF_PAPER_FIELDS},
        json_body={"ids": params.paper_ids},
    )
    if isinstance(data, dict) and "error" in data:
        return f"Error: {data['error']}"

    if not isinstance(data, list):
        return "Unexpected response format."

    lines = [f"**Batch lookup: {len(data)} papers**\n"]
    for i, p in enumerate(data, 1):
        if p is None:
            lines.append(f"{i}. [Not found]")
        else:
            lines.append(f"---\n{i}. {_format_paper(p)}")

    return "\n".join(lines)


@mcp.tool(
    name="s2_citations",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def s2_citations(params: CitationInput) -> str:
    """Get papers that cite a given paper (forward citations) or papers that a given paper references (backward citations). Useful for exploring citation networks."""
    url = f"{API_BASE}/paper/{params.paper_id}/{params.direction}"
    data = await _api_request(
        "GET",
        url,
        params={"fields": BRIEF_PAPER_FIELDS, "limit": params.limit, "offset": params.offset},
    )
    if "error" in data:
        return f"Error: {data['error']}"

    items = data.get("data", [])
    if not items:
        return f"No {params.direction} found for this paper."

    direction_label = "Cited by" if params.direction == "citations" else "References"
    lines = [f"**{direction_label}** ({len(items)} results)\n"]
    for i, item in enumerate(items, 1):
        cited_paper = item.get("citingPaper" if params.direction == "citations" else "citedPaper", {})
        if cited_paper:
            lines.append(f"---\n{i}. {_format_paper(cited_paper)}")

    return "\n".join(lines)


@mcp.tool(
    name="s2_search_authors",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def s2_search_authors(params: AuthorSearchInput) -> str:
    """Search for authors by name. Returns author profiles with affiliation, paper count, citation count, and h-index."""
    data = await _api_request(
        "GET",
        f"{API_BASE}/author/search",
        params={"query": params.query, "fields": DEFAULT_AUTHOR_FIELDS, "limit": params.limit, "offset": params.offset},
    )
    if "error" in data:
        return f"Error: {data['error']}"

    authors = data.get("data", [])
    if not authors:
        return f"No authors found for '{params.query}'."

    lines = [f"**Author search: '{params.query}'** — {len(authors)} results\n"]
    for i, a in enumerate(authors, 1):
        name = a.get("name", "?")
        affils = ", ".join(a.get("affiliations", [])) or "No affiliation listed"
        papers = a.get("paperCount", "?")
        cites = a.get("citationCount", "?")
        h = a.get("hIndex", "?")
        url = a.get("url", "")
        lines.append(
            f"{i}. **{name}** — {affils}\n"
            f"   Papers: {papers} | Citations: {cites} | h-index: {h}\n"
            f"   {url}"
        )

    return "\n".join(lines)


@mcp.tool(
    name="s2_get_author",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def s2_get_author(params: AuthorLookupInput) -> str:
    """Look up a specific author by Semantic Scholar Author ID. Returns their profile with affiliations, paper count, citation count, and h-index."""
    data = await _api_request(
        "GET", f"{API_BASE}/author/{params.author_id}", params={"fields": DEFAULT_AUTHOR_FIELDS}
    )
    if "error" in data:
        return f"Error: {data['error']}"

    name = data.get("name", "?")
    affils = ", ".join(data.get("affiliations", [])) or "No affiliation listed"
    return (
        f"**{name}**\n"
        f"Affiliations: {affils}\n"
        f"Papers: {data.get('paperCount', '?')} | Citations: {data.get('citationCount', '?')} | h-index: {data.get('hIndex', '?')}\n"
        f"URL: {data.get('url', 'N/A')}"
    )


@mcp.tool(
    name="s2_author_papers",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def s2_author_papers(params: AuthorPapersInput) -> str:
    """Get a list of papers by a specific author. Paginated."""
    data = await _api_request(
        "GET",
        f"{API_BASE}/author/{params.author_id}/papers",
        params={"fields": BRIEF_PAPER_FIELDS, "limit": params.limit, "offset": params.offset},
    )
    if "error" in data:
        return f"Error: {data['error']}"

    papers = data.get("data", [])
    if not papers:
        return "No papers found for this author."

    lines = [f"**Papers by author {params.author_id}** ({len(papers)} results)\n"]
    for i, p in enumerate(papers, 1):
        lines.append(f"---\n{i}. {_format_paper(p)}")

    return "\n".join(lines)


@mcp.tool(
    name="s2_recommend_single",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def s2_recommend_single(params: RecommendInput) -> str:
    """Get paper recommendations based on a single seed paper. Returns papers similar to the provided one."""
    data = await _api_request(
        "GET",
        f"{RECOMMENDATIONS_URL}/papers/forpaper/{params.paper_id}",
        params={"fields": BRIEF_PAPER_FIELDS, "limit": params.limit},
    )
    if "error" in data:
        return f"Error: {data['error']}"

    papers = data.get("recommendedPapers", [])
    if not papers:
        return "No recommendations found."

    lines = [f"**Recommendations based on paper {params.paper_id}** ({len(papers)} results)\n"]
    for i, p in enumerate(papers, 1):
        lines.append(f"---\n{i}. {_format_paper(p)}")

    return "\n".join(lines)


@mcp.tool(
    name="s2_recommend_multi",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def s2_recommend_multi(params: MultiRecommendInput) -> str:
    """Get paper recommendations based on multiple seed papers. Provide positive examples (papers to recommend similar to) and optional negative examples (papers to recommend unlike)."""
    body: Dict[str, Any] = {"positivePaperIds": params.positive_paper_ids}
    if params.negative_paper_ids:
        body["negativePaperIds"] = params.negative_paper_ids

    data = await _api_request(
        "POST",
        f"{RECOMMENDATIONS_URL}/papers/",
        params={"fields": BRIEF_PAPER_FIELDS, "limit": params.limit},
        json_body=body,
    )
    if "error" in data:
        return f"Error: {data['error']}"

    papers = data.get("recommendedPapers", [])
    if not papers:
        return "No recommendations found."

    lines = [f"**Multi-paper recommendations** ({len(papers)} results)\n"]
    for i, p in enumerate(papers, 1):
        lines.append(f"---\n{i}. {_format_paper(p)}")

    return "\n".join(lines)


# ==============================================================================
# Entry point
# ==============================================================================

if __name__ == "__main__":
    mcp.run()
