import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { DeploymentEvent } from './api/harbor';

// Hoisted fake state lives in `vi.hoisted` so it can be referenced inside the
// factory below — `vi.mock` is hoisted above the file's normal imports.
const fakeHarbor = vi.hoisted(() => {
  const subscribers: ((e: DeploymentEvent) => void)[] = [];
  return {
    listCatalog: vi.fn().mockResolvedValue([
      {
        identifier: 'Qwen/Qwen2.5-3B-Instruct',
        parameters_billion: 3.09,
        native_dtype: 'bf16',
        max_context: 32768,
        weights_size_gb: 6.2,
      },
      {
        identifier: 'Qwen/Qwen2.5-7B-Instruct',
        parameters_billion: 7.62,
        native_dtype: 'bf16',
        max_context: 32768,
        weights_size_gb: 15.2,
      },
    ]),
    createDeployment: vi
      .fn()
      .mockResolvedValue({ deployment_id: 'dep_fake' }),
    streamDeploymentEvents: vi.fn(
      (_id: string, handlers: { onEvent: (e: DeploymentEvent) => void }) => {
        subscribers.push(handlers.onEvent);
        return { close: () => undefined };
      },
    ),
    getDeployment: vi.fn().mockResolvedValue({
      deployment_id: 'dep_fake',
      state: 'HEALTHY',
      endpoint_url: 'https://endpoint.test/v1',
      failure_reason: null,
      created_at: '2026-05-23T12:00:00Z',
      updated_at: '2026-05-23T12:00:01Z',
    }),
    emit(event: DeploymentEvent) {
      for (const sub of subscribers) sub(event);
    },
    reset() {
      subscribers.length = 0;
      this.listCatalog.mockClear();
      this.createDeployment.mockClear();
      this.streamDeploymentEvents.mockClear();
      this.getDeployment.mockClear();
    },
  };
});

vi.mock('./api/harbor', async () => {
  const actual = await vi.importActual<typeof import('./api/harbor')>(
    './api/harbor',
  );
  return {
    ...actual,
    harborClient: fakeHarbor,
  };
});

// Imports below run after the mock is installed.
import App from './App';

describe('App router', () => {
  beforeEach(() => {
    fakeHarbor.reset();
    window.location.hash = '#/';
  });

  afterEach(() => {
    window.location.hash = '';
  });

  it('renders the Harbor brand chrome and the picker by default', async () => {
    render(<App />);
    expect(screen.getByRole('link', { name: 'Harbor' })).toBeInTheDocument();
    await screen.findByRole('heading', { level: 1, name: 'Pick a model' });
  });

  it('navigates to the provisioning screen after a deployment is created', async () => {
    render(<App />);
    await screen.findByRole('heading', { level: 1, name: 'Pick a model' });
    fireEvent.click(
      screen.getByRole('button', { name: /provision endpoint/i }),
    );
    await waitFor(() =>
      expect(fakeHarbor.createDeployment).toHaveBeenCalled(),
    );
    await screen.findByRole('heading', { level: 1, name: 'Provisioning' });
    expect(window.location.hash).toBe('#/deployments/dep_fake');

    act(() =>
      fakeHarbor.emit({
        type: 'healthy',
        deployment_id: 'dep_fake',
        at: 't0',
        endpoint_url: 'https://endpoint',
      }),
    );
    await screen.findByText('https://endpoint');
  });

  it('renders the chat screen for the chat hash route', async () => {
    render(<App />);
    await screen.findByRole('heading', { level: 1, name: 'Pick a model' });
    window.location.hash =
      '#/deployments/dep_fake/chat?model=Qwen%2FQwen2.5-7B-Instruct';
    await screen.findByRole('heading', { level: 1, name: 'Chat' });
    expect(
      await screen.findByText('Qwen/Qwen2.5-7B-Instruct'),
    ).toBeInTheDocument();
  });

  it('renders a not-found screen for unknown hashes', async () => {
    render(<App />);
    await screen.findByRole('heading', { level: 1, name: 'Pick a model' });
    window.location.hash = '#/nope';
    await screen.findByRole('heading', { level: 1, name: 'Not found' });
  });
});
