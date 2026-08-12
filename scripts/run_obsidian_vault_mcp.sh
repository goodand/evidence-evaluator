#!/bin/sh
# stdio launcher for the evidence_evaluator.retrieval Obsidian vault MCP
# server (v0.1: vault_search / vault_read / vault_backlinks).
#
# No install is required to run this: `evidence_evaluator` is imported by
# running the module from inside this checkout, same as the tests do
# (tests/test_v01_tool_contract.py, tests/test_vault_retrieval_transports.py).
# `cd` into the repo first so that import works regardless of the caller's
# working directory -- an MCP client launches this from wherever the session
# started, not from here.
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$HERE"

: "${EVIDENCE_VAULT_ROOT:=/Users/jaehyuntak/Desktop/Project_in_progress}"
: "${EVIDENCE_VAULT_NAME:=Project_in_progress}"
export EVIDENCE_VAULT_ROOT EVIDENCE_VAULT_NAME

exec python3 -m evidence_evaluator.retrieval.mcp_server
