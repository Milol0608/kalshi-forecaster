# 0002: Add database tables in the milestone that first uses them

## Context
The build spec lists 13 tables (Section 6). Milestone 1 needs Alembic working but no market data yet.

## Decision
The first migration creates only `runs`. Each later milestone adds its tables in its own migration, shaped by the real API responses it stores.

## Alternatives considered
- **Create all 13 tables now.** Columns would be guesses about Kalshi and Open-Meteo payloads we haven't fetched, and would need churn migrations later. Rejected.

## Consequences
The schema grows one migration per milestone. `alembic upgrade head` is the only setup step at any point.

## Status
Accepted, 2026-11-22.
