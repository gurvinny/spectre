# SPECTRE · web

[![Next.js](https://img.shields.io/badge/Next.js-15-C9D6DF.svg?style=flat-square&logo=nextdotjs&logoColor=white&labelColor=0a0e12)](.)
[![Tailwind](https://img.shields.io/badge/Tailwind-v4-9B8CFF.svg?style=flat-square&logo=tailwindcss&logoColor=white&labelColor=0a0e12)](.)
[![Recharts](https://img.shields.io/badge/Recharts-2.x-35E0C4.svg?style=flat-square&labelColor=0a0e12)](.)

The SOC console — a spectrum-analyzer–styled dashboard over the sensor API.

## Design language

RF test-equipment aesthetic: phosphor-teal signal on scope-black, `Chakra Petch` display,
`IBM Plex Sans` UI, `IBM Plex Mono` for all data (MACs, frames, JSON — the idiom the firmware
speaks). The signature is the live **SPECTRE console banner** and the channel-utilization
**spectrum sweep**.

## Pages

`Overview` · `Live Feed` · `Devices` · `Access Points` · `Threats` · `Channels` · `Settings`,
behind a single-password gate with a first-run setup wizard.

One shared WebSocket (`LiveProvider`) feeds the whole app; REST polling backs the inventory tables.

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

_Author: gurvinny · Project: SPECTRE_
