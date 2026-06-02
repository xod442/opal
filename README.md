# Opal

**Operational Priority and At-Risk Likelihood**

A customer escalation risk tracking dashboard for HPE Networking. Account managers and sales engineers submit weekly status via Microsoft Forms; a CSV export is ingested into Opal to keep the team aligned on which customers need attention.

---

## Features

- **Heat-coded dashboard** — Critical, Hot, Concerned, Stable with sortable, filterable table
- **Metric cards** — clickable counts for Total, Critical, Hot, Concerned, Stable, and At Risk
- **Detail & edit pages** — full customer record with editable fields and notes
- **Executive overview** — at-a-glance summary for leadership and QBRs
- **Stale records** — top 20 customers longest without an update
- **Weekly CSV ingest** — upload Microsoft Forms exports; duplicates and Mist rows filtered automatically
- **Secure login** — bcrypt passwords, signed session cookies, forced password change on first login
- **User management** — create users, enable/disable accounts, reset passwords (admin only)
- **Audit trail** — every database change logged with the user who made it
- **Auto-backup** — database backed up at 6 AM and 6 PM daily, last 20 backups retained
- **Admin tools** — manual backup, CSV upload, export, restore, delete database

---

## Requirements

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (includes Docker Compose v2)
- Available port 9090

No Python or other dependencies needed on the host.

---

## Quick Start

```bash
git clone https://github.com/xod442/opal.git
cd opal
docker compose up -d --build
```

Open **http://localhost:9090** in your browser.

**Default credentials:** `admin` / `admin`
You will be required to change the password on first login.

---

## Ingesting CSV Data

### Via the Admin UI (recommended)
1. Log in as an admin and click **Admin** in the header
2. Under **Upload CSV**, select the Microsoft Forms export file
3. Click **Upload & ingest**

### Via command line
```bash
mkdir -p csv
cp ~/Downloads/engagement.csv csv/
docker compose run --rm ingest
```

**Ingest rules:**
- Rows are deduplicated on the Microsoft Forms `ID` column — re-ingesting the same file is safe
- Rows where the *Current deployed Architecture* field starts with `Mist` are skipped
- Microsoft Forms BOM encoding (`utf-8-sig`) is handled automatically

---

## Docker Commands

| Command | Description |
|---|---|
| `docker compose up -d` | Start the application |
| `docker compose down` | Stop the application |
| `docker compose up -d --build` | Rebuild and start after code changes |
| `docker compose logs -f` | View live logs |
| `docker compose restart` | Restart the container |

---

## Configuration

Set these in the `environment:` section of `docker-compose.yaml`:

| Variable | Default | Description |
|---|---|---|
| `DB_PATH` | `/data/opal.db` | Path to the SQLite database inside the container |
| `BACKUP_DIR` | `/data/backups` | Directory for backup files |
| `SECRET_KEY` | `opal-change-me-in-production` | HMAC key for session cookies — **change this in production** |

Data is persisted in `./data/` on the host filesystem and is unaffected by container restarts.

---

## Project Structure

```
opal/
├── app.py                  # FastAPI application
├── ingest.py               # Standalone CSV ingester
├── requirements.txt        # Python dependencies
├── Dockerfile
├── docker-compose.yaml
├── admin-guide.html        # Full administrator guide (open in browser)
├── voiceover-script.md     # Voiceover script for intro video
└── templates/
    ├── dashboard.html
    ├── detail.html
    ├── edit.html
    ├── executive.html
    ├── stale.html
    ├── admin.html
    ├── audit.html
    ├── login.html
    └── change_password.html
```

---

## Administrator Guide

A full administrator guide covering installation, user management, backup/restore, data model, environment variables, and troubleshooting is included as a self-contained HTML file:

```
open admin-guide.html
```

---

## Roadmap

- [x] Heat-coded dashboard with metric cards
- [x] Weekly CSV ingest (dedup + Mist filter)
- [x] Detail and edit pages
- [x] Executive overview
- [x] Stale records page
- [x] Additional notes field
- [x] Secure login and user management
- [x] Audit trail
- [ ] Email alerts for new Critical customers
- [ ] Week-over-week trend tracking

---

## License

Internal use only — HPE Networking.
