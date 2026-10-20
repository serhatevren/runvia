# Runvia

A self-hosted developer PaaS: connect a Git repository and Runvia builds a container image, runs it on Kubernetes, gives it a URL, and lets you manage it through an API, a dashboard and a CLI.

> **Security:** until sandboxed builds land (Phase 15), Runvia builds images with the host Docker daemon, which is equivalent to root on the host. Only deploy repositories you trust.

## Status

Phase 0 (Bootstrap) is in progress: backend skeleton, `GET /health/live` and request IDs are done. See the [engineering spec](runvia-engineering-spec.md) §23 for the roadmap to v1.0.

## Development

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/).

```bash
cd backend
uv sync
uv run uvicorn runvia.api.app:create_app --factory --reload
```

The API listens on `http://127.0.0.1:8000`; interactive docs are at `/docs`.

Quality checks (all must pass before a pull request is merged):

```bash
uv run ruff check
uv run ruff format --check
uv run mypy
uv run pytest
```

## Documentation

- [Engineering spec](runvia-engineering-spec.md): architecture, rules and roadmap.
- [Learning guide](runvia-learning-guide.md): study plan that accompanies each phase.
