import { useCallback, useEffect, useState } from 'react';
import PickModel from './screens/PickModel';
import Provisioning from './screens/Provisioning';

interface ParsedRoute {
  kind: 'pick' | 'provisioning' | 'chat-placeholder' | 'unknown';
  deploymentId?: string;
}

function parseRoute(hash: string): ParsedRoute {
  // Strip leading "#" and any leading slash so both "#/" and "#" work.
  const path = hash.replace(/^#\/?/, '/');
  if (path === '/' || path === '') return { kind: 'pick' };
  const provisioningMatch = path.match(/^\/deployments\/([^/]+)$/);
  if (provisioningMatch) {
    return { kind: 'provisioning', deploymentId: provisioningMatch[1] };
  }
  const chatMatch = path.match(/^\/deployments\/([^/]+)\/chat$/);
  if (chatMatch) {
    return { kind: 'chat-placeholder', deploymentId: chatMatch[1] };
  }
  return { kind: 'unknown' };
}

function App() {
  const [route, setRoute] = useState<ParsedRoute>(() =>
    parseRoute(window.location.hash),
  );

  useEffect(() => {
    const onHashChange = (): void => {
      setRoute(parseRoute(window.location.hash));
    };
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  const goTo = useCallback((hash: string): void => {
    window.location.hash = hash;
  }, []);

  const handleProvisioned = useCallback(
    (deploymentId: string): void => {
      goTo(`#/deployments/${deploymentId}`);
    },
    [goTo],
  );

  return (
    <div className="harbor-shell">
      <nav className="harbor-nav">
        <a href="#/" className="harbor-nav__brand">
          Harbor
        </a>
        <span className="harbor-nav__tag">model picker · status</span>
      </nav>
      <main>
        {route.kind === 'pick' && (
          <PickModel onProvisioned={handleProvisioned} />
        )}
        {route.kind === 'provisioning' && route.deploymentId && (
          <Provisioning deploymentId={route.deploymentId} />
        )}
        {route.kind === 'chat-placeholder' && (
          <section className="harbor-screen">
            <header className="harbor-screen__header">
              <h1>Chat coming soon</h1>
              <p className="harbor-screen__lede">
                The chat panel lands with SYM-215. Endpoint is provisioned and
                ready.
              </p>
            </header>
            <a href="#/" className="harbor-primary harbor-primary--link">
              Back to model picker
            </a>
          </section>
        )}
        {route.kind === 'unknown' && (
          <section className="harbor-screen">
            <header className="harbor-screen__header">
              <h1>Not found</h1>
              <p className="harbor-screen__lede">
                Nothing lives at <code>{window.location.hash || '#/'}</code>.
              </p>
            </header>
            <a href="#/" className="harbor-primary harbor-primary--link">
              Back to model picker
            </a>
          </section>
        )}
      </main>
    </div>
  );
}

export default App;
