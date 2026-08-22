# Changelog

Versions are the thing to cite. A count produced under one release is not
reproducible against another, so the release actually used should be named in
the text and, where a version DOI exists, cited by it.

Releases earlier than those below are on the repository's releases page; this
file begins where the record is precise enough to be worth writing down.

## 1.0.0 — 2026-08-22

First tagged release.

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
