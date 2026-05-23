import { act, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type {
  DeploymentEvent,
  HarborClient,
} from '../api/harbor';
import Provisioning from './Provisioning';

interface MockSubscription {
  emit: (event: DeploymentEvent) => void;
  fail: () => void;
  terminate: () => void;
  closed: boolean;
}

function makeClient(): { client: HarborClient; sub: () => MockSubscription } {
  let current: MockSubscription | null = null;
  const client: Pick<HarborClient, 'streamDeploymentEvents'> = {
    streamDeploymentEvents: (
      _deploymentId,
      handlers,
    ) => {
      const sub: MockSubscription = {
        closed: false,
        emit: (event) => act(() => handlers.onEvent(event)),
        fail: () => act(() => handlers.onError?.(new Event('error'))),
        terminate: () => act(() => handlers.onTerminal?.()),
      };
      current = sub;
      return {
        close: () => {
          sub.closed = true;
        },
      } as unknown as EventSource;
    },
  };
  return {
    client: client as unknown as HarborClient,
    sub: () => {
      if (!current) throw new Error('No subscription opened yet');
      return current;
    },
  };
}

const STEP_KEYS: Record<string, string> = {
  Requested: 'requested',
  Compiled: 'compiled',
  Placed: 'placed',
  Provisioning: 'provisioning',
  Starting: 'starting',
  Healthy: 'healthy',
};

function timelineItem(label: string): HTMLElement {
  const key = STEP_KEYS[label];
  const item = document.querySelector(
    `.harbor-timeline__item[data-step="${key}"]`,
  );
  if (!item) throw new Error(`No timeline item for ${label}`);
  return item as HTMLElement;
}

describe('Provisioning', () => {
  it('renders all lifecycle steps as pending initially', () => {
    const { client } = makeClient();
    render(<Provisioning deploymentId="dep_1" client={client} />);
    for (const label of [
      'Requested',
      'Compiled',
      'Placed',
      'Provisioning',
      'Starting',
      'Healthy',
    ]) {
      expect(timelineItem(label)).toHaveAttribute('data-status', 'pending');
    }
  });

  it('marks earlier steps done and the latest active as events arrive', () => {
    const { client, sub } = makeClient();
    render(<Provisioning deploymentId="dep_1" client={client} />);
    sub().emit({ type: 'requested', deployment_id: 'dep_1', at: 't0' });
    sub().emit({
      type: 'compiled',
      deployment_id: 'dep_1',
      at: 't1',
      model: 'Qwen',
      runtime: 'vllm',
      quantization: 'bf16',
      context_len: 32768,
    });
    sub().emit({
      type: 'placed',
      deployment_id: 'dep_1',
      at: 't2',
      provider: 'modal',
      region: 'us-east',
    });

    expect(timelineItem('Requested')).toHaveAttribute('data-status', 'done');
    expect(timelineItem('Compiled')).toHaveAttribute('data-status', 'done');
    expect(timelineItem('Placed')).toHaveAttribute('data-status', 'active');
    expect(timelineItem('Provisioning')).toHaveAttribute('data-status', 'pending');
  });

  it('renders progress percent + message during provisioning', () => {
    const { client, sub } = makeClient();
    render(<Provisioning deploymentId="dep_1" client={client} />);
    sub().emit({
      type: 'provisioning',
      deployment_id: 'dep_1',
      at: 't0',
    });
    sub().emit({
      type: 'progress',
      deployment_id: 'dep_1',
      at: 't1',
      percent: 60,
      message: 'pulling weights',
    });

    const progress = screen.getByRole('progressbar');
    expect(progress).toHaveAttribute('aria-valuenow', '60');
    expect(within(progress).getByText('60%')).toBeInTheDocument();
    expect(within(progress).getByText(/pulling weights/i)).toBeInTheDocument();
  });

  it('renders the endpoint URL and an Open chat link on HEALTHY', () => {
    const { client, sub } = makeClient();
    render(<Provisioning deploymentId="dep_1" client={client} />);
    sub().emit({
      type: 'healthy',
      deployment_id: 'dep_1',
      at: 't0',
      endpoint_url: 'https://endpoint.test/v1',
    });

    expect(screen.getByText('https://endpoint.test/v1')).toBeInTheDocument();
    const cta = screen.getByRole('link', { name: /open chat/i });
    expect(cta).toHaveAttribute('href', '#/deployments/dep_1/chat');
    expect(timelineItem('Healthy')).toHaveAttribute('data-status', 'done');
  });

  it('renders failure messaging on a failed event', () => {
    const { client, sub } = makeClient();
    render(<Provisioning deploymentId="dep_1" client={client} />);
    sub().emit({ type: 'requested', deployment_id: 'dep_1', at: 't0' });
    sub().emit({
      type: 'failed',
      deployment_id: 'dep_1',
      at: 't1',
      reason: 'GPU shortage',
    });
    expect(
      screen.getByRole('alert', { name: undefined }),
    ).toHaveTextContent(/deployment failed.*gpu shortage/i);
  });

  it('shows a transport warning if the SSE connection drops mid-flight', async () => {
    const { client, sub } = makeClient();
    render(<Provisioning deploymentId="dep_1" client={client} />);
    sub().fail();
    expect(
      await screen.findByText(/connection to deployment events lost/i),
    ).toBeInTheDocument();
  });

  it('does not show the transport warning after a terminal event', () => {
    const { client, sub } = makeClient();
    render(<Provisioning deploymentId="dep_1" client={client} />);
    sub().emit({
      type: 'healthy',
      deployment_id: 'dep_1',
      at: 't0',
      endpoint_url: 'https://endpoint',
    });
    sub().fail();
    expect(
      screen.queryByText(/connection to deployment events lost/i),
    ).not.toBeInTheDocument();
  });

  it('closes the SSE connection on unmount', async () => {
    const { client, sub } = makeClient();
    const { unmount } = render(
      <Provisioning deploymentId="dep_1" client={client} />,
    );
    unmount();
    await waitFor(() => expect(sub().closed).toBe(true));
  });
});
