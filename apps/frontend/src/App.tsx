import { useState } from 'react';

function App() {
  const [count, setCount] = useState(0);
  return (
    <main>
      <h1>Harbor</h1>
      <p>Count: {count}</p>
      <button onClick={() => setCount((c) => c + 1)}>increment</button>
    </main>
  );
}

export default App;
