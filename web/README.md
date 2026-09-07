# SPECTRE · web

[![Next.js](https://img.shields.io/badge/Next.js-15-C9D6DF.svg?style=flat-square&logo=nextdotjs&logoColor=white&labelColor=0a0e12)](.)
[![Tailwind](https://img.shields.io/badge/Tailwind-v4-9B8CFF.svg?style=flat-square&logo=tailwindcss&logoColor=white&labelColor=0a0e12)](.)
[![ECharts](https://img.shields.io/badge/ECharts-5.x-35E0C4.svg?style=flat-square&labelColor=0a0e12)](.)
[![three](https://img.shields.io/badge/three%20%2F%20r3f-WebGL-9B8CFF.svg?style=flat-square&labelColor=0a0e12)](.)

The SOC console — a spectrum-analyzer–styled dashboard over the sensor API.

## Design language

RF test-equipment aesthetic: phosphor-teal signal on scope-black, `Chakra Petch` display,
`IBM Plex Sans` UI, `IBM Plex Mono` for all data (MACs, frames, JSON — the idiom the firmware
speaks). The signature is the live **SPECTRE console banner** and the channel-utilization
**spectrum sweep**.

## Pages

| Route | What it is |
|---|---|
| `/` | **Command Center** — headline counters, live feed, threat timeline |
| `/spectrum` | Channel-utilization analyzer + waterfall heatmap |
| `/live` | Raw live frame feed |
| `/inventory` | Devices and access points, with trust/mute and `active` / `archived` / `all` scopes |
| `/threats` | Detection log with a severity spine |
| `/battlespace` | 3D WebGL view of the RF environment |
| `/settings` | Live config, Known Networks, appearance |

All behind a single-password gate with a first-run setup wizard.

One shared WebSocket (`LiveProvider`) feeds the whole app; REST polling backs the inventory tables.
`⌘K` opens a global search backed by SQLite FTS5.

## Charts and 3D

Charts go through a thin `components/viz/Chart.tsx` wrapper over ECharts core; `lib/echartsTheme.ts`
resolves CSS-variable tokens to hex so charts re-tint when the theme changes. Four dark skins
(Phosphor, Amber, Ice, Nightvision) swap only the accent — severity and status colours stay
semantic.

The `/battlespace` route is a `dynamic(..., { ssr: false })` import, so the `three` /
react-three-fiber dependencies stay isolated to that one route and never enter the shared bundle.
Its position layout is deterministic (azimuth clusters by SSID, radius and height from signal
strength) — **not** triangulation. It carries an adaptive quality engine with three user-facing
modes; on low-end or software WebGL it degrades to a fully static render rather than dropping
frames.

## Develop

```bash
npm install
NEXT_PUBLIC_API_BASE=http://localhost:8100 npm run dev   # http://localhost:4100
```

`NEXT_PUBLIC_API_BASE` points the browser at the sensor API; it is baked into the client bundle at
build time (Docker passes it as a build arg from `.env`).

## Build

```bash
npm run build     # Next standalone output, served by the Docker runner on :3000 (→ :4100)
```

## Test

```bash
npm run test      # 24 checks — esbuild-bundles each *.test.ts, runs under `node --test`
```

`npm run lint` is defined but ESLint is **not** installed here; `npx tsc --noEmit` is the gate.

_Author: gurvinny · Project: SPECTRE_
