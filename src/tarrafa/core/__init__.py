"""Shared core for Tarrafa tools (envelope, writers, HTTP, crawl, doctor)."""

from tarrafa.core.envelope import JobEnvelope, build_envelope
from tarrafa.core.writers import utc_now_iso, write_json, write_jsonl

__all__ = [
    "JobEnvelope",
    "build_envelope",
    "utc_now_iso",
    "write_json",
    "write_jsonl",
]

# Submodules: config, runtime, run, workspace, summary, doctor, …
