import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { CatalogEntry, HarborClient } from '../api/harbor';
import PickModel from './PickModel';

const CATALOG: CatalogEntry[] = [
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
];

function makeClient(overrides: Partial<HarborClient> = {}): HarborClient {
  const base: Partial<HarborClient> = {
    listCatalog: vi.fn().mockResolvedValue(CATALOG),
    createDeployment: vi
      .fn()
      .mockResolvedValue({ deployment_id: 'dep_test' }),
  };
  return { ...base, ...overrides } as unknown as HarborClient;
}

describe('PickModel', () => {
  it('shows a loading state and then renders catalog cards', async () => {
    const client = makeClient();
    render(<PickModel client={client} onProvisioned={() => undefined} />);
    expect(screen.getByText(/loading catalog/i)).toBeInTheDocument();
    await screen.findByText('Qwen/Qwen2.5-3B-Instruct');
    expect(screen.getByText('Qwen/Qwen2.5-7B-Instruct')).toBeInTheDocument();
    expect(screen.getByText('3.09B params')).toBeInTheDocument();
    expect(screen.getByText('7.62B params')).toBeInTheDocument();
    expect(screen.getAllByText('32K context')).toHaveLength(2);
    expect(screen.getByText('6.2 GB weights')).toBeInTheDocument();
    expect(screen.getByText('15.2 GB weights')).toBeInTheDocument();
  });

  it('default-selects the 7B model when present', async () => {
    const client = makeClient();
    render(<PickModel client={client} onProvisioned={() => undefined} />);
    const sevenB = await screen.findByRole('radio', {
      name: /Qwen2\.5-7B-Instruct/,
    });
    expect(sevenB).toHaveAttribute('aria-checked', 'true');
  });

  it('lets the user switch the selected model', async () => {
    const client = makeClient();
    render(<PickModel client={client} onProvisioned={() => undefined} />);
    const threeB = await screen.findByRole('radio', {
      name: /Qwen2\.5-3B-Instruct/,
    });
    fireEvent.click(threeB);
    expect(threeB).toHaveAttribute('aria-checked', 'true');
  });

  it('calls createDeployment with the selected model and routes onProvisioned', async () => {
    const createDeployment = vi
      .fn()
      .mockResolvedValue({ deployment_id: 'dep_xyz' });
    const client = makeClient({
      createDeployment,
    });
    const onProvisioned = vi.fn();
    render(<PickModel client={client} onProvisioned={onProvisioned} />);
    await screen.findByText('Qwen/Qwen2.5-7B-Instruct');

    fireEvent.click(screen.getByRole('button', { name: /provision endpoint/i }));

    await waitFor(() => expect(createDeployment).toHaveBeenCalledTimes(1));
    expect(createDeployment).toHaveBeenCalledWith({
      model_ref: 'Qwen/Qwen2.5-7B-Instruct',
      workflow_type: 'chat',
      priority: 'latency',
    });
    await waitFor(() =>
      expect(onProvisioned).toHaveBeenCalledWith('dep_xyz'),
    );
  });

  it('surfaces a catalog load error', async () => {
    const client = makeClient({
      listCatalog: vi.fn().mockRejectedValue(new Error('catalog down')),
    });
    render(<PickModel client={client} onProvisioned={() => undefined} />);
    expect(
      await screen.findByText(/catalog down/i),
    ).toBeInTheDocument();
  });

  it('surfaces a deployment-creation error and re-enables the button', async () => {
    const client = makeClient({
      createDeployment: vi
        .fn()
        .mockRejectedValue(new Error('deploy upstream offline')),
    });
    render(<PickModel client={client} onProvisioned={() => undefined} />);
    await screen.findByText('Qwen/Qwen2.5-7B-Instruct');
    const button = screen.getByRole('button', {
      name: /provision endpoint/i,
    });
    fireEvent.click(button);
    expect(
      await screen.findByText(/deploy upstream offline/i),
    ).toBeInTheDocument();
    await waitFor(() => expect(button).not.toBeDisabled());
  });
});
