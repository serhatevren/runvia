# Runvia — Engineering Specification

> **Runvia** is a self-hosted developer PaaS (a small Render/Railway/Heroku): connect a Git repository and it builds a container image, runs it on Kubernetes, gives it a URL, and lets you manage it through an API, a dashboard and a CLI.
>
> This document is the source of truth for **what to build and the rules to build it by**, for the developer and for coding agents. The [learning guide](runvia-learning-guide.md) covers what to study along the way; it never changes what gets built.
>
> **Standard:** Runvia is built as a production product. Every choice here is one a professional team would ship, and the developer learning along the way never lowers that bar.
>
> Guiding rule: **build one thing completely before adding the next abstraction.**

---

## 1. Product

### 1.1 Core flow

```text
Deploy clicked ─► API: validate, insert deployment row, enqueue job, return 202
                   └─► worker: resolve SHA → clone → docker build → push (digest)
                        └─► worker: apply Kubernetes resources → wait for rollout → SUCCEEDED | FAILED
User sees: URL · status · build & runtime logs · history · metrics · rollback
```

Runvia is the **control plane**. It stores desired state, authenticates and authorizes requests, runs builds and deployments, tracks their state, and reports it. GitHub (source), Docker/BuildKit (builds) and Kubernetes (scheduling) are external systems that Runvia drives. Never reimplement them.

### 1.2 Scope

| | Features |
|---|---|
| **MVP** (milestone: local, no cloud, trusted repos) | register/login · organizations, members, roles · application CRUD · public GitHub repo + branch · Dockerfile builds · env vars & secrets · manual deploy (latest or a specific commit) · status & history · build + runtime logs · app URL · cancel, rollback, restart · replicas, CPU/memory, health-check path · runtime status & basic metrics · audit log · delete app · dashboard |
| **v1.0** (production-ready: the definition of done) | everything in the MVP, plus: deploy-on-push webhooks · GitHub App (private repos, commit statuses) · outbox, reconciler, idempotency keys · sandboxed builds (rootless BuildKit in ephemeral Jobs) · metrics, tracing, dashboards, alerts · persisted runtime logs · AWS via Terraform · HTTPS + wildcard DNS · CI/CD with promotion · email verification + password reset · API keys + Go CLI · custom domains with automatic TLS |
| **Extensions** (after v1.0, each with an ADR) | preview environments · blue/green · canary · HPA autoscaling · chaos experiments · SQS adapter (only if a deployment target needs it) |
| **Non-goals** | own Git hosting, container runtime or scheduler · buildpacks / language auto-detection · billing · multi-region · service mesh · tenant shell access · building **untrusted** code without a sandbox · splitting out services without a concrete reason (§2) |

---

## 2. Principles

1. **Local-first.** Everything runs on a laptop with no paid services. AWS is just another environment (mapping below).
2. **Modular monolith + workers.** One Python codebase and two processes (API and worker), with explicit module boundaries. Split out a service only for a concrete reason, and record it in an ADR.
3. **Long work is asynchronous.** Handlers validate, write to the DB, enqueue and return `202`. Only workers clone, build, push and deploy.
4. **PostgreSQL is the source of truth.** Redis and the broker hold only derived, in-flight or loss-tolerant data. Invariants are DB constraints, not just code.
5. **Explicit state machines.** Status is persisted and transitions are validated. Status is never inferred from logs.
6. **Everything is retry-safe.** Any job may run twice and must still reach the same result (terminal-state checks, conditional updates, declarative apply).
7. **Immutable artifacts.** Deploy commit SHAs and image digests, never branch names or `latest`.
8. **Thin adapters.** Infrastructure sits behind small interfaces (§16), so local and cloud share logic. No plugin frameworks.

| Concern | Local | AWS |
|---|---|---|
| Kubernetes | k3d (k3s in Docker) | EC2 + k3s (cheap) → EKS |
| Ingress / TLS | Traefik (bundled with k3s) | AWS Load Balancer Controller + ALB (or NLB → Traefik); ACM / cert-manager |
| Registry | k3d-managed registry | ECR |
| Database / cache | PostgreSQL, Redis containers | RDS, ElastiCache (or in-cluster Redis) |
| Queue | RabbitMQ | RabbitMQ in-cluster / Amazon MQ, or SQS via `JobQueue` |
| Object storage (post-MVP) | any S3-compatible server (MinIO, SeaweedFS…) | S3 |
| DNS | `*.localhost` (resolves to 127.0.0.1) | Route 53 wildcard |

---

## 3. Tech stack

| Area | Choice | Notes |
|---|---|---|
| Backend | Python 3.14, FastAPI, Pydantic v2, pydantic-settings, SQLAlchemy 2.x, Alembic, psycopg 3, uvicorn | `uv` (locked) · Ruff (lint + format) · mypy (strict) · pytest, httpx2 (Starlette's test client), Testcontainers · pre-commit |
| Security libs | `pwdlib[argon2]` or `argon2-cffi` · PyJWT · `cryptography` (Fernet) | not passlib (unmaintained) or python-jose |
| Database | PostgreSQL 16+ | source of truth |
| Cache / coordination | Redis 7+ | cache, rate limits, pub/sub, leases |
| Broker | RabbitMQ + aio-pika | durable queues, manual ack, publisher confirms, DLQ |
| Builds | Docker with BuildKit (MVP); rootless BuildKit in ephemeral Kubernetes Jobs (Phase 15) | see §8 and §12 |
| Runtime | Kubernetes, official `kubernetes` Python client | server-side apply |
| Frontend | React + TypeScript (Next.js or Vite) | production quality: responsive, accessible (WCAG 2.2 AA), built on a component library (chosen in Phase 10 with an ADR), Vitest + Playwright |
| CLI | Go: the `runvia` CLI (Phase 16) | single static binary, cross-compiled for Linux/macOS/Windows, released with GoReleaser |
| Infrastructure | Terraform ≥ 1.11, Kustomize for platform manifests | |
| Observability | JSON logs, prometheus-client, OpenTelemetry, Prometheus, Grafana, Loki (Phase 13) | |
| CI/CD | GitHub Actions | |

- **Sync vs async:** choose one DB style (sync SQLAlchemy with `def` routes, or `AsyncSession` with `async def`) and use it everywhere. **Never do blocking I/O inside `async def`.** In the worker, run subprocesses and the sync Kubernetes client off the event loop (`asyncio.to_thread` / asyncio subprocesses), or RabbitMQ heartbeats will stall.
- **Platform images:** multi-stage Dockerfiles, pinned base images, a non-root user. Every component (API, worker, frontend) has one.

---

## 4. Architecture

```text
Dashboard / CLI / GitHub
        │ HTTPS
        ▼
  API (FastAPI) ──publish──► RabbitMQ ──consume──► Worker (build · deploy)
    │      │                                        │    │        │
    │      └──────► Redis ◄──── log lines ──────────┘    │        │
    │   cache · rate limits · pub/sub · leases           │        │
    ▼                                                    │        │
  PostgreSQL ◄───────── status, logs, events ────────────┘        │
  (source of truth)                                               │
                                        ┌──── docker push ────────┤
                                        ▼                         ▼ apply / watch
                                    Registry ────── pull ─────► Kubernetes (rv-<org> namespaces)
                                                   App users ─► Ingress ─► Service ─► Pods
```

| Component | Responsibility |
|---|---|
| **API** | authn/authz, CRUD, deployment creation, status/log/metric queries, webhooks. Never builds or deploys. |
| **Worker** | consumes `jobs.build` and `jobs.deploy`. One process may consume both in the MVP; scale them separately later. |
| **Reconciler** (Phase 12) | periodically compares desired state (PostgreSQL) with actual state (Kubernetes) and fixes drift, e.g. desired 3 replicas vs actual 2. A single active instance holds a Redis lease. It is rate-limited to avoid control-loop storms. |
| **Outbox relay** (Phase 12) | publishes committed `outbox_events` (§9). |

---

## 5. Data model

**Conventions:** UUID primary keys (v7 preferred) · `timestamptz` in UTC · `created_at`/`updated_at` on mutable tables · invariants enforced with `NOT NULL`, `UNIQUE`, `FOREIGN KEY`, `CHECK` and partial indexes, never by app code alone. **Slugs** are DNS-1123 labels (`^[a-z0-9]([-a-z0-9]*[a-z0-9])?$`, ≤ 30 chars) and are **immutable**, because they appear in hostnames and Kubernetes names.

```text
users                 id, email (UQ on lower(email)), password_hash, display_name, is_active,
                      email_verified_at NULL                                             (Phase 16)
refresh_tokens        id, user_id→users, family_id, token_hash UQ, expires_at, revoked_at, replaced_by_id
user_tokens           id, user_id→, purpose (VERIFY_EMAIL|RESET_PASSWORD), token_hash UQ,
                      expires_at, used_at NULL                                           (Phase 16)
organizations         id, name, slug UQ
organization_members  id, organization_id→, user_id→, role                 UQ(organization_id, user_id)
applications          id, organization_id→, name, slug, status (ACTIVE|DELETING),
                      active_deployment_id→deployments NULL, deployment_seq,
                      port=8000, health_path NULL, replicas=1,
                      cpu_request, cpu_limit, memory_request, memory_limit  UQ(organization_id, slug)
repositories          id, application_id→ UQ, provider=GITHUB, url, branch,
                      dockerfile_path='Dockerfile', build_context='.', webhook_secret_enc NULL
env_vars              id, application_id→, key, value_enc, is_secret       UQ(application_id, key)
deployments           id, application_id→, number, status, trigger (MANUAL|WEBHOOK|ROLLBACK),
                      triggered_by_user_id NULL, branch, commit_sha NULL, image_ref NULL (repo@sha256:…),
                      source_deployment_id NULL (rollback target), idempotency_key NULL,
                      cancel_requested, error_code NULL, error_message NULL, started_at, finished_at
                      UQ(application_id, number) · UQ(application_id, idempotency_key)
deployment_events     id, deployment_id→, from_status, to_status, message, created_at   (stage timeline)
deployment_logs       id, deployment_id→, seq, stream (BUILD|DEPLOY|SYSTEM), line, created_at
                      UQ(deployment_id, seq)
audit_logs            id, organization_id, actor_user_id NULL, action, resource_type, resource_id,
                      metadata JSONB, request_id, created_at                  (append-only)
outbox_events         id, type, payload JSONB, created_at, published_at NULL             (Phase 12)
webhook_deliveries    delivery_id PK (X-GitHub-Delivery), received_at                    (Phase 11)
api_keys              id, organization_id, user_id, name, prefix, key_hash UQ, role,
                      last_used_at, expires_at, revoked_at                               (Phase 16)
domains               id, application_id, hostname UQ, verification_token, status,
                      certificate_status, verified_at                                    (Phase 16)
```

- Builds are the first stages of a deployment, so there is no separate Build table. Secrets are env vars with `is_secret` set, so there is no separate Secret table.
- A deployment row plus its events must answer: which commit, which image digest, who triggered it, when each stage started and ended, which stage failed and why, and whether it is the active one.
- `number` comes from `UPDATE applications SET deployment_seq = deployment_seq + 1 … RETURNING deployment_seq`. This also serializes concurrent creates for the same app.
- **Audit actions:** `APPLICATION_CREATED/UPDATED/DELETED`, `DEPLOYMENT_CREATED/CANCELLED`, `ROLLBACK_CREATED`, `ENV_VAR_CHANGED`, `SECRET_CHANGED`, `APPLICATION_SCALED`, `MEMBER_ADDED/ROLE_CHANGED/REMOVED`, `DOMAIN_ADDED`. App code never updates or deletes audit rows; revoke `UPDATE`/`DELETE` on the table from the app's DB role.
- **Indexes:** the unique constraints above, plus `organization_members(user_id)` · `deployments(application_id, created_at DESC, id DESC)` · the in-flight partial unique index (§7.5) · `audit_logs(organization_id, created_at DESC)` · `outbox_events(created_at) WHERE published_at IS NULL`. Verify them with `EXPLAIN ANALYZE`, and don't index every column.

---

## 6. API

Base path `/api/v1`, with OpenAPI at `/docs`. These are unversioned: `GET /health/live`, `GET /health/ready`, `GET /metrics` (internal only).

```text
Auth         POST /auth/register · /auth/login · /auth/refresh · /auth/logout · GET /auth/me
             POST /auth/verify-email · /auth/forgot-password · /auth/reset-password              (Phase 16)
Orgs         POST|GET /organizations · GET|PATCH|DELETE /organizations/{org_id}
Members      GET|POST /organizations/{org_id}/members · PATCH|DELETE /organizations/{org_id}/members/{member_id}
Audit        GET  /organizations/{org_id}/audit-logs
Apps         POST|GET /organizations/{org_id}/applications · GET|PATCH|DELETE /applications/{app_id}
             POST /applications/{app_id}/restart
             GET  /applications/{app_id}/status     live pods, ready replicas, restarts
             GET  /applications/{app_id}/metrics    CPU/memory via metrics-server
             GET  /applications/{app_id}/logs       runtime logs (?tail=&since=)
Repository   PUT|GET /applications/{app_id}/repository · POST /applications/{app_id}/repository/test
Env          GET /applications/{app_id}/env · PUT|DELETE /applications/{app_id}/env/{key}
Deployments  POST|GET /applications/{app_id}/deployments · GET /deployments/{dep_id}
             POST /deployments/{dep_id}/cancel · POST /deployments/{dep_id}/rollback
             GET  /deployments/{dep_id}/logs?after_seq= · GET /deployments/{dep_id}/logs/stream (SSE)
Webhooks     POST /webhooks/github/{repository_id}                                      (Phase 11)
Domains      POST|GET /applications/{app_id}/domains · DELETE /domains/{id} · POST /domains/{id}/verify  (Phase 16)
API keys     POST|GET /organizations/{org_id}/api-keys · DELETE /api-keys/{key_id}                  (Phase 16)
```

**Convention:** collections are nested under their parent, and single resources are addressed at the top level by ID.

**Every endpoint:** authenticate → resolve org scope → authorize role → validate (Pydantic, body-size limit) → do transactional work → write audit rows for sensitive actions → return consistent JSON.

**Errors** always use this envelope. FastAPI's default 422 is reshaped into it, and stack traces are never exposed.

```json
{ "error": { "code": "APPLICATION_NOT_FOUND", "message": "Application not found", "request_id": "…", "details": [] } }
```

**Status codes:** `201` created · `202` accepted (async: deploy, delete app) · `204` no content · `400` malformed · `401` not authenticated · `403` member but role too low · `404` missing **or belongs to another org** · `409` conflict (slug taken, illegal state transition, org still has apps) · `422` validation · `429` rate limited (`Retry-After`) · `503` dependency down.

**Pagination:** cursor-based `?limit=25&cursor=<opaque>` (max 100), ordered by `created_at DESC, id DESC`, returning `{ "items": [...], "next_cursor": … }`.

**Versioning:** only additive changes inside `v1`; breaking changes go to `/api/v2`. The OpenAPI schema drives the frontend client, the CLI and contract tests.

**Performance sanity targets** (measure them, don't guess): authenticated GET under 200 ms p95 locally; `POST …/deployments` returns 202 in under 500 ms.

---

## 7. Deployment lifecycle

### 7.1 State machine

```text
QUEUED ─► CLONING ─► BUILDING ─► PUSHING ─► DEPLOYING ─► HEALTH_CHECK ─► SUCCEEDED
   │                                            ▲
   └────── rollback: image already exists ──────┘
any non-terminal state ─► FAILED
QUEUED | CLONING | BUILDING | PUSHING ─► CANCELLED           terminal: SUCCEEDED, FAILED, CANCELLED
```

- All changes go through `transition(dep, target)`, which checks `can_transition(current, target)` and runs a **conditional update**: `UPDATE deployments SET status=:target WHERE id=:id AND status=:current`. Zero rows updated means someone else moved it, so re-read and stop. Each transition inserts a `deployment_events` row. Every valid and invalid pair has a unit test.
- Once a deployment reaches `DEPLOYING` it can't be cancelled (`409`); use a rollback instead.

### 7.2 Create (API)

`POST /applications/{id}/deployments` takes `{ "commit_sha"?: "…" }` and an optional `Idempotency-Key` header.

1. Authorize (DEVELOPER+) and require a repository config.
2. In one transaction: allocate `number`, insert the deployment as `QUEUED` with `branch` from the repository, write the audit row, and from Phase 12 also the outbox row.
3. Publish a `BUILD` job after the commit. Until the outbox exists, a sweeper re-publishes deployments stuck in `QUEUED`.
4. Return `202 {deployment_id, number, status: "QUEUED"}`. A repeated `Idempotency-Key` returns the existing deployment.

### 7.3 Build job — `QUEUED → CLONING → BUILDING → PUSHING`

1. Load the deployment. If it is terminal, ack and stop. If `cancel_requested` is set, or a **newer** `QUEUED` deployment exists for the app (superseded), set `CANCELLED`, ack and stop.
2. `QUEUED → CLONING`. If another deployment of the app is in flight, the partial unique index (§7.5) rejects this and the job is requeued with a delay. That is not a failure.
3. Resolve the branch to a SHA with `git ls-remote`, unless a SHA was given. Fetch exactly that SHA into a fresh temp dir: `git init && git fetch --depth 1 origin <sha> && git checkout FETCH_HEAD`. Use `GIT_TERMINAL_PROMPT=0`, `GIT_ALLOW_PROTOCOL=https` and a timeout.
4. Check that `dockerfile_path` and `build_context` resolve inside the workspace: no `..` and no symlink escapes.
5. `BUILDING`: `docker build` (BuildKit) with a timeout and resource limits. The tag is `<REGISTRY_URL>/<org-slug>/<app-slug>:<sha>`.
6. `PUSHING`: push the image and store `image_ref = <repo>@sha256:<digest>` using the digest the registry reports.
7. Stream stdout/stderr line by line to `deployment_logs` (batched) and to Redis pub/sub, scrubbing known secret values. Check `cancel_requested` between stages, and while building (kill the subprocess if it is set).
8. Always delete the workspace. Then publish a `DEPLOY` job and ack.

For every subprocess: pass an argv list (never `shell=True`), set an explicit timeout, and validate inputs (for example `git check-ref-format --branch`). Never pass secrets as build args, because they end up in the image history.

### 7.4 Deploy job — `DEPLOYING → HEALTH_CHECK → SUCCEEDED`

1. `DEPLOYING`: build a `RuntimeSpec` from the application, its env vars and the deployment's image, then server-side apply the resources (§8).
2. `HEALTH_CHECK`: watch the Deployment until `observedGeneration ≥ generation` and `updatedReplicas == availableReplicas == replicas` (after `minReadySeconds`), within `DEPLOY_TIMEOUT_SECONDS`.
3. Fail fast on `ErrImagePull`/`ImagePullBackOff`, `CrashLoopBackOff`, `CreateContainerConfigError` and `ProgressDeadlineExceeded`. Store `error_code` and the message, and copy pod events into the logs.
4. On success: set `SUCCEEDED` and `applications.active_deployment_id`. On failure: set `FAILED` and **auto-revert** by re-applying the active deployment's image, so the cluster matches PostgreSQL. With no previous deployment, scale to 0.

A deployment is never successful just because the Kubernetes API accepted the manifest.

### 7.5 Concurrency and idempotency

- **One in-flight deployment per application**, enforced by the database: `CREATE UNIQUE INDEX … ON deployments(application_id) WHERE status IN ('CLONING','BUILDING','PUSHING','DEPLOYING','HEALTH_CHECK')`. The newest queued deployment wins, and older queued ones are superseded (§7.3).
- Job messages carry IDs only. Workers re-read PostgreSQL.
- Stages are re-runnable. On redelivery the handler resumes from the persisted status: re-fetching and rebuilding the same SHA is safe, and apply is declarative.
- Duplicate inputs are absorbed: terminal-state checks for messages, `webhook_deliveries` for webhooks, `Idempotency-Key` for API retries and double clicks.

### 7.6 Other operations

| Operation | Behavior |
|---|---|
| **Rollback** to #N | #N must be `SUCCEEDED` with an image. Creates a **new** deployment (`trigger=ROLLBACK`, `source_deployment_id=N`, same commit and image) that goes `QUEUED → DEPLOYING`, skipping the build. History is never mutated. Uses #N's image with the app's **current** config (the UI says so). |
| **Deploy an old commit** | a manual deployment with `commit_sha`. |
| **Config change** (env, replicas, resources, health path) | update PostgreSQL, then publish `SYNC_RUNTIME`, which re-applies the full spec with the active image. The job is requeued while a deployment is in flight, since that deployment applies the latest config anyway. |
| **Restart** | `SYNC_RUNTIME` with a new `runvia.io/restarted-at` pod-template annotation (the same thing `kubectl rollout restart` does). No new deployment. |
| **Delete app** | `status=DELETING`, cancel queued deployments, return 202 → `DELETE_APPLICATION_RUNTIME` removes Kubernetes objects by label → the row is deleted (cascade) → audit row. |
| **Delete org** | `409` while it still has applications. |

---

## 8. Kubernetes runtime

**Layout.** There is one namespace per organization, `rv-<org-slug>`, with:

- a ResourceQuota;
- a LimitRange (container defaults);
- NetworkPolicies: default-deny ingress except from the ingress controller, and deny egress to the platform namespace and to `169.254.169.254/32` (cloud metadata);
- Pod Security Admission labels `enforce=baseline`, `warn=restricted`.

Each application gets these resources, named by its app slug: **Deployment**, **Service** (ClusterIP), **Ingress**, **ConfigMap** (plain env), **Secret** (secret env), and a **ServiceAccount** with `automountServiceAccountToken: false`.

**Labels.**

- Every object: `app.kubernetes.io/managed-by=runvia`, `runvia.io/org-id`, `runvia.io/app-id`.
- Pod templates also get `runvia.io/deployment-id`.
- **Selectors use only `runvia.io/app-id`**, because selectors are immutable.
- The pod template carries a `runvia.io/config-checksum` annotation (a hash of env) so env changes roll the pods. Updating a ConfigMap or Secret alone does not restart pods.

**Container defaults.**

- Networking: the app listens on `0.0.0.0:$PORT`. `PORT` is injected from `applications.port`.
- Probes: HTTP GET on `health_path` if set, otherwise TCP. Liveness gets looser thresholds than readiness.
- Resources: requests `100m`/`128Mi`, limits `500m`/`256Mi` (each app can override within the quota).
- Security context: `allowPrivilegeEscalation: false`, drop all capabilities, `seccompProfile: RuntimeDefault`. `runAsNonRoot` is opt-in, because many base images run as root.
- Rollout: `maxUnavailable: 0`, `maxSurge: 1`, `minReadySeconds: 5`, `progressDeadlineSeconds` ≤ the deploy timeout, `revisionHistoryLimit: 3`.
- Images are pulled by digest.

**Generation.**

- Business code builds a typed `RuntimeSpec(app_id, org_slug, name, image, replicas, port, env, secret_env, resources, health_path, hostname)`.
- The Kubernetes adapter turns it into manifests with a **pure function** (unit-tested without a cluster) and applies them with server-side apply (field manager `runvia`).
- No YAML string templating in business logic.

**Routing.**

- Hostname: `<app-slug>-<org-slug>.<PLATFORM_DOMAIN>`. App slugs are only unique inside an org, so the org slug is part of the name.
- Local URL: `http://hello-acme.localhost:8080`.
- Cloud: a wildcard DNS record `*.<PLATFORM_DOMAIN>` points to the load balancer, and TLS comes from cert-manager (Let's Encrypt, with DNS-01 for wildcards) or ACM.
- Custom domains (Phase 16): the user publishes a TXT record `_runvia-challenge.<host>` containing the verification token, then a CNAME to the platform; after verification the host gets its own certificate from cert-manager (HTTP-01).

**Local cluster and registry.**

```bash
k3d registry create runvia-registry.localhost --port 5000
k3d cluster create runvia --registry-use k3d-runvia-registry.localhost:5000 -p "8080:80@loadbalancer"
```

- Set `REGISTRY_URL=k3d-runvia-registry.localhost:5000`. The **same reference** must work for the push (worker) and the pull (cluster). If the name doesn't resolve on the host, add it to `/etc/hosts` as 127.0.0.1.
- The worker needs Docker, the registry and the cluster API. The simplest setup runs it on the host (`make worker`). A containerized worker must join the `k3d-runvia` Docker network and use a kubeconfig with in-network addresses. Document the working setup in `docs/DEVELOPMENT.md`.
- Kubernetes nodes have **no Docker daemon**. In-cluster (cloud) builds therefore use rootless BuildKit in ephemeral Jobs (Phase 15) behind the same `ImageBuilder` interface.

---

## 9. Jobs and messaging

| Item | Spec |
|---|---|
| Queues | `jobs.build` (slow; prefetch 1 per build slot) · `jobs.deploy` (`DEPLOY`, `SYNC_RUNTIME`, `DELETE_APPLICATION_RUNTIME`, from Phase 16 `VERIFY_DOMAIN`) · `jobs.retry.<delay>` · `jobs.dlq`. Phase 6 builds the worker framework before any real job type exists, and proves it with job types registered only in tests. No demo job ships in production code. |
| Message | `{job_id, type, deployment_id \| application_id, attempt, correlation_id}` plus a W3C `traceparent` header. IDs only, never whole rows. |
| Delivery | durable queues, persistent messages, publisher confirms, manual **ack only after the outcome is persisted**, `prefetch` = worker concurrency. Delivery is at-least-once, so handlers are idempotent (§7.5). |
| Time limits | Every job must finish well within RabbitMQ's `consumer_timeout` (30 min by default): `BUILD_TIMEOUT_SECONDS=900`, `DEPLOY_TIMEOUT_SECONDS=300`. |

**Retries.** `classify_error(exc) -> RETRYABLE | NON_RETRYABLE` is unit-tested. Never retry forever.

| Retryable (with backoff) | Non-retryable (fail now) |
|---|---|
| network/DNS timeouts, GitHub 5xx, registry unavailable, Kubernetes API 5xx/429/conflict, lost DB or broker connection | invalid repo URL, missing branch or commit, missing or invalid Dockerfile, build/compile error, invalid config, app crashes on start |

- **Delays:** 10 s → 30 s → 2 min → 10 min, plus jitter, configurable.
- **Mechanism:** one retry queue per delay; each uses a message TTL and dead-letters back to the work exchange, and the message carries an `attempt` counter.
- **After the last attempt:** route to `jobs.dlq` and mark the deployment `FAILED` with `error_code=RETRIES_EXHAUSTED`.

**Outbox (Phase 12).** This solves the dual-write problem: the DB commits but the publish fails, or the reverse. Business changes and an `outbox_events` row are written in the **same transaction**. A relay reads unpublished rows with `FOR UPDATE SKIP LOCKED` (safe to run several relays), publishes with confirms and sets `published_at`. Outbox event types (`DeploymentCreated`, `BuildSucceeded`, `DeploymentFailed`, …) are versioned internal contracts, not public API.

---

## 10. Redis

| Use | Design |
|---|---|
| Cache-aside | Read the key; on a miss, read PostgreSQL and `SET key EX 60`. Delete the key **after** the DB commit on writes. Cache entities, not authorization results, and still authorize every request. Never cache secrets. |
| Rate limiting | Fixed window with atomic `INCR` + `EXPIRE`: login 5/min per IP (and per email) · deployments 10/min per user · app creation 20/h per user · capped concurrent log streams per user. Returns `429` + `Retry-After`. Trust `X-Forwarded-For` only from the known proxy. |
| Live logs | Pub/sub channel `logs:deployment:<id>`. It is not durable; the copy lives in PostgreSQL. |
| Leases | `SET lease:<name> <owner> NX PX 30000`, renewed while held, released with a check-and-delete Lua script. A lease is **not** a correctness guarantee, so writes still use conditional updates. |

Redis is a **soft dependency**. If it is down, the API bypasses the cache, rate limits fail open (with a log line and a metric), and live logs fall back to polling. Core reads and writes keep working.

---

## 11. Authentication, authorization, tenancy

**Authentication.**

- **Passwords:** Argon2id. Never logged or returned.
- **Access token:** JWT with a 15 min TTL and claims `sub`, `exp`, `iat`, `iss`, `jti`. It is stateless, so logout cannot revoke it; the short TTL bounds the damage.
- **Refresh token:** 256-bit random, stored **hashed**, 30 days, **rotated on every use**. Reusing a rotated token revokes its whole family. Logout revokes the family.
- **Browser:** tokens live in `HttpOnly; Secure; SameSite=Lax` cookies (the refresh cookie is scoped to `/api/v1/auth`). State-changing requests need a CSRF header (double-submit). Cookies also make SSE work, because `EventSource` can't send an `Authorization` header. In development, proxy the API through the dashboard's dev server so both share one origin.
- **Email verification and password reset (Phase 16):** single-use tokens, stored hashed in `user_tokens`, expiring after 24 h (verify) or 1 h (reset). `forgot-password` responds the same whether or not the email exists. A successful reset revokes all of the user's refresh-token families. Email goes through an `EmailSender` adapter (SMTP: Mailpit locally, Amazon SES in the cloud).
- **CLI / automation:** `Authorization: Bearer <access token | API key>`. API keys (Phase 16) look like `rv_<prefix>_<secret>`, are shown once and stored as a SHA-256 hash, are scoped to an org and role, and are revocable.

**Roles** (checked server-side; the UI only hides what the server would reject):

| Permission | VIEWER | DEVELOPER | ADMIN | OWNER |
|---|:-:|:-:|:-:|:-:|
| Read apps, deployments, logs, status, env keys (never secret values) | ✓ | ✓ | ✓ | ✓ |
| Deploy, cancel, rollback, restart | | ✓ | ✓ | ✓ |
| Edit env and secrets, replicas, resources, health path | | ✓ | ✓ | ✓ |
| Create/delete apps, edit repository config, domains, API keys | | | ✓ | ✓ |
| Manage non-owner members, read the audit log | | | ✓ | ✓ |
| Manage owners, update/delete the organization | | | | ✓ |

**Invariants.**

- The org creator becomes OWNER in the same transaction that creates the org.
- An org always has at least one OWNER; the last owner can't be removed or demoted.
- Members are added by the email of an existing user (no invitation emails in the MVP).

**Tenant isolation.** Every tenant-owned query is scoped through membership. Implement this once, as a dependency (`get_app_for(user, app_id, min_role)`):

```sql
SELECT a.* FROM applications a
JOIN organization_members m ON m.organization_id = a.organization_id
WHERE a.id = :app_id AND m.user_id = :user_id;
```

Non-members get **404** (not 403), so the existence of other tenants' resources doesn't leak. A permanent cross-tenant test suite calls every endpoint as a foreign user.

---

## 12. Security

**The main boundary is tenant code vs the control plane.** Builds and running apps must never obtain:

- PostgreSQL, Redis or RabbitMQ credentials;
- the Kubernetes admin kubeconfig;
- cloud credentials, including instance metadata;
- the host Docker socket;
- other tenants' data.

> **The MVP is for trusted repositories only.** The worker runs `docker build` against the host daemon, which is equivalent to root on the host. `README.md` and `docs/SECURITY.md` must say so. v1.0 requires sandboxed builds (Phase 15): ephemeral Kubernetes Jobs with rootless BuildKit, no platform credentials, CPU/memory/time limits, and restricted egress.

| Threat | Controls |
|---|---|
| Malicious repository or Dockerfile | trusted repos only in the MVP; timeouts and resource limits; no secrets in the build environment; sandboxed builds from Phase 15 |
| Malicious running app | per-org namespace, NetworkPolicy, no service-account token, PSA baseline, quotas, metadata endpoint blocked |
| Cross-tenant access (IDOR) | membership-scoped queries, 404s, cross-tenant tests |
| Stolen token or API key | short access TTL, refresh rotation with reuse detection, hashed storage, revocation |
| SSRF | repo URLs limited to `https://github.com/<owner>/<repo>`; `GIT_ALLOW_PROTOCOL=https`; no fetches to user-supplied hosts |
| Command injection | argv lists, never `shell=True`; validated refs and paths |
| Secret leakage | values Fernet-encrypted at rest (`SECRETS_ENCRYPTION_KEY`, from day one); write-only API (`value: null` when `is_secret`); scrubbed from logs; never in build args or image layers; in the cloud the key comes from AWS Secrets Manager, with a documented rotation procedure |
| Webhook forgery or replay | HMAC-SHA256 checked with `hmac.compare_digest`; delivery-ID dedupe |
| Brute force, abuse, exhaustion | rate limits, request-size limits, per-org build concurrency, namespace quotas |
| Supply chain | `pip-audit`/`npm audit` and Trivy image scans in CI; pinned base images |

Also: HTTPS everywhere in the cloud, least-privilege IAM, and a namespaced RBAC role for the platform's ServiceAccount (not cluster-admin in the cloud). Secrets never go in Git; only `.env.example` is committed. Don't call it production-safe until it has been hardened and tested.

---

## 13. Git integration

- **MVP:** public repos only. Validate the URL against `^https://github\.com/[\w.-]+/[\w.-]+(\.git)?$` and the branch with `git check-ref-format`. `POST …/repository/test` runs `git ls-remote`.
- **Phase 11, webhooks:**
  - Runvia generates a per-repository secret (stored encrypted) and the user configures it on GitHub.
  - On `push` events, verify `X-Hub-Signature-256` and dedupe by `X-GitHub-Delivery`.
  - Ignore pushes to branches other than the configured one.
  - Create a deployment (`trigger=WEBHOOK`, `commit_sha` from the payload) and respond within 10 s.
- **Phase 11, GitHub App:** private repos via short-lived installation tokens, plus commit statuses and deployments. Never store long-lived personal access tokens.

---

## 14. Logs and observability

| Log kind | Source | Storage | API |
|---|---|---|---|
| Build/deploy | worker subprocesses and stage messages | `deployment_logs` (archived to object storage later) | `/deployments/{id}/logs`, `…/stream` |
| Runtime | pod stdout/stderr | MVP: read live from the Kubernetes API; Phase 13: Loki, with a retention period | `/applications/{id}/logs` |
| Platform | API and worker | stdout as JSON → collector | — |
| Audit | sensitive actions | `audit_logs` | `/organizations/{id}/audit-logs` |

- **Log streaming** (SSE): subscribe to Redis first, then send the persisted lines, then live lines with `seq` greater than the last one sent. This avoids both gaps and duplicates.
- **Platform log fields:** `timestamp, level, service, request_id, correlation_id, trace_id, org_id, app_id, deployment_id, message`. **Never log** passwords, tokens, API keys, secret values, or `Authorization`/`Cookie` headers.
- **Request IDs:** accept or generate `X-Request-ID`, return it in the response, and include it in logs and error bodies. Propagate it to jobs as `correlation_id`, together with `traceparent`.
- **Metrics** on API `/metrics` and worker `:8001/metrics`:
  - HTTP: `http_requests_total{method,route,status}`, `http_request_duration_seconds`.
  - Jobs: `jobs_total{type,outcome}`, `job_duration_seconds{type}`, `jobs_in_progress`.
  - Deployments: `deployments_total{outcome}`, `deployment_stage_duration_seconds{stage}`.
  - From other sources: queue depth from RabbitMQ's Prometheus plugin; app CPU/memory from metrics-server (bundled with k3s); restarts from pod status.
  - Label by route template, never by raw path, and never use unbounded values (IDs) as labels.
- **Tracing** (OpenTelemetry): auto-instrument FastAPI, SQLAlchemy and httpx. Add manual spans for queue publish/consume, git, build, push, apply and rollout wait. The result is one trace per deployment: API → broker → worker → Kubernetes.
- **Grafana:** start with one useful dashboard (API rate/errors/latency, queue depth and age, deployment success rate, stage durations). Alerts (Phase 13): DLQ not empty, deployment failure rate, API 5xx.

---

## 15. Reliability

- **Timeouts** on every network call (GitHub, git, registry, Kubernetes API, PostgreSQL `statement_timeout`, Redis, RabbitMQ) and on every subprocess.
- **Retries** only for retryable errors, bounded, with backoff and jitter (§9).
- **Health checks:**
  - `live` means the process responds. It checks no dependencies, so a DB outage doesn't send pods into a restart loop.
  - `ready` means hard dependencies are reachable: PostgreSQL, plus RabbitMQ until the outbox exists. Redis is soft.
  - The worker serves `/health/*` and `/metrics` on port 8001.
- **Graceful shutdown** on SIGTERM, for the API and the worker (tested):
  1. Stop taking work (cancel consumers).
  2. Finish in-flight jobs within the grace period; unacked messages are redelivered.
  3. Close DB, Redis and broker connections, then exit.
- **Backpressure:** bounded worker concurrency (prefetch), per-org build limits, rate limits, namespace quotas, monitored queue depth.
- **Consistency:** deployment state is strongly consistent in PostgreSQL. Cache, metrics and runtime status may be briefly stale.
- **Database:** size the pool so pool size × processes stays below `max_connections`, and use `pool_pre_ping`. Back up with `pg_dump` locally and RDS snapshots/PITR in the cloud, and **prove a restore works**.
- **Self-healing:** the reconciler (§4), auto-revert (§7.4) and the stuck-`QUEUED` sweeper (§7.2).

**Failure scenarios that must be tested.** The sample app has fixture branches for these: `main`, `broken-build`, `crash-on-start`, `broken-health`, `slow-start`.

| Scenario | Expected behavior |
|---|---|
| Worker killed mid-job | message redelivered; the handler resumes from the persisted status |
| Duplicate message, webhook or double click | no duplicate work |
| API crashes between commit and publish | the sweeper (later the outbox) publishes the job |
| Registry, GitHub or Kubernetes API briefly down | retries with backoff; after the last attempt, `FAILED` and DLQ |
| PostgreSQL down | API returns 503 and reports not ready; workers requeue; automatic recovery |
| Bad Dockerfile or compile error | `FAILED` with no retries; the logs show why |
| Crash loop, failing health check, hung rollout | `FAILED` with a reason within the deploy timeout; auto-revert |
| Pod deleted, or replicas changed by hand | Kubernetes recreates the pod; the reconciler restores desired replicas |
| Two deployments started at once | never run concurrently; the newest queued one wins |

---

## 16. Code organization

```text
runvia/
├── backend/                       # one Python package, two processes (api, worker)
│   ├── pyproject.toml · uv.lock · alembic.ini · alembic/versions/
│   ├── src/runvia/
│   │   ├── api/                   # app factory, middleware (request ID, errors), router mounting
│   │   ├── worker/                # consumer loop, dispatch, handlers: build, deploy, sync, delete
│   │   ├── auth/ organizations/ applications/ repositories/ env/ deployments/ audit/ logs/
│   │   │   └── router.py · schemas.py · service.py · domain.py · models.py · store.py
│   │   ├── integrations/          # git, builder, runtime (k8s), queue, storage
│   │   └── core/                  # config, db, cache, security, logging, telemetry, errors
│   └── tests/{unit,integration,e2e}/
├── frontend/                      # dashboard
├── cli/                           # Go CLI (Phase 16)
├── examples/sample-app/           # source of the test "customer"; published as its own public GitHub
│                                  #   repo with the fixture branches, because that is what Runvia clones
├── infra/{compose/, k8s/{base,overlays}/, terraform/{modules,envs/{dev,prod}}/}
├── docs/{ARCHITECTURE,DEVELOPMENT,OPERATIONS,SECURITY}.md · docs/adr/
└── .github/workflows/ · Makefile · .env.example · README.md
```

**Layers inside a module.** Create files only as needed.

| File | Contains |
|---|---|
| `router.py` | HTTP only: parse, authorize via deps, call the service, map the response |
| `service.py` | use cases, transactions, orchestration |
| `domain.py` | pure rules (state machine, permissions, validation), with no FastAPI, SQLAlchemy or Kubernetes imports |
| `store.py` | SQLAlchemy queries (called "store" so it doesn't clash with the Git `Repository` entity) |

**Adapters.** Only these, no more:

```python
class GitProvider(Protocol):
    def resolve_ref(self, url: str, branch: str) -> str: ...            # → commit SHA
    def fetch(self, url: str, commit_sha: str, dest: Path) -> None: ...
class ImageBuilder(Protocol):
    def build(self, context: Path, dockerfile: str, tag: str, log: LogSink) -> None: ...
    def push(self, tag: str, log: LogSink) -> str: ...                  # → repo@sha256:digest
class Runtime(Protocol):
    def apply(self, spec: RuntimeSpec) -> None: ...
    def wait_ready(self, app: AppRef, timeout: float) -> RolloutResult: ...
    def status(self, app: AppRef) -> RuntimeStatus: ...
    def delete(self, app: AppRef) -> None: ...
class JobQueue(Protocol):
    def publish(self, job: Job) -> None: ...
    def consume(self, queue: str, handler: Callable[[Job], None]) -> None: ...  # ack/retry/DLQ inside
class EmailSender(Protocol):                                            # Phase 16
    def send(self, message: EmailMessage) -> None: ...
```

| Adapter | Implementations |
|---|---|
| `GitProvider` | `GitHubProvider` |
| `ImageBuilder` | `DockerBuilder` → `BuildKitBuilder` |
| `Runtime` | `KubernetesRuntime` (one class for k3d and EKS; only the kubeconfig differs) |
| `JobQueue` | `RabbitMQQueue` → optional `SQSQueue` |
| `EmailSender` | `SmtpEmailSender` (Mailpit locally, the Amazon SES SMTP endpoint in the cloud) |

Every adapter also has a fake for tests. The registry and object storage are configuration (URL and credentials), not classes; one S3 client covers both MinIO and S3.

---

## 17. Configuration and local development

Settings are typed (pydantic-settings) and read from env vars. The app fails fast at startup on missing or invalid values. `.env` is git-ignored; `.env.example` holds local-development defaults, with secrets left empty (never real credentials).

| Group | Variables |
|---|---|
| App | `APP_ENV`, `APP_HOST`, `APP_PORT`, `LOG_LEVEL`, `CORS_ORIGINS`, `PLATFORM_DOMAIN` (`localhost`), `APP_URL_SCHEME`, `APP_URL_PORT` (`8080` locally) |
| Data | `DATABASE_URL`, `REDIS_URL`, `RABBITMQ_URL` |
| Auth | `JWT_SECRET`, `JWT_ISSUER`, `ACCESS_TOKEN_TTL`, `REFRESH_TOKEN_TTL`, `SECRETS_ENCRYPTION_KEY` |
| Build/runtime | `REGISTRY_URL`, `WORKSPACE_DIR`, `BUILD_TIMEOUT_SECONDS`, `DEPLOY_TIMEOUT_SECONDS`, `KUBECONFIG` (optional: in-cluster config inside Kubernetes, else `~/.kube/config`), `INGRESS_CLASS` |
| Later | `OBJECT_STORAGE_ENDPOINT`, `OBJECT_STORAGE_BUCKET`, `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `AWS_REGION`, `SMTP_URL`, `EMAIL_FROM` |

Onboarding: `git clone … && cd runvia && cp .env.example .env && make cluster-up && make dev`.

| Service | Local port |
|---|---|
| API (+ `/docs`) · worker health/metrics | 8000 · 8001 |
| Dashboard | 3000 |
| PostgreSQL · Redis · RabbitMQ (AMQP / management) | 5432 · 6379 · 5672 / 15672 |
| Registry (k3d) · tenant apps (k3d ingress) | 5000 · 8080 |
| Prometheus · Grafana (Compose profile `observability`) | 9090 · 3001 |
| MinIO (post-MVP) | 9000 / 9001 |
| Mailpit (SMTP / web UI, Phase 16) | 1025 / 8025 |

Make targets: `dev`, `down`, `api`, `worker`, `migrate`, `test`, `lint`, `fmt`, `typecheck`, `cluster-up`, `cluster-down`, `e2e`. The Kubernetes runtime (k3d) runs outside Compose.

---

## 18. Testing

| Layer | What | How |
|---|---|---|
| Unit | state machine (every pair), role matrix, `classify_error`, validators (slugs, URLs, refs, paths), `RuntimeSpec` → manifests, settings | pytest, no I/O |
| API | auth flows, roles, cross-tenant 404s, validation and the error envelope, status codes, pagination | httpx against the app, real PostgreSQL |
| Integration | migrations from an empty DB and from the previous head, constraints, the in-flight index under races, rate limiter, RabbitMQ ack/retry/DLQ | Testcontainers (never SQLite) |
| Worker | job handlers with a real broker and DB; fake git, builder and runtime | Testcontainers |
| End-to-end | register → org → app → repo → deploy the sample app → `GET` its URL returns the expected JSON; the fixture branches fail as expected | k3d, locally and in CI (on `main` or nightly) |
| Failure | the §15 table | scripted, with pytest markers |

Tests ship with every feature. The target is covered invariants, not a coverage percentage.

**Quality gate.** Every change passes `ruff check`, `ruff format --check`, `mypy` (strict) and pytest (strict mode, warnings as errors), locally through pre-commit and in CI. A failing gate blocks the merge.

---

## 19. CI/CD and migrations

This pipeline is for Runvia itself, not tenant apps:

```text
PR     pre-commit · ruff · mypy · unit/API/integration tests · build images · pip-audit + Trivy
main   the above → push images tagged <git-sha> → dev: migration Job, rollout, smoke tests
prod   manual promotion of an image SHA that already passed dev
```

**Repository workflow** (from the first commit with CI):

- `main` is protected: changes land only through pull requests with green required checks. No direct pushes.
- Short-lived branches named `<type>/<topic>` (e.g. `feat/json-logging`); conventional commits; squash merge, so the PR title becomes the commit on `main`.
- Dependency updates come from Dependabot (or Renovate), grouped weekly, and pass the same checks.
- Releases are SemVer tags with a changelog generated from the conventional commits.

- GitHub Actions authenticates to AWS with **OIDC**, not static keys.
- **Alembic rules:**
  - one migration per schema change, committed and reviewed (autogenerate output is only a draft);
  - never edit a migration after it's merged;
  - migrations run as a one-off Job **before** the rollout.
- **Incompatible changes use expand → deploy → contract:** add nullable columns or new tables, deploy code that works with both schemas, then drop the old parts in a later release. `CREATE INDEX CONCURRENTLY` must run outside a transaction.

---

## 20. AWS and Terraform

```text
Route 53: api.<domain>, *.<PLATFORM_DOMAIN>
   └─► Load balancer (ALB via LB Controller, or NLB → Traefik) + TLS
        └─► Kubernetes: EC2 + k3s (cheap path) → EKS (managed path)
             ├── runvia namespace: API, worker, reconciler (+ RabbitMQ, buildkitd)
             └── rv-<org> namespaces: tenant apps
Private subnets: RDS PostgreSQL · ElastiCache Redis (or in-cluster) · SQS (optional)
Regional: ECR (images) · S3 (log archives, backups) · Secrets Manager (platform secrets)
```

- **Everything is code.** All infrastructure is created by Terraform and changed through pull requests (`terraform plan` runs in CI). Nothing is created by hand in the console, except a small bootstrap config that creates the state bucket.
- **Terraform modules:** `network` (VPC, public/private subnets, routes, IGW/NAT), `iam`, `ecr`, `s3`, `rds`, `redis`, `compute` (`k3s` or `eks`), `dns`, `monitoring`. Environments: `envs/dev`, `envs/prod`.
- **Terraform state:**
  - Remote state in S3 with `use_lockfile = true` (no DynamoDB table needed).
  - State can contain secrets, so keep the bucket private and encrypted.
  - No secrets in `.tf` files; outputs expose endpoints and IDs.
  - **Commit `.terraform.lock.hcl`.**
- **Ownership:** Terraform owns infrastructure; Runvia owns tenant deployments. Never run Terraform per app.
- **AWS access and exposure:**
  - Platform pods get AWS access through EKS Pod Identity or IRSA (on k3s: the node instance profile). Tenant namespaces block the metadata endpoint (§8).
  - ECR pull tokens expire after 12 h, so the k3s path needs the kubelet ECR credential provider or refreshed pull secrets.
  - Databases live in private subnets; only the load balancer is public.
- **Cost:** EKS, NAT gateways, load balancers and RDS bill hourly even when idle. Create an AWS Budget alert first, and `terraform destroy` environments you aren't using.

---

## 21. Frontend and CLI

**Dashboard pages:**

- `/login`, `/register`; from Phase 16 `/verify-email`, `/forgot-password`, `/reset-password`
- `/` (org switcher + app list), `/apps/new`
- `/apps/:id`: status, URL, current deployment, recent deployments
- `/apps/:id/deployments/:dep`: stage timeline, live logs
- `/apps/:id/logs`, `/apps/:id/env`, `/apps/:id/metrics`
- `/apps/:id/settings`: repository, scaling, resources, health, delete; from Phase 16 domains
- `/orgs/:id/members`, `/orgs/:id/audit`; from Phase 16 `/orgs/:id/api-keys`

The typed API client is generated from OpenAPI. The UI is held to the same standard as the backend: consistent design system, loading/empty/error states for every view, keyboard and screen-reader accessible, and E2E tests for the core flows.

**CLI (Go, Phase 16):** `runvia login · apps list|create · deploy [--commit SHA] [--wait] · status · logs [-f] · rollback <number> · env set KEY=VALUE [--secret] · env unset KEY`. It uses the public API with API keys and stores its config in `~/.config/runvia/`. Build it with goroutines (stream logs while polling status) and cancel with `context` on Ctrl-C.

---

## 22. Documentation

| File | Content |
|---|---|
| `README.md` | what it is, quick start, phase status, the trusted-repos security disclaimer |
| `docs/ARCHITECTURE.md` | components, ERD, deployment flow, state machine |
| `docs/DEVELOPMENT.md` | setup, cluster and registry, ports, make targets, troubleshooting |
| `docs/OPERATIONS.md` | runbook: when the API, worker, RabbitMQ, Redis, PostgreSQL or Kubernetes is down · finding logs · restarting workers · draining the DLQ · recovering a stuck deployment · rolling back · restoring a backup |
| `docs/SECURITY.md` | threat model (§12), known limitations |
| `docs/adr/NNNN-*.md` | Context · Decision · Alternatives · Consequences. First ADRs: modular monolith · PostgreSQL as source of truth · RabbitMQ over Kafka · k3d locally, EKS later · immutable digests · deployment concurrency policy · outbox |

The API reference is the generated OpenAPI schema.

---

## 23. Implementation phases

Each phase ends with its acceptance criteria passing in CI and the docs updated. Don't build later-phase features early. Track work as one issue per deliverable, prefixed by area: `BOOT`, `DB`, `AUTH`, `ORG`, `APP`, `REDIS`, `QUEUE`, `BUILD`, `K8S`, `DEPLOY`, `WEB`, `GIT`, `REL`, `OBS`, `AWS`, `CICD`, `CLI`, `DOM`, `EXT`.

| # | Phase | Deliver | Acceptance |
|---|---|---|---|
| 0 | Bootstrap | backend skeleton (uv, Ruff, mypy, pytest), pre-commit and PR CI with branch protection **first**, then `/health/live`, request-ID and JSON logging, Dockerfile, Compose, Makefile | `make dev` → `GET /health/live` returns 200; CI green and required on `main` |
| 1 | Database | PostgreSQL, SQLAlchemy, Alembic, core tables, Testcontainers, `/health/ready` | migrations run from an empty DB; constraint tests pass |
| 2 | Auth | register/login/refresh/logout/me, Argon2, JWT, refresh rotation with reuse detection, error envelope | private endpoints return 401; token reuse revokes the family; no secrets in logs |
| 3 | Orgs & RBAC | orgs, members, role matrix, scoped-access dependency, audit log | cross-tenant suite returns 404s; last-owner invariant holds |
| 4 | Applications | app + repository CRUD, encrypted write-only env/secrets, slug/URL validation, cursor pagination | CRUD and validation tests; secret values never returned |
| 5 | Redis | cache-aside with invalidation, rate limits, soft-dependency behavior | cache hits observed; 6th login in a minute gets 429; API works with Redis stopped |
| 6 | Queue & worker | RabbitMQ, `JobQueue`, worker process with job dispatch, ack/prefetch, retry queues, DLQ, graceful shutdown (proved with test-only job types) | jobs survive a worker restart; a poison message reaches the DLQ after N attempts; duplicate delivery is harmless |
| 7 | Build | sample-app repo, git resolve/fetch, build + push to the local registry, digest, build logs, timeouts, cleanup | sample repo → image by digest; `broken-build` → `FAILED` with logs |
| 8 | Runtime | k3d + registry, org namespaces, `RuntimeSpec` → manifests, server-side apply, rollout wait, failure detection | sample image served at `http://<app>-<org>.localhost:8080`; `crash-on-start` → `FAILED` with a reason |
| 9 | End-to-end | API → build → deploy → `SUCCEEDED`, active deployment, status/logs/metrics endpoints, cancel, rollback, restart, scale, delete, concurrency policy, stuck-`QUEUED` sweeper | E2E test passes; two rapid deploys never run concurrently |
| 10 | Dashboard | pages from §21, live build logs | **MVP done:** the whole flow works without curl |
| 11 | GitHub | webhooks (HMAC, dedupe, branch filter), GitHub App (private repos, installation tokens, commit statuses) | a push to `main` of a private repo deploys automatically and sets a commit status |
| 12 | Hardening | outbox, `Idempotency-Key`, reconciler, auto-revert, timeout audit, failure-injection suite, backup/restore drill, `SECURITY.md` | every row of the §15 table passes |
| 13 | Observability | metrics, tracing through the queue, Grafana dashboard, alerts, Loki for platform and runtime logs | one trace spans API → broker → worker → Kubernetes; runtime logs survive a pod restart |
| 14 | AWS & Terraform | bootstrap state config, Terraform modules, remote state, budget alert, `terraform plan` in CI | `terraform apply` builds an environment from scratch; `destroy` removes it |
| 15 | Cloud & CD | control plane on cloud Kubernetes, sandboxed builds (rootless BuildKit in ephemeral Jobs), ECR, RDS, HTTPS, wildcard DNS, CD with promotion | `git push` to the sample repo → public HTTPS URL; a build cannot reach platform credentials, the metadata endpoint or the platform namespace |
| 16 | Product completion | API keys + Go CLI, custom domains with automatic TLS, email verification + password reset | `runvia deploy --wait` works with an API key; a verified custom domain serves the app over HTTPS; reset tokens are single-use and expire |
| 17 | Extensions (pick, after v1.0) | preview environments · blue/green · canary · HPA · chaos experiments · SQS adapter | each with an ADR and tests |

**v1.0 (production-ready)** means Phases 0–16 are done: a user registers, verifies their email, connects a private repo, deploys by push and gets a public HTTPS URL (or their own domain), with logs, history, rollback, an API and a CLI. Builds are sandboxed. The system is tested at every layer, observable, rebuilt from Terraform, and documented, with ADRs and a runbook.

---

## 24. Rules for coding agents

1. **Production standard.** Write what a strong team would approve in code review. Never simplify, stub or pick a toy approach because the developer is learning; teach in the explanation instead.
2. Read `README.md`, `docs/ARCHITECTURE.md` and this spec before changing architecture. Stay within the current phase unless asked.
3. Ship tests with every feature, a migration with every schema change, and doc/ADR updates with every architectural change.
4. Preserve tenant isolation and the role matrix. Never hard-code, commit or log secrets.
5. Keep business logic out of route handlers, and infrastructure code behind the §16 adapters.
6. Use typed Python (mypy strict), meaningful error codes, and structured logs with request and correlation IDs.
7. Make jobs idempotent. Give every network call and subprocess a timeout.
8. Prefer maintained, widely used libraries for solved problems. Hand-roll only Runvia's own domain logic, or code no library fits, and say why.
9. No demo, placeholder or dead code in the repository. Experiments live outside it.
10. Every change passes the quality gate (§18) and lands through a pull request (§19). The developer runs every Git and pull-request command; agents never branch, commit, push, merge or open pull requests, and only propose the branch names, commit messages and PR text. Commits, PR text, code and docs carry no tool attribution: no co-author trailers and no "generated with" lines.
11. Keep `make dev` and the local path working.
12. Never replace a simple working implementation with a more complex one just for the look of sophistication.
