# Contributing to SPECTRE

SPECTRE is a single-author project and **does not accept code contributions**. Please do not open
pull requests — they will be closed unmerged.

This is not a judgement on anyone's code. SPECTRE is dual-licensed: AGPL-3.0-or-later for everyone,
plus a separate commercial licence for closed-source use. Offering that second licence requires one
author to hold copyright in the whole codebase. A merged contribution stays the contributor's
copyright, licensed to the project under the AGPL only, which would make the commercial option
impossible to honour without tracking down every past contributor for permission. Declining code up
front is the honest way to keep that promise.

## What is welcome

- **Bug reports** — open an [issue](../../issues). Include the sensor firmware version, how the
  sensor is being fed (real hardware or `SPECTRE_SOURCE=sim`), and the relevant log lines.
- **Feature requests and detection-rule ideas** — also issues. A description of the traffic pattern
  and why it matters is more useful than an implementation.
- **Security reports** — please do not open a public issue. Reach out via
  [github.com/gurvinny](https://github.com/gurvinny).
- **Questions about the design** — issues are fine for these too.

## Running your own copy

The AGPL gives you the right to run, study and modify SPECTRE, and to distribute your changes under
the same licence. The rest of this file documents how to do that in your own fork. Nothing here is a
request for a pull request.

```bash
bash init.sh
# Sensor (no hardware): run with the simulator
docker compose up -d --build          # then set SPECTRE_SOURCE=sim in .env, or:
docker run --rm -e SPECTRE_SOURCE=sim -p 8100:8100 $(docker build -q sensor)
# Web
cd web && npm install && NEXT_PUBLIC_API_BASE=http://localhost:8100 npm run dev
```

Keep secrets out of git — use `.env` (gitignored); `.env.example` documents every key.

The sensor's ingest/detection/storage **core is standard-library only** on purpose, so it stays
testable without installing anything. Third-party dependencies belong to the API layer.

## Verifying a change in your fork

- **Sensor core** — exercise parser → pipeline → detection with the simulator; confirm the four rule
  families fire (`deauth_flood`, `evil_twin`, `beacon_probe_flood`, `anomaly`).
- **Detection** — `python -m spectre.sim.generate --scenario <name>` to reproduce an attack.
- **Web** — `npm run build` must pass with no type errors.
- **Real hardware** — run the `sensor` container with `--device /dev/ttyUSB0` and confirm the boot
  event, band auto-detection, and live inventory.

## Adding a detection rule

1. Add `sensor/spectre/detect/<rule>.py` subclassing `Rule`.
2. Register it in `detect/__init__.py::Engine`.
3. Add its thresholds to `config.py::DEFAULTS` and surface them in **Settings**.
4. Document it in `docs/detection-rules.md`.

## House conventions

Match the surrounding code's conventions and comment density. Every source file carries a short
header (`Author: … · Project: SPECTRE`). Commits follow conventional prefixes — `feat:`, `fix:`,
`docs:`, `refactor:`, `chore:`.

_Maintainer: gurvinny — [github.com/gurvinny](https://github.com/gurvinny)_
