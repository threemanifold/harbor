/**
 * Typed Harbor backend client used by the model picker + provisioning screens.
 *
 * Mirrors the pydantic schemas from `backend/harbor/interfaces/http/schemas`
 * (see SYM-212). Kept dependency-free on purpose — `fetch` and `EventSource`
 * are both in the modern browser baseline that the rest of the Vite/React 19
 * app already targets.
 */

// ---------- Wire types ----------

export type WorkflowType = 'chat' | 'finetune' | 'steer';
export type Priority = 'latency' | 'throughput' | 'quality' | 'cost';

export type DeploymentState =
  | 'PENDING'
  | 'COMPILED'
  | 'PLACED'
  | 'PROVISIONING'
  | 'STARTING'
  | 'HEALTHY'
  | 'DEGRADED'
  | 'TERMINATING'
  | 'TERMINATED'
  | 'FAILED';

export interface CatalogEntry {
  identifier: string;
  parameters_billion: number;
  native_dtype: string;
  max_context: number;
  weights_size_gb: number;
}

export interface DeploymentRequest {
  model_ref: string;
  workflow_type: WorkflowType;
  priority: Priority;
}

export interface DeploymentResponse {
  deployment_id: string;
}

export interface DeploymentStatus {
  deployment_id: string;
  state: DeploymentState;
  endpoint_url: string | null;
  failure_reason: string | null;
  created_at: string;
  updated_at: string;
}

// ---------- Event types ----------

interface EventBase {
  deployment_id: string;
  at: string;
}

export interface DeploymentRequestedEvent extends EventBase {
  type: 'requested';
}
export interface DeploymentCompiledEvent extends EventBase {
  type: 'compiled';
  model: string;
  runtime: string;
  quantization: string;
  context_len: number;
}
export interface DeploymentPlacedEvent extends EventBase {
  type: 'placed';
  provider: string;
  region: string;
}
export interface DeploymentProvisioningEvent extends EventBase {
  type: 'provisioning';
}
export interface DeploymentStartingEvent extends EventBase {
  type: 'starting';
}
export interface DeploymentProgressEvent extends EventBase {
  type: 'progress';
  percent: number;
  message: string;
}
export interface DeploymentHealthyEvent extends EventBase {
  type: 'healthy';
  endpoint_url: string;
}
export interface DeploymentDegradedEvent extends EventBase {
  type: 'degraded';
  reason: string;
}
export interface DeploymentTerminatingEvent extends EventBase {
  type: 'terminating';
}
export interface DeploymentTerminatedEvent extends EventBase {
  type: 'terminated';
}
export interface DeploymentFailedEvent extends EventBase {
  type: 'failed';
  reason: string;
}

export type DeploymentEvent =
  | DeploymentRequestedEvent
  | DeploymentCompiledEvent
  | DeploymentPlacedEvent
  | DeploymentProvisioningEvent
  | DeploymentStartingEvent
  | DeploymentProgressEvent
  | DeploymentHealthyEvent
  | DeploymentDegradedEvent
  | DeploymentTerminatingEvent
  | DeploymentTerminatedEvent
  | DeploymentFailedEvent;

// ---------- Errors ----------

export class HarborApiError extends Error {
  readonly status: number;
  readonly body: unknown;
  constructor(status: number, body: unknown, message?: string) {
    super(message ?? `Harbor API error: ${status}`);
    this.name = 'HarborApiError';
    this.status = status;
    this.body = body;
  }
}

// ---------- Client ----------

/**
 * Default backend base URL. When the frontend is served by Vite on a different
 * port from the backend, set `VITE_HARBOR_API_BASE` (e.g. `http://localhost:8000`).
 */
function defaultBaseUrl(): string {
  // `import.meta.env` is populated by Vite at build time. The check guards
  // against test environments (jsdom) where `import.meta.env` is absent.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const env = (import.meta as any).env as Record<string, string> | undefined;
  if (env?.VITE_HARBOR_API_BASE) return env.VITE_HARBOR_API_BASE;
  return '';
}

export interface HarborClientOptions {
  baseUrl?: string;
  fetch?: typeof fetch;
  eventSourceCtor?: typeof EventSource;
}

export class HarborClient {
  private readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;
  private readonly EventSourceCtor: typeof EventSource;

  constructor(opts: HarborClientOptions = {}) {
    this.baseUrl = (opts.baseUrl ?? defaultBaseUrl()).replace(/\/+$/, '');
    this.fetchImpl = opts.fetch ?? globalThis.fetch.bind(globalThis);
    this.EventSourceCtor = opts.eventSourceCtor ?? globalThis.EventSource;
  }

  private url(path: string): string {
    return `${this.baseUrl}${path}`;
  }

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await this.fetchImpl(this.url(path), init);
    if (!res.ok) {
      let body: unknown = undefined;
      try {
        // ``clone`` so a JSON parse failure doesn't consume the body — we
        // still need it intact to fall through to ``text()``.
        body = await res.clone().json();
      } catch {
        try {
          body = await res.text();
        } catch {
          body = undefined;
        }
      }
      throw new HarborApiError(res.status, body);
    }
    return (await res.json()) as T;
  }

  /** ``GET /catalog`` */
  listCatalog(): Promise<CatalogEntry[]> {
    return this.request<CatalogEntry[]>('/catalog');
  }

  /** ``POST /deployments`` */
  createDeployment(req: DeploymentRequest): Promise<DeploymentResponse> {
    return this.request<DeploymentResponse>('/deployments', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    });
  }

  /** ``GET /deployments/{id}`` */
  getDeployment(deploymentId: string): Promise<DeploymentStatus> {
    return this.request<DeploymentStatus>(
      `/deployments/${encodeURIComponent(deploymentId)}`,
    );
  }

  /**
   * Open an SSE subscription for ``GET /deployments/{id}/events``.
   *
   * Returns the underlying ``EventSource`` so callers can ``.close()`` it on
   * unmount. Each lifecycle event is delivered through `onEvent`; transport
   * errors (the upstream closing without a terminal frame, network loss) are
   * surfaced through `onError`.
   */
  streamDeploymentEvents(
    deploymentId: string,
    handlers: {
      onEvent: (event: DeploymentEvent) => void;
      onError?: (err: Event) => void;
      onTerminal?: () => void;
    },
  ): EventSource {
    const source = new this.EventSourceCtor(
      this.url(`/deployments/${encodeURIComponent(deploymentId)}/events`),
    );
    source.onmessage = (msg: MessageEvent<string>) => {
      try {
        const parsed = JSON.parse(msg.data) as DeploymentEvent;
        handlers.onEvent(parsed);
      } catch {
        // Ignore non-JSON payloads (e.g. comments/keepalives). The backend
        // doesn't currently emit any, but be defensive.
      }
    };
    // The backend emits a final ``event: terminal`` frame after HEALTHY/FAILED.
    // EventSource routes non-default event types through addEventListener.
    source.addEventListener('terminal', () => {
      handlers.onTerminal?.();
      source.close();
    });
    if (handlers.onError) {
      source.onerror = handlers.onError;
    }
    return source;
  }
}

/** Convenience singleton wired to the default base URL. */
export const harborClient = new HarborClient();
