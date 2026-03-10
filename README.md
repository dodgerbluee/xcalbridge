# xCalBridge

[![CI](https://github.com/dodgerbluee/xcalbridge/actions/workflows/ci.yml/badge.svg)](https://github.com/dodgerbluee/xcalbridge/actions/workflows/ci.yml)

A lightweight, self-hosted application that converts sports schedules (Excel/CSV) into ICS calendar feeds. Designed for homelab deployment.

## What It Does

xCalBridge acts as a universal bridge between sports schedule sources and ICS calendar feeds. Upload or link to spreadsheets from platforms like GotSport, TeamSideline, RankOne, or Mojo, and the app generates subscribable ICS feeds that work with:

- Apple Calendar
- Google Calendar
- Nextcloud Calendar
- Radicale
- vdirsyncer
- Any CalDAV client

## Quick Start

### Option 1: Pull from GHCR (recommended)

```bash
docker pull ghcr.io/dodgerbluee/xcalbridge:latest
docker run -d -p 8080:8080 -v ./data:/data ghcr.io/dodgerbluee/xcalbridge:latest
```

### Option 2: Build locally

```bash
docker compose up -d
```

- **Web UI:** http://localhost:8080
- **ICS Feeds:** http://localhost:8080/feeds/{calendar_name}.ics

## Features

- **Multiple source types:** Excel upload, CSV upload, Excel URL, CSV URL
- **Auto-detect columns:** Automatically maps common column names (Date, Time, Location, etc.)
- **Preview before saving:** Parse and preview events before creating a source
- **Background sync:** Automatically refreshes URL-based sources every 3 hours
- **Manual sync:** Force-refresh any source from the dashboard
- **RFC 5545 compliant:** Generated ICS files include UID, DTSTART, DTEND, SUMMARY, LOCATION, DESCRIPTION
- **Clean feed URLs:** `/feeds/natalie_softball.ics`, `/feeds/gregory_soccer.ics`

## Supported Source Formats

| Source Type    | Input                          | Example                                    |
|---------------|-------------------------------|--------------------------------------------|
| Excel Upload  | `.xlsx` file upload           | Schedule downloaded from GotSport          |
| CSV Upload    | `.csv` file upload            | Exported schedule from TeamSideline        |
| Excel URL     | Direct link to `.xlsx` file   | `https://example.com/schedule.xlsx`        |
| CSV URL       | Direct link to `.csv` file    | `https://example.com/schedule.csv`         |

## Column Mapping

The app auto-detects common column names. You can also manually map columns:

| Calendar Field | Common Column Names Detected              |
|---------------|-------------------------------------------|
| Event Name    | Title, Event, Game, Match, Opponent       |
| Date          | Date, Game Date, Event Date               |
| Start Time    | Start Time, Time, Game Time, Kickoff      |
| End Time      | End Time, Finish                          |
| Location      | Location, Venue, Field, Stadium, Facility |
| Description   | Description, Notes, Details, Comments     |

## API Endpoints

| Method   | Endpoint                      | Description              |
|----------|-------------------------------|--------------------------|
| `GET`    | `/feeds/{name}.ics`           | ICS calendar feed        |
| `GET`    | `/api/sources`                | List all sources         |
| `POST`   | `/api/sources`                | Create a new source      |
| `PUT`    | `/api/sources/{id}`           | Update a source          |
| `DELETE` | `/api/sources/{id}`           | Delete a source          |
| `POST`   | `/api/sources/{id}/sync`      | Force immediate sync     |

## Configuration

Environment variables:

| Variable             | Default | Description                        |
|---------------------|---------|------------------------------------|
| `DATA_DIR`          | `data`  | Base directory for all data        |
| `SYNC_INTERVAL_HOURS` | `3`   | Hours between automatic syncs      |
| `HOST`              | `0.0.0.0` | Server bind address             |
| `PORT`              | `8080`  | Server port                        |

## Data Persistence

All data is stored under the `DATA_DIR`:

```
data/
  db.sqlite          # Source configuration database
  feeds/             # Generated ICS calendar files
  uploads/           # Uploaded spreadsheet files
```

Mount `./data:/data` in Docker to persist across container restarts.

## Development

Run locally without Docker:

```bash
pip install -r requirements.txt
python -m xcalbridge.main
```

The app will be available at http://localhost:8080 with auto-reload enabled.

## Architecture

```
xcalbridge/
  main.py              # FastAPI app, lifespan, router mounts
  config.py            # Settings and path constants
  database.py          # SQLite CRUD operations
  models.py            # Pydantic models
  routes/
    api.py             # REST API endpoints
    feeds.py           # ICS feed serving
    ui.py              # HTMX-powered web UI
  services/
    parser.py          # Excel/CSV parsing + column detection
    ics_generator.py   # ICS file generation (ics.py)
    sync.py            # Sync pipeline orchestration
    scheduler.py       # APScheduler background worker
  templates/           # Jinja2 + HTMX templates
  static/              # CSS
```

## CI/CD

The project uses GitHub Actions to automatically:

- **Build** the Docker image on every push and pull request to `main`
- **Push** the image to GitHub Container Registry (`ghcr.io`) on pushes to `main`
- Images are tagged with `latest` and the git commit SHA

## Tech Stack

- **Backend:** Python, FastAPI, SQLite
- **Frontend:** HTMX, Jinja2, Pico CSS
- **Libraries:** pandas, openpyxl, ics.py, APScheduler, httpx
- **Container:** Docker, single container
- **CI/CD:** GitHub Actions, GHCR
