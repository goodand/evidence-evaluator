#!/usr/bin/env python3
"""Provider adapters: turn a prompt into a validated JSON payload from a
fresh, sandboxed subject process -- for the Claude CLI and for the Codex CLI
via a single stdio MCP tool bridge.

Extracted from `_providers.py` in the source experiment (see package README).
This is the part of the source experiment that already worked across two
different agent CLIs, which is why it is the core of this package: the
runner owns the corpus, the guard, the action trace, and the judge; a
provider adapter owns exactly one thing -- turning a prompt into a validated
JSON payload from a fresh, sandboxed subject process. Nothing here may touch
the corpus, gold, evaluator, action set, BudgetGuard, the four-key
retrieval-subagent contract, the public bundle, or the host-owned trace.

WHY A SECOND SEATBELT PROFILE EXISTS
-------------------------------------
A `(allow default)` + repo-and-control-root-deny profile (v1) is not enough on
macOS: everything ELSE on the machine is still readable, and some of that
"elsewhere" carries answers -- prior session transcripts
(`~/.claude/projects/*.jsonl`, `~/.codex/`), which can contain corpus text and
gold structures printed during earlier work. v2 (`seatbelt_profile_v2`) adds
explicit denies for those channels. This is macOS-specific (`sandbox-exec`);
port the deny-list concept to your platform's process sandbox if you are not
on macOS.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

# Tools a retrieval subject must never have: they would bypass the host
# client and make the action trace incomplete rather than wrong -- which is
# worse, because an incomplete trace still scores.
CLAUDE_DENIED_TOOLS = (
    "Read", "Glob", "Grep", "WebFetch", "WebSearch", "Task", "Agent",
    "Edit", "Write", "NotebookEdit", "TodoWrite",
)

# OAuth remains available to the Codex parent process. These switches remove
# every model-facing capability other than the explicitly configured MCP tool.
CODEX_MCP_DISABLED_FEATURES = (
    "apps", "browser_use", "browser_use_external", "code_mode",
    "computer_use", "image_generation", "multi_agent", "multi_agent_v2",
    "shell_tool", "unified_exec",
)
_TRANSIENT_PROVIDER_KEYS = frozenset(("session_id", "thread_id"))


class ProviderError(RuntimeError):
    """A provider failed to produce a usable payload. Map to your own
    'invalid run' failure code upstream (V1 in the reference contract)."""

    def __init__(self, message: str, *, raw: str = "",
                 provider_meta: dict[str, Any] | None = None):
        super().__init__(message)
        self.raw = raw
        self.provider_meta = provider_meta or {}


def _remove_transient_keys(value: Any) -> Any:
    """Remove run-local provider identifiers before a raw transcript is saved."""
    if isinstance(value, dict):
        return {key: _remove_transient_keys(item) for key, item in value.items()
                if key not in _TRANSIENT_PROVIDER_KEYS}
    if isinstance(value, list):
        return [_remove_transient_keys(item) for item in value]
    return value


def sanitize_provider_raw(raw: str) -> str:
    """Preserve JSONL diagnostics while excluding transient provider session IDs."""
    out: list[str] = []
    for line in raw.splitlines():
        try:
            decoded = json.loads(line)
        except json.JSONDecodeError:
            out.append(line)
        else:
            out.append(json.dumps(_remove_transient_keys(decoded), ensure_ascii=False,
                                  separators=(",", ":")))
    return "\n".join(out)


def _codex_event_summary(
    raw: str,
    allowed_mcp_tools: frozenset[str] = frozenset({"handoff_action"}),
) -> dict[str, Any]:
    """Reject any native tool event except the one host-owned MCP action tool.

    The checker is deliberately fail-closed for a reported tool event.
    Ordinary lifecycle and message events remain allowed; host action counts
    separately prove that the MCP bridge was actually used.
    """
    seen: list[str] = []
    mcp_tools: list[str] = []
    failed_mcp_tools: list[str] = []
    forbidden: list[str] = []
    for line in raw.split("\n-- STDERR --\n", 1)[0].splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("item") if isinstance(event, dict) else None
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if not isinstance(item_type, str):
            continue
        seen.append(item_type)
        lowered = item_type.lower()
        if item_type == "command_execution" or any(token in lowered for token in (
                "file_change", "browser", "computer", "web_search")):
            forbidden.append(item_type)
            continue
        if "mcp" not in lowered:
            if "tool" in lowered:
                forbidden.append(item_type)
            continue
        names = [item.get(key) for key in ("tool", "tool_name", "name")]
        names = [name for name in names if isinstance(name, str)]
        if len(names) != 1 or names[0] not in allowed_mcp_tools:
            forbidden.append(f"{item_type}:{names or 'unnamed'}")
        elif event.get("type") in {None, "item.completed"}:
            # Codex emits started and completed envelopes for one MCP call.
            # Count only the completion; the server audit also records once.
            if item.get("status") == "failed" or item.get("error"):
                failed_mcp_tools.extend(names)
            else:
                mcp_tools.extend(names)
    if forbidden:
        raise ProviderError(
            f"Codex emitted a forbidden or unrecognized tool event: {sorted(set(forbidden))}",
            provider_meta={"provider": "codex-mcp-cli", "tool_event_summary": {
                "event_types": sorted(set(seen)), "mcp_tools": mcp_tools,
                "failed_mcp_tools": failed_mcp_tools,
                "forbidden": sorted(set(forbidden))}})
    return {"event_types": sorted(set(seen)), "mcp_tools": mcp_tools,
            "failed_mcp_tools": failed_mcp_tools, "forbidden": []}


# --------------------------------------------------------------------------
# sandbox (macOS Seatbelt)
# --------------------------------------------------------------------------
def home_leak_denies() -> list[str]:
    """Paths outside the repository that carry prior-session content."""
    home = Path.home()
    return [
        str(home / ".claude" / "projects"),
        str(home / ".claude" / "todos"),
        str(home / ".claude" / "shell-snapshots"),
        str(home / ".claude" / "history.jsonl"),
        str(home / ".codex"),
        str(home / "Library" / "Application Support" / "Claude"),
    ]


def seatbelt_profile_v2(project_root: Path, host_control: Path,
                        *, extra_denies: list[str] | None = None) -> str:
    """v1 plus the home-directory transcript channels.

    `~/.claude.json` is deliberately NOT denied: the CLI reads it to resolve
    the logged-in account, and denying it stops the subject from starting at
    all. Its account/config and project-path metadata therefore remain
    reachable -- an accepted, documented residual risk, not an oversight.
    """
    lines = ["(version 1)", "(allow default)"]
    for path in [str(project_root), str(host_control), *home_leak_denies(),
                 *(extra_denies or [])]:
        lines.append(f'(deny file-read* (subpath "{path}"))')
        lines.append(f'(deny file-write* (subpath "{path}"))')
    return "\n".join(lines)


# --------------------------------------------------------------------------
# minimal JSON-schema check (neither CLI has a full --output-schema validator)
# --------------------------------------------------------------------------
# JSON-schema keywords this validator actually implements. Anything else is
# refused rather than ignored -- see validate_against_schema's docstring.
_SUPPORTED_SCHEMA_KEYWORDS = frozenset({
    "type", "required", "properties", "additionalProperties", "items",
    "minLength", "minimum", "const", "enum",
    # Annotations that carry no constraint; safe to ignore.
    "description", "title", "$schema", "default", "examples",
})


def validate_against_schema(payload: Any, schema: dict, path: str = "$") -> None:
    """Validate the JSON-schema subset this package implements.

    Deliberately NOT a general JSON-schema validator. It refuses schemas it
    cannot enforce instead of passing them, because the alternative is a
    validator that reports success for constraints it never checked --
    indistinguishable from real validation at the call site.

    Reproduced before this guard existed (adversarial review finding #10,
    2026-08-09): a node with no `type` key, e.g.
    `{"oneOf": [{"type": "object", "required": ["answer_text"]}]}`, fell
    through every branch, so `{"totally": "wrong"}` validated clean. Any
    provider response shaped by `oneOf`/`anyOf`/`allOf`/`$ref`/`not` was
    being accepted unchecked.

    If you need those keywords, implement them here or validate with a real
    JSON-schema library -- do not remove this check.
    """
    unsupported = sorted(set(schema) - _SUPPORTED_SCHEMA_KEYWORDS)
    if unsupported:
        raise ProviderError(
            f"{path}: schema uses keyword(s) this validator does not "
            f"implement: {unsupported}. Refusing rather than reporting a "
            f"pass it did not verify.")

    kind = schema.get("type")
    if kind is None and not ({"const", "enum"} & set(schema)):
        raise ProviderError(
            f"{path}: schema node has no 'type', 'const', or 'enum' -- "
            f"nothing to validate against, and silently accepting it would "
            f"mean this call verified nothing.")

    if kind == "object":
        if not isinstance(payload, dict):
            raise ProviderError(f"{path}: expected object, got {type(payload).__name__}")
        for key in schema.get("required", []):
            if key not in payload:
                raise ProviderError(f"{path}: missing required key {key!r}")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = sorted(set(payload) - set(props))
            if extra:
                raise ProviderError(f"{path}: unexpected key(s) {extra}")
        for key, sub in props.items():
            if key in payload:
                validate_against_schema(payload[key], sub, f"{path}.{key}")
    elif kind == "array":
        if not isinstance(payload, list):
            raise ProviderError(f"{path}: expected array")
        if "items" in schema:
            for i, item in enumerate(payload):
                validate_against_schema(item, schema["items"], f"{path}[{i}]")
    elif kind == "string":
        if not isinstance(payload, str):
            raise ProviderError(f"{path}: expected string")
        if len(payload) < schema.get("minLength", 0):
            raise ProviderError(f"{path}: shorter than minLength")
    elif kind == "boolean":
        if not isinstance(payload, bool):
            raise ProviderError(f"{path}: expected boolean")
    elif kind == "integer":
        if not isinstance(payload, int) or isinstance(payload, bool):
            raise ProviderError(f"{path}: expected integer")
        if "minimum" in schema and payload < schema["minimum"]:
            raise ProviderError(f"{path}: below minimum {schema['minimum']}")
    if "const" in schema and payload != schema["const"]:
        raise ProviderError(f"{path}: {payload!r} does not equal const {schema['const']!r}")
    if "enum" in schema and payload not in schema["enum"]:
        raise ProviderError(f"{path}: {payload!r} not in {schema['enum']}")


_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)


def _decoded_objects(text: str) -> list[dict[str, Any]]:
    """Decode objects without treating braces inside JSON strings as syntax."""
    decoder = json.JSONDecoder()
    found: list[dict[str, Any]] = []
    cursor = 0
    while cursor < len(text):
        index = text.find("{", cursor)
        if index < 0:
            break
        try:
            value, consumed = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            cursor = index + 1
            continue
        if isinstance(value, dict):
            found.append(value)
            cursor = index + consumed
        else:
            cursor = index + 1
    return found


def extract_json_object(text: str) -> dict:
    """Pull the final JSON object out of a model's prose.

    Codex is given `--output-schema` and writes the object to a file. The
    Claude CLI has no such flag, so the object arrives inside `result` as
    text and the adapter must find it. Preferring the LAST fenced block, then
    the last balanced object, matches how a model that reasons then answers
    actually formats a reply.
    """
    blocks = _FENCE.findall(text or "")
    fenced = [obj for block in blocks for obj in _decoded_objects(block)]
    if fenced:
        return fenced[-1]
    objects = _decoded_objects(text or "")
    if objects:
        return objects[-1]
    raise ProviderError("no JSON object found in the subject's final message")


def payload_from_claude_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    """Prefer the CLI's native structured output; retain prose fallback."""
    structured = envelope.get("structured_output")
    if isinstance(structured, dict):
        return structured
    return extract_json_object(envelope.get("result", ""))


def claude_cli_schema(schema_path: Path) -> dict[str, Any]:
    """Remove only the draft URI unsupported by Claude CLI's schema parser."""
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema.pop("$schema", None)
    return schema


# --------------------------------------------------------------------------
# claude-cli adapter
# --------------------------------------------------------------------------
def claude_command(claude: str, sandbox: str, profile: str, subject: Path,
                   schema_path: Path, config: dict[str, Any],
                   session_id: str) -> list[str]:
    """Built separately from execution so tests can assert on it without
    calling a model."""
    return [
        sandbox, "-p", profile, claude, "--print",
        "--output-format", "json",
        "--json-schema", json.dumps(
            claude_cli_schema(schema_path), separators=(",", ":")),
        "--model", config["model"],
        "--max-turns", str(config.get("max_turns", 40)),
        # A fresh subject per run. No session is written, so none can be
        # resumed; the id is unique so nothing is joined to a prior run.
        "--no-session-persistence",
        "--session-id", session_id,
        # No user/project/local settings and no CLAUDE.md: the workspace's
        # own instructions would otherwise become part of the subject's
        # prompt -- exactly the coupling this package exists to remove.
        "--setting-sources", "",
        "--safe-mode", "--disable-slash-commands", "--no-chrome",
        "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
        # The host client is the only evidence channel. Bash is required to
        # run it; every other retrieval tool is blocked so a read cannot
        # happen off the trace.
        "--tools", "Bash", "--allowedTools", "Bash",
        "--disallowedTools", *CLAUDE_DENIED_TOOLS,
        # The surrounding Seatbelt profile is the OS boundary, exactly as
        # with Codex. This flag only removes the interactive approval prompt.
        "--dangerously-skip-permissions",
        "--add-dir", str(subject),
    ]


def run_claude_cli(subject: Path, socket_path: Path, prompt: str, schema_name: str,
                   config: dict[str, Any], *, project_root: Path, host_control: Path,
                   run_name: str) -> dict[str, Any]:
    """Same signature and return shape as `run_codex_mcp_cli`, so
    `resolve_provider` can swap them without the caller changing."""
    claude = shutil.which("claude")
    sandbox = Path("/usr/bin/sandbox-exec")
    if not claude or not sandbox.is_file():
        raise ProviderError("Claude CLI or macOS sandbox-exec is unavailable")
    run_dir = subject / "run"
    run_dir.mkdir(exist_ok=True)
    raw_path = run_dir / f"{run_name}.jsonl"
    output_path = run_dir / f"{run_name}.json"
    schema_path = subject / schema_name
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    session_id = str(uuid.uuid4())
    profile = seatbelt_profile_v2(project_root, host_control)
    command = claude_command(claude, str(sandbox), profile, subject, schema_path,
                             config, session_id)

    env = dict(os.environ)
    env["HANDOFF_LIVE_TOOL_SOCKET"] = str(socket_path)
    # The CLI cannot see the workspace anyway (Seatbelt), but an inherited
    # CLAUDE_CODE_* var could still change behaviour between cells.
    for key in [k for k in env if k.startswith("CLAUDE_CODE_")]:
        env.pop(key)

    started = time.perf_counter()
    try:
        proc = subprocess.run(command, input=prompt, text=True, capture_output=True,
                              env=env, cwd=subject,
                              timeout=config["timeout_seconds"], check=False)
    except subprocess.TimeoutExpired as exc:
        raw = sanitize_provider_raw((exc.stdout or "") + "\n-- STDERR --\n" +
                                    (exc.stderr or ""))
        raw_path.write_text(raw, encoding="utf-8")
        raise ProviderError(
            f"Claude CLI timed out after {config['timeout_seconds']} seconds", raw=raw) from exc

    raw = sanitize_provider_raw(proc.stdout + "\n-- STDERR --\n" + proc.stderr)
    raw_path.write_text(raw, encoding="utf-8")
    if proc.returncode != 0:
        tail = ("stdout=" + proc.stdout[-1200:] + " stderr=" + proc.stderr[-1200:]).strip()
        raise ProviderError(f"Claude CLI exited {proc.returncode}: {tail}", raw=raw)
    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise ProviderError(f"Claude CLI envelope is not JSON: {exc}", raw=raw) from exc
    if envelope.get("is_error"):
        raise ProviderError(f"Claude CLI reported an error: "
                            f"{str(envelope.get('result'))[:300]}", raw=raw)

    provider_meta = {"provider": "claude-cli", "cost_usd": envelope.get("total_cost_usd"),
                     "num_turns": envelope.get("num_turns"),
                     "sandbox_profile": "v2",
                     "structured_output": isinstance(
                         envelope.get("structured_output"), dict)}
    try:
        payload = payload_from_claude_envelope(envelope)
        # Native schema enforcement is primary. Revalidation protects against
        # CLI regressions and keeps provider artifacts comparable over time.
        validate_against_schema(payload, schema)
    except ProviderError as exc:
        raise ProviderError(str(exc), raw=raw, provider_meta=provider_meta) from exc
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    return {"payload": payload, "raw": raw_path.read_text(encoding="utf-8"),
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "provider_meta": provider_meta}


# --------------------------------------------------------------------------
# Codex CLI with exactly one stdio MCP action bridge
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class CodexMcpServerSpec:
    """One model-visible stdio MCP server and its complete tool allowlist."""

    name: str
    command: str
    args: tuple[str, ...]
    env: dict[str, str]
    enabled_tools: tuple[str, ...]

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", self.name):
            raise ProviderError(f"invalid MCP server name: {self.name!r}")
        if not self.command or not self.enabled_tools:
            raise ProviderError("MCP command and enabled_tools must not be empty")


def codex_external_mcp_command(
    codex: str,
    subject: Path,
    schema_path: Path,
    output_path: Path,
    config: dict[str, Any],
    server: CodexMcpServerSpec,
) -> list[str]:
    """Build a Codex command exposing only one allowlisted stdio MCP server."""
    prefix = f"mcp_servers.{server.name}"
    invalid_env_keys = [
        key for key in server.env if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)
    ]
    if invalid_env_keys:
        raise ProviderError(f"invalid MCP environment key(s): {invalid_env_keys}")
    env_table = "{ " + ", ".join(
        f"{key} = {json.dumps(value)}" for key, value in server.env.items()
    ) + " }"
    overrides = (
        f"{prefix}.command={json.dumps(server.command)}",
        f"{prefix}.args={json.dumps(list(server.args))}",
        f"{prefix}.env={env_table}",
        f"{prefix}.enabled_tools={json.dumps(list(server.enabled_tools))}",
    )
    command = [
        codex, "exec", "--ephemeral", "--skip-git-repo-check",
        "--ignore-user-config", "--ignore-rules",
        "-C", str(subject), "-m", config["model"], "-c",
        f'model_reasoning_effort={json.dumps(config["reasoning_effort"])}',
        "-c", f'approval_policy={json.dumps(config.get("approval_policy", "on-request"))}',
    ]
    if config.get("auto_approve_mcp") is True:
        command.append("--approve-for-me")
    else:
        command.extend(("--sandbox", "read-only"))
    for override in overrides:
        command.extend(("-c", override))
    for feature in CODEX_MCP_DISABLED_FEATURES:
        command.extend(("--disable", feature))
    return command + [
        "--output-schema", str(schema_path), "--output-last-message", str(output_path),
        "--json", "-",
    ]


def codex_mcp_command(codex: str, subject: Path, socket_path: Path,
                      schema_path: Path, output_path: Path,
                      config: dict[str, Any], *,
                      bridge_script: Path | None = None) -> list[str]:
    """Build a Codex command where OAuth is parent-only and tools are closed.

    `bridge_script` defaults to `mcp_bridge.py` shipped next to this module
    (see `subject_tool.request` / `mcp_bridge.py`); pass your own if you
    have a different action surface.
    """
    server = bridge_script or (Path(__file__).resolve().parent / "mcp_bridge.py")
    return codex_external_mcp_command(
        codex,
        subject,
        schema_path,
        output_path,
        config,
        CodexMcpServerSpec(
            name="handoff",
            command=sys.executable,
            args=(str(server),),
            env={"HANDOFF_LIVE_TOOL_SOCKET": str(socket_path)},
            enabled_tools=("handoff_action",),
        ),
    )


def run_codex_external_mcp_cli(
    subject: Path,
    prompt: str,
    schema_path: Path,
    config: dict[str, Any],
    *,
    server: CodexMcpServerSpec,
    run_name: str,
) -> dict[str, Any]:
    """Run a fresh Codex subject with only ``server.enabled_tools`` visible."""
    codex = shutil.which("codex")
    if not codex:
        raise ProviderError("Codex CLI is unavailable")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    run_dir = subject / "run"
    run_dir.mkdir(exist_ok=True)
    output_path = run_dir / f"{run_name}.json"
    raw_path = run_dir / f"{run_name}.jsonl"
    command = codex_external_mcp_command(
        codex, subject, schema_path, output_path, config, server
    )
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            command,
            input=prompt,
            text=True,
            capture_output=True,
            env=dict(os.environ),
            cwd=subject,
            timeout=config["timeout_seconds"],
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raw = sanitize_provider_raw(
            (exc.stdout or "") + "\n-- STDERR --\n" + (exc.stderr or "")
        )
        raw_path.write_text(raw, encoding="utf-8")
        raise ProviderError(
            f"Codex MCP CLI timed out after {config['timeout_seconds']} seconds",
            raw=raw,
        ) from exc
    raw = sanitize_provider_raw(proc.stdout + "\n-- STDERR --\n" + proc.stderr)
    raw_path.write_text(raw, encoding="utf-8")
    allowed = frozenset(server.enabled_tools)
    event_summary = _codex_event_summary(raw, allowed)
    if proc.returncode != 0:
        tail = ("stdout=" + proc.stdout[-1200:] + " stderr=" + proc.stderr[-1200:]).strip()
        raise ProviderError(f"Codex MCP CLI exited {proc.returncode}: {tail}", raw=raw)
    if not output_path.is_file():
        raise ProviderError("Codex MCP CLI did not produce a final JSON response", raw=raw)
    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        validate_against_schema(payload, schema)
    except (json.JSONDecodeError, ProviderError) as exc:
        raise ProviderError(f"Codex MCP final response is invalid: {exc}", raw=raw) from exc
    return {
        "payload": payload,
        "raw": raw,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "provider_meta": {
            "provider": "codex-external-mcp-cli",
            "tool_policy": "single-stdio-mcp-allowlist-v1",
            "auth_boundary": "codex-parent-oauth-only",
            "server": server.name,
            "enabled_tools": list(server.enabled_tools),
            "tool_event_summary": event_summary,
        },
    }


def run_codex_mcp_cli(subject: Path, socket_path: Path, prompt: str, schema_name: str,
                      config: dict[str, Any], *, project_root: Path,
                      host_control: Path, run_name: str) -> dict[str, Any]:
    """Run Codex without model shell/file tools; only ``handoff_action`` exists.

    Do not put the Codex parent under Seatbelt. The parent needs its own
    OAuth credentials to start. Capability isolation is instead explicit in
    the CLI feature set and the sole stdio MCP server; its event stream is
    checked before the response is accepted.
    """
    del project_root, host_control  # The parent must retain OAuth access.
    codex = shutil.which("codex")
    if not codex:
        raise ProviderError("Codex CLI is unavailable")
    try:
        import fastmcp  # noqa: F401  # runner interpreter must start the bridge
    except ImportError as exc:
        raise ProviderError("FastMCP is not installed for the runner interpreter") from exc
    run_dir = subject / "run"
    run_dir.mkdir(exist_ok=True)
    output_path = run_dir / f"{run_name}.json"
    raw_path = run_dir / f"{run_name}.jsonl"
    schema_path = subject / schema_name
    command = codex_mcp_command(codex, subject, socket_path, schema_path, output_path, config)
    env = dict(os.environ)
    env["HANDOFF_LIVE_TOOL_SOCKET"] = str(socket_path)
    started = time.perf_counter()
    try:
        proc = subprocess.run(command, input=prompt, text=True, capture_output=True,
                              env=env, cwd=subject,
                              timeout=config["timeout_seconds"], check=False)
    except subprocess.TimeoutExpired as exc:
        raw = sanitize_provider_raw((exc.stdout or "") + "\n-- STDERR --\n" +
                                    (exc.stderr or ""))
        raw_path.write_text(raw, encoding="utf-8")
        raise ProviderError(
            f"Codex MCP CLI timed out after {config['timeout_seconds']} seconds", raw=raw) from exc
    raw = sanitize_provider_raw(proc.stdout + "\n-- STDERR --\n" + proc.stderr)
    raw_path.write_text(raw, encoding="utf-8")
    if proc.returncode != 0:
        tail = ("stdout=" + proc.stdout[-1200:] + " stderr=" + proc.stderr[-1200:]).strip()
        raise ProviderError(f"Codex MCP CLI exited {proc.returncode}: {tail}", raw=raw)
    event_summary = _codex_event_summary(raw)
    if not output_path.is_file():
        raise ProviderError("Codex MCP CLI did not produce a final JSON response", raw=raw,
                            provider_meta={"provider": "codex-mcp-cli",
                                           "tool_event_summary": event_summary})
    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProviderError(f"Codex MCP final response is not JSON: {exc}", raw=raw) from exc
    return {"payload": payload, "raw": raw,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "provider_meta": {
                "provider": "codex-mcp-cli",
                "tool_policy": "single-stdio-mcp-handoff_action-v1",
                "auth_boundary": "codex-parent-oauth-only",
                "tool_event_summary": event_summary,
            }}


# --------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------
def resolve_provider(config: dict[str, Any],
                     codex_impl: Callable[..., dict[str, Any]] | None = None
                     ) -> Callable[..., dict[str, Any]]:
    """Pick the adapter named by `config["provider"]`.

    `codex_impl` lets you register your own bare-Codex-CLI adapter (no MCP
    bridge) without this module importing it -- pass your own callable, or
    omit it if you only use `claude-cli` / `codex-mcp-cli`.
    """
    name = config.get("provider")
    if name == "codex-cli":
        if codex_impl is None:
            raise ProviderError("provider 'codex-cli' requires codex_impl to be supplied")
        return codex_impl
    if name == "claude-cli":
        return run_claude_cli
    if name == "codex-mcp-cli":
        return run_codex_mcp_cli
    raise ProviderError(f"unknown provider: {name!r}")
