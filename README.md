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

## Try the Qwen flow locally

The Harbor MVP is wired end-to-end against a real Qwen model running on
Modal. Once SYM-213's `modal deploy` has shipped to a workspace, the
following sequence lets you exercise the full user journey from a clean
checkout:

```sh
# 1. Start the backend. backend/.env (gitignored) must contain
#    MODAL_TOKEN_ID / MODAL_TOKEN_SECRET / HF_TOKEN / MODAL_WORKSPACE /
#    MODAL_WEB_URL_3B / MODAL_WEB_URL_7B per SYM-213.
uv run --directory backend uvicorn harbor.main:app --port 8000

# 2. Build + preview the frontend, pointed at the local backend.
VITE_HARBOR_API_BASE=http://127.0.0.1:8000 pnpm --filter frontend build
pnpm --filter frontend preview --port 4173 --strictPort
```

Open <http://127.0.0.1:4173/> and:

1. Pick **Qwen/Qwen2.5-7B-Instruct** (default-selected).
2. Click **Provision endpoint** → watch the timeline march to **Healthy**.
3. Click **Open chat** → land on `/deployments/{id}/chat`.
4. Type `Hello Qwen, who are you?` and press <kbd>Cmd/Ctrl + Enter</kbd>.
5. Watch the streamed reply land token-by-token.

The chat panel posts OpenAI-compatible chat completions bodies to
`POST /deployments/{id}/chat`. The upstream bearer token never leaves the
backend — open DevTools → Network → request to `/chat` → no
`Authorization` header on the request, no token in the response body.

### Recording the walkthroughs

Two Playwright specs live under `apps/frontend/e2e/`:

- `chat-e2e.spec.ts` — fully mocked walkthrough. Deterministic, runs in
  CI; produces the canonical `.webm`.
- `chat-live.spec.ts` — same gestures, but lets `POST /deployments/{id}/chat`
  flow through to a real running backend. Skipped unless
  `HARBOR_LIVE_CHAT=1` is set, since it requires public-internet egress
  to `*.modal.run`.

Helper scripts:

```sh
./.claude/scripts/record-walkthrough.sh e2e/chat-e2e.spec.ts
./.claude/scripts/attach-walkthrough.sh SYM-215 walkthroughs/<file>.webm
```
