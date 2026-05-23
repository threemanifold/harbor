import { expect, test } from '@playwright/test';

/**
 * Real-backend walkthrough for SYM-215.
 *
 * Mirrors the mocked ``chat-e2e.spec.ts`` flow but lets the chat traffic
 * flow through to a *live* Harbor backend that proxies to the
 * SYM-213-deployed Qwen Modal endpoint. The catalog / deployments /
 * lifecycle SSE are still stubbed so the recording is deterministic from
 * "load app" through "Healthy".
 *
 * # Why the gate
 *
 * The orchestration sandbox cannot reach ``*.modal.run`` (only
 * ``api.modal.com`` is in ``/etc/hosts``). Running this spec therefore has
 * to happen from a host with public-internet egress; ``HARBOR_LIVE_CHAT=1``
 * opts that host in.
 *
 * # Preconditions
 *
 * 1. Backend running locally with the SYM-213 ``.env`` in place:
 *
 *      uv run --directory backend uvicorn harbor.main:app --port 8000
 *
 *    The backend's ``modal_catalog`` adapter reads ``MODAL_WEB_URL_3B`` /
 *    ``MODAL_WEB_URL_7B`` from ``backend/.env``; those resolve to the live
 *    Modal Functions.
 *
 * 2. Frontend ``preview`` server pointed at the backend:
 *
 *      VITE_HARBOR_API_BASE=http://127.0.0.1:8000 pnpm --filter frontend build
 *      pnpm --filter frontend preview --port 4173 --strictPort
 *
 * 3. ``HARBOR_LIVE_CHAT=1 pnpm --filter frontend e2e chat-live.spec.ts``.
 *
 * The recording produced by Playwright is the artefact attached to
 * SYM-215 as the "real-backend walkthrough".
 */

const LIVE = process.env.HARBOR_LIVE_CHAT === '1';

const CATALOG = [
  {
    identifier: 'Qwen/Qwen2.5-3B-Instruct',
    parameters_billion: 3.09,
    native_dtype: 'bf16',
    max_context: 32_768,
    weights_size_gb: 6.2,
  },
  {
    identifier: 'Qwen/Qwen2.5-7B-Instruct',
    parameters_billion: 7.62,
    native_dtype: 'bf16',
    max_context: 32_768,
    weights_size_gb: 15.2,
  },
];

const DEPLOYMENT_ID = 'dep_live_walkthrough';
// The backend's real Modal endpoint URL — kept here only for header display
// in the recording. The browser never talks to it directly; the chat panel
// goes through the local backend proxy.
const ENDPOINT_URL =
  process.env.MODAL_WEB_URL_7B ??
  'https://sametbalkan1--harbor-qwen-vllm-serve-7b.modal.run/v1';

function provisioningTranscript(): string {
  const frames: string[] = [];
  const push = (data: Record<string, unknown>): void => {
    frames.push(`data: ${JSON.stringify(data)}\n\n`);
  };
  const at = (offsetMs: number): string =>
    new Date(Date.parse('2026-05-23T12:00:00Z') + offsetMs).toISOString();
  push({ type: 'requested', deployment_id: DEPLOYMENT_ID, at: at(0) });
  push({
    type: 'compiled',
    deployment_id: DEPLOYMENT_ID,
    at: at(200),
    model: 'Qwen/Qwen2.5-7B-Instruct',
    runtime: 'vllm',
    quantization: 'awq',
    context_len: 32_768,
  });
  push({
    type: 'placed',
    deployment_id: DEPLOYMENT_ID,
    at: at(400),
    provider: 'modal',
    region: 'us-east',
  });
  push({ type: 'provisioning', deployment_id: DEPLOYMENT_ID, at: at(600) });
  push({
    type: 'progress',
    deployment_id: DEPLOYMENT_ID,
    at: at(800),
    percent: 60,
    message: 'pulling weights',
  });
  push({ type: 'starting', deployment_id: DEPLOYMENT_ID, at: at(1_000) });
  push({
    type: 'healthy',
    deployment_id: DEPLOYMENT_ID,
    at: at(1_200),
    endpoint_url: ENDPOINT_URL,
  });
  frames.push('event: terminal\ndata: {}\n\n');
  return frames.join('');
}

test.describe('live Qwen walkthrough', () => {
  test.skip(!LIVE, 'set HARBOR_LIVE_CHAT=1 to record against the real backend');

  test('user provisions, opens chat, and chats with the real Modal endpoint', async ({
    page,
  }) => {
    // Stub catalog so the recording always shows both Qwen options.
    await page.route('**/catalog', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(CATALOG),
      });
    });

    // Short-circuit POST /deployments so we don't actually spin up a Modal
    // function from a Playwright run. The "deployment" is a synthetic ID we
    // surface in the URL; the chat path passes the *model identifier* to the
    // backend, which it ignores because the proxy looks up the endpoint by
    // deployment_id from the repository.
    //
    // ↳ For this walkthrough we instead pre-seed the backend repository
    //   with a HEALTHY deployment whose ``endpoint_url`` matches the real
    //   Modal Function URL. See the README "Try the Qwen flow locally"
    //   section for the helper command that does that.
    await page.route('**/deployments', async (route) => {
      if (route.request().method() !== 'POST') {
        await route.fallback();
        return;
      }
      await route.fulfill({
        status: 202,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ deployment_id: DEPLOYMENT_ID }),
      });
    });

    await page.route(
      `**/deployments/${DEPLOYMENT_ID}/events`,
      async (route) => {
        const frames = provisioningTranscript().split(/(?<=\n\n)/);
        const body = await new Promise<Buffer>((resolve) => {
          const chunks: string[] = [];
          let i = 0;
          const tick = (): void => {
            if (i >= frames.length) {
              resolve(Buffer.from(chunks.join('')));
              return;
            }
            chunks.push(frames[i]);
            i += 1;
            setTimeout(tick, 250);
          };
          tick();
        });
        await route.fulfill({
          status: 200,
          headers: {
            'Content-Type': 'text/event-stream',
            'Cache-Control': 'no-cache',
          },
          body,
        });
      },
    );

    // GET /deployments/{id} — only matched if the chat screen re-fetches.
    // We let the request fall through to the real backend so the chat
    // header shows whatever the backend has on file.

    await page.goto('/');
    await expect(
      page.getByRole('heading', { level: 1, name: 'Pick a model' }),
    ).toBeVisible();
    await page.getByRole('button', { name: /provision endpoint/i }).click();

    const healthyItem = page.locator(
      '.harbor-timeline__item[data-step="healthy"]',
    );
    await expect(healthyItem).toHaveAttribute('data-status', 'done', {
      timeout: 30_000,
    });

    await page.getByRole('link', { name: /open chat/i }).click();
    await expect(
      page.getByRole('heading', { level: 1, name: 'Chat' }),
    ).toBeVisible();

    const message = page.getByLabel('Message');
    await message.fill('Hello Qwen, who are you?');
    await message.press('Control+Enter');

    // The real Modal Qwen endpoint typically streams the first token under
    // 5s once the container is warm; allow a generous timeout for cold
    // starts.
    await expect(
      page.locator('.harbor-chat__bubble--assistant'),
    ).toBeVisible({ timeout: 60_000 });
    await expect(
      page
        .locator('.harbor-chat__bubble--assistant')
        .first()
        .locator('.harbor-chat__content'),
    ).not.toBeEmpty({ timeout: 60_000 });

    // Wait for the streaming caret to disappear (= ``[DONE]`` received).
    await expect(
      page.locator(
        '.harbor-chat__bubble--assistant[data-streaming="false"]',
      ),
    ).toBeVisible({ timeout: 120_000 });
  });
});
