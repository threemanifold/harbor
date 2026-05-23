# Repository Diary

Date: 2026-05-23

## Summary

Harbor is a small full-stack monorepo for a bring-your-own-cloud language model
deployment control plane. The repository currently contains a React/Vite
frontend, a Python/FastAPI backend, shared workspace orchestration through pnpm
and Turborepo, and CI that validates both sides of the stack.

The backend is the most developed part of the codebase. It models a deployment
lifecycle with explicit domain objects, ports, events, provider-placement
concepts, and one application use case that orchestrates deployment creation.
The frontend is still a minimal placeholder app with a title, counter, and
basic render tests.

## Repository Layout

- `README.md` documents Harbor's purpose, prerequisites, setup, development,
  test, and lint commands.
- `package.json`, `pnpm-workspace.yaml`, `pnpm-lock.yaml`, and `turbo.json`
  define the JavaScript monorepo workspace and top-level scripts.
- `apps/frontend/` contains a React 19, TypeScript, Vite, Vitest, and ESLint
  frontend package.
- `backend/` contains the Python 3.13 FastAPI backend managed by `uv`.
- `.github/workflows/ci.yml` runs backend and frontend checks on pushes to
  `main` and pull requests.
- `.codex/` contains automation scripts and workflow skills used by the
  orchestration environment.

## Backend State

The backend follows an onion-style layout:

- `harbor.domain` contains pure domain types and behavior.
- `harbor.application` contains use case orchestration.
- `harbor.infrastructure` is present as adapter namespace scaffolding.
- `harbor.interfaces` is present as HTTP and realtime interface scaffolding.
- `harbor.composition` is reserved for wiring.
- `harbor.config` is reserved for configuration.

Implemented backend behavior:

- `harbor.main` exposes a FastAPI app with a `/health` endpoint.
- `harbor.domain.deployment` implements a deployment aggregate and state
  machine covering requested, compiled, placed, provisioning, starting,
  healthy, degraded, terminating, terminated, and failed states.
- Domain modules define value objects for catalog entries, endpoints,
  identifiers, placement, provider plans, recipes, resources, workflow
  requests, and deployment events.
- Domain ports define protocols for clocks, repositories, event buses, ID
  factories, model catalogs, provider adapters, and connected provider
  registries.
- Domain service protocols define placement policy, recipe compilation, and
  resource resolution boundaries.
- `harbor.application.use_cases.create_deployment.CreateDeployment` orchestrates
  deployment creation through domain ports and provider adapters, including
  catalog lookup, recipe compilation, resource resolution, placement selection,
  provider planning, provisioning progress, endpoint readiness, and failure
  handling.

Backend gaps and risks:

- Infrastructure adapters are namespace placeholders only; persistence,
  catalog, clock, eventing, provider, and proxy implementations are not present.
- Interface packages are namespace placeholders; no HTTP routes beyond `/health`
  and no realtime API are implemented.
- Composition and configuration are empty, so production dependency wiring is
  not yet represented.
- The use case is well-covered with fakes, but there is not yet an end-to-end
  API path that exercises it through FastAPI.

## Frontend State

The frontend is intentionally minimal:

- `apps/frontend/src/App.tsx` renders a `Harbor` heading, a count label, and an
  increment button.
- `apps/frontend/src/App.test.tsx` verifies the heading and initial count.
- `apps/frontend/src/index.tsx`, `index.css`, and `setupTests.ts` provide the
  expected Vite/Vitest app bootstrap.

Frontend gaps and risks:

- No Harbor-specific product workflow is implemented yet.
- The frontend is not connected to the backend.
- There is no routing, API client, state management, design system, deployment
  flow, provider connection UI, or realtime status UI.

## Tooling And Quality Gates

Top-level scripts:

- `pnpm dev:frontend` starts the Vite frontend.
- `pnpm dev:backend` starts FastAPI via uvicorn.
- `pnpm test` delegates to `./.codex/scripts/run-tests.sh`.
- `pnpm test:frontend` runs Vitest.
- `pnpm test:backend` runs pytest through `uv`.
- `pnpm lint` runs Turborepo lint tasks.
- `pnpm build` runs Turborepo build tasks.

Backend tooling:

- Python is pinned to `==3.13.*`.
- Runtime dependencies are FastAPI, Uvicorn, and Pydantic.
- Development dependencies include pytest, pytest-asyncio, httpx, ruff, mypy,
  and import-linter.
- Mypy is configured in strict mode.
- Import-linter contracts enforce the onion architecture, configuration
  isolation, use-case independence, and use-case dependency on strategy
  protocols rather than application service implementations.

Frontend tooling:

- React 19, TypeScript, Vite, Vitest, Testing Library, ESLint, and jsdom are
  configured.
- Node 22 and pnpm 10 are expected by README and CI.

CI:

- Backend CI runs `uv sync --all-groups`, `ruff check`, `mypy`, `lint-imports`,
  and `pytest`.
- Frontend CI runs `pnpm install`, `pnpm lint`, `pnpm test:run`, and
  `pnpm build`.

## Test Coverage Observed

Backend tests cover:

- FastAPI `/health`.
- Domain value-object import and immutability smoke tests.
- Domain port import smoke tests.
- Deployment aggregate state transitions, event buffering, invalid transitions,
  terminal states, and lifecycle behavior.
- `CreateDeployment` orchestration with fakes for success and failure paths.

Frontend tests cover:

- Rendering the `Harbor` heading.
- Rendering the initial counter state.

Coverage is strongest in the backend domain and application orchestration
layers. Coverage is intentionally shallow for the frontend because the frontend
currently has little product behavior.

## Git And Hygiene Notes

- The repository was clean before adding this diary.
- The initial checkout was `main` tracking `origin/main`.
- `origin/main` was fetched and merged before the diary was created; the branch
  was already up to date.
- A feature branch named `sym-207-repo-update` was created for this report.
- `node_modules/` exists in the working tree and is ignored by the file search
  used for this analysis.

## Recommended Follow-Ups

- Implement composition wiring for the backend once concrete infrastructure
  adapters exist.
- Add HTTP routes that expose deployment creation and status read models.
- Add at least one real provider or mock provider adapter behind the domain
  provider port.
- Replace the frontend counter placeholder with the first Harbor workflow:
  model selection, provider connection state, deployment request submission,
  and deployment status display.
- Add end-to-end tests once an HTTP deployment path and frontend workflow exist.


---

Date: 2026-05-23 (SYM-215 — Qwen e2e milestone)

## Qwen end-to-end milestone

SYM-208 (the umbrella ticket "a user can chat with Qwen") is satisfied with
the merge of SYM-215. The full flow now lives in the repo:

- **Backend** exposes `POST /deployments`, an SSE lifecycle stream at
  `GET /deployments/{id}/events`, and the OpenAI-compatible chat proxy
  at `POST /deployments/{id}/chat` that strips the upstream bearer.
- **Frontend** ships three screens — `PickModel`, `Provisioning`, and the
  new `Chat` panel — wired by a hash-based router. The chat panel parses
  OpenAI SSE deltas via `src/api/chat-stream.ts` and renders the assistant
  response token-by-token. Conversation history is kept in component
  state; no backend persistence yet (intentional, per the SYM-215 scope).
- **Modal** hosts the actual Qwen 2.5 7B (AWQ-INT4) and 3B vLLM Functions
  (SYM-213). The Harbor backend reads their URLs from `backend/.env` and
  proxies user messages through.

## Notable shape decisions in SYM-215

- The chat hash route carries `?model=` and `?endpoint=` query params so
  the chat header can show the user which model they are talking to
  without an extra round-trip. `Provisioning` bakes these into the
  `Open chat` CTA href from the `compiled` and `healthy` lifecycle
  events.
- `chat-stream.ts` is the single place that knows the wire format. It
  understands both `data: ...` SSE frames and bare-JSON NDJSON lines so
  the proxy stays a true pass-through if a future vLLM build switches
  formats.
- The composer accepts <kbd>Cmd/Ctrl + Enter</kbd> as the submit
  shortcut and lets plain <kbd>Enter</kbd> insert a newline — so users
  can compose multi-line prompts.

## Walkthroughs

- `apps/frontend/e2e/chat-e2e.spec.ts` — the canonical mocked walkthrough
  recorded into `walkthroughs/*.webm` and attached to SYM-215.
- `apps/frontend/e2e/chat-live.spec.ts` — the same gestures against the
  live SYM-213 Modal endpoint. Skipped unless `HARBOR_LIVE_CHAT=1` is set,
  because the orchestration sandbox cannot reach `*.modal.run` (only
  `api.modal.com` is whitelisted in `/etc/hosts`). The live recording is
  followed up as a manual run from a host with public-internet egress.

## Where to go next

- Persist conversation history server-side once authentication lands.
- Surface streaming usage metrics (tokens/sec, first-token latency) on
  the chat header.
- Add tool-call rendering for OpenAI tool/function responses.
