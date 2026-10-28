# Learning progress

## Current stage

**Stage 0: Bootstrap.** Done: project skeleton, `GET /health/live` + first test, request-ID middleware, quality-gate config (Ruff, mypy strict, pytest strict), pre-commit hooks + GitHub Actions CI + Dependabot. Next: turn on branch protection and watch CI block a failing PR, then JSON logging.

## Concepts covered

- [S0] Git tracks files, not folders; an empty folder does not survive a clone.
- [S0] Python package: a folder with `__init__.py`; `src/` layout keeps tests importing the installed package.
- [S0] `pyproject.toml` + `uv`: project metadata, virtual environment (`.venv`), lock file (`uv.lock`).
- [S0] Modular monolith vs microservices: one deployable, module boundaries; split only for a concrete reason (ADR).
- [S0] Monorepo layout: frontend/CLI talk to the backend only via the HTTP API (OpenAPI contract).
- [S0] `infra/` (runs Runvia itself) vs `examples/` (tenant app Runvia deploys): two pipelines, trust boundary.
- [S0] Dependency direction: `api/` and `worker/` depend on business modules and `core/`, never on each other.
- [S0] ASGI: FastAPI is the app (a callable), uvicorn is the server that owns the socket and calls it.
- [S0] App factory (`create_app()`), `APIRouter` + `include_router`, path operations; `/docs` is rendered from `/openapi.json`.
- [S0] Runtime vs dev dependency groups (`uv add` / `uv add --dev`); `TestClient` calls the app in-process, no network.
- [S0] Liveness checks no dependencies (avoids restart loops during a DB outage); readiness does (Stage 1).
- [S0] Pure ASGI middleware: wraps the app, intercepts `send` to add response headers on `http.response.start`.
- [S0] `contextvars`: per-request value, safe with concurrent requests; set + `reset(token)` in `finally`.
- [S0] Headers are untrusted input: validate before reuse/logging (`fullmatch`, charset + length).
- [S0] Quality gate: Ruff = linter (bug/style patterns) + formatter; mypy strict = types checked before the code runs; pytest strict = typos in markers/config fail.
- [S0] pre-commit: Git hooks run the gate before a commit (Ruff, mypy) or push (pytest); skippable with `--no-verify`, so CI is the real enforcement.
- [S0] One tool version source: hooks call `uv run --locked`, so hooks, CI and editor share the versions in `uv.lock`.
- [S0] CI on GitHub Actions: clean machine per PR; least-privilege token, actions pinned to commit SHAs; branch protection makes the checks required.
- [S0] Pydantic response model on a route → typed schema in `/openapi.json`, the contract clients are generated from.

## Weak spots

- Skeleton check-yourself questions were explained, not yet answered unaided. Re-quiz at the Stage 0 exit check.

## Open questions

- Unhandled exceptions return a 500 without `X-Request-ID` (Starlette's error middleware sits outside ours). Fix with the error envelope (Phase 2).
- httpx vs httpx2 for outbound calls: decide when the first outbound integration lands.
