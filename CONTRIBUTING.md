# Contributing to SPECTRE

Thanks for your interest in SPECTRE.

## Ground rules

- **Conventional commits** — `feat:`, `fix:`, `docs:`, `refactor:`, `chore:`.
- **No secrets in git** — use `.env` (gitignored); `.env.example` documents every key.
- Keep the sensor's ingest/detection/storage **core standard-library only** so it stays testable
  without installing anything; third-party deps belong to the API layer.

## Dev setup

```bash
bash init.sh
# Sensor (no hardware): run with the simulator
docker compose up -d --build          # then set SPECTRE_SOURCE=sim in .env, or:
docker run --rm -e SPECTRE_SOURCE=sim -p 8100:8100 $(docker build -q sensor)
# Web
cd web && npm install && NEXT_PUBLIC_API_BASE=http://localhost:8100 npm run dev
```

## Testing your change

- **Sensor core** — exercise parser → pipeline → detection with the simulator; confirm the four
  rule families fire (`deauth_flood`, `evil_twin`, `beacon_probe_flood`, `anomaly`).
- **Detection** — `python -m spectre.sim.generate --scenario <name>` to reproduce an attack.
- **Web** — `npm run build` must pass with no type errors.
- **Real hardware** — run the `sensor` container with `--device /dev/ttyUSB0` and confirm the boot
  event, band auto-detection, and live inventory.

## Adding a detection rule

1. Add `sensor/spectre/detect/<rule>.py` subclassing `Rule`.
2. Register it in `detect/__init__.py::Engine`.
3. Add its thresholds to `config.py::DEFAULTS` and surface them in **Settings**.
4. Document it in `docs/detection-rules.md`.

## Style

Match the surrounding code's conventions and comment density. Every source file carries a short
header (`Author: … · Project: SPECTRE`). No AI-attribution markers anywhere.

_Maintainer: gurvinny — [github.com/gurvinny](https://github.com/gurvinny)_
