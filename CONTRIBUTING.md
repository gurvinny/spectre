# Contributing to SPECTRE

Thanks for taking an interest. SPECTRE is a single-author project: all of its code, firmware and
documentation are written and maintained by one person. That keeps the design coherent and the
licensing simple, so **pull requests are not merged**, however good they are. The rest of this page is
about everything that does help, and there is plenty.

## Ways to help

- **Report a bug.** Open an [issue](../../issues). It helps most when it includes the firmware version
  (on the **Boards** page, or the `ver` in a board's `boot` line), how the sensor is fed (real boards
  or `SPECTRE_SOURCE=sim`), and the relevant `docker compose logs sensor` lines.
- **Suggest a feature or a detection.** Also an issue. A description of the traffic pattern and why it
  matters is worth more than an implementation: the rule gets built to fit the rest of the engine.
- **Report a vulnerability privately.** Not as an issue: use **Security → Report a vulnerability** on
  this repository. [SECURITY.md](SECURITY.md) covers scope and what to expect.
- **Ask about the design.** Issues are fine for questions too.

If you have already written a fix, describe it in the issue. A clear description of the change, or a
failing test case, gets it into the project quickly, written to match the surrounding code.

## Running your own copy

SPECTRE is AGPL-3.0-or-later, so you are free to run, study, modify and share it under those terms. If
you host a modified version for others, the AGPL asks you to publish your changes under the same
licence. Everything below is for working on your own fork.

```bash
bash init.sh
# set SPECTRE_SOURCE=sim in .env and comment out devices: in docker-compose.yml to run without boards
docker compose up -d --build
# Web, with hot reload
cd web && npm install && NEXT_PUBLIC_API_BASE=http://localhost:8100 npm run dev
```

Boards and firmware: [docs/hardware.md](docs/hardware.md) and [docs/flashing.md](docs/flashing.md).
Keep secrets out of git: use `.env` (gitignored); `.env.example` documents every key.

The sensor's ingest/detection/storage **core is standard-library only** on purpose, so it stays
testable without installing anything. Third-party dependencies belong to the API layer.

### Checking a change in your fork

- **Sensor**: `python sensor/scripts/run_tests.py` (floors enforced) and `python sensor/scripts/mutate.py`.
- **Detection**: `python -m spectre.sim.generate --scenario <name>` reproduces an attack; confirm the four
  rule families fire (`deauth_flood`, `evil_twin`, `beacon_probe_flood`, `anomaly`).
- **Web**: `npm run test`, `npm run lint` (`tsc --noEmit`) and `npm run build`.
- **Firmware**: `make -C firmware/test samples` and `python3 firmware/scripts/mutate.py`.
- **Real hardware**: flash with `firmware/flash.py`, then check the Boards page: firmware version, band,
  plan, loss.

### Adding a detection rule

1. Add `sensor/spectre/detect/<rule>.py` subclassing `Rule`.
2. Register it in `detect/__init__.py::Engine`.
3. Add its thresholds to `config.py::DEFAULTS` and surface them in **Settings**.
4. Document it in `docs/detection-rules.md`.

### House conventions

Match the surrounding code's conventions and comment density. Every source file carries a short
header (`Author: … · Project: SPECTRE`). Commits follow conventional prefixes: `feat:`, `fix:`,
`docs:`, `refactor:`, `chore:`.

_Maintainer: gurvinny · [github.com/gurvinny](https://github.com/gurvinny)_
