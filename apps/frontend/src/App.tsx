import { useCallback, useEffect, useState } from 'react';
import Chat from './screens/Chat';
import PickModel from './screens/PickModel';
import Provisioning from './screens/Provisioning';

interface ParsedRoute {
  kind: 'pick' | 'provisioning' | 'chat' | 'unknown';
  deploymentId?: string;
  /** Model identifier carried through the chat hash query (``?model=…``). */
  model?: string;
  /** Endpoint URL hint, also passed via the hash query. */
  endpointUrl?: string;
}

function parseRoute(hash: string): ParsedRoute {
  // Strip leading "#" + optional "/" so both "#/" and "#" work. Split the
  // query off the path before pattern-matching: hash routes don't enjoy the
  // automatic ``URL`` parsing of regular paths.
  const trimmed = hash.replace(/^#\/?/, '/');
  const [pathPart, queryPart = ''] = trimmed.split('?');
  const params = new URLSearchParams(queryPart);

  if (pathPart === '/' || pathPart === '') return { kind: 'pick' };

  const provisioningMatch = pathPart.match(/^\/deployments\/([^/]+)$/);
  if (provisioningMatch) {
    return { kind: 'provisioning', deploymentId: provisioningMatch[1] };
  }

  const chatMatch = pathPart.match(/^\/deployments\/([^/]+)\/chat$/);
  if (chatMatch) {
    return {
      kind: 'chat',
      deploymentId: chatMatch[1],
      model: params.get('model') ?? undefined,
      endpointUrl: params.get('endpoint') ?? undefined,
    };
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
        <span className="harbor-nav__tag">model picker · status · chat</span>
      </nav>
      <main>
        {route.kind === 'pick' && (
          <PickModel onProvisioned={handleProvisioned} />
        )}
        {route.kind === 'provisioning' && route.deploymentId && (
          <Provisioning deploymentId={route.deploymentId} />
        )}
        {route.kind === 'chat' && route.deploymentId && (
          <Chat
            deploymentId={route.deploymentId}
            model={route.model}
            endpointUrl={route.endpointUrl}
          />
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
