# vault-backlinks-mcp

One MCP tool, `vault_backlinks`: exact-path, live-only "what links to this
file, right now" lookup for an Obsidian vault. Complements the existing
`vault_search` MCP tool (question-driven graph-walk search,
`.vault-harness/vault-md-retrieval/vault_retrieval_mcp_server.py` in the
source workspace, not touched or reimplemented here) rather than replacing
it — see `contracts.py`'s module docstring for the split.

## Why this exists, and why it is NOT the original design

An earlier design proposal
(`concept-gate-taxonomy/notes/audits/vault/correspondence/DESIGN_PROPOSAL_vault_backlinks_mcp_server_20260807.md`)
specified a dual-backend server: an always-available SQLite index, with the
Obsidian CLI as an optional live cross-check. An independent adversarial
review measured the indexed backend to be 3 days stale, to miss half of a
real file's backlinks (5 indexed vs 10 live), and to report an
already-resolved orphan as still orphaned — producing *confident, wrong*
answers, which the review judged worse than an honest failure. Verdict:
**DO-NOT-BUILD** the dual-backend design.

That review left one documented fallback: if a live-agent-facing tool is
still needed, build **live-only, with honest failure and no indexed
fallback**. This package is that fallback, built 2026-08-08 after
`evidence-evaluator` (sibling package, same workspace) demonstrated the
cross-agent need — "does a zero-context agent in another workspace/CLI
correctly find and cite sources" — that the DO-NOT-BUILD ruling had left
unconfirmed.

## What was measured before writing any code

The design proposal assumed a result schema (`source_path`, `link_count` as
int, `relation`, `authority_class`, `is_replica`) and a reliable `vault=`
CLI argument. Neither held up:

- **Real schema**: `obsidian backlinks vault=X path=Y counts format=json`
  returns `[{"file": "relative/path.md", "count": "1"}]` — `count` is a
  **string**. None of the proposal's other fields exist.
- **Exit code is always 0**, success or failure — errors are a plain-text
  `Error: ...` on stdout, not a nonzero return code.
- **Zero backlinks is the plain text `No backlinks found.`**, not `[]`.
- **`vault=` does not reliably scope the query, and `cwd` only sometimes
  helps.** Across repeated tests: a file that exists only in vault A,
  queried with `vault=B`, sometimes returned vault A's real data instead of
  "not found"; setting `cwd` to vault B's root sometimes then correctly
  reported "not found" for that same query, but a file that genuinely
  exists in vault B was, in a separate attempt, *also* reported "not found"
  right after a vault switch. A raw vault-switch attempt hung past 120
  seconds once and returned near-instantly on other attempts. This looks
  like IPC-mediated, latency-variable vault switching, not a single clean
  failure mode — see `obsidian_backend.py`'s module docstring for the exact
  sequence.

**Consequence for the design**: nothing this server gets back from the CLI
is trusted on the CLI's own say-so. Every returned backlink source path is
cross-checked against the target vault's own filesystem
(`security.exists_under_root`) before being kept; anything that doesn't
exist there is dropped and the response is flagged `review_required` with a
specific code, never silently folded into "zero backlinks" (`contracts.py`).
A real query against this server's own workspace surfaced this in production
almost immediately (see `dropped_out_of_scope` in a live example below) —
and a second real bug (a raw-string result from the CLI's non-JSON fallback
path crashing the dict-shaped parser) was only found by running an actual
query against a vault other than the primary one, not by unit tests with a
mocked backend alone. Trust what you run, not what you assume.

## Reuse, not a copy

`obsidian_backend.fetch_backlinks` imports `graph_for_candidate()` from the
source workspace's `.vault-harness/vault-md-retrieval/vault_md_harness.py` —
a protected, dirty worktree there, read-only, imported via `sys.path`
insertion rather than hand-copied (per that workspace's own rule against
duplicating code across trees). It reuses that function's retry-on-IPC-
failure logic and output parsing; it does **not** reuse anything from that
harness's SQLite index path, so the DO-NOT-BUILD finding about index
staleness does not apply here.

## Setup

```bash
pip install -e ".[dev]"
mkdir -p ~/.config/vault-backlinks-mcp
cp registry.example.json ~/.config/vault-backlinks-mcp/registry.json
# edit registry.json: vault_id -> {root, obsidian_vault_name} per vault you
# want this tool to answer for. vault_id is the only thing a caller ever
# supplies; absolute paths never appear in a tool call.
```

Registry contract: `{"contract_version": "vault-registry-v1", "vaults":
{"<vault_id>": {"root": "<absolute path>", "obsidian_vault_name": "<name
obsidian vaults verbose lists>"}}}`. Override the registry location with
`VAULT_BACKLINKS_REGISTRY=/path/to/registry.json`.

## Running

```bash
python3 vault_backlinks_mcp/server.py   # stdio MCP transport
```

Register with Claude Code / Codex the same way as any local stdio MCP
server (`mcpServers` config pointing `command`/`args` at this script and a
Python interpreter with `fastmcp` installed) — that registration step
touches global app config and was intentionally left for the user to do,
not performed by this build.

## Example (real call against this workspace, 2026-08-08)

```
vault_backlinks(vault_id="project-in-progress", path="CLAUDE.md")
```

returned 4 real backlinks with `dropped_out_of_scope: 0` (all four confirmed
present under the registered root) and a `BASENAME_COLLISION` review check
listing 11 other `CLAUDE.md` files across this workspace's worktrees — a
real, previously-known hazard this session had already run into by hand,
caught automatically here instead.

## Tests

```bash
python3 -m pytest tests/ -q
```

43 tests across four files. `test_security.py` exercises path/symlink/
collision checks directly against a `tmp_path` fixture vault.
`test_registry.py` exercises registry-file validation (malformed entries
must become `RegistryError`, never an uncaught exception). `test_contracts.py`
drives the full `query_backlinks()` pipeline with a fake `fetch_backlinks`
standing in for the *external* IPC call only — registry lookup, path safety,
the vault-root cross-check, and result shaping are this package's own code
and run for real. `test_obsidian_backend.py` exercises the actual CLI-command
construction and retry logic with a fake subprocess runner (`run_fn`), not a
faked-away `fetch_backlinks`.

**What none of these 43 tests cover**: the real `fastmcp` stdio registration
in `server.py`. `fastmcp` is not installed in the environment this suite has
been run in so far, so `@mcp.tool` registration, argument marshalling, and
the `readOnlyHint` annotation have only been read, never executed. If you
have `fastmcp` installed, running `python3 vault_backlinks_mcp/server.py`
and issuing a real `vault_backlinks` call is the only way to close that gap
today; no smoke test for it exists yet.

## What this does not do

- No indexed/cached backend, by design (see above).
- No multi-vault "switch and confirm" guarantee — see the measured `vault=`
  unreliability above. The safety property this server provides is "never
  silently return the wrong vault's data as if it were the right vault's",
  not "reliably force-switch to any registered vault on demand".
- Does not register itself in any Claude Code / Codex global MCP config.
- Does not touch `.vault-harness/` — read/import only.
