# 0001: Gate 1 freshness comes from the timestamp inside the file

## Context
Live mode needs `gate1_passed.json` to be under 30 days old. "Age" can mean the file's mtime or a timestamp the gate checker writes into it.

## Decision
Use the `passed_at` field (ISO 8601, timezone required) that `scripts/gate_check.py` writes. The file must also record `"passed": true`. A missing timezone, a future timestamp, or an unparsable file all count as locked. `LiveExecutor` re-checks on every order, not only at startup.

## Alternatives considered
- **File mtime.** Simple, but copying, restoring from backup, or `touch` makes a stale pass look fresh. Rejected.
- **Check only at startup.** A long-running process would keep trading after the gate expired. Rejected.

## Consequences
A hand-edited `passed_at` can still fake freshness. The gate protects against accidents, not against the owner. Each refusal lists every failed condition so the reason is never a guess.

## Status
Accepted, 2026-11-22.
