# Runvia

A self-hosted developer PaaS: connect a Git repository and Runvia builds a container image, runs it on Kubernetes, gives it a URL, and lets you manage it through an API, a dashboard and a CLI.

> **Security:** until sandboxed builds land (Phase 15), Runvia builds images with the host Docker daemon, which is equivalent to root on the host. Only deploy repositories you trust.

## Status

Phase 0 (Bootstrap) is in progress: backend skeleton, `GET /health/live`, request IDs, pre-commit hooks and CI are done; JSON logging is next. See the [engineering spec](runvia-engineering-spec.md) §23 for the roadmap to v1.0.

## Development

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/) 0.12.

```bash
cd backend
uv sync
uv run pre-commit install
uv run uvicorn runvia.api.app:create_app --factory --reload
```

The API listens on `http://127.0.0.1:8000`; interactive docs are at `/docs`.

Quality checks (all must pass before a pull request is merged). `pre-commit install` runs them as Git hooks: file checks, Ruff and mypy on every commit, pytest on every push. CI runs the same checks on every pull request, and `main` accepts only pull requests with green CI.

```bash
uv run pre-commit run --all-files
uv run pytest
```

## Documentation

- [Engineering spec](runvia-engineering-spec.md): architecture, rules and roadmap.
- [Learning guide](runvia-learning-guide.md): study plan that accompanies each phase.
