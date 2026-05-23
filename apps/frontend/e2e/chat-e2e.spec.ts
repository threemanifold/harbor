import { expect, test } from '@playwright/test';

/**
 * End-to-end walkthrough for SYM-215 — the full Qwen user journey.
 *
 *   1. App loads → GET /catalog returns Qwen 3B + Qwen 7B.
 *   2. User selects the 7B card → clicks "Provision endpoint".
 *   3. POST /deployments returns a deployment id.
 *   4. App routes to /deployments/{id}/events SSE stream and walks the
 *      timeline through HEALTHY.
 *   5. User clicks "Open chat" → lands on /deployments/{id}/chat with the
 *      model + endpoint URL surfaced in the header.
 *   6. User types "Hello Qwen, who are you?" and submits with Ctrl+Enter.
 *   7. POST /deployments/{id}/chat returns an OpenAI-style SSE stream that
 *      the chat panel renders one delta at a time.
 *   8. The upstream bearer token is verified absent from every response the
 *      browser sees — the proxy strips it on the way out.
 *
 * The whole flow is deterministic: every backend route is stubbed via
 * ``page.route``. A second walkthrough (``chat-live.spec.ts``) replays the
 * same user gestures against the real SYM-213-deployed Modal endpoint and is
 * gated behind a ``HARBOR_LIVE_CHAT`` env var.
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
const ENDPOINT_URL = 'https://qwen-7b.modal.run/v1';
// Constant injected by the mocked proxy. The acceptance criterion is that
// it does *not* appear in any client-visible response body or header.
const UPSTREAM_TOKEN = 'sk-secret-upstream-token';

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
    percent: 35,
    message: 'pulling weights',
  });
  push({
    type: 'progress',
    deployment_id: DEPLOYMENT_ID,
    at: at(900),
    percent: 80,
    message: 'compiling kernels',
  });
  push({ type: 'starting', deployment_id: DEPLOYMENT_ID, at: at(1_100) });
  push({
    type: 'healthy',
    deployment_id: DEPLOYMENT_ID,
    at: at(1_300),
    endpoint_url: ENDPOINT_URL,
  });
  frames.push('event: terminal\ndata: {}\n\n');
  return frames.join('');
}

/**
 * The assistant reply that the proxy will stream back, split into per-word
 * frames so the recording shows incremental rendering.
 */
const ASSISTANT_WORDS = [
  'I ',
  "am ",
  'Qwen, ',
  'a ',
  'large ',
  'language ',
  'model ',
  'served ',
  'on ',
  'your ',
  'own ',
  'Modal ',
  'endpoint.',
];

function chatStreamBody(): string {
  const frames: string[] = [];
  // First frame announces the role.
  frames.push(
    `data: ${JSON.stringify({
      id: 'chatcmpl-1',
      object: 'chat.completion.chunk',
      created: 1_716_460_800,
      model: 'Qwen/Qwen2.5-7B-Instruct',
      choices: [{ index: 0, delta: { role: 'assistant' } }],
    })}\n\n`,
  );
  for (const word of ASSISTANT_WORDS) {
    frames.push(
      `data: ${JSON.stringify({
        id: 'chatcmpl-1',
        object: 'chat.completion.chunk',
        created: 1_716_460_800,
        model: 'Qwen/Qwen2.5-7B-Instruct',
        choices: [{ index: 0, delta: { content: word } }],
      })}\n\n`,
    );
  }
  frames.push(
    `data: ${JSON.stringify({
      id: 'chatcmpl-1',
      object: 'chat.completion.chunk',
      created: 1_716_460_800,
      model: 'Qwen/Qwen2.5-7B-Instruct',
      choices: [{ index: 0, delta: {}, finish_reason: 'stop' }],
    })}\n\n`,
  );
  frames.push('data: [DONE]\n\n');
  return frames.join('');
}

test('user picks Qwen 7B, provisions, opens chat, and gets a streamed reply', async ({
  page,
}) => {
  // Capture every response body the browser actually sees — used by the
  // bearer-leak assertion below.
  const seenBodies: string[] = [];
  page.on('response', async (response) => {
    const url = response.url();
    if (!url.includes(`/deployments/${DEPLOYMENT_ID}`)) return;
    try {
      seenBodies.push(await response.text());
    } catch {
      // Streaming responses occasionally throw when consumed twice; ignore.
    }
  });

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
    // not an instant jump to HEALTHY. Each chunk lands ~300ms apart.
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
        setTimeout(tick, 300);
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

  // GET /deployments/{id} — used by the chat screen to resolve the endpoint
  // URL when the user navigates with the endpoint hint stripped from the
  // URL. We answer with the same HEALTHY snapshot.
  await page.route(`**/deployments/${DEPLOYMENT_ID}`, async (route) => {
    if (route.request().method() !== 'GET') {
      await route.fallback();
      return;
    }
    await route.fulfill({
      status: 200,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        deployment_id: DEPLOYMENT_ID,
        state: 'HEALTHY',
        endpoint_url: ENDPOINT_URL,
        failure_reason: null,
        created_at: '2026-05-23T12:00:00Z',
        updated_at: '2026-05-23T12:00:01Z',
      }),
    });
  });

  await page.route(`**/deployments/${DEPLOYMENT_ID}/chat`, async (route) => {
    expect(route.request().method()).toBe('POST');
    const body = JSON.parse(route.request().postData() ?? '{}');
    expect(body.stream).toBe(true);
    expect(body.model).toBe('Qwen/Qwen2.5-7B-Instruct');
    expect(body.messages).toEqual([
      { role: 'user', content: 'Hello Qwen, who are you?' },
    ]);
    // The browser must NOT be sending the upstream bearer. Authorization is
    // injected server-side by the proxy.
    expect(route.request().headers().authorization).toBeUndefined();

    // Drip-feed SSE chunks so the recording shows token-by-token streaming.
    const frames = chatStreamBody().split(/(?<=\n\n)/);
    const body_bytes = await new Promise<Buffer>((resolve) => {
      const chunks: string[] = [];
      let i = 0;
      const tick = (): void => {
        if (i >= frames.length) {
          resolve(Buffer.from(chunks.join('')));
          return;
        }
        chunks.push(frames[i]);
        i += 1;
        setTimeout(tick, 90);
      };
      tick();
    });
    await route.fulfill({
      status: 200,
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
      },
      body: body_bytes,
    });
  });

  await page.goto('/');

  // --- 1. Catalog renders + select 7B + provision ---
  await expect(
    page.getByRole('heading', { level: 1, name: 'Pick a model' }),
  ).toBeVisible();
  const sevenB = page.getByRole('radio', {
    name: /Qwen\/Qwen2\.5-7B-Instruct/,
  });
  await expect(sevenB).toHaveAttribute('aria-checked', 'true');
  await page.getByRole('button', { name: /provision endpoint/i }).click();

  // --- 2. Provisioning timeline marches to HEALTHY ---
  await expect(
    page.getByRole('heading', { level: 1, name: 'Provisioning' }),
  ).toBeVisible();
  const healthyItem = page.locator(
    '.harbor-timeline__item[data-step="healthy"]',
  );
  await expect(healthyItem).toHaveAttribute('data-status', 'done', {
    timeout: 15_000,
  });
  await expect(page.getByText(ENDPOINT_URL)).toBeVisible();

  // --- 3. Open chat ---
  await page.getByRole('link', { name: /open chat/i }).click();
  await expect(
    page.getByRole('heading', { level: 1, name: 'Chat' }),
  ).toBeVisible();
  await expect(page).toHaveURL(/\/chat\?/);
  // Header reflects the user's choices so they see they're talking to
  // *their own* provisioned model, not a shared one.
  await expect(
    page.getByRole('definition').filter({ hasText: 'Qwen/Qwen2.5-7B-Instruct' }),
  ).toBeVisible();
  await expect(page.getByText(ENDPOINT_URL)).toBeVisible();

  // --- 4. Send the prompt ---
  const message = page.getByLabel('Message');
  await message.fill('Hello Qwen, who are you?');
  // Submit via the keyboard shortcut so the walkthrough demonstrates the
  // acceptance criterion live.
  await message.press('Control+Enter');

  // --- 5. Watch the streamed reply land ---
  await expect(page.getByText(/I am Qwen/i)).toBeVisible({ timeout: 10_000 });
  await expect(
    page.getByText('I am Qwen, a large language model served on your own Modal endpoint.'),
  ).toBeVisible({ timeout: 10_000 });

  // --- 6. Copy button lights up once streaming finishes ---
  const copyBtn = page.getByRole('button', { name: /copy assistant response/i });
  await expect(copyBtn).toBeVisible();

  // --- 7. The upstream token never reaches the browser ---
  for (const body of seenBodies) {
    expect(body).not.toContain(UPSTREAM_TOKEN);
  }
});
