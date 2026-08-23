# semantic-scholar-mcp

MCP stdio server for the Semantic Scholar Academic Graph API.

Data via Semantic Scholar, Allen Institute for AI.

## What this is for

The Semantic Scholar Academic Graph, reached through citation traversal in both directions: the works a paper cites, and the works that went on to cite it. Look up as many as five hundred papers in a single call when a bibliography needs resolving.

The recommendation tools answer a question searching cannot: hand it two or three papers you already trust and it proposes adjacent work, which is how you enter a literature whose vocabulary you have not yet learned.

Records carry abstracts, influential-citation counts, open-access links, and machine-generated one-line summaries useful for triage. Where [`openalex-mcp`](https://github.com/ckgerteis/openalex-mcp) is strongest on institutions and geography, this is strongest on the shape of a citation network.

## Install

The package installs a `semantic-scholar-mcp` console script. It is namespaced, so it can
share one environment with the rest of this server family.

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

## Tools

| Tool |
| --- |
| `s2_author_papers` |
| `s2_batch_papers` |
| `s2_citations` |
| `s2_get_author` |
| `s2_get_paper` |
| `s2_recommend_multi` |
| `s2_recommend_single` |
| `s2_search_authors` |
| `s2_search_papers` |

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

**Changed in 1.1.0.** Earlier versions were registered by path —
`"command": "…\\python.exe", "args": ["…\\server.py"]`. That entry will not
start this version, because `server.py` is now a module inside a package rather
than a script beside its imports. Replace it with the console script above.

Restart Claude Desktop. The nine tools should appear under "semantic-scholar" in the
tool list.

## Query receipts

Every query can be deposited to an append-only, hash-chained JSONL log by
`semantic_scholar_mcp.ledger`. It is **off unless `MCP_RECEIPT_LOG` is set**, and a
logging failure is swallowed rather than raised — a search matters more than
the record of it. Secrets are redacted before a line is composed.

```
MCP_RECEIPT_LOG=C:\path\to\receipts.jsonl
MCP_RECEIPT_SESSION=project-or-article-slug
MCP_RECEIPT_STRICT=1        # optional: make logging failure raise
```

Verify a deposited log's hash chain:

```bash
semantic-scholar-mcp-ledger verify receipts.jsonl
```

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
