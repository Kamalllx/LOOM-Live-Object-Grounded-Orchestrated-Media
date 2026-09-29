"use client";
import { useEffect, useState } from "react";

export default function AgentsPage() {
  const [cards, setCards] = useState([]);
  const [url, setUrl] = useState("http://127.0.0.1:8100");
  const [msg, setMsg] = useState("");
  const load = () => fetch("/api/agents").then((r) => r.json()).then(setCards);
  useEffect(() => { load(); }, []);

  async function register() {
    setMsg("");
    const r = await fetch("/api/agents/register", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url }) });
    setMsg(r.ok ? "Registered - the orchestrator will now include this agent in every session." : `Failed: ${await r.text()}`);
    load();
  }
  async function remove(name) {
    await fetch(`/api/agents/${name}`, { method: "DELETE" });
    load();
  }

  return (
    <div className="grid" style={{ gap: 22 }}>
      <div>
        <div className="eyebrow">02 · Orchestrate</div>
        <h1>An <em>open</em> protocol. An <em>open</em> team.</h1>
        <p className="muted" style={{ maxWidth: 760 }}>Every agent publishes an A2A Agent Card and is tasked over JSON-RPC <span className="mono">message/send</span>.
          A school's or publisher's own agent joins by URL - no rebuild - and its output is still gated by the Critic.</p>
      </div>
      <div className="card">
        <h3>Register a third-party agent</h3>
        <div className="controls">
          <input value={url} onChange={(e) => setUrl(e.target.value)} style={{ maxWidth: 420 }} />
          <button className="btn primary" onClick={register}>Discover card & register</button>
        </div>
        {msg && <p className="muted">{msg}</p>}
      </div>
      <div className="grid two">
        {cards.map((c) => (
          <div key={c.name} className="card">
            <div className="controls" style={{ marginTop: 0 }}>
              <strong>{c.name}</strong>
              <span className="chip">v{c.version}</span>
              {!c.name.startsWith("loom-") && <span className="chip amber">third-party</span>}
              {!c.name.startsWith("loom-") && <button className="btn" onClick={() => remove(c.name)}>Remove</button>}
            </div>
            <p className="muted">{c.description}</p>
            <div className="controls">{c.skills.map((s) => <span key={s.id} className="chip teal">{s.id}</span>)}</div>
            <pre className="card-json">{JSON.stringify({ name: c.name, url: c.url, protocolVersion: c.protocolVersion, skills: c.skills.map((s) => ({ id: s.id, input: s.input, output: s.output })) }, null, 2)}</pre>
          </div>
        ))}
      </div>
    </div>
  );
}
