"""
Core verification: duplicates, duration, clusters, patterns, demographics, pass/fail.
"""
from typing import List, Dict, Any, Optional, Set
import pandas as pd
import numpy as np
from rapidfuzz import fuzz

try:
    from sklearn.cluster import DBSCAN
except ImportError:
    DBSCAN = None


# ---------------------------------------------------------------------------
# Duplicates
# ---------------------------------------------------------------------------

def find_exact_duplicates(df: pd.DataFrame, key_cols: List[str]) -> Dict[str, Any]:
    if not key_cols or not all(c in df.columns for c in key_cols):
        return {"count": 0, "indexes": [], "rows": []}
    mask = df.duplicated(subset=key_cols, keep=False)
    idxs = df.index[mask].tolist()
    return {
        "count": int(mask.sum()),
        "indexes": idxs,
        "rows": df.loc[mask].head(200).to_dict(orient="records"),
    }


def find_fuzzy_duplicates(
    df: pd.DataFrame,
    text_cols: List[str],
    threshold: int = 90,
    max_pairs: int = 300,
) -> List[Dict]:
    if not text_cols or not all(c in df.columns for c in text_cols):
        return []
    work = df[text_cols].fillna("").astype(str)
    texts = work.agg(" | ".join, axis=1).tolist()
    results = []
    n = len(texts)
    for i in range(n):
        for j in range(i + 1, n):
            score = fuzz.token_sort_ratio(texts[i], texts[j])
            if score >= threshold:
                results.append({
                    "index_a": int(df.index[i]),
                    "index_b": int(df.index[j]),
                    "score": int(score),
                    "text_a": texts[i][:180],
                    "text_b": texts[j][:180],
                })
                if len(results) >= max_pairs:
                    return results
    return results


# ---------------------------------------------------------------------------
# Duration (strict)
# ---------------------------------------------------------------------------

def _parse_time_series(s: pd.Series) -> pd.Series:
    """Parse datetimes, time strings, and Excel serial / fraction-of-day values."""
    parsed = pd.to_datetime(s, errors="coerce")
    numeric = pd.to_numeric(s, errors="coerce")

    # Excel time-only as fraction of day (0 < x < 1)
    frac_mask = parsed.isna() & numeric.notna() & (numeric > 0) & (numeric < 1)
    if frac_mask.any():
        base = pd.Timestamp("1899-12-30")
        parsed.loc[frac_mask] = base + pd.to_timedelta(numeric.loc[frac_mask], unit="D")

    # Excel full serial date-time
    serial_mask = parsed.isna() & numeric.notna() & (numeric >= 1)
    if serial_mask.any():
        parsed.loc[serial_mask] = pd.to_datetime(
            numeric.loc[serial_mask], unit="D", origin="1899-12-30", errors="coerce"
        )
    return parsed


def check_interview_duration(
    df: pd.DataFrame,
    start_col: Optional[str],
    end_col: Optional[str],
    min_minutes: float = 5.0,
    max_minutes: float = 120.0,
) -> Dict[str, Any]:
    """
    duration = end - start (minutes).
    Flags:
      - short: duration < min_minutes
      - long:  duration > max_minutes
      - invalid: missing, unparseable, or negative (these must NOT pass)
    """
    empty = {
        "enabled": False,
        "flagged_short_count": 0,
        "flagged_long_count": 0,
        "flagged_invalid_count": 0,
        "flagged_indexes": [],
        "short_indexes": [],
        "long_indexes": [],
        "invalid_indexes": [],
        "duration_by_index": {},
        "message": "Duration check not configured",
    }

    if not start_col or not end_col:
        return empty
    if start_col not in df.columns or end_col not in df.columns:
        empty["message"] = f"Missing columns: {start_col} / {end_col}"
        return empty

    min_minutes = float(min_minutes)
    max_minutes = float(max_minutes)

    start_ts = _parse_time_series(df[start_col])
    end_ts = _parse_time_series(df[end_col])
    duration_min = (end_ts - start_ts).dt.total_seconds() / 60.0

    short_indexes: List = []
    long_indexes: List = []
    invalid_indexes: List = []
    duration_by_index: Dict[str, Optional[float]] = {}

    for idx in df.index:
        d = duration_min.loc[idx] if idx in duration_min.index else np.nan
        if pd.isna(d):
            duration_by_index[str(idx)] = None
            invalid_indexes.append(idx)
            continue
        d = float(d)
        duration_by_index[str(idx)] = round(d, 2)
        if d < 0:
            invalid_indexes.append(idx)
        elif d < min_minutes:
            short_indexes.append(idx)
        elif d > max_minutes:
            long_indexes.append(idx)

    flagged = list(dict.fromkeys(short_indexes + long_indexes + invalid_indexes))

    return {
        "enabled": True,
        "min_minutes": min_minutes,
        "max_minutes": max_minutes,
        "flagged_short_count": len(short_indexes),
        "flagged_long_count": len(long_indexes),
        "flagged_invalid_count": len(invalid_indexes),
        "flagged_indexes": flagged,
        "short_indexes": short_indexes,
        "long_indexes": long_indexes,
        "invalid_indexes": invalid_indexes,
        "duration_by_index": duration_by_index,
        "message": (
            f"Short (<{min_minutes} min): {len(short_indexes)} | "
            f"Long (>{max_minutes} min): {len(long_indexes)} | "
            f"Invalid times: {len(invalid_indexes)}"
        ),
    }


# ---------------------------------------------------------------------------
# Geographic clusters
# ---------------------------------------------------------------------------

def check_geographic_clusters(
    df: pd.DataFrame,
    lat_col: Optional[str],
    lon_col: Optional[str],
    min_points: int = 5,
    radius_meters: float = 100.0,
    enabled: bool = True,
) -> Dict[str, Any]:
    empty = {
        "enabled": False,
        "flagged_count": 0,
        "flagged_indexes": [],
        "clusters": [],
        "message": "Cluster check not configured",
    }
    if not enabled or not lat_col or not lon_col:
        return empty
    if lat_col not in df.columns or lon_col not in df.columns:
        empty["message"] = "Lat/lon columns missing"
        return empty
    if DBSCAN is None:
        empty["message"] = "scikit-learn not installed"
        return empty

    work = df[[lat_col, lon_col]].copy()
    work[lat_col] = pd.to_numeric(work[lat_col], errors="coerce")
    work[lon_col] = pd.to_numeric(work[lon_col], errors="coerce")
    work = work.dropna()
    if len(work) < min_points:
        return {
            "enabled": True,
            "flagged_count": 0,
            "flagged_indexes": [],
            "clusters": [],
            "message": "Not enough points",
        }

    # approx degrees from meters (latitude)
    eps_deg = float(radius_meters) / 111_320.0
    coords = work[[lat_col, lon_col]].values
    labels = DBSCAN(eps=eps_deg, min_samples=int(min_points), metric="euclidean").fit_predict(coords)

    clusters = []
    flagged: List = []
    for lab in sorted(set(labels)):
        if lab < 0:
            continue
        members = work.index[labels == lab].tolist()
        if len(members) >= min_points:
            clusters.append({"cluster_id": int(lab), "size": len(members), "indexes": members})
            flagged.extend(members)

    flagged = list(dict.fromkeys(flagged))
    return {
        "enabled": True,
        "flagged_count": len(flagged),
        "flagged_indexes": flagged,
        "clusters": clusters,
        "message": f"{len(clusters)} cluster(s), {len(flagged)} points flagged",
    }


# ---------------------------------------------------------------------------
# Agent patterns
# ---------------------------------------------------------------------------

def agent_pattern_analysis(
    df: pd.DataFrame,
    agent_col: Optional[str],
    timestamp_col: Optional[str] = None,
    rules: Optional[Dict] = None,
) -> Dict[str, Any]:
    if not agent_col or agent_col not in df.columns:
        return {"agents": {}, "summary": {"n_flagged": 0, "flagged_agents": []}}

    rules = rules or {}
    min_entropy = float(rules.get("min_entropy", 1.5))
    max_same_pct = float(rules.get("max_same_answer_pct", 0.6))
    short_fill_sec = float(rules.get("flag_short_fill_time_seconds", 30))

    meta = {agent_col}
    if timestamp_col:
        meta.add(timestamp_col)
    answer_cols = [
        c for c in df.columns
        if c not in meta and not pd.api.types.is_numeric_dtype(df[c])
    ][:40]

    agents_out: Dict[str, Any] = {}
    flagged_agents: List[str] = []

    for agent, group in df.groupby(agent_col):
        if group.empty:
            continue
        agent_key = str(agent)
        flags: List[str] = []
        info: Dict[str, Any] = {"n_records": len(group), "flags": flags}

        for col in answer_cols:
            vc = group[col].dropna().astype(str)
            if len(vc) < 2:
                continue
            counts = vc.value_counts(normalize=True)
            if len(counts) == 0:
                continue
            mode_pct = float(counts.iloc[0])
            if mode_pct >= max_same_pct:
                flags.append(f"High same-answer on '{col}' ({mode_pct:.0%})")
            probs = counts.values
            ent = float(-np.sum(probs * np.log2(probs + 1e-12)))
            if ent < min_entropy and len(counts) > 1:
                flags.append(f"Low entropy on '{col}' ({ent:.2f})")

        if timestamp_col and timestamp_col in group.columns and len(group) >= 2:
            ts = pd.to_datetime(group[timestamp_col], errors="coerce").dropna().sort_values()
            if len(ts) >= 2:
                deltas = ts.diff().dt.total_seconds().dropna()
                if not deltas.empty and float(deltas.min()) < short_fill_sec:
                    flags.append(f"Very short fill interval ({float(deltas.min()):.0f}s)")

        info["flags"] = flags
        agents_out[agent_key] = info
        if flags:
            flagged_agents.append(agent_key)

    return {
        "agents": agents_out,
        "summary": {"n_flagged": len(flagged_agents), "flagged_agents": flagged_agents},
    }


# ---------------------------------------------------------------------------
# Demographics (counts by state)
# ---------------------------------------------------------------------------

def check_demographics_by_state(
    df: pd.DataFrame,
    state_col: Optional[str],
    gender_col: Optional[str],
    age_col: Optional[str],
    targets_by_state: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    targets_by_state example:
    {
      "Lagos": {"gender": {"Male": 100, "Female": 100}, "age": {"18-24": 50}},
      ...
    }
    Returns actual count tables; flags states that miss targets (under target).
    """
    result: Dict[str, Any] = {
        "gender_table": [],
        "age_table": [],
        "flags": [],
    }
    targets_by_state = targets_by_state or {}

    if state_col and state_col in df.columns and gender_col and gender_col in df.columns:
        g = (
            df.groupby([state_col, gender_col])
            .size()
            .unstack(fill_value=0)
        )
        g = g.reset_index()
        # normalize column names
        rename = {state_col: "state"}
        g = g.rename(columns=rename)
        result["gender_table"] = g.to_dict(orient="records")

        for state, tgt in targets_by_state.items():
            g_tgt = (tgt or {}).get("gender") or {}
            row = g[g["state"].astype(str) == str(state)]
            if row.empty:
                continue
            for sex, need in g_tgt.items():
                if sex in row.columns and int(row.iloc[0][sex]) < int(need):
                    result["flags"].append(
                        f"{state}: {sex} count {int(row.iloc[0][sex])} < target {int(need)}"
                    )

    if state_col and state_col in df.columns and age_col and age_col in df.columns:
        a = (
            df.groupby([state_col, age_col])
            .size()
            .unstack(fill_value=0)
        )
        a = a.reset_index().rename(columns={state_col: "state"})
        result["age_table"] = a.to_dict(orient="records")

        for state, tgt in targets_by_state.items():
            a_tgt = (tgt or {}).get("age") or {}
            row = a[a["state"].astype(str) == str(state)]
            if row.empty:
                continue
            for age_val, need in a_tgt.items():
                if age_val in row.columns and int(row.iloc[0][age_val]) < int(need):
                    result["flags"].append(
                        f"{state}: age {age_val} count {int(row.iloc[0][age_val])} < target {int(need)}"
                    )

    return result


# ---------------------------------------------------------------------------
# Full run + pass/fail table
# ---------------------------------------------------------------------------

def run_full_verification(df: pd.DataFrame, rules: Dict) -> Dict[str, Any]:
    rules = rules or {}
    report: Dict[str, Any] = {
        "n_rows": len(df),
        "n_cols": len(df.columns),
    }

    # --- duplicates ---
    key_cols = [c for c in rules.get("duplicate_keys", []) if c in df.columns]
    exact = find_exact_duplicates(df, key_cols)
    report["duplicates"] = {"exact": exact}

    text_candidates = key_cols[:3] if key_cols else [
        c for c in df.columns if df[c].dtype == object
    ][:3]
    fuzzy = find_fuzzy_duplicates(
        df, text_candidates, threshold=int(rules.get("fuzzy_threshold", 90))
    )
    report["duplicates"]["fuzzy"] = fuzzy
    fuzzy_indexes: Set = set()
    for pair in fuzzy:
        fuzzy_indexes.add(pair["index_a"])
        fuzzy_indexes.add(pair["index_b"])

    # --- duration (strict) ---
    duration_check = check_interview_duration(
        df,
        start_col=rules.get("start_time_col"),
        end_col=rules.get("end_time_col"),
        min_minutes=float(rules.get("min_duration_minutes", 5)),
        max_minutes=float(rules.get("max_duration_minutes", 120)),
    )
    report["duration_check"] = duration_check

    # --- clusters ---
    cluster_check = check_geographic_clusters(
        df,
        lat_col=rules.get("lat_col"),
        lon_col=rules.get("lon_col"),
        min_points=int(rules.get("cluster_min_points", 5)),
        radius_meters=float(rules.get("cluster_radius_meters", 100)),
        enabled=bool(rules.get("cluster_enabled", True)),
    )
    report["cluster_check"] = cluster_check

    # --- agent patterns ---
    agent_col = rules.get("agent_col")
    patterns = agent_pattern_analysis(
        df,
        agent_col=agent_col,
        timestamp_col=rules.get("timestamp_col"),
        rules=rules.get("pattern_checks") or {},
    )
    report["patterns"] = patterns
    flagged_agent_names = set(patterns.get("summary", {}).get("flagged_agents") or [])

    # --- demographics ---
    demo = check_demographics_by_state(
        df,
        state_col=rules.get("state_col"),
        gender_col=rules.get("gender_col"),
        age_col=rules.get("age_col"),
        targets_by_state=rules.get("demographic_by_state") or {},
    )
    report["demographics"] = demo

    # --- build failed index set ---
    failed: Set = set()
    failed.update(exact.get("indexes") or [])
    failed.update(fuzzy_indexes)
    failed.update(duration_check.get("flagged_indexes") or [])
    failed.update(cluster_check.get("flagged_indexes") or [])

    # agent-level: flag all rows for flagged agents
    if agent_col and agent_col in df.columns and flagged_agent_names:
        for idx, val in df[agent_col].items():
            if str(val) in flagged_agent_names:
                failed.add(idx)

    report["failed_indexes"] = list(failed)

    # --- pass/fail table (original data + Status + Failure_Reason) ---
    short_set = set(duration_check.get("short_indexes") or [])
    long_set = set(duration_check.get("long_indexes") or [])
    invalid_time_set = set(duration_check.get("invalid_indexes") or [])
    cluster_set = set(cluster_check.get("flagged_indexes") or [])
    exact_set = set(exact.get("indexes") or [])
    min_m = duration_check.get("min_minutes", rules.get("min_duration_minutes", 5))
    max_m = duration_check.get("max_minutes", rules.get("max_duration_minutes", 120))
    dur_map = duration_check.get("duration_by_index") or {}

    statuses = []
    reasons = []
    for idx in df.index:
        why: List[str] = []
        if idx in exact_set:
            why.append("Exact duplicate")
        if idx in fuzzy_indexes:
            why.append("Fuzzy duplicate")
        if idx in short_set:
            d = dur_map.get(str(idx))
            why.append(f"Short interview ({d} min < {min_m} min)")
        if idx in long_set:
            d = dur_map.get(str(idx))
            why.append(f"Long interview ({d} min > {max_m} min)")
        if idx in invalid_time_set:
            why.append("Invalid or missing start/end time")
        if idx in cluster_set:
            why.append("Geographic cluster")
        if agent_col and agent_col in df.columns:
            if str(df.at[idx, agent_col]) in flagged_agent_names:
                why.append("Agent pattern flag")

        if why:
            statuses.append("FAIL")
            reasons.append("; ".join(why))
        else:
            statuses.append("PASS")
            reasons.append("")

    out = df.copy()
    out.insert(0, "Status", statuses)
    out.insert(1, "Failure_Reason", reasons)
    report["pass_fail_table"] = out

    return report