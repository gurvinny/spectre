/**
 * Shares a single live WebSocket feed across the whole console so we don't open
 * one socket per page/component.
 * Author: gurvinny
 */
"use client";

import { createContext, useContext } from "react";
import { useLiveFeed } from "@/hooks/useLiveFeed";

type Live = ReturnType<typeof useLiveFeed>;
const LiveContext = createContext<Live | null>(null);

export function LiveProvider({ children }: { children: React.ReactNode }) {
  const live = useLiveFeed(true);
  return <LiveContext.Provider value={live}>{children}</LiveContext.Provider>;
}

export function useLive(): Live {
  const ctx = useContext(LiveContext);
  if (!ctx) throw new Error("useLive must be used within LiveProvider");
  return ctx;
}
