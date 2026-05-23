import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from 'react';
import type { DeploymentStatus, HarborClient } from '../api/harbor';
import { harborClient } from '../api/harbor';
import {
  streamChatCompletion,
  type ChatCompletionBody,
} from '../api/chat-stream';

/**
 * A single chat turn. Persisted only in component state — SYM-215's scope
 * deliberately does not yet wire any backend storage.
 */
export interface ChatTurn {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  /** ``true`` while the assistant is still streaming this turn. */
  streaming?: boolean;
}

export interface ChatProps {
  deploymentId: string;
  /** Catalog identifier for the upstream model (e.g. ``Qwen/Qwen2.5-7B-Instruct``). */
  model?: string;
  /** Endpoint URL hint passed from the previous screen; otherwise fetched. */
  endpointUrl?: string;
  client?: HarborClient;
  /** Override fetch for tests + the e2e stub. */
  fetchImpl?: typeof fetch;
  /** Clipboard target. ``navigator.clipboard`` by default. */
  clipboard?: { writeText: (text: string) => Promise<void> };
}

interface ScreenState {
  turns: ChatTurn[];
  draft: string;
  pending: boolean;
  error: string | null;
}

const INITIAL: ScreenState = {
  turns: [],
  draft: '',
  pending: false,
  error: null,
};

/**
 * Stable id helper. ``crypto.randomUUID`` is available in modern browsers and
 * jsdom (vitest); the fallback keeps the component usable in any odd runtime.
 */
function nextId(prefix: string): string {
  const c = globalThis.crypto as Crypto | undefined;
  if (c && typeof c.randomUUID === 'function') return `${prefix}_${c.randomUUID()}`;
  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

function modeKeyComboHint(): string {
  // ``navigator.platform`` is deprecated but still the most reliable signal
  // for picking the right modifier label; fall back to "Ctrl" on unknowns.
  const platform =
    typeof navigator !== 'undefined' ? navigator.platform : '';
  return /Mac|iPhone|iPad/i.test(platform) ? '⌘ + Enter' : 'Ctrl + Enter';
}

export function Chat({
  deploymentId,
  model,
  endpointUrl,
  client = harborClient,
  fetchImpl,
  clipboard,
}: ChatProps) {
  const [state, setState] = useState<ScreenState>(INITIAL);
  const [resolvedEndpoint, setResolvedEndpoint] = useState<string | null>(
    endpointUrl ?? null,
  );
  const [endpointError, setEndpointError] = useState<string | null>(null);
  const [copyFeedback, setCopyFeedback] = useState<string | null>(null);
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  // Resolve the endpoint URL from the backend whenever we don't already
  // have it from the previous screen. The fetch is best-effort — chat still
  // works without it, the header just won't display the upstream URL.
  useEffect(() => {
    if (resolvedEndpoint) return;
    let active = true;
    client
      .getDeployment(deploymentId)
      .then((status: DeploymentStatus) => {
        if (!active) return;
        if (status.endpoint_url) setResolvedEndpoint(status.endpoint_url);
      })
      .catch((err: unknown) => {
        if (!active) return;
        const message =
          err instanceof Error ? err.message : 'Failed to load deployment.';
        setEndpointError(message);
      });
    return () => {
      active = false;
    };
  }, [client, deploymentId, resolvedEndpoint]);

  // Autoscroll the message list to the bottom on every turn change.
  useEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [state.turns]);

  // Clear the transient "Copied!" badge after a short delay so it doesn't
  // stick around forever.
  useEffect(() => {
    if (!copyFeedback) return;
    const handle = window.setTimeout(() => setCopyFeedback(null), 1_500);
    return () => window.clearTimeout(handle);
  }, [copyFeedback]);

  const send = useCallback(async (): Promise<void> => {
    const draft = state.draft.trim();
    if (!draft || state.pending) return;

    const userTurn: ChatTurn = {
      id: nextId('user'),
      role: 'user',
      content: draft,
    };
    const assistantTurn: ChatTurn = {
      id: nextId('asst'),
      role: 'assistant',
      content: '',
      streaming: true,
    };

    // Snapshot the conversation history that will be POSTed. We include the
    // just-typed user turn but *not* the empty assistant placeholder.
    const history = [...state.turns, userTurn].map((t) => ({
      role: t.role,
      content: t.content,
    }));

    setState((prev) => ({
      ...prev,
      turns: [...prev.turns, userTurn, assistantTurn],
      draft: '',
      pending: true,
      error: null,
    }));

    const body: ChatCompletionBody = {
      model: model ?? 'qwen',
      messages: history,
      stream: true,
    };

    try {
      await streamChatCompletion({
        deploymentId,
        body,
        fetchImpl,
        onDelta: (delta) => {
          if (delta.done) return;
          if (!delta.content) return;
          setState((prev) => ({
            ...prev,
            turns: prev.turns.map((t) =>
              t.id === assistantTurn.id
                ? { ...t, content: t.content + delta.content }
                : t,
            ),
          }));
        },
      });
      setState((prev) => ({
        ...prev,
        pending: false,
        turns: prev.turns.map((t) =>
          t.id === assistantTurn.id ? { ...t, streaming: false } : t,
        ),
      }));
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'Chat request failed.';
      setState((prev) => ({
        ...prev,
        pending: false,
        error: message,
        // Drop the empty assistant placeholder so the user can retry without
        // a phantom blank bubble.
        turns: prev.turns.filter((t) => t.id !== assistantTurn.id),
      }));
    }
  }, [deploymentId, fetchImpl, model, state.draft, state.pending, state.turns]);

  const onComposerKeyDown = useCallback(
    (event: KeyboardEvent<HTMLTextAreaElement>): void => {
      // Cmd+Enter (mac) / Ctrl+Enter (everywhere else) submits.
      if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        void send();
      }
    },
    [send],
  );

  const onCopy = useCallback(
    async (turn: ChatTurn): Promise<void> => {
      const target =
        clipboard ??
        (typeof navigator !== 'undefined'
          ? navigator.clipboard
          : undefined);
      if (!target) {
        setCopyFeedback('Clipboard unavailable');
        return;
      }
      try {
        await target.writeText(turn.content);
        setCopyFeedback('Copied!');
      } catch {
        setCopyFeedback('Copy failed');
      }
    },
    [clipboard],
  );

  const onBack = useCallback((): void => {
    window.location.hash = `#/deployments/${deploymentId}`;
  }, [deploymentId]);

  const shortcutHint = useMemo(() => modeKeyComboHint(), []);
  const canSend = state.draft.trim().length > 0 && !state.pending;

  return (
    <section className="harbor-screen harbor-chat" aria-label="Chat">
      <header className="harbor-screen__header harbor-chat__header">
        <div>
          <h1>Chat</h1>
          <p className="harbor-screen__lede">
            Talking to your own provisioned model. Messages are streamed via{' '}
            <code>POST /deployments/{deploymentId}/chat</code>; the upstream
            bearer token stays server-side.
          </p>
        </div>
        <dl className="harbor-chat__meta">
          <div>
            <dt>Model</dt>
            <dd>
              <code>{model ?? 'qwen'}</code>
            </dd>
          </div>
          <div>
            <dt>Endpoint</dt>
            <dd>
              {resolvedEndpoint ? (
                <code>{resolvedEndpoint}</code>
              ) : endpointError ? (
                <span className="harbor-status--warning">
                  {endpointError}
                </span>
              ) : (
                <span className="harbor-status--loading">resolving…</span>
              )}
            </dd>
          </div>
          <div>
            <dt>Deployment</dt>
            <dd>
              <code>{deploymentId}</code>
            </dd>
          </div>
        </dl>
        <button
          type="button"
          className="harbor-chat__back"
          onClick={onBack}
        >
          ← Back to status
        </button>
      </header>

      <div
        ref={scrollerRef}
        className="harbor-chat__list"
        role="log"
        aria-live="polite"
        aria-relevant="additions text"
      >
        {state.turns.length === 0 && (
          <p className="harbor-chat__empty">
            Say hello to your model. Press <kbd>{shortcutHint}</kbd> to send.
          </p>
        )}
        {state.turns.map((turn) => (
          <article
            key={turn.id}
            className={`harbor-chat__bubble harbor-chat__bubble--${turn.role}`}
            data-role={turn.role}
            data-streaming={turn.streaming ? 'true' : 'false'}
          >
            <header className="harbor-chat__bubble-header">
              <span className="harbor-chat__role">
                {turn.role === 'user' ? 'You' : 'Assistant'}
              </span>
              {turn.role === 'assistant' && !turn.streaming && turn.content && (
                <button
                  type="button"
                  className="harbor-chat__copy"
                  aria-label="Copy assistant response"
                  onClick={() => void onCopy(turn)}
                >
                  Copy
                </button>
              )}
            </header>
            <p className="harbor-chat__content">
              {turn.content}
              {turn.streaming && (
                <span className="harbor-chat__caret" aria-hidden="true">
                  ▍
                </span>
              )}
            </p>
          </article>
        ))}
      </div>

      {copyFeedback && (
        <p role="status" className="harbor-chat__feedback">
          {copyFeedback}
        </p>
      )}

      {state.error && (
        <p role="alert" className="harbor-status harbor-status--error">
          {state.error}
        </p>
      )}

      <footer className="harbor-chat__composer">
        <textarea
          ref={textareaRef}
          className="harbor-chat__textarea"
          placeholder="Send a message…"
          value={state.draft}
          aria-label="Message"
          rows={3}
          disabled={state.pending}
          onChange={(e) =>
            setState((prev) => ({ ...prev, draft: e.target.value }))
          }
          onKeyDown={onComposerKeyDown}
        />
        <div className="harbor-chat__composer-actions">
          <span className="harbor-chat__hint">
            <kbd>{shortcutHint}</kbd> to send
          </span>
          <button
            type="button"
            className="harbor-primary"
            disabled={!canSend}
            onClick={() => void send()}
          >
            {state.pending ? 'Sending…' : 'Send'}
          </button>
        </div>
      </footer>
    </section>
  );
}

export default Chat;
