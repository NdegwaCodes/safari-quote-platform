# Acacia Tours & Travel Platform — Claude context

API-first tour **sales & operations** platform (quotation → pricing → itinerary → CRM →
bookings → operations). One FastAPI backend serves admin, website, portal, and a future
mobile app.

Project overview, prerequisites, and the command table live in [README.md](README.md) —
read it rather than re-deriving setup here.

## Routing — where to look for what

| Task type | Start here |
|---|---|
| Setup, commands, local quick starts | [README.md](README.md) |
| A new CRUD catalogue module | [scripts/scaffold_module.py](scripts/scaffold_module.py) |
| Lint + typecheck + tests in one go | [scripts/verify.sh](scripts/verify.sh) |
| Rate-sheet import format | [docs/templates/rate-intake/hotel-rates.csv](docs/templates/rate-intake/hotel-rates.csv) |

## Key directories

```
apps/api/            FastAPI backend — the ONLY backend. Python 3.11+, uv, Alembic.
  app/core/          config, deps, security, ids (UUIDv7), errors, crud base, redis
  app/db/            session, base, seed (permissions/roles/superuser)
  app/api/v1/        router assembly + health; feature routes live in modules
  app/modules/<m>/   models.py schemas.py router.py service.py  ← the unit of work
  app/integrations/  external-provider seams (e.g. exchange_rate)
  alembic/           migrations
  tests/             pytest, one file per module
apps/admin/          Next.js admin dashboard; talks to the API only via its BFF (/api/proxy/*)
apps/web             Next.js public website
apps/portal          Next.js client portal
packages/            api-client (generated), brand, ui, shared eslint/tsconfig
scripts/             scaffold_module.py, verify.sh (lint + typecheck + tests)
```

## Non-negotiable conventions

- Business logic lives in backend **services**. Never in routers, never in the frontend.
- Money is `NUMERIC`/`Decimal` **plus a currency code** — never floats.
- Timestamps are UTC `TIMESTAMPTZ`; display timezone defaults to `Africa/Nairobi`.
- Nothing business-related is hard-coded: park fees, rates, fuel, FX, markups, taxes,
  child-age rules, vehicle consumption all come from DB / config / verified input / API.
- Internal cost & margin are a **schema-level** split, gated by permission
  (`quote:read_cost`). Client-facing roles get a price-only view.
- New tables get a UUIDv7 PK + timestamp mixins; new CRUD gets RBAC-guarded routes and
  seeded permissions.
- Verification before claiming done: `bash scripts/verify.sh` (ruff + mypy + pytest).

## Working habits for this repo

1. **Fix reliability structurally.** If something is repeatedly gotten wrong, add a helper,
   a lint, a test, or a fail-safe default — not another warning sentence here.
2. **Structural over prose.** Prefer a table or a JSON spec (see the scaffolder) over a
   paragraph.
3. **Migrations are verified, not trusted.** After autogenerate, run `alembic check` and read
   the diff — autogenerate silently drops some constructs.
