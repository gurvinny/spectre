/**
 * First-run setup wizard: create the admin access key and confirm the Wazuh
 * forwarding target. Only reachable before any user exists.
 * Author: gurvinny
 */
"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { SpectreMark } from "@/components/SpectreMark";

export function SetupWizard({ onDone }: { onDone: () => void }) {
  const [pw, setPw] = useState("");
  const [confirm, setConfirm] = useState("");
  const [wazuhHost, setWazuhHost] = useState("10.0.0.20");
  const [wazuhPort, setWazuhPort] = useState("514");
  const [wazuhProto, setWazuhProto] = useState("udp");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (pw.length < 6) return setError("Access key must be at least 6 characters.");
    if (pw !== confirm) return setError("Access keys do not match.");
    setBusy(true);
    setError(null);
    try {
      await api.post("/api/setup", {
        password: pw,
        wazuh_host: wazuhHost,
        wazuh_port: Number(wazuhPort),
        wazuh_proto: wazuhProto,
      });
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "setup failed");
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen relative z-10 grid place-items-center px-6 py-10">
      <div className="panel scanlines w-full max-w-lg p-8">
        <div className="mb-2">
          <SpectreMark size="md" />
        </div>
        <p className="text-ink-mute text-xs mb-8 leading-relaxed">
          First-run provisioning. Set an access key for this console and confirm
          where threats should be forwarded. You can change everything later in
          Settings.
        </p>

        <form onSubmit={submit} className="flex flex-col gap-6">
          <section className="flex flex-col gap-3">
            <div className="eyebrow flex items-center gap-2">
              <span className="text-phosphor">01</span> Console access
            </div>
            <input
              type="password"
              autoFocus
              placeholder="Access key"
              value={pw}
              onChange={(e) => setPw(e.target.value)}
              className="font-mono bg-scope-bg border border-scope-line rounded-sm px-3 py-2.5 focus:border-phosphor"
            />
            <input
              type="password"
              placeholder="Confirm access key"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              className="font-mono bg-scope-bg border border-scope-line rounded-sm px-3 py-2.5 focus:border-phosphor"
            />
          </section>

          <section className="flex flex-col gap-3">
            <div className="eyebrow flex items-center gap-2">
              <span className="text-phosphor">02</span> Wazuh forwarding
            </div>
            <div className="grid grid-cols-[1fr_auto_auto] gap-2">
              <input
                placeholder="host"
                value={wazuhHost}
                onChange={(e) => setWazuhHost(e.target.value)}
                className="font-mono bg-scope-bg border border-scope-line rounded-sm px-3 py-2.5 focus:border-phosphor"
              />
              <input
                placeholder="port"
                value={wazuhPort}
                onChange={(e) => setWazuhPort(e.target.value)}
                className="font-mono w-20 bg-scope-bg border border-scope-line rounded-sm px-3 py-2.5 focus:border-phosphor"
              />
              <select
                value={wazuhProto}
                onChange={(e) => setWazuhProto(e.target.value)}
                className="font-mono bg-scope-bg border border-scope-line rounded-sm px-2 focus:border-phosphor"
              >
                <option value="udp">UDP</option>
                <option value="tcp">TCP</option>
              </select>
            </div>
            <p className="text-ink-mute text-[0.68rem] font-mono">
              RFC 5424 syslog · threats + summaries only
            </p>
          </section>

          {error && <p className="text-alert text-xs font-mono">{error}</p>}

          <button
            type="submit"
            disabled={busy}
            className="font-mono text-sm tracking-wider py-3 bg-phosphor/10 border border-phosphor-dim text-phosphor hover:bg-phosphor/20 disabled:opacity-40 rounded-sm"
          >
            {busy ? "ARMING…" : "ARM SENSOR ▸"}
          </button>
        </form>
      </div>
    </div>
  );
}
