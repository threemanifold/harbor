import { useEffect, useState } from 'react';
import type {
  CatalogEntry,
  DeploymentRequest,
  HarborClient,
  Priority,
  WorkflowType,
} from '../api/harbor';
import { harborClient } from '../api/harbor';

const DEFAULT_WORKFLOW: WorkflowType = 'chat';
const DEFAULT_PRIORITY: Priority = 'latency';

interface PickModelProps {
  client?: HarborClient;
  onProvisioned: (deploymentId: string) => void;
}

type Status =
  | { kind: 'loading' }
  | { kind: 'ready'; entries: CatalogEntry[] }
  | { kind: 'error'; message: string };

function describeBillions(value: number): string {
  // Two decimals reads natural for 3.09B / 7.62B
  return `${value.toFixed(2)}B params`;
}

function describeContext(tokens: number): string {
  if (tokens >= 1024) {
    const k = tokens / 1024;
    return `${Number.isInteger(k) ? k : k.toFixed(1)}K context`;
  }
  return `${tokens} context`;
}

function describeWeights(gb: number): string {
  return `${gb.toFixed(1)} GB weights`;
}

export function PickModel({
  client = harborClient,
  onProvisioned,
}: PickModelProps) {
  const [status, setStatus] = useState<Status>({ kind: 'loading' });
  const [selected, setSelected] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    client
      .listCatalog()
      .then((entries) => {
        if (!active) return;
        setStatus({ kind: 'ready', entries });
        // Default-select the larger model as the "recommended" pick.
        const recommended =
          entries.find((e) => e.identifier.includes('7B')) ?? entries[0];
        if (recommended) setSelected(recommended.identifier);
      })
      .catch((err: unknown) => {
        if (!active) return;
        const message =
          err instanceof Error ? err.message : 'Failed to load catalog.';
        setStatus({ kind: 'error', message });
      });
    return () => {
      active = false;
    };
  }, [client]);

  const handleProvision = async (): Promise<void> => {
    if (!selected) return;
    setSubmitting(true);
    setSubmitError(null);
    const request: DeploymentRequest = {
      model_ref: selected,
      workflow_type: DEFAULT_WORKFLOW,
      priority: DEFAULT_PRIORITY,
    };
    try {
      const { deployment_id } = await client.createDeployment(request);
      onProvisioned(deployment_id);
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'Failed to provision deployment.';
      setSubmitError(message);
      setSubmitting(false);
    }
  };

  return (
    <section className="harbor-screen harbor-pick-model" aria-busy={status.kind === 'loading'}>
      <header className="harbor-screen__header">
        <h1>Pick a model</h1>
        <p className="harbor-screen__lede">
          Choose a Qwen instruct model. Harbor compiles, places, and provisions
          it on demand.
        </p>
      </header>

      {status.kind === 'loading' && (
        <p role="status" className="harbor-status harbor-status--loading">
          Loading catalog…
        </p>
      )}

      {status.kind === 'error' && (
        <p role="alert" className="harbor-status harbor-status--error">
          {status.message}
        </p>
      )}

      {status.kind === 'ready' && (
        <>
          <ul className="harbor-card-grid" role="radiogroup" aria-label="Models">
            {status.entries.map((entry) => {
              const isSelected = entry.identifier === selected;
              return (
                <li key={entry.identifier}>
                  <button
                    type="button"
                    role="radio"
                    aria-checked={isSelected}
                    className={`harbor-card${
                      isSelected ? ' harbor-card--selected' : ''
                    }`}
                    onClick={() => setSelected(entry.identifier)}
                  >
                    <span className="harbor-card__title">
                      {entry.identifier}
                    </span>
                    <span className="harbor-card__badges">
                      <span className="harbor-badge">
                        {describeBillions(entry.parameters_billion)}
                      </span>
                      <span className="harbor-badge">
                        {describeContext(entry.max_context)}
                      </span>
                      <span className="harbor-badge">
                        {describeWeights(entry.weights_size_gb)}
                      </span>
                      <span className="harbor-badge harbor-badge--muted">
                        {entry.native_dtype}
                      </span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>

          <footer className="harbor-screen__footer">
            <button
              type="button"
              className="harbor-primary"
              onClick={handleProvision}
              disabled={!selected || submitting}
            >
              {submitting ? 'Provisioning…' : 'Provision endpoint'}
            </button>
            {submitError && (
              <p role="alert" className="harbor-status harbor-status--error">
                {submitError}
              </p>
            )}
          </footer>
        </>
      )}
    </section>
  );
}

export default PickModel;
