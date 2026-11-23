"""AMS web API and static console."""
from __future__ import annotations

import json
import os
import secrets
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from fastapi import Depends, FastAPI, HTTPException, Request, Response, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .database import DATABASE_PATH, get_connection, hash_password, init_db, new_key, utcnow
from .metadata import PAGES, PAGE_MAP, RESOURCES

app = FastAPI(title="Changxin AMS", version="1.0.0", description="Restored Alarm Management System prototype")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

init_db()


def db_conn() -> Iterator[Any]:
    with get_connection() as conn:
        yield conn


def row_dict(row: Any) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def table_columns(conn: Any, table: str) -> set[str]:
    return {r[1].upper() for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def current_user_row(request: Request, conn: Any) -> dict[str, Any]:
    token = request.cookies.get("ams_session")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    session = conn.execute("SELECT * FROM SESSIONS WHERE SESSION_TOKEN=?", (token,)).fetchone()
    if not session:
        raise HTTPException(status_code=401, detail="Session expired")
    user = conn.execute("SELECT * FROM USERS WHERE USER_KEY=? AND ACTIVE='Y'", (session["USER_KEY"],)).fetchone()
    if not user:
        raise HTTPException(status_code=401, detail="User disabled")
    conn.execute("UPDATE SESSIONS SET LAST_ACTIVE_DT=? WHERE SESSION_TOKEN=?", (utcnow(), token))
    return row_dict(user)


def require_user(request: Request, conn: Any = Depends(db_conn)) -> dict[str, Any]:
    return current_user_row(request, conn)


class LoginPayload(BaseModel):
    user_id: str
    password: str


class AlarmManualSendPayload(BaseModel):
    FACTORY_KEY: str
    SUB_SYS_KEY: str
    USER_KEYS: list[str]
    SEND_TYPES: list[str]
    SUBJECT: str
    CONTENT: str = ""
    NUMBER_OF_ACK_USERS: str = "1"


class AlarmSendPayload(BaseModel):
    FACTORY_ID: str
    SUB_SYS_ID: str
    EQP_ID: str
    ALARM_INFO_ID: str
    SUBJECT: str = ""
    CONTENT: str = ""
    DATA_SOURCE: str = "BModule"
    EQP_STATUS_ID: str | None = None


class AlarmAckPayload(BaseModel):
    ALARM_KEYS: list[str]
    COMMENT: str = ""


class AlarmTerminatePayload(BaseModel):
    ALARM_KEYS: list[str]
    COMMENT: str = ""


@app.post("/api/auth/login")
def login(payload: LoginPayload, response: Response, conn: Any = Depends(db_conn)) -> dict[str, Any]:
    user = conn.execute("SELECT * FROM USERS WHERE USER_ID=? AND ACTIVE='Y'", (payload.user_id,)).fetchone()
    if not user or not user["PASSWORD_HASH"] or not user["PASSWORD_SALT"]:
        raise HTTPException(status_code=401, detail="Invalid user or password")
    digest, _ = hash_password(payload.password, user["PASSWORD_SALT"])
    if not secrets.compare_digest(digest, user["PASSWORD_HASH"]):
        raise HTTPException(status_code=401, detail="Invalid user or password")
    token = secrets.token_urlsafe(32)
    now = utcnow()
    conn.execute("DELETE FROM SESSIONS WHERE USER_KEY=?", (user["USER_KEY"],))
    conn.execute(
        "INSERT INTO SESSIONS (SESSION_TOKEN, USER_KEY, LOGIN_DT, LAST_ACTIVE_DT) VALUES (?,?,?,?)",
        (token, user["USER_KEY"], now, now),
    )
    response.set_cookie("ams_session", token, httponly=True, samesite="lax", max_age=28800)
    return {"ok": True, "user": {"USER_ID": user["USER_ID"], "USER_NAME": user["USER_NAME"]}}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response, conn: Any = Depends(db_conn)) -> dict[str, Any]:
    token = request.cookies.get("ams_session")
    if token:
        conn.execute("DELETE FROM SESSIONS WHERE SESSION_TOKEN=?", (token,))
    response.delete_cookie("ams_session")
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    return {"USER_ID": user["USER_ID"], "USER_NAME": user["USER_NAME"]}


@app.get("/api/menu")
def menu(user: dict[str, Any] = Depends(require_user), conn: Any = Depends(db_conn)) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM FUNCTION_MENU WHERE VISIBLE='Y' ORDER BY PARENT_KEY NULLS FIRST, DISPLAY_SEQ, FUNCTION_ID"
    ).fetchall()
    items = [row_dict(r) for r in rows]
    by_parent: dict[str | None, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        by_parent[item.get("PARENT_KEY")].append(item)
    return items


CUSTOM_PAGE_NAMES = {
    "alarm-manual-send": ("警報手動發送作業", "AVPA002"),
    "alarm-send": ("警報補登作業", "AVPA009"),
    "alarm-ack": ("警報確認回報作業", "AVPA003"),
    "alarm-terminate": ("警報強制中斷作業", "AVPA006"),
    "alarm-summary": ("即時警報彙整", "AVPA013"),
    "alarm-report": ("警報處理查詢", "AVPA004"),
    "alarm-history": ("歷史紀錄查詢", "AVPA007"),
    "invalid-alarms": ("無效警報查詢", "AVPA005"),
    "device-status-report": ("系統裝置狀態查詢", "AVPA008"),
    "batch-status-setting": ("批次狀態變更設定", "MCMS051"),
    "report-setting": ("報表設定", "RPTSET001"),
    "batch-hide": ("警報通知設定批次隱藏", "CVMA014"),
    "chamber-alarm-mapping": ("子機台與警報對應設定", "CBRM_CHAMBER_ALARM_MAPPING"),
}


@app.get("/api/pages/{page_key:path}")
def resolve_extra_page(page_key: str, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    normalized = "/" + page_key.lstrip("/")
    page = PAGE_MAP.get(normalized)
    if page:
        return page
    custom = CUSTOM_PAGE_NAMES.get(page_key.strip("/"))
    if custom:
        return {"kind": "custom", "title": custom[0], "code": custom[1], "path": normalized}
    raise HTTPException(status_code=404, detail="Page not found")


@app.get("/api/meta/resources")
def resource_names(user: dict[str, Any] = Depends(require_user)) -> list[str]:
    return list(RESOURCES.keys())


@app.get("/api/meta/send-types")
def send_types(user: dict[str, Any] = Depends(require_user)) -> list[dict[str, str]]:
    return [
        {"value": "EMail", "label": "電子郵件"},
        {"value": "Sms", "label": "簡訊"},
        {"value": "Voice", "label": "電話語音"},
        {"value": "Wechat", "label": "微信"},
        {"value": "Line", "label": "LINE"},
        {"value": "IPPhoneExt", "label": "IPPhone Ext"},
        {"value": "IPPhoneIM", "label": "IPPhone IM"},
        {"value": "IM", "label": "TeamPlus"},
    ]


def _resource_or_404(resource: str) -> dict[str, Any]:
    meta = RESOURCES.get(resource)
    if not meta:
        raise HTTPException(status_code=404, detail="Resource not found")
    return meta


def _validate_payload(meta: dict[str, Any], payload: dict[str, Any], *, partial: bool, exclude_pk: str | None = None) -> dict[str, Any]:
    fields = set(meta["fields"])
    data = {k: v for k, v in payload.items() if k.upper() in fields}
    if not partial:
        missing = [f for f in meta.get("required", []) if f not in data or data[f] in (None, "")]
        if missing:
            raise HTTPException(status_code=422, detail=f"Missing required fields: {', '.join(missing)}")
    unique_fields = meta.get("unique_fields")
    if unique_fields:
        if all(data.get(field) not in (None, "") for field in unique_fields):
            table = meta["table"]
            pk = meta["pk"]
            where = " AND ".join(f'"{field}"=?' for field in unique_fields)
            with get_connection() as c:
                if exclude_pk:
                    row = c.execute(f'SELECT 1 FROM "{table}" WHERE {where} AND "{pk}"<>?',
                                    [*(data[field] for field in unique_fields), exclude_pk]).fetchone()
                else:
                    row = c.execute(f'SELECT 1 FROM "{table}" WHERE {where}',
                                    [data[field] for field in unique_fields]).fetchone()
            if row:
                raise HTTPException(status_code=409, detail=f"{', '.join(unique_fields)} combination already exists")
    unique_field = meta.get("unique")
    if unique_field and unique_field in data and data[unique_field]:
        table = meta["table"]
        pk = meta["pk"]
        existing = conn_unique_check(unique_field, data[unique_field], table, pk, exclude_pk)
        if existing:
            raise HTTPException(status_code=409, detail=f"{unique_field} already exists")
    return data


# helper kept outside endpoint to avoid leaking conn-specific details
def conn_unique_check(field: str, value: Any, table: str, pk: str, exclude_pk: str | None) -> bool:
    with get_connection() as conn:
        if exclude_pk:
            row = conn.execute(f'SELECT 1 FROM "{table}" WHERE "{field}"=? AND "{pk}"<>?', (value, exclude_pk)).fetchone()
        else:
            row = conn.execute(f'SELECT 1 FROM "{table}" WHERE "{field}"=?', (value,)).fetchone()
    return row is not None


def _log_change(conn: Any, meta: dict[str, Any], record_key: str, mode: str, before: dict[str, Any] | None, after: dict[str, Any], user: dict[str, Any]) -> None:
    data_status = after.get("ACTIVE", before.get("ACTIVE") if before else None) or "Y"
    conn.execute(
        """INSERT INTO TABLE_LOGS (LOG_KEY, TABLE_NAME, RECORD_KEY, TRX_MODE, DATA_STATUS, UPDATED_AT, UPDATED_BY,
            UPDATED_IP, HOST_NAME, BEFORE_JSON, AFTER_JSON)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (new_key("LOG"), meta["table"], record_key, mode, data_status, utcnow(),
         user.get("USER_ID", "SYSTEM"), user.get("UPDATED_IP", ""), user.get("HOST_NAME", ""),
         json.dumps(before, ensure_ascii=False, default=str), json.dumps(after, ensure_ascii=False, default=str)),
    )


@app.get("/api/resources/{resource}")
def list_resource(
    resource: str,
    request: Request,
    limit: int = 500,
    offset: int = 0,
    show_inactive: int = 0,
    user: dict[str, Any] = Depends(require_user),
    conn: Any = Depends(db_conn),
) -> list[dict[str, Any]]:
    meta = _resource_or_404(resource)
    allowed_filters = set(meta.get("filters", []))
    conditions: list[str] = []
    params: list[Any] = []
    cols = table_columns(conn, meta["table"])
    if "ACTIVE" in cols and not show_inactive:
        conditions.append("ACTIVE='Y'")
    for key, value in request.query_params.items():
        upper = key.upper()
        if upper in allowed_filters and value not in ("", None):
            op = "LIKE" if any(ch in str(value) for ch in "%_") else "="
            conditions.append(f'"{upper}" {op} ?')
            params.append(value if op == "=" else f"%{value}%")
    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    order_field = meta.get("unique") or meta["fields"][1] if len(meta["fields"]) > 1 else meta["pk"]
    sql = f'SELECT * FROM "{meta["table"]}"{where} ORDER BY "{order_field}" LIMIT ? OFFSET ?'
    rows = conn.execute(sql, [*params, limit, offset]).fetchall()
    return [row_dict(r) for r in rows]


@app.get("/api/resources/{resource}/options")
def resource_options(resource: str, user: dict[str, Any] = Depends(require_user), conn: Any = Depends(db_conn)) -> list[dict[str, Any]]:
    meta = _resource_or_404(resource)
    display_field = meta.get("unique") or next((f for f in meta["fields"] if f not in (meta["pk"], "ACTIVE")), meta["pk"])
    cols = table_columns(conn, meta["table"])
    where = " WHERE ACTIVE='Y'" if "ACTIVE" in cols else ""
    rows = conn.execute(f'SELECT "{meta["pk"]}" AS KEY, "{display_field}" AS LABEL FROM "{meta["table"]}"{where} ORDER BY "{display_field}"').fetchall()
    return [{"KEY": r["KEY"], "LABEL": r["LABEL"]} for r in rows]


@app.get("/api/resources/{resource}/{record_key}")
def get_resource(resource: str, record_key: str, user: dict[str, Any] = Depends(require_user), conn: Any = Depends(db_conn)) -> dict[str, Any]:
    meta = _resource_or_404(resource)
    row = conn.execute(f'SELECT * FROM "{meta["table"]}" WHERE "{meta["pk"]}"=?', (record_key,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Record not found")
    return row_dict(row)


@app.post("/api/resources/{resource}")
def create_resource(resource: str, payload: dict[str, Any], user: dict[str, Any] = Depends(require_user), conn: Any = Depends(db_conn)) -> dict[str, Any]:
    meta = _resource_or_404(resource)
    data = _validate_payload(meta, payload, partial=False)
    pk = meta["pk"]
    prefix = meta["table"].split("_")[0]
    data[pk] = data.get(pk) or new_key(prefix)
    cols = table_columns(conn, meta["table"])
    data.setdefault("ACTIVE", "Y")
    data.setdefault("UPDATED_AT", utcnow())
    data.setdefault("UPDATED_BY", user["USER_ID"])
    data = {k: v for k, v in data.items() if k in cols}
    placeholders = ", ".join("?" for _ in data)
    names = ", ".join(f'"{k}"' for k in data)
    try:
        conn.execute(f'INSERT INTO "{meta["table"]}" ({names}) VALUES ({placeholders})', list(data.values()))
    except Exception as exc:
        raise HTTPException(status_code=409, detail=f"Insert rejected: {str(exc)}") from exc
    _log_change(conn, meta, data[pk], "AddNew", None, data, user)
    return data


@app.put("/api/resources/{resource}/{record_key}")
def update_resource(resource: str, record_key: str, payload: dict[str, Any], user: dict[str, Any] = Depends(require_user), conn: Any = Depends(db_conn)) -> dict[str, Any]:
    meta = _resource_or_404(resource)
    row = conn.execute(f'SELECT * FROM "{meta["table"]}" WHERE "{meta["pk"]}"=?', (record_key,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Record not found")
    before = row_dict(row)
    data = _validate_payload(meta, payload, partial=True, exclude_pk=record_key)
    for field in meta.get("readonly_on_modify", []):
        data.pop(field, None)
    cols = table_columns(conn, meta["table"])
    data = {k: v for k, v in data.items() if k in cols and k != meta["pk"]}
    if not data:
        return before
    data["UPDATED_AT"] = utcnow()
    data["UPDATED_BY"] = user["USER_ID"]
    assignments = ", ".join(f'"{k}"=?' for k in data)
    try:
        conn.execute(f'UPDATE "{meta["table"]}" SET {assignments} WHERE "{meta["pk"]}"=?', [*data.values(), record_key])
    except Exception as exc:
        raise HTTPException(status_code=409, detail=f"Update rejected: {str(exc)}") from exc
    updated_row = conn.execute(f'SELECT * FROM "{meta["table"]}" WHERE "{meta["pk"]}"=?', (record_key,)).fetchone()
    after = row_dict(updated_row)
    _log_change(conn, meta, record_key, "Modify", before, after, user)
    return after


@app.post("/api/resources/{resource}/{record_key}/hide")
def hide_resource(resource: str, record_key: str, user: dict[str, Any] = Depends(require_user), conn: Any = Depends(db_conn)) -> dict[str, Any]:
    return _change_active(resource, record_key, "N", "Hide", user, conn)


@app.post("/api/resources/{resource}/{record_key}/show")
def show_resource(resource: str, record_key: str, user: dict[str, Any] = Depends(require_user), conn: Any = Depends(db_conn)) -> dict[str, Any]:
    return _change_active(resource, record_key, "Y", "Show", user, conn)


def _change_active(resource: str, record_key: str, active: str, mode: str, user: dict[str, Any], conn: Any) -> dict[str, Any]:
    meta = _resource_or_404(resource)
    cols = table_columns(conn, meta["table"])
    if "ACTIVE" not in cols:
        raise HTTPException(status_code=400, detail="Resource does not support soft hide/show")
    row = conn.execute(f'SELECT * FROM "{meta["table"]}" WHERE "{meta["pk"]}"=?', (record_key,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Record not found")
    before = row_dict(row)
    after = {**before, "ACTIVE": active, "UPDATED_AT": utcnow(), "UPDATED_BY": user["USER_ID"]}
    conn.execute(f'UPDATE "{meta["table"]}" SET ACTIVE=?, UPDATED_AT=?, UPDATED_BY=? WHERE "{meta["pk"]}"=?',
                 (active, after["UPDATED_AT"], after["UPDATED_BY"], record_key))
    _log_change(conn, meta, record_key, mode, before, after, user)
    return after


@app.get("/api/resources/{resource}/{record_key}/logs")
def resource_logs(resource: str, record_key: str, user: dict[str, Any] = Depends(require_user), conn: Any = Depends(db_conn)) -> list[dict[str, Any]]:
    meta = _resource_or_404(resource)
    rows = conn.execute(
        "SELECT * FROM TABLE_LOGS WHERE TABLE_NAME=? AND RECORD_KEY=? ORDER BY UPDATED_AT DESC",
        (meta["table"], record_key),
    ).fetchall()
    return [row_dict(r) for r in rows]


@app.post("/api/resources/{resource}/bulk-hide")
def bulk_hide(resource: str, payload: dict[str, Any], user: dict[str, Any] = Depends(require_user), conn: Any = Depends(db_conn)) -> dict[str, Any]:
    keys = payload.get("keys", [])
    if not keys:
        return {"changed": 0}
    changed = 0
    for key in keys:
        _change_active(resource, key, "N", "Hide", user, conn)
        changed += 1
    return {"changed": changed}


@app.post("/api/resources/{resource}/bulk-show")
def bulk_show(resource: str, payload: dict[str, Any], user: dict[str, Any] = Depends(require_user), conn: Any = Depends(db_conn)) -> dict[str, Any]:
    keys = payload.get("keys", [])
    if not keys:
        return {"changed": 0}
    changed = 0
    for key in keys:
        _change_active(resource, key, "Y", "Show", user, conn)
        changed += 1
    return {"changed": changed}


@app.post("/api/auth/change-password")
def change_password(payload: dict[str, Any], user: dict[str, Any] = Depends(require_user), conn: Any = Depends(db_conn)) -> dict[str, Any]:
    if payload.get("new_password") != payload.get("confirm_password"):
        raise HTTPException(status_code=422, detail="Passwords do not match")
    row = conn.execute("SELECT * FROM USERS WHERE USER_KEY=?", (user["USER_KEY"],)).fetchone()
    digest, _ = hash_password(payload.get("old_password", ""), row["PASSWORD_SALT"])
    if not secrets.compare_digest(digest, row["PASSWORD_HASH"]):
        raise HTTPException(status_code=401, detail="Old password is incorrect")
    password_hash, salt = hash_password(payload["new_password"])
    conn.execute("UPDATE USERS SET PASSWORD_HASH=?, PASSWORD_SALT=?, UPDATED_AT=?, UPDATED_BY=? WHERE USER_KEY=?",
                 (password_hash, salt, utcnow(), user["USER_ID"], user["USER_KEY"]))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Alarm lifecycle
# ---------------------------------------------------------------------------

def add_alarm_transaction(conn: Any, alarm_key: str, transaction_type: str, status_after: str,
                          status_before: str | None = None, event_level_id: int | None = None,
                          user_key: str | None = None, user_id: str | None = None,
                          comment: str = "") -> None:
    seq = (conn.execute("SELECT COALESCE(MAX(TRANSACTION_SEQ),0)+1 FROM ALARM_TRANSACTIONS WHERE ALARM_KEY=?",
                        (alarm_key,)).fetchone()[0])
    conn.execute(
        """INSERT INTO ALARM_TRANSACTIONS (ALARM_TRANSACTION_KEY, ALARM_KEY, TRANSACTION_SEQ, TRANSACTION_TYPE,
            STATUS_BEFORE, STATUS_AFTER, EVENT_LEVEL_ID, USER_KEY, USER_ID, COMMENT, TRX_DT)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (new_key("TRX"), alarm_key, seq, transaction_type, status_before, status_after, event_level_id,
         user_key, user_id, comment, utcnow()),
    )


def create_invalid_alarm(conn: Any, subject: str, content: str, factory_id: str | None, sub_sys_id: str | None,
                         eqp_id: str | None, alarm_info_id: str | None, data_source: str, failure_type: str) -> str:
    guid = str(uuid.uuid4())
    key = new_key("INV")
    conn.execute(
        """INSERT INTO INVALID_ALARMS (INVALID_ALARM_KEY, INVALID_ALARM_GUID, SUBJECT, CONTENT, FACTORY_KEY,
            SUB_SYS_KEY, EQP_KEY, ALARM_INFO_ID, DATA_SOURCE, FAILURE_TYPE, CREATE_DT)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (key, guid, subject, content, factory_id, sub_sys_id, eqp_id, alarm_info_id, data_source, failure_type, utcnow()),
    )
    return key


def _match_alarm_info(conn: Any, factory_id: str, sub_sys_id: str, eqp_id: str, alarm_info_id: str) -> Any:
    return conn.execute(
        """SELECT ai.* FROM ALARM_INFOS ai
           JOIN FACTORIES f ON f.FACTORY_KEY=ai.FACTORY_KEY AND f.FACTORY_ID=?
           JOIN SUB_SYSTEMS s ON s.SUB_SYS_KEY=ai.SUB_SYS_KEY AND s.SUB_SYS_ID=?
           JOIN EQP e ON e.EQP_KEY=ai.EQP_KEY AND (e.EQP_ID=? OR e.EQP_ID='*')
           WHERE ai.ALARM_INFO_ID=? AND ai.ACTIVE='Y' LIMIT 1""",
        (factory_id, sub_sys_id, eqp_id, alarm_info_id),
    ).fetchone()


def _is_machine_status_suppressed(conn: Any, alarm_info_key: str, eqp_status_id: str | None) -> bool:
    if not eqp_status_id:
        return False
    row = conn.execute(
        """SELECT 1 FROM ALARM_INFOS ai
           JOIN EQP e ON e.EQP_KEY=ai.EQP_KEY
           JOIN EQP_TYPE_STATUS_MAP m ON m.EQP_TYPE_KEY=e.EQP_TYPE_KEY AND m.ACTIVE='Y'
           JOIN EQP_STATUSES es ON es.EQP_STATUS_KEY=m.EQP_STATUS_KEY AND es.EQP_STATUS_ID=?
           WHERE ai.ALARM_INFO_KEY=? LIMIT 1""",
        (eqp_status_id, alarm_info_key),
    ).fetchone()
    return row is not None


def _duplicate_alarm(conn: Any, alarm_info_key: str, ignore_period: int | None) -> bool:
    if not ignore_period or ignore_period <= 0:
        return False
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=ignore_period)).isoformat(timespec="seconds")
    row = conn.execute(
        "SELECT 1 FROM ALARMS WHERE ALARM_INFO_KEY=? AND CREATE_DT>=? LIMIT 1",
        (alarm_info_key, cutoff),
    ).fetchone()
    return row is not None


def send_alarm_by_level(conn: Any, alarm_key: str, event_key: str | None, level_id: int) -> int:
    if not event_key:
        return 0
    level_groups = conn.execute(
        """SELECT lg.*, g.EVENT_GROUP_ID, g.EVENT_GROUP_NAME FROM EVENT_LEVEL_GROUPS lg
           JOIN EVENT_GROUPS g ON g.EVENT_GROUP_KEY=lg.EVENT_GROUP_KEY AND g.ACTIVE='Y'
           WHERE lg.EVENT_KEY=? AND lg.EVENT_LEVEL_ID=? AND lg.ACTIVE='Y' ORDER BY lg.GROUP_SEQ""",
        (event_key, level_id),
    ).fetchall()
    if not level_groups:
        return 0
    sent = 0
    for group in level_groups:
        send_types = [x for x in (group["ENABLE_SEND_DEVICES"] or "").split(";") if x]
        members = conn.execute(
            """SELECT u.* FROM EVENT_GROUP_MEMBERS m JOIN USERS u ON u.USER_KEY=m.USER_KEY AND u.ACTIVE='Y'
               WHERE m.EVENT_GROUP_KEY=? AND m.ACTIVE='Y' ORDER BY m.MEMBER_SEQ""",
            (group["EVENT_GROUP_KEY"],),
        ).fetchall()
        for member in members:
            for send_type in send_types:
                conn.execute(
                    """INSERT OR IGNORE INTO ALARM_RECIPIENTS (ALARM_RECIPIENT_KEY, ALARM_KEY, USER_KEY, EVENT_GROUP_KEY,
                        SEND_TYPE, SEND_STATUS, ACK_FLAG, UPDATED_AT, UPDATED_BY)
                        VALUES (?,?,?,?,?,?,?,?,?)""",
                    (new_key("RCPT"), alarm_key, member["USER_KEY"], group["EVENT_GROUP_KEY"], send_type,
                     "Success", "N", utcnow(), "SYSTEM"),
                )
                sent += 1
    return sent


@app.post("/api/alarms/manual-send")
def manual_send_alarm(payload: AlarmManualSendPayload, user: dict[str, Any] = Depends(require_user), conn: Any = Depends(db_conn)) -> dict[str, Any]:
    factory = conn.execute("SELECT * FROM FACTORIES WHERE FACTORY_KEY=? AND ACTIVE='Y'", (payload.FACTORY_KEY,)).fetchone()
    sub_sys = conn.execute("SELECT * FROM SUB_SYSTEMS WHERE SUB_SYS_KEY=? AND ACTIVE='Y'", (payload.SUB_SYS_KEY,)).fetchone()
    if not factory or not sub_sys:
        raise HTTPException(status_code=422, detail="Invalid factory or subsystem")
    if not payload.USER_KEYS or not payload.SEND_TYPES:
        raise HTTPException(status_code=422, detail="Recipients and send types are required")
    subject = payload.SUBJECT or "Empty Subject"
    content = payload.CONTENT or "Empty Content"
    key = new_key("ALM")
    guid = str(uuid.uuid4())
    now = utcnow()
    conn.execute(
        """INSERT INTO ALARMS (ALARM_KEY, ALARM_GUID, SUBJECT, CONTENT, ALARM_SOURCE, FACTORY_KEY, SUB_SYS_KEY,
            EVENT_LEVEL_ID, NUMBER_OF_ACK_USERS, ACK_USER_COUNT, SEND_TYPES, STATUS, PROCESS_START_DT, LEVEL_START_DT,
            SEND_START_DT, CREATE_DT, UPDATED_AT, UPDATED_BY)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (key, guid, subject, content, "ManualSend", factory["FACTORY_KEY"], sub_sys["SUB_SYS_KEY"], 1,
         payload.NUMBER_OF_ACK_USERS, 0, ";".join(payload.SEND_TYPES), "Process", now, now, now, now, now, user["USER_ID"]),
    )
    for user_key in payload.USER_KEYS:
        row = conn.execute("SELECT USER_ID FROM USERS WHERE USER_KEY=? AND ACTIVE='Y'", (user_key,)).fetchone()
        if not row:
            continue
        for send_type in payload.SEND_TYPES:
            conn.execute(
                """INSERT OR IGNORE INTO ALARM_RECIPIENTS (ALARM_RECIPIENT_KEY, ALARM_KEY, USER_KEY, SEND_TYPE,
                    SEND_STATUS, ACK_FLAG, UPDATED_AT, UPDATED_BY) VALUES (?,?,?,?,?,?,?,?)""",
                (new_key("RCPT"), key, user_key, send_type, "Success", "N", now, user["USER_ID"]),
            )
    add_alarm_transaction(conn, key, "Create", "Process", None, 1, user["USER_KEY"], user["USER_ID"], "Manual send")
    add_alarm_transaction(conn, key, "Modify", "Process", "Process", 1, user["USER_KEY"], user["USER_ID"], f"Sent via {';'.join(payload.SEND_TYPES)}")
    conn.execute(
        """INSERT INTO SUBJECT_CACHE (SUBJECT_CACHE_KEY, USER_KEY, SUBJECT, USED_COUNT, LAST_USED_DT)
           VALUES (?,?,?,?,?)
           ON CONFLICT(USER_KEY, SUBJECT) DO UPDATE SET USED_COUNT=USED_COUNT+1, LAST_USED_DT=excluded.LAST_USED_DT""",
        (new_key("SBJ"), user["USER_KEY"], subject, 1, now),
    )
    return {"ALARM_KEY": key, "ALARM_GUID": guid, "STATUS": "Process"}


@app.post("/api/alarms/send")
def send_alarm(payload: AlarmSendPayload, user: dict[str, Any] = Depends(require_user), conn: Any = Depends(db_conn)) -> dict[str, Any]:
    subject = payload.SUBJECT or "Empty Subject"
    content = payload.CONTENT or "Empty Content"
    source = payload.DATA_SOURCE or "BModule"
    base_values = [payload.FACTORY_ID, payload.SUB_SYS_ID, payload.EQP_ID, payload.ALARM_INFO_ID]
    factory = conn.execute("SELECT * FROM FACTORIES WHERE FACTORY_ID=? AND ACTIVE='Y'", (payload.FACTORY_ID,)).fetchone()
    if not factory:
        create_invalid_alarm(conn, subject, content, payload.FACTORY_ID, payload.SUB_SYS_ID, payload.EQP_ID, payload.ALARM_INFO_ID, source, "FACTORY_NOT_FOUND")
        raise HTTPException(status_code=422, detail="Invalid alarm: FACTORY_NOT_FOUND")
    sub_sys = conn.execute("SELECT * FROM SUB_SYSTEMS WHERE SUB_SYS_ID=? AND ACTIVE='Y'", (payload.SUB_SYS_ID,)).fetchone()
    if not sub_sys:
        create_invalid_alarm(conn, subject, content, payload.FACTORY_ID, payload.SUB_SYS_ID, payload.EQP_ID, payload.ALARM_INFO_ID, source, "SUB_SYSTEM_NOT_FOUND")
        raise HTTPException(status_code=422, detail="Invalid alarm: SUB_SYSTEM_NOT_FOUND")
    eqp = conn.execute("SELECT * FROM EQP WHERE EQP_ID=? AND ACTIVE='Y'", (payload.EQP_ID,)).fetchone()
    if not eqp:
        create_invalid_alarm(conn, subject, content, payload.FACTORY_ID, payload.SUB_SYS_ID, payload.EQP_ID, payload.ALARM_INFO_ID, source, "EQP_NOT_FOUND")
        raise HTTPException(status_code=422, detail="Invalid alarm: EQP_NOT_FOUND")
    alarm_info = _match_alarm_info(conn, payload.FACTORY_ID, payload.SUB_SYS_ID, payload.EQP_ID, payload.ALARM_INFO_ID)
    if not alarm_info:
        create_invalid_alarm(conn, subject, content, payload.FACTORY_ID, payload.SUB_SYS_ID, payload.EQP_ID, payload.ALARM_INFO_ID, source, "ALARM_INFO_NOT_FOUND")
        raise HTTPException(status_code=422, detail="Invalid alarm: ALARM_INFO_NOT_FOUND")
    if _is_machine_status_suppressed(conn, alarm_info["ALARM_INFO_KEY"], payload.EQP_STATUS_ID):
        create_invalid_alarm(conn, subject, content, payload.FACTORY_ID, payload.SUB_SYS_ID, payload.EQP_ID, payload.ALARM_INFO_ID, source, "MACHINE_STATUS_FILTER")
        return {"ok": True, "filtered": True, "FAILURE_TYPE": "MACHINE_STATUS_FILTER"}
    if _duplicate_alarm(conn, alarm_info["ALARM_INFO_KEY"], alarm_info["IGNORE_PERIOD"]):
        create_invalid_alarm(conn, subject, content, payload.FACTORY_ID, payload.SUB_SYS_ID, payload.EQP_ID, payload.ALARM_INFO_ID, source, "IGNORE_SAME_ALARM")
        return {"ok": True, "filtered": True, "FAILURE_TYPE": "IGNORE_SAME_ALARM"}
    level_rows = conn.execute(
        "SELECT * FROM EVENT_LEVELS WHERE EVENT_KEY=? AND ACTIVE='Y' ORDER BY EVENT_LEVEL_ID",
        (alarm_info["EVENT_KEY"],),
    ).fetchall()
    if not level_rows or level_rows[0]["EVENT_LEVEL_ID"] != 1:
        create_invalid_alarm(conn, subject, content, payload.FACTORY_ID, payload.SUB_SYS_ID, payload.EQP_ID, payload.ALARM_INFO_ID, source, "NO_LEVEL_1")
        raise HTTPException(status_code=422, detail="Invalid alarm: NO_LEVEL_1")
    first_level = level_rows[0]
    key = new_key("ALM")
    guid = str(uuid.uuid4())
    now = utcnow()
    conn.execute(
        """INSERT INTO ALARMS (ALARM_KEY, ALARM_GUID, SUBJECT, CONTENT, ALARM_SOURCE, ALARM_INFO_KEY, FACTORY_KEY,
            SUB_SYS_KEY, EQP_KEY, EVENT_KEY, EVENT_LEVEL_ID, NUMBER_OF_ACK_USERS, ACK_USER_COUNT, SEND_TYPES, STATUS,
            PROCESS_START_DT, LEVEL_START_DT, SEND_START_DT, CREATE_DT, UPDATED_AT, UPDATED_BY)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (key, guid, subject, content, source, alarm_info["ALARM_INFO_KEY"], factory["FACTORY_KEY"], sub_sys["SUB_SYS_KEY"],
         eqp["EQP_KEY"], alarm_info["EVENT_KEY"], 1, first_level["NUMBER_OF_ACK_USERS"], 0, "Event", "Process",
         now, now, now, now, now, user["USER_ID"]),
    )
    sent = send_alarm_by_level(conn, key, alarm_info["EVENT_KEY"], 1)
    if sent == 0:
        conn.execute("UPDATE ALARMS SET STATUS='NoNextLevel', COMPLETE_DT=?, UPDATED_AT=? WHERE ALARM_KEY=?", (now, now, key))
        add_alarm_transaction(conn, key, "Create", "Process", None, 1, user["USER_KEY"], user["USER_ID"], "Supplement send")
        add_alarm_transaction(conn, key, "AlarmFail", "NoNextLevel", "Process", 1, user["USER_KEY"], user["USER_ID"], "No recipients")
        return {"ALARM_KEY": key, "ALARM_GUID": guid, "STATUS": "NoNextLevel", "sent": 0}
    add_alarm_transaction(conn, key, "Create", "Process", None, 1, user["USER_KEY"], user["USER_ID"], "Supplement send")
    add_alarm_transaction(conn, key, "Modify", "Process", "Process", 1, user["USER_KEY"], user["USER_ID"], f"Sent to {sent} recipients")
    conn.execute(
        """INSERT INTO SUBJECT_CACHE (SUBJECT_CACHE_KEY, USER_KEY, SUBJECT, USED_COUNT, LAST_USED_DT)
           VALUES (?,?,?,?,?) ON CONFLICT(USER_KEY, SUBJECT) DO UPDATE SET USED_COUNT=USED_COUNT+1, LAST_USED_DT=excluded.LAST_USED_DT""",
        (new_key("SBJ"), user["USER_KEY"], subject, 1, now),
    )
    return {"ALARM_KEY": key, "ALARM_GUID": guid, "STATUS": "Process", "sent": sent}


@app.get("/api/alarms/process")
def process_alarm_data(user: dict[str, Any] = Depends(require_user), conn: Any = Depends(db_conn)) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT a.*, f.FACTORY_ID, s.SUB_SYS_ID, e.EQP_ID, ev.EVENT_ID
           FROM ALARMS a
           LEFT JOIN FACTORIES f ON f.FACTORY_KEY=a.FACTORY_KEY
           LEFT JOIN SUB_SYSTEMS s ON s.SUB_SYS_KEY=a.SUB_SYS_KEY
           LEFT JOIN EQP e ON e.EQP_KEY=a.EQP_KEY
           LEFT JOIN EVENTS ev ON ev.EVENT_KEY=a.EVENT_KEY
           WHERE a.STATUS='Process' ORDER BY a.CREATE_DT DESC"""
    ).fetchall()
    return [row_dict(r) for r in rows]


@app.get("/api/alarms/ack")
def alarm_ack_data(user: dict[str, Any] = Depends(require_user), conn: Any = Depends(db_conn)) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT DISTINCT a.*, r.USER_KEY AS CURRENT_USER_KEY, f.FACTORY_ID, s.SUB_SYS_ID, e.EQP_ID, ev.EVENT_ID
           FROM ALARMS a
           JOIN ALARM_RECIPIENTS r ON r.ALARM_KEY=a.ALARM_KEY AND r.USER_KEY=? AND r.ACK_FLAG='N'
           LEFT JOIN FACTORIES f ON f.FACTORY_KEY=a.FACTORY_KEY
           LEFT JOIN SUB_SYSTEMS s ON s.SUB_SYS_KEY=a.SUB_SYS_KEY
           LEFT JOIN EQP e ON e.EQP_KEY=a.EQP_KEY
           LEFT JOIN EVENTS ev ON ev.EVENT_KEY=a.EVENT_KEY
           WHERE a.STATUS='Process' ORDER BY a.CREATE_DT DESC""",
        (user["USER_KEY"],),
    ).fetchall()
    return [row_dict(r) for r in rows]


@app.post("/api/alarms/ack")
def ack_alarm(payload: AlarmAckPayload, user: dict[str, Any] = Depends(require_user), conn: Any = Depends(db_conn)) -> dict[str, Any]:
    results = []
    now = utcnow()
    for alarm_key in payload.ALARM_KEYS:
        alarm = conn.execute("SELECT * FROM ALARMS WHERE ALARM_KEY=? AND STATUS='Process'", (alarm_key,)).fetchone()
        if not alarm:
            results.append({"ALARM_KEY": alarm_key, "ok": False, "reason": "Not processable"})
            continue
        recipients = conn.execute(
            "SELECT * FROM ALARM_RECIPIENTS WHERE ALARM_KEY=? AND USER_KEY=?", (alarm_key, user["USER_KEY"])
        ).fetchall()
        if not recipients:
            results.append({"ALARM_KEY": alarm_key, "ok": False, "reason": "Not a recipient"})
            continue
        conn.execute(
            "UPDATE ALARM_RECIPIENTS SET ACK_FLAG='Y', ACK_DT=?, ACK_COMMENT=?, UPDATED_AT=?, UPDATED_BY=? WHERE ALARM_KEY=? AND USER_KEY=? AND ACK_FLAG='N'",
            (now, payload.COMMENT, now, user["USER_ID"], alarm_key, user["USER_KEY"]),
        )
        already_acked = conn.execute(
            "SELECT 1 FROM ALARM_TRANSACTIONS WHERE ALARM_KEY=? AND TRANSACTION_TYPE='UserAck' AND USER_KEY=?",
            (alarm_key, user["USER_KEY"]),
        ).fetchone()
        if not already_acked:
            conn.execute("UPDATE ALARMS SET ACK_USER_COUNT=ACK_USER_COUNT+1, LAST_ACK_DT=?, UPDATED_AT=?, UPDATED_BY=? WHERE ALARM_KEY=?",
                         (now, now, user["USER_ID"], alarm_key))
            add_alarm_transaction(conn, alarm_key, "UserAck", alarm["STATUS"], alarm["STATUS"], alarm["EVENT_LEVEL_ID"], user["USER_KEY"], user["USER_ID"], payload.COMMENT)
        updated = conn.execute("SELECT * FROM ALARMS WHERE ALARM_KEY=?", (alarm_key,)).fetchone()
        required_raw = updated["NUMBER_OF_ACK_USERS"]
        unique_recipients = conn.execute("SELECT COUNT(DISTINCT USER_KEY) FROM ALARM_RECIPIENTS WHERE ALARM_KEY=?", (alarm_key,)).fetchone()[0]
        required = unique_recipients if str(required_raw).strip() == "*" else int(required_raw or 1)
        if updated["ACK_USER_COUNT"] >= required:
            conn.execute("UPDATE ALARMS SET STATUS='Completed', COMPLETE_DT=?, UPDATED_AT=?, UPDATED_BY=? WHERE ALARM_KEY=?",
                         (now, now, user["USER_ID"], alarm_key))
            add_alarm_transaction(conn, alarm_key, "AlarmComplete", "Completed", "Process", updated["EVENT_LEVEL_ID"], user["USER_KEY"], user["USER_ID"], payload.COMMENT)
            results.append({"ALARM_KEY": alarm_key, "ok": True, "status": "Completed"})
        else:
            results.append({"ALARM_KEY": alarm_key, "ok": True, "status": "Process"})
    return {"results": results}


@app.post("/api/alarms/terminate")
def terminate_alarm(payload: AlarmTerminatePayload, user: dict[str, Any] = Depends(require_user), conn: Any = Depends(db_conn)) -> dict[str, Any]:
    results = []
    now = utcnow()
    for alarm_key in payload.ALARM_KEYS:
        alarm = conn.execute("SELECT * FROM ALARMS WHERE ALARM_KEY=? AND STATUS='Process'", (alarm_key,)).fetchone()
        if not alarm:
            results.append({"ALARM_KEY": alarm_key, "ok": False, "reason": "Not processable"})
            continue
        conn.execute("UPDATE ALARMS SET STATUS='Terminated', COMPLETE_DT=?, UPDATED_AT=?, UPDATED_BY=? WHERE ALARM_KEY=?",
                     (now, now, user["USER_ID"], alarm_key))
        add_alarm_transaction(conn, alarm_key, "Terminate", "Terminated", "Process", alarm["EVENT_LEVEL_ID"], user["USER_KEY"], user["USER_ID"], payload.COMMENT)
        results.append({"ALARM_KEY": alarm_key, "ok": True, "status": "Terminated"})
    return {"results": results}


@app.post("/api/alarms/upgrade")
def upgrade_alarms(user: dict[str, Any] = Depends(require_user), conn: Any = Depends(db_conn)) -> dict[str, Any]:
    now_dt = datetime.now(timezone.utc)
    rows = conn.execute("SELECT * FROM ALARMS WHERE STATUS='Process'").fetchall()
    changed = []
    for alarm in rows:
        start = datetime.fromisoformat(alarm["LEVEL_START_DT"] or alarm["PROCESS_START_DT"] or utcnow())
        if alarm["EVENT_KEY"]:
            level = conn.execute(
                "SELECT * FROM EVENT_LEVELS WHERE EVENT_KEY=? AND EVENT_LEVEL_ID=? AND ACTIVE='Y'",
                (alarm["EVENT_KEY"], alarm["EVENT_LEVEL_ID"]),
            ).fetchone()
            if not level:
                continue
            interval = timedelta(minutes=level["LEVEL_INTERVAL"])
        else:
            interval = timedelta(minutes=30)
        if now_dt - start < interval:
            continue
        next_level = None
        if alarm["EVENT_KEY"]:
            next_level = conn.execute(
                """SELECT * FROM EVENT_LEVELS WHERE EVENT_KEY=? AND EVENT_LEVEL_ID>? AND ACTIVE='Y'
                   ORDER BY EVENT_LEVEL_ID LIMIT 1""",
                (alarm["EVENT_KEY"], alarm["EVENT_LEVEL_ID"]),
            ).fetchone()
        if next_level:
            sent = send_alarm_by_level(conn, alarm["ALARM_KEY"], alarm["EVENT_KEY"], next_level["EVENT_LEVEL_ID"])
            conn.execute(
                "UPDATE ALARMS SET EVENT_LEVEL_ID=?, LEVEL_START_DT=?, SEND_START_DT=?, NUMBER_OF_ACK_USERS=?, UPDATED_AT=?, UPDATED_BY=? WHERE ALARM_KEY=?",
                (next_level["EVENT_LEVEL_ID"], utcnow(), utcnow(), next_level["NUMBER_OF_ACK_USERS"], utcnow(), user["USER_ID"], alarm["ALARM_KEY"]),
            )
            add_alarm_transaction(conn, alarm["ALARM_KEY"], "LevelUpgrade", "Process", "Process", next_level["EVENT_LEVEL_ID"], user["USER_KEY"], user["USER_ID"], f"Auto upgraded; sent={sent}")
            changed.append({"ALARM_KEY": alarm["ALARM_KEY"], "status": "Process", "level": next_level["EVENT_LEVEL_ID"]})
        else:
            conn.execute("UPDATE ALARMS SET STATUS='NoNextLevel', COMPLETE_DT=?, UPDATED_AT=?, UPDATED_BY=? WHERE ALARM_KEY=?",
                         (utcnow(), utcnow(), user["USER_ID"], alarm["ALARM_KEY"]))
            add_alarm_transaction(conn, alarm["ALARM_KEY"], "AlarmFail", "NoNextLevel", "Process", alarm["EVENT_LEVEL_ID"], user["USER_KEY"], user["USER_ID"], "No next level")
            changed.append({"ALARM_KEY": alarm["ALARM_KEY"], "status": "NoNextLevel"})
    return {"processed": len(changed), "alarms": changed}


@app.get("/api/alarms/{alarm_key}/transactions")
def alarm_transactions(alarm_key: str, user: dict[str, Any] = Depends(require_user), conn: Any = Depends(db_conn)) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM ALARM_TRANSACTIONS WHERE ALARM_KEY=? ORDER BY TRANSACTION_SEQ", (alarm_key,)).fetchall()
    return [row_dict(r) for r in rows]


@app.get("/api/alarms/subject-cache")
def alarm_subject_cache(user: dict[str, Any] = Depends(require_user), conn: Any = Depends(db_conn)) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT SUBJECT, USED_COUNT, LAST_USED_DT FROM SUBJECT_CACHE WHERE USER_KEY=? ORDER BY LAST_USED_DT DESC LIMIT 100",
        (user["USER_KEY"],),
    ).fetchall()
    return [row_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

@app.get("/api/reports/alarm-summary")
def alarm_summary(user: dict[str, Any] = Depends(require_user), conn: Any = Depends(db_conn)) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT f.FACTORY_ID, f.FACTORY_NAME, s.SUB_SYS_ID, s.SUB_SYS_NAME, COUNT(*) AS ALARM_COUNT
           FROM ALARMS a
           JOIN FACTORIES f ON f.FACTORY_KEY=a.FACTORY_KEY
           JOIN SUB_SYSTEMS s ON s.SUB_SYS_KEY=a.SUB_SYS_KEY
           WHERE a.STATUS='Process'
           GROUP BY f.FACTORY_ID, f.FACTORY_NAME, s.SUB_SYS_ID, s.SUB_SYS_NAME
           ORDER BY f.FACTORY_ID, s.SUB_SYS_ID"""
    ).fetchall()
    return [row_dict(r) for r in rows]


@app.get("/api/reports/alarm-summary/detail")
def alarm_summary_detail(factory_id: str, sub_sys_id: str, user: dict[str, Any] = Depends(require_user), conn: Any = Depends(db_conn)) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT f.FACTORY_ID, f.FACTORY_NAME, s.SUB_SYS_ID, s.SUB_SYS_NAME, e.EQP_ID, COUNT(*) AS ALARM_COUNT
           FROM ALARMS a
           JOIN FACTORIES f ON f.FACTORY_KEY=a.FACTORY_KEY
           JOIN SUB_SYSTEMS s ON s.SUB_SYS_KEY=a.SUB_SYS_KEY
           JOIN EQP e ON e.EQP_KEY=a.EQP_KEY
           WHERE a.STATUS='Process' AND f.FACTORY_ID=? AND s.SUB_SYS_ID=?
           GROUP BY f.FACTORY_ID, f.FACTORY_NAME, s.SUB_SYS_ID, s.SUB_SYS_NAME, e.EQP_ID
           ORDER BY e.EQP_ID""",
        (factory_id, sub_sys_id),
    ).fetchall()
    return [row_dict(r) for r in rows]


@app.get("/api/reports/alarms")
def alarm_report(request: Request, user: dict[str, Any] = Depends(require_user), conn: Any = Depends(db_conn)) -> list[dict[str, Any]]:
    conditions: list[str] = []
    params: list[Any] = []
    qp = request.query_params
    if qp.get("from"):
        conditions.append("a.CREATE_DT>=?")
        params.append(qp["from"])
    if qp.get("to"):
        conditions.append("a.CREATE_DT<=?")
        params.append(qp["to"] + ("T23:59:59" if len(qp["to"]) == 10 else ""))
    if qp.get("eqp_group_key"):
        conditions.append("e.EQP_GROUP_KEY=?")
        params.append(qp["eqp_group_key"])
    if qp.get("eqp_id"):
        conditions.append("e.EQP_ID LIKE ?")
        params.append(f"%{qp['eqp_id']}%")
    if qp.get("sub_sys_id"):
        conditions.append("s.SUB_SYS_ID LIKE ?")
        params.append(f"%{qp['sub_sys_id']}%")
    if qp.get("status"):
        conditions.append("a.STATUS=?")
        params.append(qp["status"])
    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = conn.execute(
        """SELECT a.*, f.FACTORY_ID, s.SUB_SYS_ID, e.EQP_ID, ev.EVENT_ID
           FROM ALARMS a
           LEFT JOIN FACTORIES f ON f.FACTORY_KEY=a.FACTORY_KEY
           LEFT JOIN SUB_SYSTEMS s ON s.SUB_SYS_KEY=a.SUB_SYS_KEY
           LEFT JOIN EQP e ON e.EQP_KEY=a.EQP_KEY
           LEFT JOIN EVENTS ev ON ev.EVENT_KEY=a.EVENT_KEY""" + where + " ORDER BY a.CREATE_DT DESC LIMIT 1000",
        params,
    ).fetchall()
    return [row_dict(r) for r in rows]


@app.get("/api/reports/history")
def history_report(request: Request, user: dict[str, Any] = Depends(require_user), conn: Any = Depends(db_conn)) -> list[dict[str, Any]]:
    conditions: list[str] = []
    params: list[Any] = []
    qp = request.query_params
    if qp.get("from"):
        conditions.append("t.TRX_DT>=?")
        params.append(qp["from"])
    if qp.get("to"):
        conditions.append("t.TRX_DT<=?")
        params.append(qp["to"] + ("T23:59:59" if len(qp["to"]) == 10 else ""))
    if qp.get("eqp_id"):
        conditions.append("e.EQP_ID LIKE ?")
        params.append(f"%{qp['eqp_id']}%")
    if qp.get("sub_sys_id"):
        conditions.append("s.SUB_SYS_ID LIKE ?")
        params.append(f"%{qp['sub_sys_id']}%")
    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = conn.execute(
        """SELECT t.*, a.SUBJECT, a.CONTENT, a.ALARM_GUID, a.STATUS, f.FACTORY_ID, s.SUB_SYS_ID, e.EQP_ID,
                  ev.EVENT_ID, a.CREATE_DT, a.EVENT_LEVEL_ID AS CURRENT_EVENT_LEVEL_ID
           FROM ALARM_TRANSACTIONS t
           JOIN ALARMS a ON a.ALARM_KEY=t.ALARM_KEY
           LEFT JOIN FACTORIES f ON f.FACTORY_KEY=a.FACTORY_KEY
           LEFT JOIN SUB_SYSTEMS s ON s.SUB_SYS_KEY=a.SUB_SYS_KEY
           LEFT JOIN EQP e ON e.EQP_KEY=a.EQP_KEY
           LEFT JOIN EVENTS ev ON ev.EVENT_KEY=a.EVENT_KEY""" + where + " ORDER BY t.TRX_DT DESC, t.TRANSACTION_SEQ DESC LIMIT 1000",
        params,
    ).fetchall()
    return [row_dict(r) for r in rows]


@app.get("/api/reports/invalid-alarms")
def invalid_alarm_report(request: Request, user: dict[str, Any] = Depends(require_user), conn: Any = Depends(db_conn)) -> list[dict[str, Any]]:
    conditions: list[str] = []
    params: list[Any] = []
    qp = request.query_params
    if qp.get("from"):
        conditions.append("CREATE_DT>=?")
        params.append(qp["from"])
    if qp.get("to"):
        conditions.append("CREATE_DT<=?")
        params.append(qp["to"] + ("T23:59:59" if len(qp["to"]) == 10 else ""))
    if qp.get("eqp_id"):
        conditions.append("EQP_KEY IN (SELECT EQP_KEY FROM EQP WHERE EQP_ID LIKE ?)")
        params.append(f"%{qp['eqp_id']}%")
    if qp.get("sub_sys_id"):
        conditions.append("SUB_SYS_KEY IN (SELECT SUB_SYS_KEY FROM SUB_SYSTEMS WHERE SUB_SYS_ID LIKE ?)")
        params.append(f"%{qp['sub_sys_id']}%")
    if qp.get("failure_type"):
        conditions.append("FAILURE_TYPE=?")
        params.append(qp["failure_type"])
    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = conn.execute("SELECT * FROM INVALID_ALARMS" + where + " ORDER BY CREATE_DT DESC LIMIT 1000", params).fetchall()
    return [row_dict(r) for r in rows]


@app.get("/api/reports/device-status")
def device_status_report(user: dict[str, Any] = Depends(require_user), conn: Any = Depends(db_conn)) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM ALARM_SERVICE_CONFIG ORDER BY SERVER_ID, AGENT_ID, DEVICE_ID").fetchall()
    return [row_dict(r) for r in rows]


@app.get("/api/export/{report_name}")
def export_report(report_name: str, request: Request, user: dict[str, Any] = Depends(require_user), conn: Any = Depends(db_conn)) -> StreamingResponse:
    endpoint_map = {
        "alarm-report": "/api/reports/alarms?",
        "alarm-history": "/api/reports/history?",
        "invalid-alarms": "/api/reports/invalid-alarms?",
        "device-status-report": "/api/reports/device-status",
    }
    if report_name not in endpoint_map:
        raise HTTPException(status_code=404, detail="Report not found")
    query = str(request.url.query)
    # Read through the same public report function to keep filters consistent.
    if report_name == "alarm-report":
        data = alarm_report(request, user, conn)
    elif report_name == "alarm-history":
        data = history_report(request, user, conn)
    elif report_name == "invalid-alarms":
        data = invalid_alarm_report(request, user, conn)
    else:
        data = device_status_report(user, conn)
    if not data:
        yield ""
        return
    headers = list(data[0].keys())
    def csv_escape(v: Any) -> str:
        s = "" if v is None else str(v).replace('"', '""')
        return f'"{s}"'
    output = ",".join(csv_escape(h) for h in headers) + "\n"
    yield output
    for row in data:
        yield ",".join(csv_escape(row.get(h)) for h in headers) + "\n"
    return


@app.get("/health", include_in_schema=False)
def health() -> dict[str, str]:
    return {"status": "ok", "service": "AMS", "database": os.path.basename(DATABASE_PATH)}


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse("app/static/index.html")


app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
