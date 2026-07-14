/**
 * Live WebSocket feed hook.
 * Maintains a rolling window of frames + threats and the latest overview
 * snapshot, and auto-reconnects. Frames arrive batched (~4 Hz) so the UI stays
 * smooth under ~60 frames/sec.
 * Author: gurvinny
 */
"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { api, wsUrl } from "@/lib/api";
import type { Frame, Threat, Overview, WsMessage } from "@/lib/types";

const MAX_FRAMES = 500;
const MAX_THREATS = 120;

export type ConnState = "connecting" | "live" | "down";

export function useLiveFeed(enabled = true) {
  const [conn, setConn] = useState<ConnState>("connecting");
  const [frames, setFrames] = useState<Frame[]>([]);
  const [threats, setThreats] = useState<Threat[]>([]);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [fps, setFps] = useState(0);
  const wsRef = useRef<WebSocket | null>(null);
  const retry = useRef<ReturnType<typeof setTimeout> | null>(null);
  const paused = useRef(false);

  const setPaused = useCallback((p: boolean) => {
    paused.current = p;
  }, []);

  useEffect(() => {
    if (!enabled) return;
    let closed = false;

    function connect() {
      setConn("connecting");
      const ws = new WebSocket(wsUrl());
      wsRef.current = ws;

      ws.onopen = () => setConn("live");
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data) as WsMessage;
        if (msg.type === "snapshot") {
          setOverview(msg.overview);
          setFps(msg.overview.fps);
          return;
        }
        setFps(msg.fps);
        if (msg.threats.length) {
          setThreats((prev) =>
            [...msg.threats, ...prev].slice(0, MAX_THREATS),
          );
        }
        if (!paused.current && msg.frames.length) {
          setFrames((prev) => [...msg.frames.slice().reverse(), ...prev].slice(0, MAX_FRAMES));
        }
      };
      ws.onclose = () => {
        if (closed) return;
        setConn("down");
        retry.current = setTimeout(connect, 2000);
      };
      ws.onerror = () => ws.close();
    }

    connect();

    // The WS snapshot only fires on connect; poll the aggregate overview so
    // counts, channel histogram and sensor state stay fresh app-wide.
    const poll = setInterval(async () => {
      try {
        setOverview(await api.get<Overview>("/api/overview"));
      } catch {
        /* transient — the WS status already reflects link health */
      }
    }, 4000);

    return () => {
      closed = true;
      if (retry.current) clearTimeout(retry.current);
      clearInterval(poll);
      wsRef.current?.close();
    };
  }, [enabled]);

  return { conn, frames, threats, overview, fps, setPaused };
}
