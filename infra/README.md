# infra

Infrastructure for running Runvia itself (not tenant apps):

- `compose/`: local PostgreSQL, Redis, RabbitMQ. Phases 0–6.
- `k8s/`: Kustomize manifests for the platform. Phases 8 and 15.
- `terraform/`: AWS environments. Phase 14.

See spec §16 and §20.
