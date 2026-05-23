/**
 * Streaming chat completion helper used by the chat panel screen.
 *
 * The SYM-212 backend exposes an OpenAI-compatible proxy at
 * ``POST /deployments/{id}/chat`` which, when called with ``stream: true``,
 * forwards the upstream's SSE body verbatim. This module wraps the browser
 * ``fetch`` + ``ReadableStream`` plumbing required to consume that body and
 * surface incremental assistant deltas to React state.
 *
 * The wire format is the OpenAI streaming standard:
 *
 *   data: {"id": "...", "choices": [{"index": 0, "delta": {"content": "Hi"}}]}
 *   data: {"id": "...", "choices": [{"index": 0, "delta": {"content": " there"}}]}
 *   data: [DONE]
 *
 * NDJSON (one JSON object per line with no ``data:`` prefix) is also accepted
 * to keep the parser tolerant of upstream variations — vLLM is canonical SSE
 * today, but the proxy is intentionally pass-through.
 */

/** Internal delta surfaced by the parser. */
export interface AssistantDelta {
  /** Text content appended to the assistant response by this frame. */
  content: string;
  /** ``true`` for the terminal ``[DONE]`` marker (no content). */
  done?: boolean;
}

/**
 * Parse a single SSE/NDJSON line into a delta.
 *
 * Returns ``null`` for blank lines, SSE comments, keepalives, and
 * unparseable payloads — the consumer should treat ``null`` as "ignore".
 */
export function parseStreamLine(rawLine: string): AssistantDelta | null {
  const line = rawLine.trim();
  if (!line) return null;
  // SSE comments start with ``:`` and serve as keepalives.
  if (line.startsWith(':')) return null;
  // SSE event-type lines (``event: foo``) carry no completion payload.
  if (line.startsWith('event:')) return null;
  // Strip the SSE ``data:`` prefix when present so the same parser can
  // handle NDJSON (one JSON object per line) without any branching above.
  const payload = line.startsWith('data:') ? line.slice(5).trim() : line;
  if (!payload) return null;
  if (payload === '[DONE]') return { content: '', done: true };
  try {
    const parsed = JSON.parse(payload) as {
      choices?: {
        delta?: { content?: string | null };
        message?: { content?: string | null };
      }[];
    };
    const choice = parsed.choices?.[0];
    const content =
      // Streaming responses use ``delta.content``; non-streaming responses
      // (NDJSON-style) sometimes use ``message.content`` for the final frame.
      choice?.delta?.content ?? choice?.message?.content ?? '';
    return { content };
  } catch {
    return null;
  }
}

/** Body shape accepted by ``POST /deployments/{id}/chat``. */
export interface ChatCompletionBody {
  model: string;
  messages: { role: 'system' | 'user' | 'assistant'; content: string }[];
  stream: true;
  // Pass-through is preserved for future tuning knobs.
  [key: string]: unknown;
}

export interface StreamChatOptions {
  deploymentId: string;
  body: ChatCompletionBody;
  /** Override fetch implementation (test injection). */
  fetchImpl?: typeof fetch;
  /** Override base URL; defaults to same-origin (the SYM-212 backend proxy). */
  baseUrl?: string;
  /** Invoked once per parsed delta. */
  onDelta: (delta: AssistantDelta) => void;
  /** Optional abort signal — closes the stream when fired. */
  signal?: AbortSignal;
}

function defaultBaseUrl(): string {
  // ``import.meta.env`` is populated by Vite at build time. The guard keeps
  // jsdom tests happy.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const env = (import.meta as any).env as Record<string, string> | undefined;
  if (env?.VITE_HARBOR_API_BASE) return env.VITE_HARBOR_API_BASE;
  return '';
}

/**
 * POST a chat completion request and drain the SSE body, calling
 * ``onDelta`` for every parsed frame. Resolves once the upstream closes the
 * stream (or the ``[DONE]`` marker arrives).
 */
export async function streamChatCompletion(
  opts: StreamChatOptions,
): Promise<void> {
  const fetchImpl = opts.fetchImpl ?? globalThis.fetch.bind(globalThis);
  const base = (opts.baseUrl ?? defaultBaseUrl()).replace(/\/+$/, '');
  const url = `${base}/deployments/${encodeURIComponent(opts.deploymentId)}/chat`;

  const response = await fetchImpl(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify(opts.body),
    signal: opts.signal,
  });

  if (!response.ok) {
    let detail = '';
    try {
      detail = await response.text();
    } catch {
      // ignore — the status code alone is enough for the screen to render
      // an error.
    }
    throw new Error(
      `Chat request failed: ${response.status}${detail ? ` ${detail}` : ''}`,
    );
  }
  if (!response.body) {
    throw new Error('Chat response has no body to stream.');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  const drainFrames = (): void => {
    // SSE separates frames with blank lines (``\n\n``). Drain every complete
    // frame currently sitting in the buffer.
    while (true) {
      const sep = buffer.indexOf('\n\n');
      if (sep === -1) return;
      const block = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      for (const line of block.split('\n')) {
        const delta = parseStreamLine(line);
        if (delta) opts.onDelta(delta);
      }
    }
  };

  const flushTrailing = (): void => {
    // NDJSON streams may end without the trailing blank line; drain whatever
    // remains in the buffer as if it were a single frame.
    if (!buffer) return;
    for (const line of buffer.split('\n')) {
      const delta = parseStreamLine(line);
      if (delta) opts.onDelta(delta);
    }
    buffer = '';
  };

  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      drainFrames();
    }
    buffer += decoder.decode();
    drainFrames();
    flushTrailing();
  } finally {
    // Always release the reader — leaving it locked breaks aborts and
    // subsequent requests on the same body.
    try {
      reader.releaseLock();
    } catch {
      // ignore: reader may already be released by the runtime.
    }
  }
}
