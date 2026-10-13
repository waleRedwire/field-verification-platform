"""
Database layer: PostgreSQL (preferred via DATABASE_URL) or SQLite fallback.
Projects are owner-scoped; rules persist per project.
"""
import os
import json
import secrets
import string
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import contextmanager
import pandas as pd

try:
    import bcrypt
except ImportError:
    bcrypt = None

try:
    import streamlit as st
    HAS_STREAMLIT = True
except ImportError:
    HAS_STREAMLIT = False


def _get_database_url() -> Optional[str]:
    if HAS_STREAMLIT:
        try:
            url = st.secrets.get("DATABASE_URL")
            if url:
                return str(url).strip()
        except Exception:
            pass
    return os.environ.get("DATABASE_URL")


def _use_postgres() -> bool:
    return bool(_get_database_url())


@contextmanager
def get_connection():
    url = _get_database_url()
    if url:
        import psycopg2
        conn = psycopg2.connect(url)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        import sqlite3
        path = Path(__file__).parent / "verification.db"
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _dict_cursor(conn):
    if _use_postgres():
        import psycopg2.extras
        return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    return conn.cursor()


def _placeholder() -> str:
    return "%s" if _use_postgres() else "?"


def _now() -> str:
    return datetime.utcnow().isoformat()


def init_db():
    with get_connection() as conn:
        cur = conn.cursor()
        if _use_postgres():
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    phone TEXT,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    must_change_password INTEGER NOT NULL DEFAULT 1,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS projects (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    owner_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS project_rules (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    rules_json TEXT NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS datasets (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    filename TEXT,
                    uploaded_at TEXT,
                    row_count INTEGER,
                    columns_json TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS verification_runs (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    dataset_id INTEGER REFERENCES datasets(id) ON DELETE SET NULL,
                    run_at TEXT,
                    results_json TEXT
                )
            """)
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_owner_name
                ON projects(owner_id, name)
            """)
        else:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    phone TEXT,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    must_change_password INTEGER NOT NULL DEFAULT 1,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    owner_id INTEGER,
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS project_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    rules_json TEXT NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS datasets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    filename TEXT,
                    uploaded_at TEXT,
                    row_count INTEGER,
                    columns_json TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS verification_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    dataset_id INTEGER,
                    run_at TEXT,
                    results_json TEXT
                )
            """)
            try:
                cur.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_owner_name ON projects(owner_id, name)"
                )
            except Exception:
                pass


def _hash_password(plain: str) -> str:
    if bcrypt is None:
        raise RuntimeError("bcrypt is not installed. Run: pip install bcrypt")
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, password_hash: str) -> bool:
    if bcrypt is None:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False


def generate_random_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.islower() for c in pwd)
                and any(c.isupper() for c in pwd)
                and any(c.isdigit() for c in pwd)):
            return pwd


def ensure_admin_user(username: str, email: str, name: str, password: str) -> None:
    ph = _placeholder()
    with get_connection() as conn:
        cur = _dict_cursor(conn)
        cur.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
        if cur.fetchone():
            return
        cur.execute(
            f"""INSERT INTO users
               (username, email, name, phone, password_hash, role, must_change_password, is_active, created_at, updated_at)
               VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, 'admin', 0, 1, {ph}, {ph})""",
            (username, email, name, "", _hash_password(password), _now(), _now())
        )


def authenticate_user(username: str, password: str) -> Optional[Dict]:
    ph = _placeholder()
    with get_connection() as conn:
        cur = _dict_cursor(conn)
        cur.execute(
            f"SELECT * FROM users WHERE username = {ph} AND is_active = 1",
            (username.strip(),)
        )
        row = cur.fetchone()
    if not row:
        return None
    user = dict(row)
    if not verify_password(password, user["password_hash"]):
        return None
    return user


def get_user_by_id(user_id: int) -> Optional[Dict]:
    ph = _placeholder()
    with get_connection() as conn:
        cur = _dict_cursor(conn)
        cur.execute(f"SELECT * FROM users WHERE id = {ph}", (user_id,))
        row = cur.fetchone()
    return dict(row) if row else None


def list_users() -> List[Dict]:
    with get_connection() as conn:
        cur = _dict_cursor(conn)
        cur.execute(
            """SELECT id, username, email, name, phone, role, must_change_password, is_active, created_at
               FROM users ORDER BY created_at DESC"""
        )
        return [dict(r) for r in cur.fetchall()]


def create_user(
    username: str,
    email: str,
    name: str,
    phone: str = "",
    role: str = "user"
) -> Dict[str, Any]:
    username = username.strip().lower()
    email = email.strip().lower()
    name = name.strip()
    phone = (phone or "").strip()
    if not username or not email or not name:
        return {"ok": False, "error": "Username, email and name are required.", "default_password": None}

    default_password = generate_random_password(12)
    ph = _placeholder()
    try:
        with get_connection() as conn:
            cur = _dict_cursor(conn)
            if _use_postgres():
                cur.execute(
                    f"""INSERT INTO users
                       (username, email, name, phone, password_hash, role, must_change_password, is_active, created_at, updated_at)
                       VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, 1, 1, {ph}, {ph})
                       RETURNING id""",
                    (username, email, name, phone, _hash_password(default_password), role, _now(), _now())
                )
                uid = cur.fetchone()["id"]
            else:
                cur.execute(
                    f"""INSERT INTO users
                       (username, email, name, phone, password_hash, role, must_change_password, is_active, created_at, updated_at)
                       VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, 1, 1, {ph}, {ph})""",
                    (username, email, name, phone, _hash_password(default_password), role, _now(), _now())
                )
                uid = cur.lastrowid
        return {"ok": True, "default_password": default_password, "user_id": uid, "error": None}
    except Exception as e:
        msg = str(e).lower()
        if "unique" in msg or "duplicate" in msg:
            return {"ok": False, "error": "Username or email already exists.", "default_password": None}
        return {"ok": False, "error": "Could not create user.", "default_password": None}


def change_password(user_id: int, new_password: str) -> Dict[str, Any]:
    if len(new_password) < 8:
        return {"ok": False, "error": "Password must be at least 8 characters."}
    ph = _placeholder()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""UPDATE users SET password_hash = {ph}, must_change_password = 0, updated_at = {ph}
               WHERE id = {ph}""",
            (_hash_password(new_password), _now(), user_id)
        )
    return {"ok": True, "error": None}


def set_user_active(user_id: int, active: bool) -> None:
    ph = _placeholder()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE users SET is_active = {ph}, updated_at = {ph} WHERE id = {ph}",
            (1 if active else 0, _now(), user_id)
        )


def user_can_access_project(project_id: int, user: Dict) -> bool:
    if not user:
        return False
    if user.get("role") == "admin":
        return True
    ph = _placeholder()
    with get_connection() as conn:
        cur = _dict_cursor(conn)
        cur.execute(f"SELECT owner_id FROM projects WHERE id = {ph}", (project_id,))
        row = cur.fetchone()
    if not row:
        return False
    return row["owner_id"] == user["id"]


def _default_rules() -> Dict:
    return {
        "duplicate_keys": [],
        "fuzzy_threshold": 90,
        "gender_col": None,
        "age_col": None,
        "demographic_targets": {"gender": {}, "age": {}},
        "demographic_by_state": {},
        "pattern_checks": {
            "min_entropy": 1.5,
            "max_same_answer_pct": 0.6,
            "flag_short_fill_time_seconds": 30
        },
        "lat_col": None,
        "lon_col": None,
        "agent_col": None,
        "audio_col": None,
        "submission_date_col": None,
        "timestamp_col": None,
        "state_col": None,
        "start_time_col": None,
        "end_time_col": None,
        "min_duration_minutes": 5,
        "max_duration_minutes": 120,
        "cluster_enabled": True,
        "cluster_min_points": 5,
        "cluster_radius_meters": 100,
    }


def create_project(name: str, description: str = "", owner_id: Optional[int] = None) -> int:
    ph = _placeholder()
    with get_connection() as conn:
        cur = _dict_cursor(conn)
        if _use_postgres():
            cur.execute(
                f"""INSERT INTO projects (name, description, owner_id, created_at, updated_at)
                   VALUES ({ph}, {ph}, {ph}, {ph}, {ph}) RETURNING id""",
                (name, description, owner_id, _now(), _now())
            )
            project_id = cur.fetchone()["id"]
        else:
            cur.execute(
                f"""INSERT INTO projects (name, description, owner_id, created_at, updated_at)
                   VALUES ({ph}, {ph}, {ph}, {ph}, {ph})""",
                (name, description, owner_id, _now(), _now())
            )
            project_id = cur.lastrowid
        cur.execute(
            f"INSERT INTO project_rules (project_id, rules_json) VALUES ({ph}, {ph})",
            (project_id, json.dumps(_default_rules()))
        )
    return project_id


def list_projects(user: Optional[Dict] = None) -> List[Dict]:
    if user is None:
        return []
    ph = _placeholder()
    with get_connection() as conn:
        cur = _dict_cursor(conn)
        if user.get("role") == "admin":
            cur.execute("""
                SELECT p.*, u.username AS owner_username
                FROM projects p
                LEFT JOIN users u ON p.owner_id = u.id
                ORDER BY p.created_at DESC
            """)
        else:
            cur.execute(
                f"""
                SELECT p.*, u.username AS owner_username
                FROM projects p
                LEFT JOIN users u ON p.owner_id = u.id
                WHERE p.owner_id = {ph}
                ORDER BY p.created_at DESC
                """,
                (user["id"],)
            )
        return [dict(r) for r in cur.fetchall()]


def get_project(project_id: int, user: Optional[Dict] = None) -> Optional[Dict]:
    if user is not None and not user_can_access_project(project_id, user):
        return None
    ph = _placeholder()
    with get_connection() as conn:
        cur = _dict_cursor(conn)
        cur.execute(f"SELECT * FROM projects WHERE id = {ph}", (project_id,))
        row = cur.fetchone()
    return dict(row) if row else None


def get_rules(project_id: int, user: Optional[Dict] = None) -> Dict:
    if user is not None and not user_can_access_project(project_id, user):
        return {}
    ph = _placeholder()
    with get_connection() as conn:
        cur = _dict_cursor(conn)
        cur.execute(f"SELECT rules_json FROM project_rules WHERE project_id = {ph}", (project_id,))
        row = cur.fetchone()
    if row:
        rules = json.loads(row["rules_json"])
        rules.setdefault("audio_col", None)
        rules.setdefault("submission_date_col", None)
        rules.setdefault("demographic_by_state", {})
        return rules
    return {}


def save_rules(project_id: int, rules: Dict, user: Optional[Dict] = None) -> bool:
    if user is not None and not user_can_access_project(project_id, user):
        return False
    ph = _placeholder()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE project_rules SET rules_json = {ph} WHERE project_id = {ph}",
            (json.dumps(rules), project_id)
        )
        cur.execute(
            f"UPDATE projects SET updated_at = {ph} WHERE id = {ph}",
            (_now(), project_id)
        )
    return True


def save_dataset(project_id: int, filename: str, df: pd.DataFrame, user: Optional[Dict] = None) -> Optional[int]:
    if user is not None and not user_can_access_project(project_id, user):
        return None
    ph = _placeholder()
    with get_connection() as conn:
        cur = _dict_cursor(conn)
        if _use_postgres():
            cur.execute(
                f"""INSERT INTO datasets (project_id, filename, uploaded_at, row_count, columns_json)
                   VALUES ({ph}, {ph}, {ph}, {ph}, {ph}) RETURNING id""",
                (project_id, filename, _now(), len(df), json.dumps(list(df.columns)))
            )
            return cur.fetchone()["id"]
        cur.execute(
            f"""INSERT INTO datasets (project_id, filename, uploaded_at, row_count, columns_json)
               VALUES ({ph}, {ph}, {ph}, {ph}, {ph})""",
            (project_id, filename, _now(), len(df), json.dumps(list(df.columns)))
        )
        return cur.lastrowid


def save_run(project_id: int, dataset_id: Optional[int], results: Dict, user: Optional[Dict] = None) -> Optional[int]:
    if user is not None and not user_can_access_project(project_id, user):
        return None
    ph = _placeholder()
    with get_connection() as conn:
        cur = _dict_cursor(conn)
        if _use_postgres():
            cur.execute(
                f"""INSERT INTO verification_runs (project_id, dataset_id, run_at, results_json)
                   VALUES ({ph}, {ph}, {ph}, {ph}) RETURNING id""",
                (project_id, dataset_id, _now(), json.dumps(results, default=str))
            )
            return cur.fetchone()["id"]
        cur.execute(
            f"""INSERT INTO verification_runs (project_id, dataset_id, run_at, results_json)
               VALUES ({ph}, {ph}, {ph}, {ph})""",
            (project_id, dataset_id, _now(), json.dumps(results, default=str))
        )
        return cur.lastrowid


try:
    init_db()
except Exception as e:
    print(f"DB init note: {e}")