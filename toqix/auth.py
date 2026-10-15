"""TOQIX accounts — Google sign-in, sessions, activity log, abuse watch.

Zero-budget, stdlib-only implementation:

* Sign-in is the standard Google OAuth 2.0 authorization-code flow
  (server-side: no third-party JS on the site, no external API keys
  beyond the owner's own Google Cloud OAuth client). Credentials come
  from the environment (TOQIX_GOOGLE_CLIENT_ID / _SECRET) and are never
  stored in the repo or the database.
* Sessions are HMAC-signed cookies; the signing secret comes from
  TOQIX_SESSION_SECRET (a per-deployment file is used as a fallback so
  local development works with zero setup).
* Every account is a row in ``users``; the owner's main Gmail is the
  admin (ADMIN_EMAILS). Admins get the /admin panel: all activity,
  all users, and an alerts feed.
* The abuse watch is deterministic: every creation prompt and agent
  message passes check_prompt() BEFORE anything is queued. Hard-block
  categories are refused AND alerted; softer signals only alert, so
  the owner sees attempts in the admin panel and decides himself
  (banning is a one-click admin action, never automatic).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
import urllib.parse
import urllib.request
import uuid

from . import config

ADMIN_EMAILS = {"itsprogrammerali@gmail.com"}
COOKIE_NAME = "toqix_session"
STATE_COOKIE = "toqix_oauth_state"
SESSION_SECONDS = 30 * 24 * 3600  # 30 days
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_auth_db() -> None:
    with _conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id          TEXT PRIMARY KEY,
                google_sub  TEXT UNIQUE,
                email       TEXT UNIQUE NOT NULL,
                name        TEXT NOT NULL DEFAULT '',
                picture     TEXT NOT NULL DEFAULT '',
                is_admin    INTEGER NOT NULL DEFAULT 0,
                banned      INTEGER NOT NULL DEFAULT 0,
                created_at  REAL NOT NULL,
                last_seen   REAL NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS activity (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    TEXT DEFAULT NULL,
                email      TEXT NOT NULL DEFAULT '',
                event      TEXT NOT NULL,
                detail     TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alerts (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    TEXT DEFAULT NULL,
                email      TEXT NOT NULL DEFAULT '',
                severity   TEXT NOT NULL DEFAULT 'medium',
                rule       TEXT NOT NULL DEFAULT '',
                prompt     TEXT NOT NULL DEFAULT '',
                detail     TEXT NOT NULL DEFAULT '',
                reviewed   INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL
            )
            """
        )


# ---------------------------------------------------------------------------
# Configuration / secrets
# ---------------------------------------------------------------------------

def google_client_id() -> str:
    return os.environ.get("TOQIX_GOOGLE_CLIENT_ID", "")


def google_client_secret() -> str:
    return os.environ.get("TOQIX_GOOGLE_CLIENT_SECRET", "")


def google_configured() -> bool:
    return bool(google_client_id() and google_client_secret())


def base_url() -> str:
    return os.environ.get("TOQIX_BASE_URL",
                          "https://toqix.pythonanywhere.com").rstrip("/")


def redirect_uri() -> str:
    return base_url() + "/auth/google/callback"


def api_key() -> str:
    """Machine key (owner's own automations act as admin with it).
    Lives only in the deployment environment — never in the repo."""
    return os.environ.get("TOQIX_API_KEY", "")


def dev_auth_enabled() -> bool:
    return os.environ.get("TOQIX_DEV_AUTH", "") == "1"


def _session_secret() -> bytes:
    env = os.environ.get("TOQIX_SESSION_SECRET", "")
    if env:
        return env.encode("utf-8")
    # Fallback: a per-install secret file under the data dir (created
    # once, never committed — the data dir is not part of the repo).
    path = config.DATA_DIR / ".session_secret"
    try:
        if path.exists():
            return path.read_bytes().strip()
        value = secrets.token_hex(32).encode("utf-8")
        path.write_bytes(value)
        return value
    except OSError:
        return b"toqix-dev-secret-change-me"


# ---------------------------------------------------------------------------
# Signed tokens (sessions + OAuth state)
# ---------------------------------------------------------------------------

def _sign(payload: bytes) -> str:
    return hmac.new(_session_secret(), payload, hashlib.sha256).hexdigest()


def _make_token(data: dict) -> str:
    raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
    body = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return body + "." + _sign(body.encode("ascii"))


def _read_token(token: str | None) -> dict | None:
    if not token or "." not in token:
        return None
    body, _, sig = token.partition(".")
    if not hmac.compare_digest(sig, _sign(body.encode("ascii"))):
        return None
    try:
        raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    if float(data.get("exp", 0)) < time.time():
        return None
    return data


def make_session_cookie(user_id: str) -> str:
    return _make_token({"uid": user_id,
                        "exp": time.time() + SESSION_SECONDS})


def make_state_cookie() -> tuple[str, str]:
    """(state value for Google, signed cookie to verify it later)."""
    state = secrets.token_urlsafe(24)
    cookie = _make_token({"state": state, "exp": time.time() + 600})
    return state, cookie


def check_state_cookie(cookie: str | None, state: str | None) -> bool:
    data = _read_token(cookie)
    return bool(data and state and hmac.compare_digest(
        str(data.get("state", "")), state))


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def _user_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    d["is_admin"] = bool(d.get("is_admin"))
    d["banned"] = bool(d.get("banned"))
    return d


def get_user(user_id: str | None) -> dict | None:
    if not user_id:
        return None
    with _conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?",
                           (user_id,)).fetchone()
    return _user_dict(row)


def upsert_google_user(sub: str, email: str, name: str,
                       picture: str) -> dict:
    email = (email or "").strip().lower()
    is_admin = 1 if email in ADMIN_EMAILS else 0
    now = time.time()
    with _conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?",
                           (email,)).fetchone()
        if row is None:
            user_id = uuid.uuid4().hex[:12]
            conn.execute(
                "INSERT INTO users (id, google_sub, email, name, picture,"
                " is_admin, created_at, last_seen)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, sub, email, name or "", picture or "",
                 is_admin, now, now),
            )
        else:
            user_id = row["id"]
            conn.execute(
                "UPDATE users SET google_sub = ?, name = ?, picture = ?,"
                " is_admin = ?, last_seen = ? WHERE id = ?",
                (sub, name or row["name"], picture or row["picture"],
                 is_admin, now, user_id),
            )
    return get_user(user_id)


def user_for_session(cookie_value: str | None) -> dict | None:
    data = _read_token(cookie_value)
    if not data:
        return None
    return get_user(str(data.get("uid", "")))


def get_or_create_admin() -> dict:
    """The admin user row for the owner's main email — the identity
    machine requests (API key) act as, so automations' creations
    belong to the owner."""
    email = sorted(ADMIN_EMAILS)[0]
    with _conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?",
                           (email,)).fetchone()
    if row is not None:
        return _user_dict(row)
    return upsert_google_user("system", email, "TOQIX Admin", "")


# ---------------------------------------------------------------------------
# Google OAuth (server-side authorization-code flow, urllib only)
# ---------------------------------------------------------------------------

def google_auth_url(state: str) -> str:
    params = {
        "client_id": google_client_id(),
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
        "access_type": "online",
    }
    return GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode(params)


def exchange_code(code: str) -> dict:
    body = urllib.parse.urlencode({
        "code": code,
        "client_id": google_client_id(),
        "client_secret": google_client_secret(),
        "redirect_uri": redirect_uri(),
        "grant_type": "authorization_code",
    }).encode("utf-8")
    req = urllib.request.Request(
        GOOGLE_TOKEN_URL, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_userinfo(access_token: str) -> dict:
    req = urllib.request.Request(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": "Bearer " + access_token})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# Activity log + alerts (the admin panel's eyes)
# ---------------------------------------------------------------------------

def log_activity(user_id: str | None, email: str, event: str,
                 detail: str = "") -> None:
    try:
        with _conn() as conn:
            conn.execute(
                "INSERT INTO activity (user_id, email, event, detail,"
                " created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, email or "", event, (detail or "")[:500],
                 time.time()),
            )
    except Exception:
        pass  # logging must never break the product


def add_alert(user_id: str | None, email: str, severity: str, rule: str,
              prompt: str = "", detail: str = "") -> None:
    try:
        with _conn() as conn:
            conn.execute(
                "INSERT INTO alerts (user_id, email, severity, rule,"
                " prompt, detail, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, email or "", severity, rule,
                 (prompt or "")[:400], (detail or "")[:400], time.time()),
            )
    except Exception:
        pass


def list_users() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT u.*, (SELECT COUNT(*) FROM jobs j"
            "              WHERE j.user_id = u.id) AS job_count,"
            "       (SELECT COUNT(*) FROM alerts a"
            "              WHERE a.user_id = u.id) AS alert_count"
            " FROM users u ORDER BY u.created_at DESC"
        ).fetchall()
    return [_user_dict(r) | {"job_count": r["job_count"],
                             "alert_count": r["alert_count"]}
            for r in rows]


def set_banned(user_id: str, banned: bool) -> dict | None:
    with _conn() as conn:
        conn.execute("UPDATE users SET banned = ? WHERE id = ?",
                     (1 if banned else 0, user_id))
    return get_user(user_id)


def list_activity(limit: int = 100) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM activity ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()
    return [dict(r) for r in rows]


def list_alerts(limit: int = 100, unreviewed_only: bool = False) -> list[dict]:
    where = " WHERE reviewed = 0" if unreviewed_only else ""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM alerts" + where
            + " ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def review_alert(alert_id: int) -> None:
    with _conn() as conn:
        conn.execute("UPDATE alerts SET reviewed = 1 WHERE id = ?",
                     (alert_id,))


def overview() -> dict:
    with _conn() as conn:
        def count(sql: str) -> int:
            return conn.execute(sql).fetchone()[0]
        return {
            "users": count("SELECT COUNT(*) FROM users"),
            "jobs_total": count("SELECT COUNT(*) FROM jobs"),
            "jobs_today": count(
                "SELECT COUNT(*) FROM jobs WHERE created_at > "
                + str(time.time() - 86400)),
            "alerts_unreviewed": count(
                "SELECT COUNT(*) FROM alerts WHERE reviewed = 0"),
            "alerts_total": count("SELECT COUNT(*) FROM alerts"),
        }


# ---------------------------------------------------------------------------
# The abuse watch — deterministic prompt screening.
#
# Returns {"blocked": bool, "severity": str, "rule": str}.
# blocked=True  -> the request is refused AND an alert is filed.
# severity only -> the request proceeds, but an alert is filed so the
#                  owner can see the attempt in the admin panel.
# ---------------------------------------------------------------------------

_MINOR_WORDS = (
    "child", "children", "minor", "underage", "kid", "kids", "teen",
    "teenage", "schoolgirl", "schoolboy", "loli", "shota", "preteen",
    "bacha", "bachi", "chhota bacha",
)
_SEXUAL_WORDS = (
    "nude", "naked", "sex", "sexual", "porn", "erotic", "nsfw",
    "topless", "undress", "striptease", "lingerie", "bikini body",
    "seductive", "sensual", "nanga", "nangi",
)
_HARD_PHRASES = (
    "child porn", "cp video", "underage sex", "minor sex",
    "schoolgirl sex", "rape scene", "sexual assault scene",
)
_WRONGDOING_PATTERNS = (
    r"how to (make|build|create|cook)\b.{0,40}\b(bomb|explosive|weapon|gun|drug|meth|poison)",
    r"(bomb|explosive|weapon)\b.{0,20}\b(tutorial|instructions|recipe|guide)",
    r"how to (kill|murder|poison)\b",
    r"(suicide|self[- ]?harm)\b.{0,20}\b(tutorial|instructions|how to|guide|method)",
    r"how to (commit suicide|kill myself)",
)
_GORE_WORDS = (
    "beheading", "decapitation", "dismember", "gore close-up",
    "graphic gore", "mutilation", "corpse close-up",
)
_INJECTION_PATTERNS = (
    r"ignore (all |your |previous |above )*(instructions|rules|prompt)",
    r"(reveal|show|print|leak)\b.{0,30}\bsystem prompt",
    r"jailbreak", r"developer mode", r"dan mode",
    r"pretend you (are|have no)\b.{0,30}(restrictions|rules|limits)",
)
_EMAIL_RE = re.compile(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", re.I)
_PHONE_RE = re.compile(r"(\+?\d[\d\s-]{7,}\d)")
_URL_RE = re.compile(r"https?://|www\.", re.I)


def _has(words, low: str) -> str:
    for w in words:
        if re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", low):
            return w
    return ""


def check_prompt(text: str) -> dict:
    low = " " + (text or "").lower() + " "
    # CRITICAL: sexual content involving minors — zero tolerance.
    hard = _has(_HARD_PHRASES, low)
    if hard:
        return {"blocked": True, "severity": "critical",
                "rule": "sexual_content_minor:" + hard}
    minor = _has(_MINOR_WORDS, low)
    sexual = _has(_SEXUAL_WORDS, low)
    if minor and sexual:
        return {"blocked": True, "severity": "critical",
                "rule": f"sexual_content_minor:{minor}+{sexual}"}
    # HIGH: explicit sexual content generation.
    if sexual:
        return {"blocked": True, "severity": "high",
                "rule": "explicit_sexual_content:" + sexual}
    # HIGH: wrongdoing instructions / graphic gore.
    for pat in _WRONGDOING_PATTERNS:
        if re.search(pat, low):
            return {"blocked": True, "severity": "high",
                    "rule": "wrongdoing_instructions"}
    gore = _has(_GORE_WORDS, low)
    if gore:
        return {"blocked": True, "severity": "high",
                "rule": "graphic_gore:" + gore}
    # MEDIUM (alert only): prompt-injection attempts on the agent.
    for pat in _INJECTION_PATTERNS:
        if re.search(pat, low):
            return {"blocked": False, "severity": "medium",
                    "rule": "prompt_injection_attempt"}
    # MEDIUM (alert only): personal data pasted into a prompt.
    if _EMAIL_RE.search(text or "") or _PHONE_RE.search(text or ""):
        return {"blocked": False, "severity": "medium",
                "rule": "personal_data_in_prompt"}
    # MEDIUM (alert only): links / spam-shaped prompts.
    if _URL_RE.search(text or ""):
        return {"blocked": False, "severity": "medium",
                "rule": "link_in_prompt"}
    if len(text or "") > 20 and len(set(text)) < 8:
        return {"blocked": False, "severity": "medium",
                "rule": "spam_like_prompt"}
    return {"blocked": False, "severity": "", "rule": ""}


# ---------------------------------------------------------------------------
# Control Room login — the private /control dashboard.
#
# Exactly ONE account can ever enter: the owner's main Gmail (already
# ADMIN_EMAILS) plus a password whose salted PBKDF2-HMAC-SHA256 hash
# lives ONLY in the deployment environment (TOQIX_CONTROL_AUTH,
# format "salt_hex$hash_hex"). The plaintext password is never stored
# anywhere — not in the repo, not in the database. There is no
# registration endpoint: nobody else can sign up, ever. A successful
# login mints a signed cookie (same HMAC machinery as sessions) with
# a "control" scope and a 7-day expiry.
# ---------------------------------------------------------------------------

CONTROL_COOKIE = "toqix_control"
CONTROL_SESSION_SECONDS = 7 * 24 * 3600  # 7 days
_CONTROL_ITERATIONS = 200_000


def control_auth_configured() -> bool:
    raw = os.environ.get("TOQIX_CONTROL_AUTH", "")
    salt_hex, sep, hash_hex = raw.partition("$")
    if not sep or not salt_hex or not hash_hex:
        return False
    try:
        bytes.fromhex(salt_hex)
        bytes.fromhex(hash_hex)
    except ValueError:
        return False
    return True


def control_password_hash(password: str,
                          salt: bytes | None = None) -> str:
    """Build a TOQIX_CONTROL_AUTH value ("salt_hex$hash_hex") for a
    password. Used by the one-time setup and by tests (which pass
    their own throwaway password) — never called at runtime."""
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                             salt, _CONTROL_ITERATIONS)
    return salt.hex() + "$" + dk.hex()


def verify_control_login(email: str, password: str) -> bool:
    """True only for the owner's main email + the password matching
    the TOQIX_CONTROL_AUTH hash. Constant-time digest comparison."""
    if (email or "").strip().lower() not in ADMIN_EMAILS:
        return False
    raw = os.environ.get("TOQIX_CONTROL_AUTH", "")
    salt_hex, sep, hash_hex = raw.partition("$")
    if not sep or not salt_hex or not hash_hex:
        return False
    try:
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"),
                             salt, _CONTROL_ITERATIONS)
    return hmac.compare_digest(dk.hex(), hash_hex)


def make_control_cookie() -> str:
    return _make_token({"scope": "control",
                        "exp": time.time() + CONTROL_SESSION_SECONDS})


def control_cookie_ok(cookie_value: str | None) -> bool:
    data = _read_token(cookie_value)
    return bool(data and data.get("scope") == "control")


init_auth_db()
