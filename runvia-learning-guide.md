# Runvia — Learning Guide

> A path for learning backend engineering by building Runvia. The [engineering spec](runvia-engineering-spec.md) says **what** to build (its phases, rules and acceptance criteria). This guide says **what to learn, in what order, and how to know you understood it**. Stage *N* here is Phase *N* in the spec.
>
> The guide decides what you study, never what gets built. Runvia's code is held to production standard (spec §24): you learn the way the industry does it, not a simplified version of it.

---

## 1. The idea

> A developer gives Runvia a Git repository and clicks **Deploy**. Runvia builds it into a container image, runs it on Kubernetes, gives it a URL, and lets them manage it.

- **Control plane (you write this).** It answers: Who is the user? Which apps exist? What should be deployed? What was deployed before? What is the status? Who may do what?
- **Runtime (you drive this).** Kubernetes, first as k3d on your laptop, later on AWS. The control plane tells the runtime what to run.

---

## 2. How to learn

Don't front-load theory ("first Kubernetes, then Terraform, then Redis…"). Let the project pull each concept in when a feature needs it:

```text
build something small → hit a need → learn just that concept → apply it → test it → break it → write it down
```

- **When to move on.** Not "have I mastered PostgreSQL?", but "can I use it correctly for this feature, and explain why I designed it this way?"
- **The understanding test.** Use it on every technology. What problem does it solve? What did people do before it? How does it fail, and what happens when it's unavailable? What are the trade-offs? How would I test it? How would I monitor it? What changes at 10× scale?
- **Rhythm per feature** (stretch it to fit your time): read the concept → run a tiny isolated experiment → integrate it → test it → break and fix it → document it → refactor.
- **Learning journal, per feature.** What problem did I solve? What confused me? What did I design wrong at first, and why did I change it? What happens on failure? Which trade-off did I make? What would change at 10×? These notes become your interview answers.
- **Tests from day one**, not at the end: feature → test → implementation → refactor.
- **Experiments stay out of the codebase.** Run them in a scratch directory, a throwaway branch or a sandbox account. What gets committed is production code only.

---

## 3. Toolbox and foundations

**Install:** Git · Python 3.14 and `uv` · Docker with Compose · Node.js and pnpm · kubectl · k3d · Terraform · AWS CLI · Go · make · curl · jq · GitHub CLI (optional).

Foundations should be good enough to be productive now. You'll deepen them as the stages need them.

| Topic | Know | Practice |
|---|---|---|
| Shell | `pwd ls cd mkdir cp mv rm cat less grep find head tail chmod chown ps top kill curl ssh` | use them daily; don't just memorize them |
| Processes | PID, signals (SIGTERM vs SIGKILL), stdout vs stderr, exit codes | `ps aux`, `kill -TERM <pid>`, `echo $?` |
| Files | owner, group, permission bits | `chmod`, `chown` |
| Networking | `localhost`/127.0.0.1, ports, TCP, DNS, HTTP | `curl -v http://localhost:8000` and explain every line of output |
| Git | working tree, staging area, commits, branches, remotes; `init clone status add commit log diff branch switch merge rebase push pull`; resolving conflicts | develop Runvia in small commits |
| HTTP | request/response, headers, cookies; `GET POST PUT PATCH DELETE`; status codes `200 201 202 204 400 401 403 404 409 422 429 500 502 503` | explain 401 vs 403, and 400 vs 409 vs 422 |
| Python | functions, classes, modules/packages, exceptions, typing, dataclasses, context managers, generators, `async`/`await` (when it helps and when it doesn't) | type-check everything with mypy |
| Docker basics | image vs container, ports, volumes, env vars, Compose | run PostgreSQL with Compose; Stage 1 needs it, and Stage 7 goes deeper |

---

## 4. Stages

Each stage lists what to **Learn** before and during the work, what to **Build** (the spec phase has the details), **Experiments** to run, and an **Exit check**: questions you can answer without notes before moving on.

### Stage 0 — Bootstrap
- **Learn:** FastAPI routing, request/response, Pydantic, dependency injection. Project tooling: `uv`, Ruff, mypy, pytest, pre-commit. What CI is for, and why a team sets it up before the second feature. Branches, pull requests and branch protection. What a modular monolith is.
- **Build:** the repo skeleton with its quality gate (Ruff, mypy, pytest, pre-commit, CI required on `main`), `GET /health/live → {"status": "ok"}`, then open `/docs`; request IDs and JSON logging; a Dockerfile; Compose and a Makefile. The first README answers: what is this, how do I run it, what is done, what is next.
- **Experiment:** push a failing test and watch CI block the PR.
- **Exit:** How does a request reach your handler? Where does `/docs` come from? Why start as a modular monolith rather than microservices? (So you learn *when* a service deserves to be split, instead of assuming everything should be.)

### Stage 1 — PostgreSQL
- **Learn:**
  - SQL: tables, primary and foreign keys, `UNIQUE`/`NOT NULL`/`CHECK`, `SELECT INSERT UPDATE DELETE`, `INNER`/`LEFT JOIN`, `WHERE`, `GROUP BY`, `ORDER BY`, `LIMIT`.
  - Transactions and ACID; indexes and `EXPLAIN ANALYZE`.
  - SQLAlchemy 2.x (engine, connection, session, model) and connection pooling.
  - Alembic (autogenerate produces a draft; read it before applying).
- **Build:** the core tables, with one model file per module.
- **Experiments:**
  - Write each query in `psql` before writing it in the ORM.
  - Insert 1M fake deployments and compare `EXPLAIN ANALYZE` for "latest deployments of an app", with and without the index.
  - Create an org and its owner membership in one transaction, and force the second insert to fail. Confirm nothing is left behind.
- **Exit:** What does a transaction protect you from? When does an index help, and what does it cost? What SQL does your ORM query emit? Why test against PostgreSQL and not SQLite?

### Stage 2 — Authentication
- **Learn:**
  - Hashing vs encryption, salts, Argon2.
  - **Authentication ("who are you?") vs authorization ("may you do this?").**
  - Sessions vs tokens. JWT is a *token format*, not an authentication system. Access vs refresh tokens, rotation, revocation.
  - Cookies (`HttpOnly`, `Secure`, `SameSite`) and CSRF.
- **Build:** register/login/refresh/logout/me (spec §11).
- **Experiments:** decode your JWT and notice it is readable, only signed. Replay an old refresh token and watch its family get revoked.
- **Exit:** Why are access tokens short-lived? How does rotation detect a stolen refresh token? Why hash passwords instead of encrypting them? Why must tokens never be logged?

### Stage 3 — Organizations, roles, tenant isolation
- **Learn:** RBAC, multi-tenancy, IDOR (insecure direct object references), audit trails.
- **Build:** memberships, the role matrix (spec §11), a single scoped-access dependency, the audit log.
- **Experiment:** create user A in org A and user B in org B. Call every endpoint as B using A's IDs; every call must return 404. Keep these as permanent tests, because security rules are tested like business logic.
- **Exit:** Why 404 and not 403 across tenants? Where does the authorization check live, and why is hiding a button in the frontend not security?

### Stage 4 — Applications and configuration
- **Learn:** REST resource design, input validation, offset vs cursor pagination, encryption at rest, write-only secrets.
- **Build:** CRUD for apps, repositories and env vars; slug rules; cursor pagination.
- **Exit:** Why are slugs immutable and DNS-safe? Why does cursor pagination stay stable under inserts when offset pagination doesn't? Why is a secret never returned by `GET`?

### Stage 5 — Redis
- **Learn:** cache-aside, TTLs, invalidation, key design. Atomic `INCR`/`EXPIRE`. Why shared state becomes necessary once more than one API instance runs (an in-memory dict isn't shared).
- **Build:** cached application reads and the login rate limit.
- **Experiments:** run two API replicas and trip the rate limit across both. Stop Redis and confirm the API still serves requests.
- **Exit:** What happens to a stale cache entry after a write? Why can't Redis be the source of truth? Which features should fail open, and which fail closed?

### Stage 6 — Queues and workers
- **Learn:**
  - Why long work is asynchronous: a build takes minutes, and an HTTP request shouldn't wait that long.
  - Producer, consumer, queue, exchange, ack/nack, redelivery, prefetch, dead-lettering.
  - Retries with backoff and jitter, at-least-once delivery, idempotency.
  - SIGTERM and graceful shutdown.
- **Build:** the `JobQueue` adapter and the worker's dispatch loop, tested with job types registered only in tests (a quick `hello` experiment is fine in a scratch script, not in the repo). Then add retry queues and the DLQ.
- **Experiments:**
  - Stop the worker, send jobs, then restart it.
  - Kill it mid-job, once with `docker stop` and once with `kill -9`.
  - Publish the same message twice.
  - Make a job that always fails and follow it into the DLQ.
- **Exit:** **What happens if the worker crashes after receiving a message but before acking it?** Which errors deserve a retry (GitHub down) and which don't (Dockerfile syntax error)? Why must every handler be idempotent? Why does the message carry IDs instead of whole rows?

### Stage 7 — Docker images, Git and builds
- **Learn:**
  - Dockerfiles, layers and the build cache, image vs container.
  - Tags vs digests, registries, BuildKit.
  - Enough Git to resolve a branch to a commit SHA.
  - Running subprocesses safely (argv lists, timeouts).
  - Why build input is untrusted code.
- **Build:** the sample app, as its own public GitHub repo with the fixture branches (`broken-build`, `crash-on-start`, `broken-health`, `slow-start`). Then the build job (spec §7.3).
- **Exit:** Why deploy a SHA and a digest, never `main` or `latest`? What exactly can a build access on your machine, and why is that the #1 security problem of any PaaS?

### Stage 8 — Kubernetes
- **Learn one resource at a time.** Apply each one by hand with `kubectl` before generating it in code, and read every field you use:
  1. Pod
  2. Deployment (desired state, ReplicaSets, rolling updates)
  3. Service (a stable address for Pods that come and go)
  4. Ingress (hostname → Service)
  5. ConfigMap and Secret
  6. Readiness vs liveness probes
  7. Requests and limits
  8. Namespace, NetworkPolicy, ResourceQuota, ServiceAccount, RBAC
- **Build:** the runtime adapter (spec §8): `RuntimeSpec` → manifests → apply → wait.
- **Experiments:** `kubectl delete pod` and watch it come back. Deploy `crash-on-start` and `broken-health`, then read `kubectl describe` and the events.
- **Exit:** Why isn't Docker alone enough? How does traffic get from the browser to the ingress, the Service and finally the Pod? What does "desired state" mean, and who makes it true?

### Stage 9 — End-to-end deployment (first big milestone)
- **Learn:** state machines, optimistic concurrency (conditional updates), invariants enforced by the database, why a rollback is a new record rather than an edit.
- **Build:** connect everything (spec §7). When one `POST` turns a repository into a working URL, stop and celebrate: you have built the core of a PaaS.
- **Experiments:** click Deploy twice quickly. Deploy while another deployment is running. Roll back.
- **Exit:** Is `SUCCEEDED → BUILDING` legal, and where is that enforced? What exactly is running right now (commit, digest, deployment number)? What happens if the worker dies after applying to Kubernetes but before updating PostgreSQL?

### Stage 10 — Dashboard
- **Learn:** React and TypeScript, calling an API with cookies, SSE for live logs, clients generated from OpenAPI, server-state caching, accessibility basics (semantic HTML, keyboard navigation, ARIA only where needed), component and E2E testing (Vitest, Playwright). The UI is part of the product and meets the same standard as the backend.
- **Exit:** Why can't the UI be trusted to enforce permissions?

### Stage 11 — GitHub integration
- **Learn:** webhooks, HMAC signatures, duplicate and replayed deliveries. GitHub Apps: app JWTs, short-lived installation tokens, why they beat personal access tokens.
- **CI/CD vs your PaaS:** GitHub Actions builds, tests and deploys *Runvia itself*. Runvia builds and deploys *users' applications*. They are two different pipelines.
- **Exit:** Why doesn't HTTPS alone make a webhook trustworthy?

### Stage 12 — Reliability and distributed systems
- **Learn:**
  - The dual-write problem and the outbox pattern.
  - Reconciliation loops (desired vs actual state; this is how Kubernetes controllers work).
  - Leases, and why a distributed lock doesn't guarantee exclusion.
  - Timeouts everywhere, bounded retries, backpressure, graceful degradation.
  - Strong vs eventual consistency; backups and restores.
- **Failure injection:**
  - Kill the worker.
  - Stop RabbitMQ, then Redis, then PostgreSQL.
  - Make the registry unreachable.
  - Send duplicate jobs and webhooks.
  - Scale a Deployment by hand and watch the reconciler fix it.

  Write down what happened each time; those notes become `docs/OPERATIONS.md`.
- **Exit:** What happens if the DB commit succeeds but the publish fails? Which data needs strong consistency (deployment state) and which may be stale (cache, metrics)? Why is a backup you have never restored only an assumption?

### Stage 13 — Observability
- **Learn:** logs vs metrics vs traces, RED metrics, the Prometheus data model and label cardinality, OpenTelemetry context propagation, log aggregation and retention (Loki).
- **Experiment:** use a single trace to find where a deployment's time went (API 50 ms → queue 2 s → build 80 s → rollout 25 s).
- **Exit:** Why do correlation IDs matter across a queue? Why is one good dashboard better than fifty?

### Stage 14 — AWS and Terraform
- **Learn by hand first, in a throwaway sandbox** (a separate AWS account or a budget-capped one; delete everything afterwards; none of it becomes part of Runvia):
  1. One EC2 instance: SSH, security groups, public vs private IPs, systemd, Docker, Linux logs.
  2. Networking: VPC, subnets, route tables, internet and NAT gateways, security groups, load balancers, DNS. **Draw the traffic paths** and ask "why isn't the database publicly reachable?"
  3. IAM (least privilege, roles vs users), S3 (buckets, keys, permissions, presigned URLs, lifecycle rules), ECR (how Kubernetes authenticates to it), RDS.
- **Then Terraform:** providers, resources, variables, outputs, modules, state (remote, with locking), `plan`/`apply`/`destroy`. Never paste an example you can't explain line by line.
- **Kubernetes path:** A) EC2 + k3s first (cheaper; teaches Linux and cluster operations). B) EKS later (managed control plane, IAM integration, node groups, load-balancer controller).
- **Before you create anything, set a budget alert.** Destroy what you aren't using.
- **Exit:** Why Terraform instead of clicking in the console? Why doesn't Terraform manage tenant deployments? What does a managed service buy you, and what does it cost?

### Stage 15 — Cloud deployment, HTTPS, CD
- **Learn:** TLS, certificates and renewal (cert-manager or ACM), wildcard DNS, secret management (Secrets Manager, rotation), GitHub OIDC to AWS, migration ordering (expand → deploy → contract), promotion between environments. Sandboxed builds: rootless BuildKit, why a build Job gets no credentials, and how NetworkPolicy limits its egress.
- **Exit:** Trace `git push` → public HTTPS URL and name every component along the way. What can a malicious Dockerfile reach in your cloud build, and what stops it?

### Stage 16 — Product completion (v1.0)
- **Learn:**
  - Go, for the `runvia` CLI: goroutines, channels, `context` (cancel on Ctrl-C), HTTP clients, JSON, flag parsing, cross-compiling and releasing a binary.
  - API keys: prefix + secret, hashing for lookup, scoping and revocation.
  - Custom domains: DNS TXT verification, CNAMEs, ACME HTTP-01 certificates.
  - Email flows: single-use expiring tokens, account-enumeration resistance, SMTP and deliverability (SPF, DKIM).
- **Exit:** Why store an API key's hash but show the key once? How do you prove someone controls a domain? Why does `forgot-password` answer the same for unknown emails?

### Stage 17 — Extensions and deep dives (pick by interest)
- **Extensions:** blue/green and canary deployments, HPA, preview environments, chaos experiments. Each one gets an ADR first.
- **Kubernetes internals:** API server, etcd, scheduler, controllers, kubelet. Who stores desired state, who schedules Pods, who notices changes? Your own control plane will make more sense afterwards.
- **Microservices, as a design exercise:** on paper, extract one component (such as the deploy worker) and answer: how does it authenticate? How are its messages versioned? How is it deployed and observed? What happens when it's down? Only split it in the code if the ADR finds a concrete reason.

---

## 5. Capstone: trace one deployment

Once push-to-deploy works, walk the whole path and answer each question from your own code and dashboards:

1. How did GitHub call me, and how did I verify it was GitHub?
2. Where did FastAPI receive the request, and where did the transaction commit?
3. How was the job published, and how did the worker receive it?
4. How did the worker clone the repository and build the image?
5. Where is the image stored, and how did Kubernetes pull it?
6. How did the Pod start, and how does traffic reach it?
7. How did the browser resolve the hostname, and how did HTTPS work?
8. Where are the logs, the metrics and the trace?
9. What happens if any single component dies right now?

---

## 6. Engineering habits

- **Where does code go?**

  | Code | Location |
  |---|---|
  | HTTP handling | `router.py` |
  | Use cases and transactions | `service.py` |
  | Pure rules | `domain.py` |
  | SQL | `store.py` |
  | Third-party systems | `integrations/` |
  | Background work | `worker/` |

  Never write a 5,000-line `main.py`.
- **Thin handlers:** validate → authorize → call the service → return.
- **Abstractions only for a reason:** a real second implementation, a test seam, or an important boundary. Never an `AbstractFactoryFactory`.
- **Ask of every component:**
  - PostgreSQL: what is the source of truth?
  - Redis: why can't PostgreSQL do this?
  - RabbitMQ: why is this asynchronous?
  - Kubernetes: why not Docker alone?
  - Terraform: why not create it manually?
  - AWS: why is this managed?
  - Go: why Go here?
  - OpenTelemetry: what does tracing solve?
- **Commits tell the story:** `feat: add deployment state machine` · `fix: prevent duplicate deployment execution` · `test: add cross-tenant authorization tests` · `docs: document deployment architecture`. Never `stuff`, `update`, `final` or `working`.

---

## 7. Working with a coding agent

- **Never merge code you can't explain.** Architecture decisions stay yours.
- **You run Git yourself:** branches, commits, pushes, pull requests and merges. The agent proposes the commit messages and PR text; reading them before you commit is part of your review.
- **The agent never simplifies code for you.** It writes what a professional team would ship and explains it. If something is too much at once, slow down the explanation, not the standard.
- Work in small steps, never "build the whole PaaS". For example: "Add application creation" → "Explain every file" → "Why is this transaction needed?" → "Write tests for the failure cases" → "Introduce a race condition and show me how it happens" → "Fix it."
- **Prompts that turn the agent into a teacher:**
  - Explain this architecture before changing it.
  - Show the request flow for this endpoint.
  - What happens if PostgreSQL fails here?
  - Write tests for duplicate queue delivery.
  - Find a race condition in this deployment flow.
  - Show the SQL this ORM query generates.
  - Explain this Kubernetes manifest, or this Terraform plan, line by line.
  - Review this code for tenant-isolation bugs.

---

## 8. Traps

1. **Technology collecting.** Kafka + NATS + RabbitMQ + Pulsar just to list them. One queue is enough.
2. **Microservices too early.** Split for a reason, after the monolith works.
3. **Copied YAML or Terraform** you can't explain.
4. **AI-generated code** you don't understand.
5. **Building the periphery first.** A log platform, a plugin framework or multi-cloud support before the core deploy works.
6. **Operational landmines.** Retrying forever, network calls without timeouts, locks without expiry.

---

## 9. If you feel overwhelmed

Ignore everything except these ten steps:

1. `/health`
2. PostgreSQL connection
3. user, organization and application tables
4. authentication
5. application CRUD
6. Redis cache
7. RabbitMQ + fake job
8. build worker
9. Kubernetes deployment
10. one-button deploy from GitHub

Once #10 works, you have a real foundation and everything else is expansion.

> The goal isn't a CV line listing FastAPI, PostgreSQL, Redis, RabbitMQ, Docker, Kubernetes, Terraform, AWS, Go and OpenTelemetry. It is being able to explain **why each one is there, what problem it solves, how it fails, what the trade-offs are, and how the system behaves when things go wrong.**
