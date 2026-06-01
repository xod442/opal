"""
Opal — Operational Priority and At-Risk Likelihood
"""

import csv
import io
import os
import secrets
import shutil
import sqlite3
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Form, Query, Request, UploadFile, File, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from passlib.context import CryptContext

# ── Config ────────────────────────────────────────────────────────────────────

DB_PATH    = os.getenv("DB_PATH",    os.path.join(os.path.dirname(__file__), "opal.db"))
BACKUP_DIR = os.getenv("BACKUP_DIR", os.path.join(os.path.dirname(__file__), "data", "backups"))
SECRET_KEY = os.getenv("SECRET_KEY", "opal-change-me-in-production")
SESSION_MAX_AGE = 8 * 3600  # 8 hours

os.makedirs(BACKUP_DIR, exist_ok=True)

app = FastAPI(title="Opal")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

pwd_ctx    = CryptContext(schemes=["bcrypt"], deprecated="auto")
serializer = URLSafeTimedSerializer(SECRET_KEY)

TEMP_ORDER = {
    "Critical - We are at risk of loosing them as a customer": 1,
    "Hot - they are escalating": 2,
    "Concerned - they are complaining": 3,
    "Stable - but needs attention": 4,
}
TEMP_LABEL = {
    "Critical - We are at risk of loosing them as a customer": "Critical",
    "Hot - they are escalating": "Hot",
    "Concerned - they are complaining": "Concerned",
    "Stable - but needs attention": "Stable",
}
ARCH_COL = "Current deployed Architecture - Not what they want to get to, but what are they running now"


# ── Auth helpers ──────────────────────────────────────────────────────────────

def get_session(request: Request):
    token = request.cookies.get("session")
    if not token:
        return None
    try:
        return serializer.loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


def require_user(request: Request):
    session = get_session(request)
    if not session:
        return None
    return session


def require_admin(request: Request):
    session = get_session(request)
    if not session or session.get("role") != "admin":
        return None
    return session


def set_session_cookie(response, user_id, username, role):
    token = serializer.dumps({"user_id": user_id, "username": username, "role": role})
    response.set_cookie("session", token, httponly=True, samesite="lax", max_age=SESSION_MAX_AGE)


# ── DB helpers ────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def migrate_db():
    if not os.path.exists(DB_PATH):
        return
    conn = sqlite3.connect(DB_PATH)

    # customers table migrations
    cols = [r[1] for r in conn.execute("PRAGMA table_info(customers)").fetchall()]
    if "last_modified" not in cols:
        conn.execute("ALTER TABLE customers ADD COLUMN last_modified TEXT")
        conn.execute("UPDATE customers SET last_modified = submission_time WHERE last_modified IS NULL")
    if "notes" not in cols:
        conn.execute("ALTER TABLE customers ADD COLUMN notes TEXT")

    # users table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            username     TEXT UNIQUE NOT NULL,
            email        TEXT,
            password_hash TEXT NOT NULL,
            role         TEXT NOT NULL DEFAULT 'user',
            is_active    INTEGER NOT NULL DEFAULT 1,
            must_change_password INTEGER NOT NULL DEFAULT 0,
            created_at   TEXT,
            last_login   TEXT
        )
    """)

    # Default admin if no users exist
    count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if count == 0:
        conn.execute("""
            INSERT INTO users (username, email, password_hash, role, is_active, must_change_password, created_at)
            VALUES (?, ?, ?, ?, 1, 1, ?)
        """, ("admin", "", pwd_ctx.hash("admin"), "admin", datetime.now().isoformat()))

    # audit_log table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            ts       TEXT NOT NULL,
            username TEXT NOT NULL,
            action   TEXT NOT NULL,
            target   TEXT,
            detail   TEXT
        )
    """)

    conn.commit()
    conn.close()


# ── Audit log ─────────────────────────────────────────────────────────────────

def log_action(username: str, action: str, target: str = "", detail: str = ""):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT INTO audit_log (ts, username, action, target, detail) VALUES (?,?,?,?,?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), username, action, target, detail),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass  # never let logging crash the app


# ── Backup helpers ────────────────────────────────────────────────────────────

def do_backup():
    if not os.path.exists(DB_PATH):
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(BACKUP_DIR, f"opal_backup_{ts}.db")
    shutil.copy2(DB_PATH, dest)
    backups = sorted([f for f in os.listdir(BACKUP_DIR) if f.endswith(".db")], reverse=True)
    for old in backups[20:]:
        os.remove(os.path.join(BACKUP_DIR, old))
    return dest


def list_backups():
    if not os.path.exists(BACKUP_DIR):
        return []
    files = sorted([f for f in os.listdir(BACKUP_DIR) if f.endswith(".db")], reverse=True)
    result = []
    for f in files:
        path = os.path.join(BACKUP_DIR, f)
        size = os.path.getsize(path)
        mtime = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M:%S")
        result.append({"name": f, "size": f"{size // 1024} KB", "modified": mtime})
    return result


def ingest_fileobj(fileobj):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY,
            submission_time TEXT, email TEXT, submitter_name TEXT,
            customer_name TEXT, location TEXT, account_manager TEXT,
            sales_engineer TEXT, temperature TEXT, temperature_label TEXT,
            temperature_order INTEGER, at_risk TEXT, risk_reasons TEXT,
            architecture TEXT, near_term_goals TEXT, bu_contact TEXT,
            ask_from_bu TEXT, background TEXT, last_modified TEXT, notes TEXT
        )
    """)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(customers)").fetchall()]
    for col in ("last_modified", "notes"):
        if col not in cols:
            conn.execute(f"ALTER TABLE customers ADD COLUMN {col} TEXT")

    inserted = skipped_mist = skipped_dup = 0
    reader = csv.DictReader(fileobj)
    for row in reader:
        arch = row.get(ARCH_COL, "").strip()
        if arch.lower().startswith("mist"):
            skipped_mist += 1
            continue
        temp = row.get("Customer Temperature", "").strip()
        submission_time = row.get("Start time", "").strip()
        try:
            conn.execute("""
                INSERT OR IGNORE INTO customers (
                    id, submission_time, email, submitter_name,
                    customer_name, location, account_manager, sales_engineer,
                    temperature, temperature_label, temperature_order,
                    at_risk, risk_reasons, architecture,
                    near_term_goals, bu_contact, ask_from_bu, background, last_modified
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                int(row.get("ID", 0)), submission_time,
                row.get("Email", "").strip(), row.get("Name", "").strip(),
                row.get("Customer Name", "").strip(), row.get("Location", "").strip(),
                row.get("Account Manager", "").strip(), row.get("Sales Engineer", "").strip(),
                temp, TEMP_LABEL.get(temp, temp), TEMP_ORDER.get(temp, 99),
                row.get("Is the customer actively at risk?", "").strip(),
                row.get("Primarily reason for risk", "").strip(), arch,
                row.get("What are the customers near term goals", "").strip(),
                row.get("Are you currently working with anyone in the business unit?", "").strip(),
                row.get("Your specific ask of what you would want from the business unit to make this customer happy? ", "").strip(),
                row.get("Any other background you want us to know", "").strip(),
                submission_time,
            ))
            if conn.execute("SELECT changes()").fetchone()[0]:
                inserted += 1
            else:
                skipped_dup += 1
        except Exception:
            skipped_dup += 1
    conn.commit()
    conn.close()
    return inserted, skipped_dup, skipped_mist


# ── Startup ───────────────────────────────────────────────────────────────────

migrate_db()
scheduler = BackgroundScheduler()
scheduler.add_job(do_backup, "cron", hour="6,18", minute=0)
scheduler.start()


# ── Login / Logout ────────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str = ""):
    if get_session(request):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request=request, name="login.html", context={"error": error})


@app.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE username = ? AND is_active = 1", (username,)).fetchone()
    if not user or not pwd_ctx.verify(password, user["password_hash"]):
        conn.close()
        return templates.TemplateResponse(
            request=request, name="login.html",
            context={"error": "Invalid username or password."},
            status_code=401,
        )
    conn.execute("UPDATE users SET last_login = ? WHERE id = ?",
                 (datetime.now().isoformat(), user["id"]))
    conn.commit()
    conn.close()

    redirect_to = "/change-password" if user["must_change_password"] else "/"
    response = RedirectResponse(url=redirect_to, status_code=303)
    set_session_cookie(response, user["id"], user["username"], user["role"])
    return response


@app.get("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("session")
    return response


# ── Change password ───────────────────────────────────────────────────────────

@app.get("/change-password", response_class=HTMLResponse)
def change_password_page(request: Request):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login", status_code=303)
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    conn.close()
    forced = bool(user and user["must_change_password"])
    return templates.TemplateResponse(
        request=request, name="change_password.html",
        context={"session": session, "forced": forced, "username": session["username"], "error": ""},
    )


@app.post("/change-password")
def change_password_submit(
    request: Request,
    current_password: str = Form(""),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login", status_code=303)

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    forced = bool(user and user["must_change_password"])

    def render(error=""):
        return templates.TemplateResponse(
            request=request, name="change_password.html",
            context={"session": session, "forced": forced, "username": session["username"], "error": error},
        )

    if new_password != confirm_password:
        conn.close()
        return render(error="New passwords do not match.")
    if len(new_password) < 8:
        conn.close()
        return render(error="Password must be at least 8 characters.")

    if not forced:
        if not current_password or not pwd_ctx.verify(current_password, user["password_hash"]):
            conn.close()
            return render(error="Current password is incorrect.")

    conn.execute("UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?",
                 (pwd_ctx.hash(new_password), session["user_id"]))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/?msg=Password+changed+successfully", status_code=303)


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    search: str = Query(""),
    filter_temp: str = Query(""),
    filter_risk: str = Query(""),
    filter_am: str = Query(""),
    msg: str = Query(""),
):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login", status_code=303)

    conn = get_db()
    metrics = {}
    for label in ("Critical", "Hot", "Concerned", "Stable"):
        metrics[label] = conn.execute(
            "SELECT COUNT(*) FROM customers WHERE temperature_label = ?", (label,)
        ).fetchone()[0]
    metrics["Total"] = sum(metrics.values())
    metrics["At Risk"] = conn.execute(
        "SELECT COUNT(*) FROM customers WHERE at_risk = 'Yes – actively evaluating other vendors'"
    ).fetchone()[0]

    ams = [r[0] for r in conn.execute(
        "SELECT DISTINCT account_manager FROM customers WHERE account_manager != '' ORDER BY account_manager"
    ).fetchall()]

    where, params = [], []
    if search:
        where.append("(customer_name LIKE ? OR sales_engineer LIKE ? OR account_manager LIKE ? OR location LIKE ?)")
        params += [f"%{search}%"] * 4
    if filter_temp:
        where.append("temperature_label = ?")
        params.append(filter_temp)
    if filter_risk:
        where.append("at_risk = ?")
        params.append(filter_risk)
    if filter_am:
        where.append("account_manager = ?")
        params.append(filter_am)

    sql = "SELECT * FROM customers"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY temperature_order ASC, customer_name ASC"

    customers = conn.execute(sql, params).fetchall()
    conn.close()

    return templates.TemplateResponse(
        request=request, name="dashboard.html",
        context={
            "customers": customers, "metrics": metrics, "ams": ams,
            "search": search, "filter_temp": filter_temp,
            "filter_risk": filter_risk, "filter_am": filter_am,
            "session": session, "msg": msg,
        },
    )


# ── Detail ────────────────────────────────────────────────────────────────────

@app.get("/customer/{customer_id}", response_class=HTMLResponse)
def detail(request: Request, customer_id: int):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login", status_code=303)
    conn = get_db()
    customer = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    conn.close()
    if not customer:
        return HTMLResponse("Not found", status_code=404)
    return templates.TemplateResponse(request=request, name="detail.html",
                                      context={"c": customer, "session": session})


# ── Edit ──────────────────────────────────────────────────────────────────────

@app.get("/customer/{customer_id}/edit", response_class=HTMLResponse)
def edit_form(request: Request, customer_id: int):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login", status_code=303)
    conn = get_db()
    customer = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    conn.close()
    if not customer:
        return HTMLResponse("Not found", status_code=404)
    return templates.TemplateResponse(
        request=request, name="edit.html",
        context={"c": customer, "temp_options": list(TEMP_ORDER.keys()), "session": session},
    )


@app.post("/customer/{customer_id}/edit")
def edit_save(
    request: Request,
    customer_id: int,
    customer_name: str = Form(...),
    temperature: str = Form(...),
    at_risk: str = Form(...),
    risk_reasons: str = Form(""),
    architecture: str = Form(""),
    near_term_goals: str = Form(""),
    bu_contact: str = Form(""),
    ask_from_bu: str = Form(""),
    background: str = Form(""),
    notes: str = Form(""),
):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login", status_code=303)
    conn = get_db()
    conn.execute("""
        UPDATE customers SET
            customer_name=?, temperature=?, temperature_label=?, temperature_order=?,
            at_risk=?, risk_reasons=?, architecture=?, near_term_goals=?,
            bu_contact=?, ask_from_bu=?, background=?, notes=?, last_modified=?
        WHERE id=?
    """, (
        customer_name, temperature,
        TEMP_LABEL.get(temperature, temperature),
        TEMP_ORDER.get(temperature, 99),
        at_risk, risk_reasons, architecture, near_term_goals,
        bu_contact, ask_from_bu, background, notes,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        customer_id,
    ))
    conn.commit()
    conn.close()
    log_action(session["username"], "edit_customer", customer_name,
               f"heat={TEMP_LABEL.get(temperature, temperature)}, at_risk={at_risk}")
    return RedirectResponse(url="/", status_code=303)


# ── Stale Records ─────────────────────────────────────────────────────────────

@app.get("/stale", response_class=HTMLResponse)
def stale(request: Request):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login", status_code=303)
    conn = get_db()
    customers = conn.execute("""
        SELECT *,
            COALESCE(last_modified, submission_time) AS last_touched,
            CAST(julianday('now') - julianday(COALESCE(last_modified, submission_time)) AS INTEGER) AS days_since
        FROM customers
        WHERE last_touched != '' AND last_touched IS NOT NULL
        ORDER BY julianday(last_touched) ASC
        LIMIT 20
    """).fetchall()
    conn.close()
    return templates.TemplateResponse(request=request, name="stale.html",
                                      context={"customers": customers, "session": session})


# ── Executive Overview ────────────────────────────────────────────────────────

@app.get("/executive", response_class=HTMLResponse)
def executive(request: Request):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login", status_code=303)
    conn = get_db()
    metrics = {}
    for label in ("Critical", "Hot", "Concerned", "Stable"):
        metrics[label] = conn.execute(
            "SELECT COUNT(*) FROM customers WHERE temperature_label = ?", (label,)
        ).fetchone()[0]
    metrics["Total"] = sum(metrics.values())
    metrics["At Risk"] = conn.execute(
        "SELECT COUNT(*) FROM customers WHERE at_risk = 'Yes – actively evaluating other vendors'"
    ).fetchone()[0]

    top_customers = conn.execute("""
        SELECT *,
            CASE WHEN at_risk = 'Yes – actively evaluating other vendors' THEN 0
                 WHEN at_risk = 'Not sure' THEN 1
                 ELSE 2 END AS risk_sort
        FROM customers
        WHERE temperature_label IN ('Critical', 'Hot')
        ORDER BY temperature_order ASC, risk_sort ASC, customer_name ASC
        LIMIT 20
    """).fetchall()

    risk_reasons = conn.execute("""
        SELECT risk_reasons, COUNT(*) as cnt
        FROM customers
        WHERE at_risk = 'Yes – actively evaluating other vendors' AND risk_reasons != ''
        ORDER BY cnt DESC
    """).fetchall()

    hot_locations = conn.execute("""
        SELECT location, COUNT(*) as cnt
        FROM customers
        WHERE temperature_label IN ('Critical', 'Hot') AND location != ''
        GROUP BY location ORDER BY cnt DESC LIMIT 8
    """).fetchall()

    conn.close()
    return templates.TemplateResponse(
        request=request, name="executive.html",
        context={
            "metrics": metrics, "top_customers": top_customers,
            "risk_reasons": risk_reasons, "hot_locations": hot_locations,
            "generated": datetime.now().strftime("%B %d, %Y at %I:%M %p"),
            "session": session,
        },
    )


# ── Admin ─────────────────────────────────────────────────────────────────────

@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request, msg: str = Query("")):
    session = get_session(request)
    if not session:
        return RedirectResponse(url="/login", status_code=303)
    if session.get("role") != "admin":
        return RedirectResponse(url="/", status_code=303)

    db_exists = os.path.exists(DB_PATH)
    db_size = f"{os.path.getsize(DB_PATH) // 1024} KB" if db_exists else "—"
    record_count = 0
    if db_exists:
        try:
            conn = get_db()
            record_count = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
            conn.close()
        except Exception:
            pass

    conn = get_db()
    users = conn.execute("SELECT * FROM users ORDER BY username").fetchall()
    conn.close()

    return templates.TemplateResponse(
        request=request, name="admin.html",
        context={
            "backups": list_backups(), "db_size": db_size,
            "record_count": record_count, "db_exists": db_exists,
            "msg": msg, "session": session, "users": users,
        },
    )


@app.post("/admin/backup")
def admin_backup(request: Request):
    session = get_session(request)
    if not session or session.get("role") != "admin":
        return RedirectResponse(url="/login", status_code=303)
    dest = do_backup()
    name = os.path.basename(dest) if dest else "nothing to backup"
    log_action(session["username"], "backup", name)
    return RedirectResponse(url=f"/admin?msg=Backup+created%3A+{name}", status_code=303)


@app.post("/admin/upload")
async def admin_upload(request: Request, file: UploadFile = File(...)):
    session = get_session(request)
    if not session or session.get("role") != "admin":
        return RedirectResponse(url="/login", status_code=303)
    content = await file.read()
    text = content.decode("utf-8-sig")
    inserted, skipped_dup, skipped_mist = ingest_fileobj(io.StringIO(text))
    log_action(session["username"], "upload_csv", file.filename,
               f"{inserted} inserted, {skipped_dup} duplicates, {skipped_mist} Mist skipped")
    msg = f"{inserted}+inserted%2C+{skipped_dup}+duplicates+ignored%2C+{skipped_mist}+Mist+rows+skipped"
    return RedirectResponse(url=f"/admin?msg={msg}", status_code=303)


@app.get("/admin/export")
def admin_export(request: Request):
    session = get_session(request)
    if not session or session.get("role") != "admin":
        return RedirectResponse(url="/login", status_code=303)
    conn = get_db()
    rows = conn.execute("SELECT * FROM customers ORDER BY temperature_order, customer_name").fetchall()
    conn.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Submission Time", "Email", "Submitter", "Customer Name",
        "Location", "Account Manager", "Sales Engineer",
        "Temperature", "Heat Level", "At Risk", "Risk Reasons",
        "Architecture", "Near Term Goals", "BU Contact", "Ask from BU",
        "Background", "Notes", "Last Modified",
    ])
    for r in rows:
        writer.writerow([
            r["id"], r["submission_time"], r["email"], r["submitter_name"],
            r["customer_name"], r["location"], r["account_manager"], r["sales_engineer"],
            r["temperature"], r["temperature_label"], r["at_risk"], r["risk_reasons"],
            r["architecture"], r["near_term_goals"], r["bu_contact"],
            r["ask_from_bu"], r["background"], r["notes"], r["last_modified"],
        ])
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_action(session["username"], "export_csv", f"opal_export_{ts}.csv",
               f"{len(rows)} records exported")
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=opal_export_{ts}.csv"},
    )


@app.post("/admin/delete-db")
def admin_delete_db(request: Request, confirm: str = Form("")):
    session = get_session(request)
    if not session or session.get("role") != "admin":
        return RedirectResponse(url="/login", status_code=303)
    if confirm.strip().upper() != "DELETE":
        return RedirectResponse(url="/admin?msg=Type+DELETE+to+confirm", status_code=303)
    log_action(session["username"], "delete_db", "opal.db", "Database permanently deleted")
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    return RedirectResponse(url="/admin?msg=Database+deleted", status_code=303)


@app.post("/admin/restore/{filename}")
def admin_restore(request: Request, filename: str):
    session = get_session(request)
    if not session or session.get("role") != "admin":
        return RedirectResponse(url="/login", status_code=303)
    src = os.path.join(BACKUP_DIR, filename)
    if not os.path.exists(src):
        return RedirectResponse(url="/admin?msg=Backup+not+found", status_code=303)
    if os.path.exists(DB_PATH):
        do_backup()
    shutil.copy2(src, DB_PATH)
    migrate_db()
    log_action(session["username"], "restore_backup", filename)
    return RedirectResponse(url=f"/admin?msg=Restored+from+{filename}", status_code=303)


# ── User management ───────────────────────────────────────────────────────────

@app.post("/admin/users/create")
def admin_user_create(
    request: Request,
    username: str = Form(...),
    email: str = Form(""),
    password: str = Form(...),
    role: str = Form("user"),
):
    session = get_session(request)
    if not session or session.get("role") != "admin":
        return RedirectResponse(url="/login", status_code=303)
    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO users (username, email, password_hash, role, is_active, created_at)
            VALUES (?, ?, ?, ?, 1, ?)
        """, (username.strip(), email.strip(), pwd_ctx.hash(password), role,
              datetime.now().isoformat()))
        conn.commit()
        log_action(session["username"], "create_user", username.strip(), f"role={role}")
        msg = f"User+{username}+created"
    except sqlite3.IntegrityError:
        msg = f"Username+{username}+already+exists"
    conn.close()
    return RedirectResponse(url=f"/admin?msg={msg}", status_code=303)


@app.post("/admin/users/{user_id}/toggle")
def admin_user_toggle(request: Request, user_id: int):
    session = get_session(request)
    if not session or session.get("role") != "admin":
        return RedirectResponse(url="/login", status_code=303)
    if session["user_id"] == user_id:
        return RedirectResponse(url="/admin?msg=Cannot+disable+your+own+account", status_code=303)
    conn = get_db()
    target_user = conn.execute("SELECT username, is_active FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.execute("UPDATE users SET is_active = 1 - is_active WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    if target_user:
        new_state = "disabled" if target_user["is_active"] else "enabled"
        log_action(session["username"], f"user_{new_state}", target_user["username"])
    return RedirectResponse(url="/admin?msg=User+updated", status_code=303)


@app.post("/admin/users/{user_id}/reset-password")
def admin_reset_password(request: Request, user_id: int):
    session = get_session(request)
    if not session or session.get("role") != "admin":
        return RedirectResponse(url="/login", status_code=303)
    temp_pw = secrets.token_urlsafe(10)
    conn = get_db()
    target_user = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.execute(
        "UPDATE users SET password_hash = ?, must_change_password = 1 WHERE id = ?",
        (pwd_ctx.hash(temp_pw), user_id)
    )
    conn.commit()
    conn.close()
    if target_user:
        log_action(session["username"], "reset_password", target_user["username"])
    return RedirectResponse(
        url=f"/admin?msg=Temporary+password%3A+{temp_pw}+%E2%80%94+user+must+change+on+next+login",
        status_code=303,
    )


# ── Audit Log ─────────────────────────────────────────────────────────────────

@app.get("/admin/audit", response_class=HTMLResponse)
def audit_log_page(request: Request):
    session = get_session(request)
    if not session or session.get("role") != "admin":
        return RedirectResponse(url="/login", status_code=303)
    conn = get_db()
    entries = conn.execute(
        "SELECT * FROM audit_log ORDER BY id DESC LIMIT 500"
    ).fetchall()
    conn.close()
    return templates.TemplateResponse(
        request=request, name="audit.html",
        context={"entries": entries, "session": session},
    )
