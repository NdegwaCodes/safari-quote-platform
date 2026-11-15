# Acacia Tours & Travel Platform

An API-first tour **sales & operations** platform — quotation, pricing, itinerary,
CRM, bookings, payments, operations — built so one backend eventually serves the
website, admin dashboard, client portal, and a future mobile app.

> Acacia Tours & Travel is a fictional company. Business names, suppliers, contact
> details and photographs in this repository are placeholders.

## Monorepo layout

```
apps/
  api/        FastAPI backend — the single backend for all clients (Python, uv)
  admin/      Next.js internal admin/sales dashboard
  web/        Next.js public website — destinations, properties, enquiries
  portal/     Next.js client portal — the trip, the statement, the proposal
packages/
  brand/          The palette + type roles, shared by the portal and the website
  api-client/     TS client generated from the API's OpenAPI schema
  ui/             Shared shadcn/ui components + Tailwind preset
  config-eslint/  Shared ESLint config
  config-tsconfig/Shared tsconfig bases
infra/          Docker & compose support files
docs/templates/ Blank rate-intake template the importer reads
```

## Prerequisites

- Docker + Docker Compose
- Node ≥ 20 and pnpm 10 (`corepack enable`)
- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- A Chromium-family browser, to print quotations to PDF. Found automatically in the
  usual places; set `PDF_BROWSER_PATH` to pin one, and `PDF_BROWSER_NO_SANDBOX=true`
  in a container. Without it the HTML document still renders and the PDF endpoint
  explains what is missing rather than failing obscurely.

## Quick start (Docker — backend)

```bash
cp .env.example .env        # then edit secrets
make up                     # db + redis + api
# API: http://localhost:8000/docs
```

The API container applies migrations and seeds the first superuser on startup.
`apps/admin`, `apps/web` and `apps/portal` are not in the compose stack — each
runs via `pnpm` (see their own Quick start sections below), so the Docker
stack is backend-only for now.

## Quick start (backend only, local)

```bash
cp .env.example .env        # set POSTGRES_HOST=localhost, REDIS_URL=redis://localhost:6379/0
make api-install            # uv sync
make migrate                # alembic upgrade head
make seed                   # permissions, roles, superuser
make api-dev                # uvicorn on :8000
```

## Quick start (admin app, local)

With the API running on `:8000`:

```bash
pnpm install
API_BASE_URL=http://localhost:8000 pnpm --filter @acacia/admin dev   # http://localhost:3000
```

Sign in with the seeded superuser (`FIRST_SUPERUSER_EMAIL` / `FIRST_SUPERUSER_PASSWORD`).
The admin talks to the API only through its server-side BFF (`/api/proxy/*`), so JWTs
live in httpOnly cookies and never touch browser JS. (A Docker image for the admin is
added in a later pass; for now run it with pnpm as above.)

## Quick start (client portal, local)

With the API running on `:8000`:

```bash
API_BASE_URL=http://localhost:8000 pnpm --filter @acacia/portal dev   # http://localhost:3001
```

There is nothing to sign in to. Issue a link from the admin — or
`POST /api/v1/bookings/{id}/portal-links` — and open the `url` it returns
once; the token is in the fragment, and the response is the only place it ever
appears. `PORTAL_BASE_URL` in the API's env is what that link points at, so it
has to match the port above.

## Quick start (public website, local)

With the API running on `:8000`:

```bash
API_BASE_URL=http://localhost:8000 SITE_URL=http://localhost:3002 \
  pnpm --filter @acacia/web dev            # http://localhost:3002
```

Nothing is on the site until somebody publishes it — `is_published` starts false on every
catalogue row. Publish one with `POST /api/v1/catalogue/destination/{id}/publish` (needs
`catalogue:publish`), and it appears within `REVALIDATE` seconds without a rebuild.

`SITE_URL` is the site's own public address, and it is read by machines rather than people:
canonical URLs, the sitemap and the structured data are all wrong together if it is wrong.

## Common commands

| Command | What it does |
| --- | --- |
| `make up` / `make down` | Start / stop the Docker stack |
| `make migrate` | Apply Alembic migrations |
| `make makemigration name="..."` | Autogenerate a migration |
| `make seed` | Seed permissions/roles/superuser |
| `make api-test` | Backend tests (pytest) |
| `make api-lint` / `make api-typecheck` | Ruff / mypy |
| `make web-dev` | Run frontend apps |

## Conventions (non-negotiable foundations)

- Business logic lives in backend **services**, never in routers or the frontend.
- Money is `NUMERIC`/`Decimal` **with a currency code** — never floats.
- Timestamps are UTC `TIMESTAMPTZ`; display timezone defaults to `Africa/Nairobi`.
- Nothing business-related is hard-coded — rates, fees, fuel, FX, markups, taxes,
  child-age rules all come from the DB / config / verified input / external API.
- Internal cost & margin are never serialized to client-facing roles.

## License

[MIT](LICENSE).
