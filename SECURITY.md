# Security Policy

SPECTRE is a WiFi intrusion-detection sensor. It runs a radio in promiscuous mode, parses
untrusted 802.11 frame metadata, and exposes a web console, so it has real attack surface. This
policy overrides the [default policy](https://github.com/gurvinny/.github/blob/main/SECURITY.md)
for this repository.

## Reporting a vulnerability

Report privately via **Security → Report a vulnerability** on this repository. Do not open a
public issue or pull request for a security concern.

Expect an initial response within seven days. Triage is best-effort; this is a personal project.

## Supported versions

Only `main` receives security fixes. Tagged releases are not backported.

## Scope

In scope:

- Remote code execution, injection, or memory-safety issues in the ingest and parsing path
  (`sensor/spectre/parser.py`, `reader.py`, the detection rules)
- Authentication bypass on the console or API, including the WebSocket upgrade path
- Cross-site scripting or request forgery in the Next.js console
- Unauthenticated access to captured data, or leakage of observed SSIDs, BSSIDs or MAC
  addresses to an unintended destination
- Container escape or privilege issues arising from the documented USB device passthrough
- Credentials or keys committed to this repository

Out of scope:

- Anything requiring physical access to the ESP32-C5 boards or the host
- Denial of service achieved by flooding the radio environment; the sensor is designed to
  observe floods and a sufficiently hostile RF environment will degrade any receiver
- Vulnerabilities in dependencies that are not reachable in the shipped configuration
- The security of a deployment that exposes the console to an untrusted network, which the
  documentation advises against

## Design constraints relevant to reports

- The sensor forwards **threat summaries only, never raw frames**, to the configured SIEM
- The ingest and detection core is standard-library only, limiting the dependency attack surface
- Console authentication is a single shared password by design; it is not a multi-user system,
  and reports that it lacks per-user accounts are not vulnerabilities

## Authorized use

Running this software against networks you do not own or have permission to test may be
unlawful. See **Authorized Use** in the README.
