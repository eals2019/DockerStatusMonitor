# 🐳 Docker Status Monitor

A lightweight, always-on-top desktop GUI application for real-time monitoring of Docker containers. Built with Python and Tkinter, it provides at-a-glance visibility into container health, uptime, and available image updates — all from a compact, dark-themed window.

![Python](https://img.shields.io/badge/Python-3.8+-blue?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Linux-lightgrey?logo=linux&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Required-2496ED?logo=docker&logoColor=white)

---

## Features

### Container Monitoring
- **Real-time status** — Automatically polls Docker every 5 seconds and displays all running containers with health status indicators (Healthy ✓, Running ●, Unhealthy ⚠).
- **Docker Compose stack grouping** — Containers belonging to the same Compose project are grouped under a collapsible stack entry (📦), with an aggregate health indicator.
- **Uptime & port display** — Each container shows its uptime and mapped host ports in a clean table view.
- **Always-on-top mode** — Stays visible over other windows by default, with a toggle to disable.

### Update Detection & Notifications
- **Automatic image update checks** — On startup (and every 24 hours), queries Docker Hub, GitHub Container Registry (GHCR), and LinuxServer.io (LSCR) to determine if newer image versions are available.
- **Semantic version comparison** — Matches your local image digest against registry tags to resolve actual version numbers (e.g., `2.10.3` → `2.11.0`), rather than relying solely on digest comparison.
- **Notification bell with badge** — A bell icon in the header shows a count badge when updates are available. Click it to open the notification sidebar.
- **Collapsible notification sidebar** — Expand the sidebar to see a consolidated list of available updates with version comparisons, how far behind you are (days/months), and per-container details.
- **Pinned version detection** — Containers using a specific version tag in their `docker-compose.yml` (e.g., `image: nginx:1.25.3`) are flagged with a 📌 icon and a lock button, indicating the update requires a manual compose file change.

### One-Click Container Updates
- **Update button per container** — For non-pinned containers, click the ⬆ Update button in the sidebar to pull the latest image and recreate the container in a visible terminal window.
- **Data-safe updates** — Uses `docker compose pull` followed by `docker compose up -d --force-recreate`, deliberately avoiding `down -v` to preserve volumes and data.

### Desktop Integration (Linux)
- **Install script** — Sets up a `.desktop` entry, autostart on login, and pins the app to the GNOME/Ubuntu taskbar.
- **Uninstall script** — Cleanly removes the desktop entry, autostart configuration, taskbar pin, and application icon.
- **Single-instance enforcement** — Uses a PID lock file to ensure only one instance runs at a time. Launching a new instance automatically kills any existing one.

---

## Requirements

- **Python 3.8+** with `tkinter` (usually included with Python on Linux)
- **Docker** installed and running
- **Docker Compose** (v2 plugin recommended)
- **Linux desktop environment** (GNOME, KDE, XFCE, etc.) for the install/uninstall scripts

No additional Python packages are required — the application uses only the standard library.

---

## Getting Started

### Run Directly

```bash
python3 docker-status-monitor.py
```

### Install as Desktop Application

```bash
chmod +x install.sh
./install.sh
```

This will:
1. Create a Docker whale SVG icon
2. Add a `Docker Monitor` entry to your applications menu
3. Enable autostart on login
4. Pin the app to your GNOME/Ubuntu taskbar

After installation, you can launch it from your applications menu or taskbar.

### Uninstall

```bash
chmod +x uninstall.sh
./uninstall.sh
```

This removes the desktop entry, autostart, taskbar pin, and icon. The source files are **not** deleted.

---

## How It Works

### Architecture

The application consists of two main modules:

| File | Purpose |
|------|---------|
| `docker-status-monitor.py` | Main GUI application — container list, sidebar, update buttons, and event loop |
| `version_checker.py` | Backend module — parses compose files, queries registries, compares versions |

### Container Discovery

1. Runs `docker ps` with a custom format string to retrieve container names, statuses, ports, uptime, and Compose project labels.
2. Groups containers by their `com.docker.compose.project` label into stacks.
3. Determines aggregate stack health (unhealthy if any child is unhealthy, healthy if any child has passing health checks, otherwise running).

### Update Checking Flow

1. Scans the parent workspace for `docker-compose.yml` files in non-numbered, non-hidden project folders.
2. Parses each compose file to extract `image:` declarations per service (handles variable substitution like `${VAR:-default}`).
3. Matches compose services to running containers by image name and project/container name correlation.
4. For each matched container:
   - Retrieves the local image digest via `docker inspect`.
   - Queries the appropriate registry API:
     - **Docker Hub** — Paginates through tag listings (up to 500 tags), matches the local digest to find the current version, then compares against the latest semantic version tag.
     - **GHCR** — Compares `Docker-Content-Digest` headers.
     - **LSCR** — Redirects to GHCR under the `linuxserver/` organization.
5. Results are cached for 24 hours to avoid excessive API calls.

### UI Theme

Uses a [Catppuccin Mocha](https://github.com/catppuccin/catppuccin)-inspired dark color scheme with color-coded status indicators:

| Color | Meaning |
|-------|---------|
| 🟢 Green | Healthy / Up to date |
| 🟡 Yellow | Unhealthy / Pinned version with update |
| 🟠 Orange | Update available |
| 🔵 Blue | Accent / Headings |
| 🔵 Cyan | Stack headers |

---

## Project Structure

```
DockerStatusMonitor/
├── docker-status-monitor.py       # Main application
├── docker-status-monitor-test.py  # Test/development version
├── version_checker.py             # Registry update checking module
├── install.sh                     # Desktop integration setup
├── uninstall.sh                   # Desktop integration removal
└── README.md                      # This file
```

---

## License

This project is provided as-is for personal use.
