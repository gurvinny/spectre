# Deployment (dev → prod)

The same `docker-compose.yml` runs on the dev box and the production Proxmox LXC — **only `.env`
changes** (host IP, serial ports, Wazuh target). Develop and fully test here with the boards
attached, then move the repo and bring it up on the LXC.

## Dev server (this box · `spectre-dev`, 10.0.0.10)

```bash
bash init.sh
docker compose up -d --build
# 2.4GHz board = /dev/ttyUSB0, 5GHz = /dev/ttyUSB1
# open http://10.0.0.10:4100
```

Verified working: the containerized reader opens the tty with DTR/RTS low and ingests real frames;
band is auto-detected from each board's boot event.

## Production LXC (Proxmox)

1. `git clone` the repo onto the LXC, `bash init.sh`, edit `.env` for the prod host/Wazuh.
2. Plug the two boards into the Proxmox host and pass them into the LXC.
3. `docker compose up -d --build`.

### USB passthrough into an **unprivileged** LXC

Unprivileged LXCs can't see host USB serial devices by default. On the **Proxmox host**, find the
adapters and add to the container config (`/etc/pve/lxc/<vmid>.conf`):

```
# major:minor of /dev/ttyUSB* — check with: ls -l /dev/ttyUSB*
lxc.cgroup2.devices.allow: c 188:* rwm
lxc.mount.entry: /dev/ttyUSB0 dev/ttyUSB0 none bind,optional,create=file
lxc.mount.entry: /dev/ttyUSB1 dev/ttyUSB1 none bind,optional,create=file
```

Restart the container. Inside it, `/dev/ttyUSB0` and `ttyUSB1` should now exist and Docker's
`devices:` mapping in `docker-compose.yml` will pass them to the `sensor` container.

> USB re-enumeration can swap `ttyUSB0`/`ttyUSB1` across reboots — that's fine, SPECTRE identifies
> each board's band from its boot event. For stable device *names* you can instead bind
> `/dev/serial/by-id/*` symlinks and set `SERIAL_PORTS` accordingly.

### Fallback: reader on the host

If device-cgroup passthrough is blocked in your environment, run the reader on the LXC host and
point it at the containerized API — the reader is modular (`SerialReader` + `Parser` feed
`Pipeline.ingest`), so a thin host script can POST/stream frames in. Containerized passthrough is
the supported default.

## Resource notes

`docker-compose.yml` caps the `sensor` at 512M / 1 CPU and `web` at 384M / 0.75 CPU to respect the
host RAM guard. Adjust `deploy.resources` if you raise the LXC's limits.

## NPM / TLS (optional)

Front the console with Nginx Proxy Manager for TLS + access control:

```bash
docker compose -f docker-compose.yml -f docker-compose.npm.yml up -d
```

_Author: gurvinny · Project: SPECTRE_
