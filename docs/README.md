# SPECTRE documentation

Start with the [project README](../README.md) for what SPECTRE is and a quick start. These pages go deeper,
in the order you are likely to need them.

## Set up

| Page | Read it when |
|---|---|
| [hardware.md](hardware.md) | Choosing boards, cabling them, and getting the ports to the sensor |
| [flashing.md](flashing.md) | Putting the firmware on both boards, verifying it, updating or rolling back |
| [deployment.md](deployment.md) | Moving from a dev box to a Proxmox LXC, USB passthrough, TLS overlay |

## Operate

| Page | Read it when |
|---|---|
| [detection-rules.md](detection-rules.md) | Tuning thresholds or working out why a rule fired |
| [wazuh-integration.md](wazuh-integration.md) | Sending threats to Wazuh: decoder, rules, ATT&CK mapping |

## Understand

| Page | Read it when |
|---|---|
| [architecture.md](architecture.md) | Following a frame from the UART to the console and the SIEM |
| [data-contract.md](data-contract.md) | Reading the wire format, the database columns, or writing your own firmware |
| [firmware/README.md](../firmware/README.md) | Building the firmware, its line format, commands, counters and limits |
| [sensor/README.md](../sensor/README.md) | The Python service: modules, simulator, replay, tests |
| [web/README.md](../web/README.md) | The console: pages, design language, build and tests |

## Project

[SECURITY.md](../SECURITY.md) (reporting a vulnerability) · [CONTRIBUTING.md](../CONTRIBUTING.md)
(issues welcome, code is single-author) · [LICENSE](../LICENSE) (AGPL-3.0-or-later)

_Author: gurvinny · Project: SPECTRE_
