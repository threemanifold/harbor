import { useEffect, useMemo, useState } from 'react';
import type { DeploymentEvent, HarborClient } from '../api/harbor';
import { harborClient } from '../api/harbor';

interface ProvisioningProps {
  deploymentId: string;
  client?: HarborClient;
  /**
   * Hash route the "Open chat" CTA navigates to once HEALTHY. Optionally
   * passes the compiled model identifier so the chat screen can show which
   * model the user is talking to without an extra round-trip.
   */
  chatHref?: (deploymentId: string, opts?: { model?: string; endpointUrl?: string }) => string;
}

/**
 * The vertical timeline rendered on the right of the screen. The order here
 * is the *expected* lifecycle; events for steps the backend skips are still
 * rendered as "pending".
 */
const STEPS = [
  { key: 'requested', label: 'Requested' },
  { key: 'compiled', label: 'Compiled' },
  { key: 'placed', label: 'Placed' },
  { key: 'provisioning', label: 'Provisioning' },
  { key: 'starting', label: 'Starting' },
  { key: 'healthy', label: 'Healthy' },
] as const;

type StepKey = (typeof STEPS)[number]['key'];
type StepStatus = 'pending' | 'active' | 'done' | 'failed';

interface ScreenState {
  /** Most recent event keyed by lifecycle stage. */
  seen: Partial<Record<StepKey, DeploymentEvent>>;
  /** Latest progress event (only populated during PROVISIONING/STARTING). */
  progress: { percent: number; message: string } | null;
  /** Currently-active step (i.e. last seen, or the next pending one). */
  current: StepKey;
  endpointUrl: string | null;
  failure: string | null;
  terminal: boolean;
  /** Transport-level error (SSE connection dropped before terminal). */
  transportError: string | null;
}

const INITIAL: ScreenState = {
  seen: {},
  progress: null,
  current: 'requested',
  endpointUrl: null,
  failure: null,
  terminal: false,
  transportError: null,
};

function nextStep(seen: Partial<Record<StepKey, DeploymentEvent>>): StepKey {
  // The "current" step is the last one we've seen — or the first lifecycle
  // step if no events have arrived yet.
  for (let i = STEPS.length - 1; i >= 0; i--) {
    const key = STEPS[i].key;
    if (seen[key]) return key;
  }
  return 'requested';
}

function reduce(state: ScreenState, event: DeploymentEvent): ScreenState {
  switch (event.type) {
    case 'requested':
    case 'compiled':
    case 'placed':
    case 'provisioning':
    case 'starting': {
      const seen = { ...state.seen, [event.type]: event };
      return {
        ...state,
        seen,
        current: nextStep(seen),
        // Provisioning/Starting resets the progress widget so it tracks the
        // most recent stage's percent rather than a stale one.
        progress:
          event.type === 'provisioning' || event.type === 'starting'
            ? null
            : state.progress,
      };
    }
    case 'progress':
      return {
        ...state,
        progress: { percent: event.percent, message: event.message },
      };
    case 'healthy': {
      const seen = { ...state.seen, healthy: event };
      return {
        ...state,
        seen,
        current: 'healthy',
        endpointUrl: event.endpoint_url,
        progress: { percent: 100, message: 'Endpoint is healthy.' },
        terminal: true,
      };
    }
    case 'failed':
      return {
        ...state,
        failure: event.reason,
        terminal: true,
      };
    case 'degraded':
      return {
        ...state,
        progress: { percent: state.progress?.percent ?? 0, message: event.reason },
      };
    // Terminating/terminated aren't part of the happy-path timeline; we still
    // surface them so the screen doesn't go silent on shutdown.
    case 'terminating':
    case 'terminated':
      return { ...state, terminal: event.type === 'terminated' };
  }
}

function statusFor(
  step: StepKey,
  state: ScreenState,
): StepStatus {
  if (state.failure && step === state.current) return 'failed';
  if (state.seen[step]) {
    // A step is "done" once a later step has been reported, otherwise it's
    // currently active.
    const myIdx = STEPS.findIndex((s) => s.key === step);
    const currentIdx = STEPS.findIndex((s) => s.key === state.current);
    if (myIdx < currentIdx) return 'done';
    if (state.terminal && state.endpointUrl) return 'done';
    return 'active';
  }
  return 'pending';
}

function defaultChatHref(
  deploymentId: string,
  opts: { model?: string; endpointUrl?: string } = {},
): string {
  // Hash route consumed by the SYM-215 chat screen. The model + endpoint
  // are surfaced as query params so the chat header can display them
  // immediately, without re-fetching the deployment status.
  const params = new URLSearchParams();
  if (opts.model) params.set('model', opts.model);
  if (opts.endpointUrl) params.set('endpoint', opts.endpointUrl);
  const query = params.toString();
  return `#/deployments/${deploymentId}/chat${query ? `?${query}` : ''}`;
}

export function Provisioning({
  deploymentId,
  client = harborClient,
  chatHref = defaultChatHref,
}: ProvisioningProps) {
  const [state, setState] = useState<ScreenState>(INITIAL);

  useEffect(() => {
    setState(INITIAL);
    const source = client.streamDeploymentEvents(deploymentId, {
      onEvent: (event) => setState((prev) => reduce(prev, event)),
      onError: () =>
        setState((prev) =>
          prev.terminal
            ? prev
            : {
                ...prev,
                transportError:
                  'Connection to deployment events lost. The deployment may still be running.',
              },
        ),
      onTerminal: () => setState((prev) => ({ ...prev, terminal: true })),
    });
    return () => {
      source.close();
    };
  }, [client, deploymentId]);

  const statuses = useMemo(
    () =>
      STEPS.map((step) => ({
        step,
        status: statusFor(step.key, state),
      })),
    [state],
  );

  return (
    <section className="harbor-screen harbor-provisioning">
      <header className="harbor-screen__header">
        <h1>Provisioning</h1>
        <p className="harbor-screen__lede">
          Deployment <code>{deploymentId}</code>
        </p>
      </header>

      <ol className="harbor-timeline" aria-label="Deployment progress">
        {statuses.map(({ step, status }) => (
          <li
            key={step.key}
            className={`harbor-timeline__item harbor-timeline__item--${status}`}
            data-step={step.key}
            data-status={status}
          >
            <span className="harbor-timeline__bullet" aria-hidden="true" />
            <span className="harbor-timeline__label">{step.label}</span>
          </li>
        ))}
      </ol>

      {state.progress && !state.failure && (
        <div
          className="harbor-progress"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={state.progress.percent}
        >
          <div
            className="harbor-progress__fill"
            style={{ width: `${state.progress.percent}%` }}
          />
          <p className="harbor-progress__message">
            <span className="harbor-progress__percent">
              {state.progress.percent}%
            </span>{' '}
            {state.progress.message}
          </p>
        </div>
      )}

      {state.endpointUrl && (
        <div className="harbor-endpoint" role="region" aria-label="Endpoint">
          <p className="harbor-endpoint__label">Endpoint</p>
          <code className="harbor-endpoint__url">{state.endpointUrl}</code>
          <a
            className="harbor-primary harbor-primary--link"
            href={chatHref(deploymentId, {
              // The compiled event carries the catalog identifier the user
              // picked. Threading it into the chat URL lets the chat
              // header render the model name without an extra round-trip.
              model:
                state.seen.compiled?.type === 'compiled'
                  ? state.seen.compiled.model
                  : undefined,
              endpointUrl: state.endpointUrl ?? undefined,
            })}
          >
            Open chat
          </a>
        </div>
      )}

      {state.failure && (
        <p role="alert" className="harbor-status harbor-status--error">
          Deployment failed: {state.failure}
        </p>
      )}

      {state.transportError && (
        <p role="alert" className="harbor-status harbor-status--warning">
          {state.transportError}
        </p>
      )}
    </section>
  );
}

export default Provisioning;
