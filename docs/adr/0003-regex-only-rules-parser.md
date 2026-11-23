# 0003: Rules parser is regex-only, with no LLM fallback

## Context
The build spec (Section 5.3) calls for a regex parser with a Claude Haiku fallback and cross-check. On 2026-11-23 the owner decided not to create an Anthropic API key.

## Decision
The rules parser is deterministic regex only. Any market the regex can't fully parse with every field present is marked `needs_review` and never traded. The `api_costs` table stays, for any paid API added later.

## Alternatives considered
- **Regex plus Haiku fallback (as specced).** Covers odd rule wording, but needs an API key and has a running cost. Declined by the owner.
- **Treat partial regex matches as tradable.** More markets covered, but risks trading on a wrong bucket or station. Rejected: an unparsed market costs nothing, while a misparsed one loses money.

## Consequences
Instead of an LLM second opinion, each parse is cross-checked against fields Kalshi publishes separately (milestone 3): `strike_type`/`floor_strike`/`cap_strike`, the title, the YES subtitle and the date in the event ticker. Each event's buckets must also cover every whole-degree reading exactly once. On 2026-11-23 all 288 live markets passed. Even so, there's no independent parser to catch a template the regex has never seen, so the regex gets tested on real rule texts from many cities and on deliberately odd wording. Coverage is reported every run: how many markets were parsed and how many went to `needs_review`. If coverage is poor, this decision gets revisited.

## Status
Accepted, 2026-11-23. Supersedes the LLM part of spec Section 5.3.
