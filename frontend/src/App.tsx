export function App() {
  return (
    <main className="shell">
      <div className="brand-mark" aria-hidden="true">
        S
      </div>
      <p className="eyebrow">API reliability · self hosted</p>
      <h1>Sentinel</h1>
      <p className="lead">Foundation is ready for development.</p>
      <p className="description">
        The API and durable worker share a modular backend. PostgreSQL owns work
        delivery, and Tempo receives standard OpenTelemetry spans.
      </p>
      <nav aria-label="Development resources">
        <a href="/health/ready">API readiness</a>
      </nav>
      <p className="milestone">
        Milestone 1 · Repository foundation and durable work skeleton
      </p>
    </main>
  );
}
