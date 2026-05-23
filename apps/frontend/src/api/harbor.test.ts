import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { HarborApiError, HarborClient } from './harbor';
import type { DeploymentEvent } from './harbor';

/**
 * Minimal in-memory EventSource stand-in. Real implementations send a single
 * `data:` payload per call to `emit`; the tests drive it with the same shape
 * the backend sends.
 */
class FakeEventSource {
  static instances: FakeEventSource[] = [];

  readonly url: string;
  onmessage: ((ev: MessageEvent<string>) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  private listeners = new Map<string, ((ev: Event) => void)[]>();
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (ev: Event) => void): void {
    const existing = this.listeners.get(type) ?? [];
    existing.push(listener);
    this.listeners.set(type, existing);
  }

  emit(data: unknown): void {
    this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(data) }));
  }

  emitRaw(data: string): void {
    this.onmessage?.(new MessageEvent('message', { data }));
  }

  emitTerminal(): void {
    for (const l of this.listeners.get('terminal') ?? []) {
      l(new Event('terminal'));
    }
  }

  fail(): void {
    this.onerror?.(new Event('error'));
  }

  close(): void {
    this.closed = true;
  }
}

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

describe('HarborClient — request handling', () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('GET /catalog returns parsed entries and uses provided baseUrl', async () => {
    const entries = [
      {
        identifier: 'Qwen/Qwen2.5-7B-Instruct',
        parameters_billion: 7.62,
        native_dtype: 'bf16',
        max_context: 32768,
        weights_size_gb: 15.2,
      },
    ];
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(entries));
    const client = new HarborClient({
      baseUrl: 'https://harbor.test',
      fetch: fetchImpl as unknown as typeof fetch,
      eventSourceCtor: FakeEventSource as unknown as typeof EventSource,
    });

    const out = await client.listCatalog();

    expect(fetchImpl).toHaveBeenCalledWith('https://harbor.test/catalog', undefined);
    expect(out).toEqual(entries);
  });

  it('POST /deployments forwards the workflow request and parses the response', async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(jsonResponse({ deployment_id: 'dep_abc' }));
    const client = new HarborClient({
      baseUrl: '',
      fetch: fetchImpl as unknown as typeof fetch,
      eventSourceCtor: FakeEventSource as unknown as typeof EventSource,
    });

    const out = await client.createDeployment({
      model_ref: 'Qwen/Qwen2.5-7B-Instruct',
      workflow_type: 'chat',
      priority: 'latency',
    });

    expect(out).toEqual({ deployment_id: 'dep_abc' });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe('/deployments');
    expect(init.method).toBe('POST');
    expect(init.headers).toEqual({ 'Content-Type': 'application/json' });
    expect(JSON.parse(init.body)).toEqual({
      model_ref: 'Qwen/Qwen2.5-7B-Instruct',
      workflow_type: 'chat',
      priority: 'latency',
    });
  });

  it('GET /deployments/{id} URL-encodes the deployment id', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({
        deployment_id: 'dep abc',
        state: 'HEALTHY',
        endpoint_url: 'https://endpoint',
        failure_reason: null,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      }),
    );
    const client = new HarborClient({
      baseUrl: 'http://api',
      fetch: fetchImpl as unknown as typeof fetch,
      eventSourceCtor: FakeEventSource as unknown as typeof EventSource,
    });

    await client.getDeployment('dep abc');

    expect(fetchImpl).toHaveBeenCalledWith(
      'http://api/deployments/dep%20abc',
      undefined,
    );
  });

  it('throws HarborApiError with parsed JSON body on non-2xx', async () => {
    // Each call gets a fresh Response — once a body is consumed it cannot
    // be re-read by a second invocation.
    const fetchImpl = vi.fn().mockImplementation(
      async () =>
        new Response(JSON.stringify({ detail: 'boom' }), {
          status: 500,
          headers: { 'Content-Type': 'application/json' },
        }),
    );
    const client = new HarborClient({
      baseUrl: 'http://api',
      fetch: fetchImpl as unknown as typeof fetch,
      eventSourceCtor: FakeEventSource as unknown as typeof EventSource,
    });

    await expect(client.listCatalog()).rejects.toBeInstanceOf(HarborApiError);
    try {
      await client.listCatalog();
    } catch (err) {
      expect((err as HarborApiError).status).toBe(500);
      expect((err as HarborApiError).body).toEqual({ detail: 'boom' });
    }
  });

  it('throws HarborApiError with text body when response is not JSON', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response('boom', {
        status: 502,
        headers: { 'Content-Type': 'text/plain' },
      }),
    );
    const client = new HarborClient({
      baseUrl: 'http://api',
      fetch: fetchImpl as unknown as typeof fetch,
      eventSourceCtor: FakeEventSource as unknown as typeof EventSource,
    });

    await expect(client.listCatalog()).rejects.toMatchObject({
      status: 502,
      body: 'boom',
    });
  });
});

describe('HarborClient — streamDeploymentEvents', () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
  });

  function makeClient() {
    return new HarborClient({
      baseUrl: 'http://api',
      fetch: vi.fn() as unknown as typeof fetch,
      eventSourceCtor: FakeEventSource as unknown as typeof EventSource,
    });
  }

  it('opens an EventSource against the events endpoint', () => {
    const client = makeClient();
    client.streamDeploymentEvents('dep_1', { onEvent: () => undefined });
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.instances[0].url).toBe(
      'http://api/deployments/dep_1/events',
    );
  });

  it('parses JSON frames and forwards them to onEvent', () => {
    const client = makeClient();
    const events: DeploymentEvent[] = [];
    client.streamDeploymentEvents('dep_1', { onEvent: (e) => events.push(e) });
    const source = FakeEventSource.instances[0];

    source.emit({ type: 'requested', deployment_id: 'dep_1', at: 't0' });
    source.emit({
      type: 'progress',
      deployment_id: 'dep_1',
      at: 't1',
      percent: 42,
      message: 'half',
    });

    expect(events).toEqual([
      { type: 'requested', deployment_id: 'dep_1', at: 't0' },
      {
        type: 'progress',
        deployment_id: 'dep_1',
        at: 't1',
        percent: 42,
        message: 'half',
      },
    ]);
  });

  it('swallows malformed JSON frames without crashing', () => {
    const client = makeClient();
    const events: DeploymentEvent[] = [];
    client.streamDeploymentEvents('dep_1', { onEvent: (e) => events.push(e) });
    const source = FakeEventSource.instances[0];

    expect(() => source.emitRaw('garbage{')).not.toThrow();
    expect(events).toHaveLength(0);
  });

  it('fires onTerminal and closes the source on the terminal frame', () => {
    const client = makeClient();
    const onTerminal = vi.fn();
    client.streamDeploymentEvents('dep_1', {
      onEvent: () => undefined,
      onTerminal,
    });
    const source = FakeEventSource.instances[0];

    source.emitTerminal();

    expect(onTerminal).toHaveBeenCalledTimes(1);
    expect(source.closed).toBe(true);
  });

  it('forwards transport errors to onError', () => {
    const client = makeClient();
    const onError = vi.fn();
    client.streamDeploymentEvents('dep_1', {
      onEvent: () => undefined,
      onError,
    });
    FakeEventSource.instances[0].fail();
    expect(onError).toHaveBeenCalledTimes(1);
  });
});
