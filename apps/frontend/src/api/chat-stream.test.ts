import { describe, expect, it, vi } from 'vitest';
import {
  parseStreamLine,
  streamChatCompletion,
  type AssistantDelta,
} from './chat-stream';

describe('parseStreamLine', () => {
  it('parses an OpenAI-style streaming delta', () => {
    const line =
      'data: {"id":"chatcmpl-1","choices":[{"index":0,"delta":{"content":"Hi"}}]}';
    expect(parseStreamLine(line)).toEqual({ content: 'Hi' });
  });

  it('returns the [DONE] sentinel', () => {
    expect(parseStreamLine('data: [DONE]')).toEqual({ content: '', done: true });
  });

  it('falls back to message.content for non-streaming-shaped lines', () => {
    const line =
      'data: {"choices":[{"index":0,"message":{"role":"assistant","content":"Hello"}}]}';
    expect(parseStreamLine(line)).toEqual({ content: 'Hello' });
  });

  it('accepts NDJSON lines (no data: prefix)', () => {
    const line =
      '{"choices":[{"index":0,"delta":{"content":"chunk"}}]}';
    expect(parseStreamLine(line)).toEqual({ content: 'chunk' });
  });

  it('returns null for keepalive comments and event-type lines', () => {
    expect(parseStreamLine(': keepalive')).toBeNull();
    expect(parseStreamLine('event: ping')).toBeNull();
  });

  it('returns empty content when delta has no content (role-only first frame)', () => {
    const line =
      'data: {"choices":[{"index":0,"delta":{"role":"assistant"}}]}';
    expect(parseStreamLine(line)).toEqual({ content: '' });
  });

  it('returns null for blank lines and malformed JSON', () => {
    expect(parseStreamLine('')).toBeNull();
    expect(parseStreamLine('   ')).toBeNull();
    expect(parseStreamLine('data: not-json{')).toBeNull();
  });
});

/**
 * Build a ``Response`` whose body is a streaming ``ReadableStream`` over the
 * given chunks. Mirrors what ``fetch`` returns when the server sends
 * ``Transfer-Encoding: chunked``.
 */
function streamingResponse(chunks: string[], init: ResponseInit = {}): Response {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      const enc = new TextEncoder();
      for (const chunk of chunks) {
        controller.enqueue(enc.encode(chunk));
      }
      controller.close();
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
    ...init,
  });
}

describe('streamChatCompletion', () => {
  it('POSTs the body and emits each delta in order', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      streamingResponse([
        'data: {"choices":[{"index":0,"delta":{"content":"Hel"}}]}\n\n',
        'data: {"choices":[{"index":0,"delta":{"content":"lo"}}]}\n\n',
        'data: {"choices":[{"index":0,"delta":{"content":"!"}}]}\n\n',
        'data: [DONE]\n\n',
      ]),
    );
    const deltas: AssistantDelta[] = [];

    await streamChatCompletion({
      deploymentId: 'dep_1',
      body: {
        model: 'qwen',
        messages: [{ role: 'user', content: 'hi' }],
        stream: true,
      },
      fetchImpl: fetchImpl as unknown as typeof fetch,
      onDelta: (d) => deltas.push(d),
    });

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe('/deployments/dep_1/chat');
    expect(init.method).toBe('POST');
    const sentBody = JSON.parse(init.body);
    expect(sentBody.stream).toBe(true);
    expect(sentBody.messages).toEqual([{ role: 'user', content: 'hi' }]);

    expect(deltas).toEqual([
      { content: 'Hel' },
      { content: 'lo' },
      { content: '!' },
      { content: '', done: true },
    ]);
  });

  it('reassembles deltas split across multiple chunks', async () => {
    // The first chunk ends mid-frame; the parser must keep the partial
    // payload buffered until the closing ``\n\n`` arrives.
    const fetchImpl = vi.fn().mockResolvedValue(
      streamingResponse([
        'data: {"choices":[{"index":0,"delta":{"content":"He',
        'llo"}}]}\n\n',
        'data: {"choices":[{"index":0,"delta":{"content":" world"}}]}\n\n',
      ]),
    );
    const deltas: AssistantDelta[] = [];

    await streamChatCompletion({
      deploymentId: 'dep_1',
      body: {
        model: 'qwen',
        messages: [{ role: 'user', content: 'hi' }],
        stream: true,
      },
      fetchImpl: fetchImpl as unknown as typeof fetch,
      onDelta: (d) => deltas.push(d),
    });

    expect(deltas).toEqual([
      { content: 'Hello' },
      { content: ' world' },
    ]);
  });

  it('uses the provided baseUrl and URL-encodes the deployment id', async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(streamingResponse(['data: [DONE]\n\n']));

    await streamChatCompletion({
      deploymentId: 'dep abc',
      baseUrl: 'https://harbor.test/',
      body: {
        model: 'qwen',
        messages: [{ role: 'user', content: 'hi' }],
        stream: true,
      },
      fetchImpl: fetchImpl as unknown as typeof fetch,
      onDelta: () => undefined,
    });

    expect(fetchImpl.mock.calls[0][0]).toBe(
      'https://harbor.test/deployments/dep%20abc/chat',
    );
  });

  it('throws when the response is non-2xx, surfacing upstream detail', async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(
        new Response('not healthy', {
          status: 409,
          headers: { 'Content-Type': 'text/plain' },
        }),
      );

    await expect(
      streamChatCompletion({
        deploymentId: 'dep_1',
        body: {
          model: 'qwen',
          messages: [{ role: 'user', content: 'hi' }],
          stream: true,
        },
        fetchImpl: fetchImpl as unknown as typeof fetch,
        onDelta: () => undefined,
      }),
    ).rejects.toThrow(/409.*not healthy/);
  });

  it('handles NDJSON-style trailing line without a final blank line', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      streamingResponse([
        '{"choices":[{"index":0,"delta":{"content":"alpha"}}]}\n',
        '{"choices":[{"index":0,"delta":{"content":"beta"}}]}',
      ]),
    );
    const deltas: AssistantDelta[] = [];

    await streamChatCompletion({
      deploymentId: 'dep_1',
      body: {
        model: 'qwen',
        messages: [{ role: 'user', content: 'hi' }],
        stream: true,
      },
      fetchImpl: fetchImpl as unknown as typeof fetch,
      onDelta: (d) => deltas.push(d),
    });

    expect(deltas).toEqual([{ content: 'alpha' }, { content: 'beta' }]);
  });
});
