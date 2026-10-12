"""
SQLite database: users, owner-scoped projects, rules, datasets, runs.
"""
import sqlite3
import json
import secrets
import string
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
import pandas as pd

try:
    import bcrypt
except ImportError:
    bcrypt = None

DB_PATH = Path(__file__).parent / "verification.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()

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
            updated_at TEXT,
            FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE SET NULL
        )
    """)

    # Migration for older DBs
    cur.execute("PRAGMA table_info(projects)")
    cols = {row[1] for row in cur.fetchall()}
    if "owner_id" not in cols:
        try:
            cur.execute("ALTER TABLE projects ADD COLUMN owner_id INTEGER")
        except sqlite3.OperationalError:
            pass

    cur.execute("""
        CREATE TABLE IF NOT EXISTS project_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            rules_json TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS datasets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            filename TEXT,
            uploaded_at TEXT,
            row_count INTEGER,
            columns_json TEXT,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS verification_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            dataset_id INTEGER,
            run_at TEXT,
            results_json TEXT,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (dataset_id) REFERENCES datasets(id) ON DELETE SET NULL
        )
    """)

    try:
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_owner_name ON projects(owner_id, name)"
        )
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()


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
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
    if cur.fetchone():
        conn.close()
        return
    now = datetime.utcnow().isoformat()
    cur.execute(
        """INSERT INTO users
           (username, email, name, phone, password_hash, role, must_change_password, is_active, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, 'admin', 0, 1, ?, ?)""",
        (username, email, name, "", _hash_password(password), now, now)
    )
    conn.commit()
    conn.close()


def authenticate_user(username: str, password: str) -> Optional[Dict]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM users WHERE username = ? AND is_active = 1",
        (username.strip(),)
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    user = dict(row)
    if not verify_password(password, user["password_hash"]):
        return None
    return user


def get_user_by_id(user_id: int) -> Optional[Dict]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def list_users() -> List[Dict]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT id, username, email, name, phone, role, must_change_password, is_active, created_at
           FROM users ORDER BY created_at DESC"""
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


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
    now = datetime.utcnow().isoformat()
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """INSERT INTO users
               (username, email, name, phone, password_hash, role, must_change_password, is_active, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 1, 1, ?, ?)""",
            (username, email, name, phone, _hash_password(default_password), role, now, now)
        )
        uid = cur.lastrowid
        conn.commit()
        return {"ok": True, "default_password": default_password, "user_id": uid, "error": None}
    except sqlite3.IntegrityError:
        return {"ok": False, "error": "Username or email already exists.", "default_password": None}
    finally:
        conn.close()


def change_password(user_id: int, new_password: str) -> Dict[str, Any]:
    if len(new_password) < 8:
        return {"ok": False, "error": "Password must be at least 8 characters."}
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """UPDATE users SET password_hash = ?, must_change_password = 0, updated_at = ?
           WHERE id = ?""",
        (_hash_password(new_password), datetime.utcnow().isoformat(), user_id)
    )
    conn.commit()
    conn.close()
    return {"ok": True, "error": None}


def set_user_active(user_id: int, active: bool) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET is_active = ?, updated_at = ? WHERE id = ?",
        (1 if active else 0, datetime.utcnow().isoformat(), user_id)
    )
    conn.commit()
    conn.close()


def user_can_access_project(project_id: int, user: Dict) -> bool:
    if not user:
        return False
    if user.get("role") == "admin":
        return True
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT owner_id FROM projects WHERE id = ?", (project_id,))
    row = cur.fetchone()
    conn.close()
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
    conn = get_connection()
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    cur.execute(
        """INSERT INTO projects (name, description, owner_id, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?)""",
        (name, description, owner_id, now, now)
    )
    project_id = cur.lastrowid
    cur.execute(
        "INSERT INTO project_rules (project_id, rules_json) VALUES (?, ?)",
        (project_id, json.dumps(_default_rules()))
    )
    conn.commit()
    conn.close()
    return project_id


def list_projects(user: Optional[Dict] = None) -> List[Dict]:
    if user is None:
        return []
    conn = get_connection()
    cur = conn.cursor()
    if user.get("role") == "admin":
        cur.execute("""
            SELECT p.*, u.username AS owner_username
            FROM projects p
            LEFT JOIN users u ON p.owner_id = u.id
            ORDER BY p.created_at DESC
        """)
    else:
        cur.execute("""
            SELECT p.*, u.username AS owner_username
            FROM projects p
            LEFT JOIN users u ON p.owner_id = u.id
            WHERE p.owner_id = ?
            ORDER BY p.created_at DESC
        """, (user["id"],))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_project(project_id: int, user: Optional[Dict] = None) -> Optional[Dict]:
    if user is not None and not user_can_access_project(project_id, user):
        return None
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_rules(project_id: int, user: Optional[Dict] = None) -> Dict:
    if user is not None and not user_can_access_project(project_id, user):
        return {}
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT rules_json FROM project_rules WHERE project_id = ?", (project_id,))
    row = cur.fetchone()
    conn.close()
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
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE project_rules SET rules_json = ? WHERE project_id = ?",
        (json.dumps(rules), project_id)
    )
    cur.execute(
        "UPDATE projects SET updated_at = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), project_id)
    )
    conn.commit()
    conn.close()
    return True


def save_dataset(project_id: int, filename: str, df: pd.DataFrame, user: Optional[Dict] = None) -> Optional[int]:
    if user is not None and not user_can_access_project(project_id, user):
        return None
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO datasets (project_id, filename, uploaded_at, row_count, columns_json)
           VALUES (?, ?, ?, ?, ?)""",
        (project_id, filename, datetime.utcnow().isoformat(), len(df), json.dumps(list(df.columns)))
    )
    dataset_id = cur.lastrowid
    conn.commit()
    conn.close()
    return dataset_id


def save_run(project_id: int, dataset_id: Optional[int], results: Dict, user: Optional[Dict] = None) -> Optional[int]:
    if user is not None and not user_can_access_project(project_id, user):
        return None
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO verification_runs (project_id, dataset_id, run_at, results_json)
           VALUES (?, ?, ?, ?)""",
        (project_id, dataset_id, datetime.utcnow().isoformat(), json.dumps(results, default=str))
    )
    run_id = cur.lastrowid
    conn.commit()
    conn.close()
    return run_id


init_db()