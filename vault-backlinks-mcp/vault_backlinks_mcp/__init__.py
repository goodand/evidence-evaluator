"""vault-backlinks-mcp: exact-path, live-only backlink lookup as an MCP tool.

Flat imports (`from registry import ...`), not package-relative, matching
`evidence-evaluator`'s convention -- see that package's `__init__.py` for the
same note. Add `vault_backlinks_mcp/` itself to `sys.path` and import
`registry`, `security`, `obsidian_backend`, `contracts`, `server` directly.
"""

__version__ = "0.1.0"
