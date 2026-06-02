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
- **Trend tracking** — week-over-week heat movement with dashboard indicators and a dedicated trends page
- **Email alerts** — automatic email notification when a new Critical customer is ingested
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

## Clean Install

These steps walk through a fresh deployment from scratch.

### 1. Prerequisites
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- Port **9090** available on the host

### 2. Clone and start

```bash
git clone https://github.com/xod442/opal.git
cd opal
docker compose up -d --build
```

The container will:
- Pull the Python 3.12 base image and install dependencies
- Create `./data/opal.db` with all tables on first startup
- Start the web server on port 9090

### 3. First login

1. Open **http://localhost:9090**
2. Log in with `admin` / `admin`
3. You will be redirected to a forced password change — set a strong password and continue
4. The dashboard will load (empty until a CSV is ingested)

### 4. Ingest your first CSV

Upload a Microsoft Forms export via **Admin → Upload CSV**, or use the command line:

```bash
mkdir -p csv
cp ~/Downloads/engagement.csv csv/
docker compose run --rm ingest
```

### 5. Verify everything is working

| Check | Expected |
|---|---|
| `docker compose ps` | `opal` container status **Up** |
| `docker compose logs` | No errors, `Application startup complete` |
| http://localhost:9090/login | Login page loads |
| Login with new password | Redirects to dashboard |
| Admin page | CSV upload, user management, email settings visible |

### Resetting to factory defaults

To wipe all data and start over:

```bash
docker compose down
rm -rf data/
docker compose up -d
```

This deletes the database (all customers, users, and audit logs) and recreates it with the default `admin` account.

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
- [x] Email alerts for new Critical customers
- [x] Week-over-week trend tracking

---

## License

Internal use only — HPE Networking.
