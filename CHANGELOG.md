# Changelog

Versions are the thing to cite. A count produced under one release is not
reproducible against another, so the release actually used should be named in
the text and, where a version DOI exists, cited by it.

Releases earlier than those below are on the repository's releases page; this
file begins where the record is precise enough to be worth writing down.

## 1.1.0 — 2026-08-23

**Not released.** No tag was cut and no Zenodo record exists for this version, so
it is citable by commit alone. Tagging waits on confirmation that this
repository's Zenodo webhook is live: a release that mints nothing spends a
version number and returns nothing citable for it.

- **`src/` layout. Breaking: the server is started by console script, not by
  path.** `server.py` and `ledger.py` move to `src/semantic_scholar_mcp/` and install as a
  package. The flat layout installed them as *top-level* modules, so any two
  servers of this family in one environment overwrote each other — and
  `pip check` reported nothing wrong. The later install simply won, silently,
  and the survivor answered under the wrong server's name. All six now coexist:
  verified by installing every wheel into one environment and driving each
  through `initialize` and `tools/list`.
- **Claude Desktop entries must change.** Replace
  `"command": "…\\python.exe", "args": ["…\\server.py"]` with
  `"command": "…\\Scripts\\semantic-scholar-mcp.exe"`. An existing entry keeps working
  against an existing flat deployment and will fail against this one.
- `python -m semantic_scholar_mcp` and a `semantic-scholar-mcp-ledger` console script are installed
  alongside it.
- **The server reports its build.** `initialize` was answered with an empty
  `serverInfo.version`. It now carries `__version__` where the SDK accepts one
  (mcp 2.x `MCPServer`). Under mcp 1.x, whose `FastMCP` takes no `version`, the
  field still reports the SDK's version rather than the server's — the argument
  is passed only where it is accepted.
- The `[tool.hatch.build.targets.wheel]` comment claimed a `src` layout the
  repository did not have. It does now.

## 1.0.0 — 2026-08-22

**Never tagged.** This version was merged to `main` and no release was cut for
it; it has no tag and no DOI.

- MCP stdio server for the Semantic Scholar Academic Graph: papers, authors,
  citation traversal, batch lookup and recommendations, rate-limited to the
  1 RPS keyed allowance.
- Append-only, hash-chained query receipts via `ledger.py`, recorded from inside
  the HTTP helper. **Off unless `MCP_RECEIPT_LOG` is set**, and a logging
  failure is swallowed rather than raised.
- Runs on `mcp` 1.x and 2.x.

Two limits worth stating for anyone citing this as an instrument. It does not
vendor `mediation.py`, so its receipts carry no `searched_for` headline and no
typed envelope, and it has no equivalent of the `RECEIPT_NOT_DEPOSITED`
diagnostic the envelope servers gained in schema 2.3.0. And the batch and
recommendation tools send their payload as a JSON body rather than as query
parameters, so the receipt for those calls records the request without the list
of identifiers requested.
