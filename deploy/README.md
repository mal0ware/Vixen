# Vixen — deploy/

Production Vixen is co-hosted on **Box A** alongside Kaizen core. The
authoritative deployment artifacts (compose file, provisioning script,
runbook, systemd units, backup config) live in the Kaizen repo:

> [github.com/mal0ware/Kaizen — `deploy/`](https://github.com/mal0ware/Kaizen/tree/master/deploy)

This repo contributes:

- The root [`Dockerfile`](../Dockerfile) — referenced from Box A's
  compose by relative path.
- This pointer file.

To deploy Vixen, follow `Kaizen/deploy/runbook.md`. It clones both
repos as siblings under `/opt/box-a/`, brings up the consolidated
stack, and runs Vixen's alembic migrations as part of first boot.

### Standalone (dev-only) runs

The repo-root `docker-compose.yml` still works for local development
(non-default ports 5433 / 6380 so it coexists with Linger); the Box A
compose in the Kaizen repo is what runs in production.
