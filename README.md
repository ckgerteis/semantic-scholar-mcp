# semantic-scholar-mcp

MCP stdio server for the Semantic Scholar Academic Graph API.

Data via Semantic Scholar, Allen Institute for AI.

## What this is for

The Semantic Scholar Academic Graph, reached through citation traversal in both directions: the works a paper cites, and the works that went on to cite it. Look up as many as five hundred papers in a single call when a bibliography needs resolving.

The recommendation tools answer a question searching cannot: hand it two or three papers you already trust and it proposes adjacent work, which is how you enter a literature whose vocabulary you have not yet learned.

Records carry abstracts, influential-citation counts, open-access links, and machine-generated one-line summaries useful for triage. Where [`openalex-mcp`](https://github.com/ckgerteis/openalex-mcp) is strongest on institutions and geography, this is strongest on the shape of a citation network.

## Install

Three routes. All three give you the same server; pick by how much you want to see of it.

### One click: the Claude Desktop bundle

Download the `.mcpb` for your platform (Windows x64, Apple Silicon, Linux x64; Intel Macs use the pip route below) from the [latest release](https://github.com/ckgerteis/semantic-scholar-mcp/releases/latest) and open it; Claude Desktop installs it. Claude Desktop asks for Semantic Scholar API key and a receipts folder at install time; the key is stored in the OS keychain. The bundle carries every library it needs, but not Python itself: a Python 3.10+ interpreter must be on the machine (`python` on Windows, `python3` on macOS and Linux).

### From GitHub, pinned to a release

```bash
pip install "git+https://github.com/ckgerteis/semantic-scholar-mcp@v2.0.1"
# or, without an environment of your own:
uvx --from "git+https://github.com/ckgerteis/semantic-scholar-mcp@v2.0.1" semantic-scholar-mcp
```

installs the `semantic-scholar-mcp` console script and `semantic-scholar-mcp-ledger`. The tag is the thing to cite; `@main` gets whatever is current. Then register it in Claude Desktop (below), or let `install.py` do that.

### The whole family

```bash
pip install "git+https://github.com/ckgerteis/bibliograph-mcp@v1.0.0" && bibliograph install
```

installs all six servers and registers them together — one receipts folder, credentials asked for once. See [bibliograph-mcp](https://github.com/ckgerteis/bibliograph-mcp). From a checkout of this repository, `python install.py` does the same for this server alone, `python install.py --all` for the six, on Windows, macOS and Linux; `install.ps1` remains for Windows.

### From source

```bash
python3 -m venv .venv
.venv/bin/pip install .
```

On Windows:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\pip.exe install .
```

Or straight from the repository, without cloning:

```bash
uvx --from "git+https://github.com/ckgerteis/semantic-scholar-mcp" semantic-scholar-mcp
```

Verify the install:

```bash
.venv/bin/python -c "import semantic_scholar_mcp; print(semantic_scholar_mcp.__version__)"
```

That fails loudly if the package or one of its vendored modules is missing. Do
not use `semantic-scholar-mcp --help` as the check: unknown arguments are ignored, the
server starts, reads end-of-input and exits 0, so it reports success whatever
the state of the code.

### Installing more than this one

Six independent packages. None imports another, none depends on another, and
each installs and answers on its own — `pip install .` in this directory is a
complete install of this server and nothing else.

They do share three things: a response envelope, a query ledger, and — if you
run more than one — a receipts folder. `install.ps1` is vendored byte-identical
into all six and handles that on Windows; `install.py` is its cross-platform port. **Both install this server by default**, because
cloning one repository is not a request for five more.

```powershell
.\install.ps1                        # this server
.\install.ps1 -All                   # all six
.\install.ps1 -Servers semantic_scholar,cinii# a chosen subset
```

Whatever subset you name is registered against one receipts folder, asked for
once. The script prefers a sibling checkout to the network, carries across
credentials already registered rather than asking again, leaves servers it was
not asked about alone, and stops rather than guessing where the servers already
registered disagree about the folder or the session slug. It also asserts that
`ledger.py` and `mediation.py` are byte-identical across everything it
installed, so two envelope versions cannot end up in one environment unnoticed.

## Tools

| Tool | Purpose |
| --- | --- |
| `s2_search_papers` | Papers by keyword, with year, field-of-study, citation-count and open-access filters |
| `s2_get_paper` | One paper by S2 ID, DOI, ArXiv ID or URL |
| `s2_batch_papers` | Up to 500 papers by ID in one call |
| `s2_citations` | Papers citing a paper, or the papers it cites |
| `s2_search_authors` | Authors by name |
| `s2_get_author` | One author by S2 Author ID |
| `s2_author_papers` | An author's papers, paginated |
| `s2_recommend_single` | Papers similar to one seed paper |
| `s2_recommend_multi` | Papers similar to a set of seeds, unlike optional negatives |

All nine return one typed JSON response envelope — see [Response format](#response-format). (Releases before 2.0.0 returned formatted markdown text; that is a breaking change, not a formatting preference.)

## Response format

Every tool returns one JSON response envelope, built by `mediation.py` and defined in [`response-schema.json`](response-schema.json). Schema version 2.3.0. The same module and schema are vendored byte-identically across the server family, so an envelope from one server can be read by a consumer written for another.

The envelope reports how the search was made, not only what it found:

- **`searched_for`** — on the two term searches (`s2_search_papers`, `s2_search_authors`), the term actually sent, its detected script, and the matching mode, hoisted to the top of the envelope so a relaying client cannot drop it. Lookups, citation traversals, batch and recommendations omit it: they were handed identifiers and chose no term.
- **`query`** — `input_terms` as supplied, `normalized` as sent, and the detected `script`. For batch and multi-seed recommendations the identifiers asked for are in `params`, so the receipt hash fixes the request and not only the answer. The key is sent as a header and never enters `params`.
- **`matching_mode`** — `relevance_ranked` for term searches (title, abstract and venue, ranked; `result.total` is the API's estimate); `filter_exact` for citation and authorship traversals; `identifier_lookup` for fetches and batch; `similarity_ranked` for the recommender.
- **`result.breadth`** — `none`, `narrow` (1–50), `broad` (51–1000), `very_broad` (>1000).
- **`items[]`** — the family's item shape. Semantic Scholar reports no language, so script decides the typed title slot: kana or Hangul place a title in `ja` or `ko`, Latin script in `en`, and a han-only title is left untyped rather than guessed; `extra.title` always carries the text. S2 and Corpus IDs, ArXiv and PubMed IDs, citation and influential-citation counts, fields of study, TL;DR and the abstract sit in `extra`; the DOI in `ids.doi`; the S2 page in `ids.url_en`; an open-access PDF in `ids.fulltext_url`. Author records use `record_type` `author`.
- **`receipt`** — an ISO 8601 timestamp, a SHA-256 over the normalised query and its parameters, and the DOIs returned. Papers without a DOI are identified only in `extra.s2_paper_id`, which the receipt's `result_ids` does not yet read.
- **`attribution`** — the required credit line, in every response.

### Diagnostic codes

Typed and closed. A diagnostic is never prose the client has to parse.

| Code | Level | Meaning |
| --- | --- | --- |
| `OK` | info | Records returned; nothing to flag. |
| `TOTAL_NOT_REPORTED` | info | The endpoint reports no corpus total (citations, references, an author's papers, batch, recommendations); `result.total` is the returned count, and the message says whether the API offers a further page. |
| `ZERO_RESULTS` | warning | No records. Coverage of non-English humanities scholarship is thin; consult the CiNii, J-STAGE, NDL and KCI servers before concluding the literature is absent. |
| `PARTIAL_NOT_FOUND` | warning | Batch: some identifiers resolved to no record; they are listed in `coverage_note`. |
| `NOT_FOUND` | warning | A lookup by identifier answered 404. |
| `RATE_LIMITED` | error | The API answered 429. Keyless callers share one pool and search endpoints are throttled first; a free key gives 1 request/second, which the server enforces. |
| `API_ERROR` | error | The API answered, and answered with an error (or with a 200 that was not JSON). |
| `TRANSPORT_ERROR` | error | The request did not complete. Kept distinct from `API_ERROR` because a failed search has an unknown result and must never be written up as an absence. |
| `RECEIPT_NOT_DEPOSITED` | info | The response was not written to the query ledger, because no receipts destination is configured. |
| `RECEIPT_WRITE_FAILED` | warning | A receipts destination is set, the write was attempted, and it did not land. |

## Configuration

```
SEMANTIC_SCHOLAR_API_KEY=your_semantic_scholar_api_key
```

### Claude Desktop

Add an entry to `%APPDATA%\Claude\claude_desktop_config.json` under
`mcpServers`, pointing at the console script in the environment you installed
into. On macOS or Linux use the absolute path to `.venv/bin/semantic-scholar-mcp`.

```json
{
  "mcpServers": {
    "semantic-scholar": {
      "command": "C:\\path\\to\\.venv\\Scripts\\semantic-scholar-mcp.exe",
      "env": {
        "SEMANTIC_SCHOLAR_API_KEY": "your_semantic_scholar_api_key"
      }
    }
  }
}
```

**Changed in 2.0.0.** Tools return the JSON envelope rather than markdown; any consumer that parsed the 1.x text must be rewritten.

**Changed in 1.1.0.** Earlier versions were registered by path —
`"command": "…\\python.exe", "args": ["…\\server.py"]`. That entry will not
start this version, because `server.py` is now a module inside a package rather
than a script beside its imports. Replace it with the console script above.

Restart Claude Desktop. The nine tools should appear under "semantic-scholar" in the
tool list.

## Query receipts

Every envelope can be deposited to an append-only, hash-chained JSONL log by
`semantic_scholar_mcp.ledger`. It is **off unless `MCP_RECEIPT_DIR` (or the legacy `MCP_RECEIPT_LOG`) is set**, and a
logging failure is swallowed rather than raised — a search matters more than
the record of it. Secrets are redacted before a line is composed.

```
MCP_RECEIPT_DIR=C:\path\to\receipts        # a folder, not a file
MCP_RECEIPT_SESSION=project-or-article-slug
MCP_RECEIPT_STRICT=1                         # optional: make logging failure raise
MCP_RECEIPT_LOG=C:\path\to\receipts.jsonl  # legacy single file; ignored when _DIR is set
```

**A folder, and one file per server.** `MCP_RECEIPT_DIR` points at a directory
and each server writes its own `<server>.jsonl` inside it. That is not tidiness.
Appending is read-the-last-hash-then-write, and the lock around it is a threading
lock, which holds within one process and not between several — six servers are
six processes, and two answering at the same moment will both read the same
predecessor and both claim it. Measured, not theorised: six processes writing 150
lines to one file produced fourteen forks. `MCP_RECEIPT_LOG` still works and is
still correct for a single server; it is the wrong shape for a family.

`install.ps1` sets this up for all six and writes a README into the folder.

Verify one chain, or the whole folder:

```bash
semantic-scholar-mcp-ledger verify      receipts/semantic-scholar.jsonl
semantic-scholar-mcp-ledger verify-dir  receipts
semantic-scholar-mcp-ledger manifest    receipts        # writes receipts/manifest.json
```

`verify` exits non-zero on failure and says which kind it found: a **fork**
(concurrent writers — a configuration fault, and every line is still there), a
**missing** line, a **reordering**, or **tamper** (a line that does not hash to
its own content). Only the last is a claim about honesty, and reporting them
alike would invite a reader to mistake one for the other. The manifest is the
object to cite: one description of the whole deposit — per-file line counts,
first and last timestamps, terminal hashes, and combined totals by server,
script and session.

## Tests

```bash
.venv/bin/pip install pytest jsonschema
.venv/bin/python -m pytest -q tests
```

The suite runs against recorded Semantic Scholar responses under `tests/fixtures/` (captured 2026-09-04 without a key) and validates every envelope against `response-schema.json`; it needs no network and no key. `RUN_LIVE=1` adds one request to the live API.

## MCP SDK compatibility

Runs on both `mcp` 1.x and 2.x. Version 2.0.0 of the SDK removed
`mcp.server.fastmcp`; this server imports `FastMCP` where it exists and falls
back to `MCPServer` where it does not.

## License

MIT © 2026 Christopher Gerteis. Covers the server code only; it grants no
rights over Semantic Scholar, Allen Institute for AI data, which remains governed by that provider's
terms.

## Author

[Dr Christopher Gerteis](https://www.christophergerteis.net), SOAS University
of London.
