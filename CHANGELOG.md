# Changelog

Versions are the thing to cite. A count produced under one release is not
reproducible against another, so the release actually used should be named in
the text and, where a version DOI exists, cited by it.

Releases earlier than those below are on the repository's releases page; this
file begins where the record is precise enough to be worth writing down.

## 2.0.0 — 2026-09-04

**Breaking: every tool now returns the family's JSON response envelope.** 1.x
returned formatted markdown. Any consumer that parsed that text must be
rewritten; the input models and tool names are unchanged.

- **Released on GitHub as a package.** `.github/workflows/release.yml` runs
  on a `vX.Y.Z` tag: tests on three OSes, wheel and sdist, one Claude
  Desktop `.mcpb` bundle per platform, then a GitHub release carrying all of
  them. Installable pinned to the tag with `pip install
  "git+https://github.com/ckgerteis/semantic-scholar-mcp@vX.Y.Z"` or `uvx --from`
  the same URL. The release is what fires the Zenodo webhook. Nothing is
  published to a package index.
- **Suite install.** `install.py` is the cross-platform port of `install.ps1`
  (Windows, macOS, Linux; same behaviour, importable). The family is also
  installable as one package, `bibliograph-mcp`, whose `bibliograph install`
  registers all six with one receipts folder.
- **`mediation.py` and `response-schema.json` vendored**, byte-identical to the
  copies in cinii-mcp, jstage-mcp, ndl-mcp, korea-scholarship-mcp and
  openalex-mcp. The README's claim that the family shares one envelope is now
  true of this server. Every response carries `searched_for` on term
  searches, a typed `query`, `matching_mode`, graduated `result.breadth`,
  per-item `matched_in`, typed diagnostics, a receipt and the attribution line.
- **Receipts go through `emit()`.** The per-request `ledger.record_request`
  call is gone; the envelope itself is deposited, and it reports
  `RECEIPT_NOT_DEPOSITED` or `RECEIPT_WRITE_FAILED` when a deposit did not
  happen. The 1.1.0 gap — batch and multi-seed recommendation receipts not
  recording which identifiers were asked for — is closed: the IDs are in
  `query.params` and so under the receipt hash.
- **Matching modes named for what the API does.** `relevance_ranked` for
  search, `filter_exact` for citation and authorship traversals,
  `identifier_lookup` for fetches and batch, `similarity_ranked` for the
  recommender.
- **A returned count is never passed off as a corpus count.** Endpoints that
  report no total (citations, references, an author's papers, batch,
  recommendations) set `result.total` to the returned count and raise
  `TOTAL_NOT_REPORTED`, saying whether a further page exists.
- **Titles typed by script**, since the API reports no language: kana or
  Hangul decide `ja` or `ko`, Latin goes to `en`, han-only stays untyped in
  `extra.title`.
- **Typed diagnostics** replace `"Error: …"` strings: `ZERO_RESULTS`,
  `PARTIAL_NOT_FOUND`, `NOT_FOUND`, `RATE_LIMITED`, `API_ERROR`,
  `TRANSPORT_ERROR`. A 200 whose body is not JSON is `API_ERROR` rather than
  an uncaught exception.
- **The rate limiter is now atomic.** 1.x read the last-request time, slept,
  and wrote it back with nothing held across the three steps, so two
  concurrent tool calls could both pass the check and fire together. An
  `asyncio.Lock` now spans check, sleep and request.
- httpx request logging is silenced, as in the rest of the family: the key
  travels in a header, but the search term travels in the URL.
- **Tests.** `tests/test_server.py` runs against recorded responses and
  validates every envelope against the schema. No network, no key.
- Known limit: the receipt's `result_ids` reads DOIs only, so a paper without
  one is fixed by the receipt hash and `extra.s2_paper_id` but not listed.
  Extending `make_receipt` is a family-wide schema change and is deferred.

## 1.1.0 — 2026-08-23

**Not released.** No tag was cut and no Zenodo record exists for this version, so
it is citable by commit alone. Tagging waits on confirmation that this
repository's Zenodo webhook is live: a release that mints nothing spends a
version number and returns nothing citable for it.

- **A receipts folder, and one chain per server.** `ledger.py` 1.1.0 adds
  `MCP_RECEIPT_DIR`: point it at a directory and each server writes its own
  `<server>.jsonl` inside it. `MCP_RECEIPT_LOG` still names a single file and is
  honoured when `MCP_RECEIPT_DIR` is unset, so nothing existing breaks.
- **Why, precisely.** Appending is read-the-last-hash-then-write and `_LOCK` is a
  `threading.Lock`, which holds within one process and not between several. Six
  servers are six processes. Six of them writing 150 lines to one file produced
  **fourteen forks** — two lines claiming the same predecessor, over and over.
  That was measured, not inferred, and it means the family's shared log was never
  safe to verify as one chain. One writer per file removes the race rather than
  mitigating it.
- **`verify_chain()` now types its failures.** It reported everything as
  `prev_hash mismatch`. It distinguishes a **fork** (concurrent writers; every
  line still present, and the file is several chains rather than one), a
  **missing** line, a **reordering**, and **tamper** (a line that does not hash to
  its own content). Only the last is a claim about honesty, and a reader given one
  label for all four cannot tell a misconfiguration from interference.
- **`verify_dir()` and a manifest.** One pass over a receipts folder returns
  per-file verdicts, line counts, first and last timestamps and terminal hashes,
  plus combined totals by server, script and session. `<dist>-ledger manifest
  <dir>` writes it to `manifest.json`. That file is what a disclosure cites: one
  description of the deposit rather than six assertions to reconcile.
- `<dist>-ledger` gains `verify-dir` and `manifest`, and `verify` now exits
  non-zero when a chain does not verify.
- **`install.ps1` installs this server by default, not the family.** These are
  six independent packages — none imports another, none depends on another, and
  each installs alone. The installer defaulted to all six, so cloning one
  repository and running it would have registered five servers nobody asked for
  and fetched them from GitHub. It now resolves the default from the repository
  it sits in; `-All` opts into the family and `-Servers` names a subset.
- The verification step now **asserts that `ledger.py` and `mediation.py` are
  byte-identical across everything it installed** and stops if they are not.
  Nothing else enforces that invariant at install time, and two envelope
  versions in one environment is precisely the sort of thing that would be found
  later, in a deposit.
- **`install.ps1` installs the family.** Vendored byte-identical into all six
  repositories: it installs any or all of the six into one environment, asks once
  for the receipts folder and the session slug, and registers every server against
  the same pair. It prefers a sibling checkout to the network, carries across
  credentials already registered rather than asking again, and stops rather than
  guessing where the registered servers disagree about either value.
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
