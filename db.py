"""
SQLite persistence for projects, verification rules, uploaded datasets and results.
"""
import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
import pandas as pd

DB_PATH = Path(__file__).parent / "verification.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)

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

    conn.commit()
    conn.close()


def create_project(name: str, description: str = "") -> int:
    conn = get_connection()
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    cur.execute(
        "INSERT INTO projects (name, description, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (name, description, now, now)
    )
    project_id = cur.lastrowid

    default_rules = {
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

    cur.execute(
        "INSERT INTO project_rules (project_id, rules_json) VALUES (?, ?)",
        (project_id, json.dumps(default_rules))
    )
    conn.commit()
    conn.close()
    return project_id


def list_projects() -> List[Dict]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM projects ORDER BY created_at DESC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_project(project_id: int) -> Optional[Dict]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_rules(project_id: int) -> Dict:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT rules_json FROM project_rules WHERE project_id = ?", (project_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        return json.loads(row["rules_json"])
    return {}


def save_rules(project_id: int, rules: Dict):
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


def save_dataset(project_id: int, filename: str, df: pd.DataFrame) -> int:
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


def save_run(project_id: int, dataset_id: Optional[int], results: Dict) -> int:
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