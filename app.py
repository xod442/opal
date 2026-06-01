"""
Opal — Customer heat dashboard.

Usage:
    uvicorn app:app --reload --port 8000
"""

import os
import sqlite3
from fastapi import FastAPI, Request, Query, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "opal.db"))

app = FastAPI(title="Opal")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    search: str = Query(""),
    filter_temp: str = Query(""),
    filter_risk: str = Query(""),
    filter_am: str = Query(""),
):
    conn = get_db()

    # Metrics
    metrics = {}
    for label in ("Critical", "Hot", "Concerned", "Stable"):
        row = conn.execute(
            "SELECT COUNT(*) FROM customers WHERE temperature_label = ?", (label,)
        ).fetchone()
        metrics[label] = row[0]
    metrics["Total"] = sum(metrics.values())
    metrics["At Risk"] = conn.execute(
        "SELECT COUNT(*) FROM customers WHERE at_risk = 'Yes – actively evaluating other vendors'"
    ).fetchone()[0]

    # Filter options
    ams = [r[0] for r in conn.execute(
        "SELECT DISTINCT account_manager FROM customers WHERE account_manager != '' ORDER BY account_manager"
    ).fetchall()]

    # Build query
    where = []
    params = []
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
        request=request,
        name="dashboard.html",
        context={
            "customers": customers,
            "metrics": metrics,
            "ams": ams,
            "search": search,
            "filter_temp": filter_temp,
            "filter_risk": filter_risk,
            "filter_am": filter_am,
        },
    )


@app.get("/customer/{customer_id}", response_class=HTMLResponse)
def detail(request: Request, customer_id: int):
    conn = get_db()
    customer = conn.execute(
        "SELECT * FROM customers WHERE id = ?", (customer_id,)
    ).fetchone()
    conn.close()
    if not customer:
        return HTMLResponse("Not found", status_code=404)
    return templates.TemplateResponse(
        request=request,
        name="detail.html",
        context={"c": customer},
    )


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


@app.get("/customer/{customer_id}/edit", response_class=HTMLResponse)
def edit_form(request: Request, customer_id: int):
    conn = get_db()
    customer = conn.execute(
        "SELECT * FROM customers WHERE id = ?", (customer_id,)
    ).fetchone()
    conn.close()
    if not customer:
        return HTMLResponse("Not found", status_code=404)
    return templates.TemplateResponse(
        request=request,
        name="edit.html",
        context={"c": customer, "temp_options": list(TEMP_ORDER.keys())},
    )


@app.post("/customer/{customer_id}/edit")
def edit_save(
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
):
    conn = get_db()
    conn.execute("""
        UPDATE customers SET
            customer_name      = ?,
            temperature        = ?,
            temperature_label  = ?,
            temperature_order  = ?,
            at_risk            = ?,
            risk_reasons       = ?,
            architecture       = ?,
            near_term_goals    = ?,
            bu_contact         = ?,
            ask_from_bu        = ?,
            background         = ?
        WHERE id = ?
    """, (
        customer_name,
        temperature,
        TEMP_LABEL.get(temperature, temperature),
        TEMP_ORDER.get(temperature, 99),
        at_risk,
        risk_reasons,
        architecture,
        near_term_goals,
        bu_contact,
        ask_from_bu,
        background,
        customer_id,
    ))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/", status_code=303)
