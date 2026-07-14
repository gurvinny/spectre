"""Hardware-free data sources for SPECTRE.

* :mod:`spectre.sim.generate` — synthesizes realistic background WiFi traffic
  and injectable attack scenarios, in the exact firmware wire format, so the
  full ingest → detect → store → forward pipeline can be exercised without the
  ESP32-C5 boards attached.
* :mod:`spectre.sim.replay` — plays back a captured UART text file at
  wall-clock speed.

Author: gurvinny
Project: SPECTRE
"""
