import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { DeploymentStatus, HarborClient } from '../api/harbor';
import Chat from './Chat';

/**
 * Build a streaming ``Response`` that drip-feeds the supplied SSE chunks
 * through the body so the screen's parser sees real partial reads.
 */
function streamingResponse(chunks: string[]): Response {
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
  });
}

function makeClient(): HarborClient {
  const status: DeploymentStatus = {
    deployment_id: 'dep_test',
    state: 'HEALTHY',
    endpoint_url: 'https://qwen-7b.modal.test/v1',
    failure_reason: null,
    created_at: '2026-05-23T12:00:00Z',
    updated_at: '2026-05-23T12:00:01Z',
  };
  return {
    getDeployment: vi.fn().mockResolvedValue(status),
  } as unknown as HarborClient;
}

describe('Chat composer', () => {
  let originalClipboard: typeof navigator.clipboard | undefined;

  beforeEach(() => {
    originalClipboard = navigator.clipboard;
  });

  afterEach(() => {
    vi.restoreAllMocks();
    if (originalClipboard) {
      Object.defineProperty(navigator, 'clipboard', {
        value: originalClipboard,
        configurable: true,
      });
    }
  });

  it('renders the deployment + model in the header', async () => {
    const client = makeClient();
    render(
      <Chat
        deploymentId="dep_test"
        model="Qwen/Qwen2.5-7B-Instruct"
        client={client}
        fetchImpl={vi.fn() as unknown as typeof fetch}
      />,
    );
    await screen.findByText('Qwen/Qwen2.5-7B-Instruct');
    expect(screen.getByText('dep_test')).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByText('https://qwen-7b.modal.test/v1')).toBeInTheDocument(),
    );
  });

  it('uses the prefetched endpointUrl prop without calling getDeployment', () => {
    const client = makeClient();
    render(
      <Chat
        deploymentId="dep_test"
        model="Qwen/Qwen2.5-7B-Instruct"
        endpointUrl="https://prefetched/v1"
        client={client}
        fetchImpl={vi.fn() as unknown as typeof fetch}
      />,
    );
    expect(screen.getByText('https://prefetched/v1')).toBeInTheDocument();
    expect(client.getDeployment).not.toHaveBeenCalled();
  });

  it('disables the Send button until the textarea has content', async () => {
    const client = makeClient();
    render(
      <Chat
        deploymentId="dep_test"
        model="qwen"
        endpointUrl="https://endpoint/v1"
        client={client}
        fetchImpl={vi.fn() as unknown as typeof fetch}
      />,
    );
    const send = screen.getByRole('button', { name: /^send$/i });
    expect(send).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Message'), {
      target: { value: 'hi' },
    });
    await waitFor(() => expect(send).not.toBeDisabled());
  });

  it('Cmd/Ctrl+Enter sends the message; plain Enter inserts a newline', async () => {
    const client = makeClient();
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(
        streamingResponse([
          'data: {"choices":[{"index":0,"delta":{"content":"Hi"}}]}\n\n',
          'data: [DONE]\n\n',
        ]),
      );
    render(
      <Chat
        deploymentId="dep_test"
        model="qwen"
        endpointUrl="https://endpoint/v1"
        client={client}
        fetchImpl={fetchImpl as unknown as typeof fetch}
      />,
    );

    const textarea = screen.getByLabelText('Message');
    fireEvent.change(textarea, { target: { value: 'hello' } });

    // Plain Enter does NOT submit — the composer should ignore it so the
    // user can compose multi-line prompts.
    fireEvent.keyDown(textarea, { key: 'Enter' });
    expect(fetchImpl).not.toHaveBeenCalled();

    // Ctrl+Enter submits.
    fireEvent.keyDown(textarea, { key: 'Enter', ctrlKey: true });

    await waitFor(() => expect(fetchImpl).toHaveBeenCalledTimes(1));
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe('/deployments/dep_test/chat');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toMatchObject({
      model: 'qwen',
      stream: true,
      messages: [{ role: 'user', content: 'hello' }],
    });

    await screen.findByText('Hi');
  });

  it('Cmd+Enter also submits on mac', async () => {
    const client = makeClient();
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(streamingResponse(['data: [DONE]\n\n']));
    render(
      <Chat
        deploymentId="dep_test"
        model="qwen"
        endpointUrl="https://endpoint/v1"
        client={client}
        fetchImpl={fetchImpl as unknown as typeof fetch}
      />,
    );
    const textarea = screen.getByLabelText('Message');
    fireEvent.change(textarea, { target: { value: 'hi' } });
    fireEvent.keyDown(textarea, { key: 'Enter', metaKey: true });
    await waitFor(() => expect(fetchImpl).toHaveBeenCalledTimes(1));
  });

  it('renders streamed deltas incrementally and finalises the bubble', async () => {
    const client = makeClient();
    // Emit chunks via a controllable stream so we can assert intermediate state.
    let controller!: ReadableStreamDefaultController<Uint8Array>;
    const stream = new ReadableStream<Uint8Array>({
      start(c) {
        controller = c;
      },
    });
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(stream, {
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
      }),
    );
    render(
      <Chat
        deploymentId="dep_test"
        model="qwen"
        endpointUrl="https://endpoint/v1"
        client={client}
        fetchImpl={fetchImpl as unknown as typeof fetch}
      />,
    );
    const textarea = screen.getByLabelText('Message');
    fireEvent.change(textarea, { target: { value: 'hi' } });
    fireEvent.click(screen.getByRole('button', { name: /^send$/i }));

    const enc = new TextEncoder();
    await act(async () => {
      controller.enqueue(
        enc.encode(
          'data: {"choices":[{"index":0,"delta":{"content":"Hel"}}]}\n\n',
        ),
      );
    });
    await screen.findByText(/Hel/);

    await act(async () => {
      controller.enqueue(
        enc.encode(
          'data: {"choices":[{"index":0,"delta":{"content":"lo"}}]}\n\n',
        ),
      );
    });
    await screen.findByText(/Hello/);

    await act(async () => {
      controller.enqueue(enc.encode('data: [DONE]\n\n'));
      controller.close();
    });

    await waitFor(() => {
      const bubble = document.querySelector(
        '.harbor-chat__bubble--assistant',
      ) as HTMLElement;
      expect(bubble.getAttribute('data-streaming')).toBe('false');
    });
    // Copy button appears once streaming finishes.
    expect(
      screen.getByRole('button', { name: /copy assistant response/i }),
    ).toBeInTheDocument();
  });

  it('copies the assistant turn to the clipboard', async () => {
    const client = makeClient();
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(
        streamingResponse([
          'data: {"choices":[{"index":0,"delta":{"content":"Hi there"}}]}\n\n',
          'data: [DONE]\n\n',
        ]),
      );
    const writeText = vi.fn().mockResolvedValue(undefined);

    render(
      <Chat
        deploymentId="dep_test"
        model="qwen"
        endpointUrl="https://endpoint/v1"
        client={client}
        fetchImpl={fetchImpl as unknown as typeof fetch}
        clipboard={{ writeText }}
      />,
    );
    fireEvent.change(screen.getByLabelText('Message'), {
      target: { value: 'hi' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^send$/i }));

    const copyBtn = await screen.findByRole('button', {
      name: /copy assistant response/i,
    });
    fireEvent.click(copyBtn);
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('Hi there'));
    await screen.findByText(/copied/i);
  });

  it('surfaces a chat error and drops the empty assistant bubble', async () => {
    const client = makeClient();
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response('upstream offline', {
        status: 502,
        headers: { 'Content-Type': 'text/plain' },
      }),
    );
    render(
      <Chat
        deploymentId="dep_test"
        model="qwen"
        endpointUrl="https://endpoint/v1"
        client={client}
        fetchImpl={fetchImpl as unknown as typeof fetch}
      />,
    );
    fireEvent.change(screen.getByLabelText('Message'), {
      target: { value: 'hi' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^send$/i }));

    await screen.findByRole('alert');
    expect(screen.getByRole('alert')).toHaveTextContent(/502.*upstream offline/i);
    // The empty assistant bubble should have been removed on error.
    expect(
      document.querySelector('.harbor-chat__bubble--assistant'),
    ).toBeNull();
  });

  it('sends a multi-turn conversation history on follow-up sends', async () => {
    const client = makeClient();
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(
        streamingResponse([
          'data: {"choices":[{"index":0,"delta":{"content":"hello"}}]}\n\n',
          'data: [DONE]\n\n',
        ]),
      )
      .mockResolvedValueOnce(
        streamingResponse([
          'data: {"choices":[{"index":0,"delta":{"content":"sure"}}]}\n\n',
          'data: [DONE]\n\n',
        ]),
      );

    render(
      <Chat
        deploymentId="dep_test"
        model="qwen"
        endpointUrl="https://endpoint/v1"
        client={client}
        fetchImpl={fetchImpl as unknown as typeof fetch}
      />,
    );
    // First turn.
    fireEvent.change(screen.getByLabelText('Message'), {
      target: { value: 'hi' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^send$/i }));
    await screen.findByText('hello');

    // Second turn — the request body should now include both prior turns.
    fireEvent.change(screen.getByLabelText('Message'), {
      target: { value: 'tell me a joke' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^send$/i }));
    await screen.findByText('sure');

    expect(fetchImpl).toHaveBeenCalledTimes(2);
    const body = JSON.parse(fetchImpl.mock.calls[1][1].body);
    expect(body.messages).toEqual([
      { role: 'user', content: 'hi' },
      { role: 'assistant', content: 'hello' },
      { role: 'user', content: 'tell me a joke' },
    ]);
  });
});
