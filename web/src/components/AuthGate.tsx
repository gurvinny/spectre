/**
 * Auth gate — decides between first-run setup, login, and the app shell.
 * Author: gurvinny
 */
"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { Shell } from "@/components/Shell";
import { LoginScreen } from "@/components/auth/LoginScreen";
import { SetupWizard } from "@/components/auth/SetupWizard";
import { BootScreen } from "@/components/auth/BootScreen";

type Gate = "boot" | "offline" | "setup" | "login" | "authed";

export function AuthGate({ children }: { children: React.ReactNode }) {
  const [gate, setGate] = useState<Gate>("boot");

  const probe = useCallback(async () => {
    try {
      const status = await api.get<{ setup_complete: boolean }>("/api/status");
      if (!status.setup_complete) {
        setGate("setup");
        return;
      }
      try {
        await api.get("/api/overview");
        setGate("authed");
      } catch (e) {
        setGate(e instanceof ApiError && e.status === 401 ? "login" : "authed");
      }
    } catch {
      setGate("offline");
    }
  }, []);

  useEffect(() => {
    probe();
  }, [probe]);

  if (gate === "boot") return <BootScreen />;
  if (gate === "offline") return <BootScreen offline onRetry={probe} />;
  if (gate === "setup") return <SetupWizard onDone={() => setGate("authed")} />;
  if (gate === "login") return <LoginScreen onDone={() => setGate("authed")} />;
  return <Shell>{children}</Shell>;
}
