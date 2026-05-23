import { expect, test } from '@playwright/test';

/**
 * End-to-end walkthrough for SYM-214.
 *
 * The flow under test:
 *   1. App loads → GET /catalog returns Qwen 3B + Qwen 7B.
 *   2. User selects the 7B card → clicks "Provision endpoint".
 *   3. POST /deployments returns a deployment_id.
 *   4. App routes to /deployments/{id} → opens SSE stream.
 *   5. SSE emits requested → compiled → placed → provisioning (with progress
 *      events) → starting → healthy, ending in a terminal frame.
 *   6. Healthy screen shows the endpoint URL and an "Open chat" CTA.
 *
 * Backend traffic is stubbed at the network layer via `page.route`.
 */

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

const DEPLOYMENT_ID = 'dep_walkthrough';

/** SSE frames emitted to drive the timeline through the happy path. */
function sseTranscript(): string {
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
    quantization: 'bf16',
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
    at: at(700),
    percent: 30,
    message: 'pulling weights',
  });
  push({
    type: 'progress',
    deployment_id: DEPLOYMENT_ID,
    at: at(900),
    percent: 70,
    message: 'compiling kernels',
  });
  push({ type: 'starting', deployment_id: DEPLOYMENT_ID, at: at(1_100) });
  push({
    type: 'healthy',
    deployment_id: DEPLOYMENT_ID,
    at: at(1_300),
    endpoint_url: 'https://qwen-7b.modal.run/v1',
  });
  // The backend always finishes with the terminal marker after HEALTHY.
  frames.push('event: terminal\ndata: {}\n\n');
  return frames.join('');
}

test('user picks Qwen 7B and watches it provision through to Healthy', async ({
  page,
}) => {
  await page.route('**/catalog', async (route) => {
    await route.fulfill({
      status: 200,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(CATALOG),
    });
  });

  await page.route('**/deployments', async (route) => {
    expect(route.request().method()).toBe('POST');
    expect(JSON.parse(route.request().postData() ?? '{}')).toMatchObject({
      model_ref: 'Qwen/Qwen2.5-7B-Instruct',
      workflow_type: 'chat',
      priority: 'latency',
    });
    await route.fulfill({
      status: 202,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ deployment_id: DEPLOYMENT_ID }),
    });
  });

  await page.route(`**/deployments/${DEPLOYMENT_ID}/events`, async (route) => {
    // Drip-feed frames so the recorded video shows the lifecycle progress,
    // not an instant jump to HEALTHY. Each chunk lands ~350ms apart.
    const frames = sseTranscript().split(/(?<=\n\n)/);
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
        setTimeout(tick, 350);
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
  });

  await page.goto('/');

  // 1. Catalog renders.
  await expect(
    page.getByRole('heading', { level: 1, name: 'Pick a model' }),
  ).toBeVisible();
  await expect(page.getByText('Qwen/Qwen2.5-7B-Instruct')).toBeVisible();
  await expect(page.getByText('7.62B params')).toBeVisible();

  // 2. Select 7B (default-selected) and provision.
  const sevenB = page.getByRole('radio', {
    name: /Qwen\/Qwen2\.5-7B-Instruct/,
  });
  await expect(sevenB).toHaveAttribute('aria-checked', 'true');
  await page.getByRole('button', { name: /provision endpoint/i }).click();

  // 3. Routed to provisioning screen.
  await expect(
    page.getByRole('heading', { level: 1, name: 'Provisioning' }),
  ).toBeVisible();
  await expect(page).toHaveURL(/#\/deployments\/dep_walkthrough$/);

  // 4. Wait for the timeline to march through HEALTHY.
  const healthyItem = page.locator(
    '.harbor-timeline__item[data-step="healthy"]',
  );
  await expect(healthyItem).toHaveAttribute('data-status', 'done', {
    timeout: 15_000,
  });

  // 5. Endpoint URL + Open chat CTA visible.
  await expect(page.getByText('https://qwen-7b.modal.run/v1')).toBeVisible();
  const cta = page.getByRole('link', { name: /open chat/i });
  await expect(cta).toBeVisible();
  await expect(cta).toHaveAttribute(
    'href',
    '#/deployments/dep_walkthrough/chat',
  );
});
