"""SPECTRE sensor entrypoint.

Wires the store, config, pipeline and API together, selects the ingest source
(real serial boards, the built-in simulator, or a capture replay), and serves
the FastAPI app with uvicorn.

    python -m spectre.main         # honours env (SPECTRE_SOURCE, SERIAL_PORTS…)

Author: gurvinny
Project: SPECTRE
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os

import uvicorn

from .api import create_app
from .config import Config
from .pipeline import Pipeline
from .reader import build_readers
from .store import Store

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("spectre")


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


def build() -> tuple:
    store = Store(_env("SPECTRE_DB", "/data/spectre.db"))
    config = Config(store)
    pipeline = Pipeline(store, config)
    app = create_app(store, config, pipeline)

    source = _env("SPECTRE_SOURCE", "serial").lower()
    ports = _env("SERIAL_PORTS", "/dev/ttyUSB0,/dev/ttyUSB1").split(",")
    baud = int(_env("SERIAL_BAUD", "115200"))

    # Attach lifecycle to the app via lifespan events.
    state: dict = {"readers": [], "source_obj": None}

    @app.on_event("startup")
    async def _startup() -> None:  # noqa: D401
        pipeline.start()
        loop = asyncio.get_running_loop()
        if source == "sim":
            from .sim.generate import SimSource
            state["source_obj"] = SimSource(pipeline)
            state["source_obj"].start()
            log.info("ingest source: SIMULATOR")
        elif source == "replay":
            from .sim.replay import ReplaySource
            path = _env("REPLAY_FILE", "/data/capture.txt")
            state["source_obj"] = ReplaySource(pipeline, path)
            state["source_obj"].start()
            log.info("ingest source: REPLAY (%s)", path)
        else:
            readers = build_readers(ports, baud, pipeline)
            for r in readers:
                try:
                    r.start(loop)
                except OSError as exc:
                    log.error("could not open %s: %s", r.path, exc)
            state["readers"] = readers
            log.info("ingest source: SERIAL %s", ports)

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        loop = asyncio.get_running_loop()
        for r in state["readers"]:
            r.stop(loop)
        if state["source_obj"]:
            await state["source_obj"].stop()
        await pipeline.stop()
        store.close()

    return app


app = build()


def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=int(_env("API_PORT", "8100")),
                log_level=os.environ.get("LOG_LEVEL", "info").lower())


if __name__ == "__main__":
    main()
