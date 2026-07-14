/**
 * Single-password login.
 * Author: gurvinny
 */
"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { SpectreMark } from "@/components/SpectreMark";

export function LoginScreen({ onDone }: { onDone: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/api/login", { password });
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "login failed");
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen relative z-10 grid place-items-center px-6">
      <div className="panel scanlines w-full max-w-sm p-8">
        <div className="mb-8">
          <SpectreMark size="md" />
        </div>
        <form onSubmit={submit} className="flex flex-col gap-4">
          <label className="eyebrow">Access key</label>
          <input
            type="password"
            autoFocus
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="font-mono bg-scope-bg border border-scope-line rounded-sm px-3 py-2.5 text-ink focus:border-phosphor"
            placeholder="••••••••"
          />
          {error && <p className="text-alert text-xs font-mono">{error}</p>}
          <button
            type="submit"
            disabled={busy || !password}
            className="mt-2 font-mono text-sm tracking-wider py-2.5 bg-phosphor/10 border border-phosphor-dim text-phosphor hover:bg-phosphor/20 disabled:opacity-40 rounded-sm"
          >
            {busy ? "AUTHENTICATING…" : "UNLOCK CONSOLE"}
          </button>
        </form>
      </div>
    </div>
  );
}
