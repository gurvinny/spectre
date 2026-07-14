/**
 * Catches errors thrown while rendering the 3D scene so a WebGL/runtime failure
 * shows a readable message instead of a white screen, and logs the stack for
 * diagnosis. Author: gurvinny
 */
"use client";

import React from "react";

interface Props {
  children: React.ReactNode;
}
interface State {
  error: Error | null;
}

export class CanvasErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    // Surface the real cause in the console for debugging the crash.
    console.error("[battlespace] scene crashed:", error, info.componentStack);
  }

  render(): React.ReactNode {
    if (this.state.error) {
      return (
        <div className="absolute inset-0 grid place-items-center p-6 text-center">
          <div className="font-mono text-xs text-alert max-w-md leading-relaxed">
            <p className="mb-2">3D battlespace failed to render.</p>
            <p className="text-ink-mute break-words">{this.state.error.message}</p>
            <p className="text-ink-mute/70 mt-3">
              Check the browser console for the full stack.
            </p>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
