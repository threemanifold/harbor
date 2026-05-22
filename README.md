# Harbor

A control plane for running language models in your own cloud. Pick a model and
a workflow, connect your provider account (Modal, GCP, AWS, …), and Harbor
orchestrates a deployment into your infrastructure. Bring-your-own-cloud, web
UI, teams from day one.

## Layout

```
apps/
  frontend/    React 19 + TypeScript + Vite + Vitest + ESLint.
backend/       Python 3.13 + FastAPI + uv. ruff + mypy strict + pytest.
               Onion architecture: domain / application / infrastructure /
               interfaces / composition.
.codex/
  skills/      commit, push, pull, land
  scripts/     run-tests.sh, commit-and-push.sh, open-pr.sh,
               linear-workpad.sh, linear-state.sh
.github/
  workflows/   ci.yml — runs backend + frontend checks on PR.
```

## Prerequisites

- Node 22+, pnpm 10
- Python 3.13, [uv](https://docs.astral.sh/uv/)

## First-time setup

```sh
pnpm install
uv sync --directory backend --all-groups
```

## Dev

```sh
pnpm dev:frontend   # vite dev server
pnpm dev:backend    # uvicorn --reload on http://127.0.0.1:8000
```

## Test

Single command runs both suites with terse output:

```sh
pnpm test            # ./.codex/scripts/run-tests.sh
```

Or per-side:

```sh
pnpm test:frontend
pnpm test:backend
```

## Lint / format

```sh
pnpm lint            # tsc + eslint (frontend); add ruff/mypy via uv for backend
pnpm lint:fix
```

Backend ruff/mypy:

```sh
uv run --directory backend ruff check .
uv run --directory backend mypy .
```
