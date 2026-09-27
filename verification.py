"""
Core verification logic
"""
from typing import List, Dict, Any, Optional
import pandas as pd
import numpy as np
from rapidfuzz import fuzz
from sklearn.ensemble import IsolationForest
from sklearn.cluster import DBSCAN


def find_exact_duplicates(df: pd.DataFrame, key_cols: List[str]) -> pd.DataFrame:
    if not key_cols or not all(c in df.columns for c in key_cols):
        return pd.DataFrame()
    dup_mask = df.duplicated(subset=key_cols, keep=False)
    return df.loc[dup_mask].sort_values(by=key_cols)


def find_fuzzy_duplicates(df: pd.DataFrame, text_cols: List[str], threshold: int = 90, max_pairs: int = 500) -> List[Dict]:
    if not text_cols or not all(c in df.columns for c in text_cols):
        return []

    texts = (
        df[text_cols]
        .fillna("")
        .astype(str)
        .agg(lambda row: " | ".join(row.values), axis=1)
        .tolist()
    )

    results = []
    n = len(texts)
    for i in range(n):
        for j in range(i + 1, n):
            score = fuzz.token_sort_ratio(texts[i], texts[j])
            if score >= threshold:
                results.append({
                    "index_a": int(df.index[i]),
                    "index_b": int(df.index[j]),
                    "score": score,
                    "text_a": texts[i][:200],
                    "text_b": texts[j][:200]
                })
                if len(results) >= max_pairs:
                    return results
    return results


def check_demographic_distribution_counts(
    df: pd.DataFrame,
    gender_col: Optional[str],
    age_col: Optional[str],
    state_col: Optional[str] = None,
    demographic_by_state: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Per-state demographic targets.
    """
    report = {
        "gender_table": None,
        "age_table": None,
        "per_state": {}
    }

    demographic_by_state = demographic_by_state or {}

    def _counts(data: pd.DataFrame, col: str) -> Dict[str, int]:
        if col not in data.columns:
            return {}
        return {str(k): int(v) for k, v in data[col].value_counts().items()}

    # Gender table
    if gender_col and gender_col in df.columns and state_col and state_col in df.columns:
        rows = []
        for state, group in df.groupby(state_col):
            state = str(state)
            counts = _counts(group, gender_col)
            state_targets = demographic_by_state.get(state, {}).get("gender", {})

            row = {"State": state}
            all_cats = sorted(set(list(counts.keys()) + list(state_targets.keys()) + ["Male", "Female"]))
            for cat in all_cats:
                row[cat] = counts.get(cat, 0)
                row[f"{cat}_Target"] = state_targets.get(cat, "")
            rows.append(row)

            report["per_state"][state] = report["per_state"].get(state, {})
            report["per_state"][state]["gender"] = {
                "actual": counts,
                "target": state_targets
            }

        report["gender_table"] = rows

    # Age table
    if age_col and age_col in df.columns and state_col and state_col in df.columns:
        rows = []
        for state, group in df.groupby(state_col):
            state = str(state)
            counts = _counts(group, age_col)
            state_targets = demographic_by_state.get(state, {}).get("age", {})

            row = {"State": state}
            all_cats = sorted(set(list(counts.keys()) + list(state_targets.keys())))
            for cat in all_cats:
                row[cat] = counts.get(cat, 0)
                row[f"{cat}_Target"] = state_targets.get(cat, "")
            rows.append(row)

            report["per_state"][state] = report["per_state"].get(state, {})
            report["per_state"][state]["age"] = {
                "actual": counts,
                "target": state_targets
            }

        report["age_table"] = rows

    return report


def agent_pattern_analysis(df: pd.DataFrame, agent_col: str, answer_cols: Optional[List[str]] = None,
                           timestamp_col: Optional[str] = None, rules: Optional[Dict] = None) -> Dict[str, Any]:
    if agent_col not in df.columns:
        return {"error": f"Agent column '{agent_col}' not found"}

    rules = rules or {}
    min_entropy = rules.get("min_entropy", 1.5)
    max_same_pct = rules.get("max_same_answer_pct", 0.6)
    short_fill_sec = rules.get("flag_short_fill_time_seconds", 30)

    if answer_cols is None:
        meta = {agent_col}
        if timestamp_col:
            meta.add(timestamp_col)
        answer_cols = [c for c in df.columns if c not in meta and df[c].dtype == object]

    results = {"agents": {}, "summary": {}}

    for agent, group in df.groupby(agent_col):
        agent_info = {"n_records": len(group), "flags": []}

        # ----- Entropy -----
        entropies = {}
        for col in answer_cols:
            if col not in group.columns:
                continue
            series = group[col].dropna()
            if len(series) == 0:
                continue
            counts = series.value_counts(normalize=True)
            if len(counts) == 0:
                continue
            ent = -np.sum(counts * np.log2(counts + 1e-12))
            entropies[col] = round(float(ent), 3)
            if ent < min_entropy and len(counts) > 1:
                agent_info["flags"].append(f"Low entropy on '{col}' ({ent:.2f})")

        agent_info["mean_entropy"] = round(float(np.mean(list(entropies.values()))) if entropies else 0, 3)
        agent_info["entropies"] = entropies

        # ----- Same-answer dominance (SAFE) -----
        same_pcts = {}
        for col in answer_cols:
            if col not in group.columns:
                continue
            series = group[col].dropna()
            if len(series) == 0:
                continue
            counts = series.value_counts(normalize=True)
            if len(counts) == 0:
                continue
            mode_pct = float(counts.iloc[0])
            same_pcts[col] = round(mode_pct, 3)
            if mode_pct > max_same_pct:
                agent_info["flags"].append(f"High same-answer rate on '{col}' ({mode_pct:.0%})")

        agent_info["max_same_answer_pct"] = max(same_pcts.values()) if same_pcts else 0

        # ----- Fill-time check -----
        if timestamp_col and timestamp_col in group.columns:
            try:
                ts = pd.to_datetime(group[timestamp_col], errors="coerce").sort_values()
                diffs = ts.diff().dt.total_seconds().dropna()
                if len(diffs) > 0:
                    median_fill = float(diffs.median())
                    agent_info["median_seconds_between_records"] = round(median_fill, 1)
                    if median_fill < short_fill_sec:
                        agent_info["flags"].append(f"Very short median interval ({median_fill:.0f}s)")
            except Exception:
                pass

        results["agents"][str(agent)] = agent_info

    # Isolation Forest (optional)
    if len(answer_cols) >= 2 and len(df) > 30:
        try:
            sample_cols = answer_cols[:5]
            encoded = pd.get_dummies(df[sample_cols].astype(str))
            iso = IsolationForest(contamination=0.1, random_state=42)
            scores = iso.fit_predict(encoded)
            anomaly_idx = df.index[scores == -1].tolist()
            results["summary"]["anomaly_record_indices"] = anomaly_idx[:100]
            results["summary"]["n_anomalies"] = int((scores == -1).sum())
        except Exception as e:
            results["summary"]["anomaly_error"] = str(e)

    flagged = [a for a, info in results["agents"].items() if info["flags"]]
    results["summary"]["flagged_agents"] = flagged
    results["summary"]["n_flagged"] = len(flagged)
    return results


def check_interview_duration(df: pd.DataFrame, start_col: str, end_col: str,
                             min_duration_minutes: float = 5.0, max_duration_minutes: float = 120.0) -> Dict[str, Any]:
    if start_col not in df.columns or end_col not in df.columns:
        return {"error": f"Columns '{start_col}' or '{end_col}' not found"}

    result = {
        "min_duration_minutes": min_duration_minutes,
        "max_duration_minutes": max_duration_minutes,
        "total_records": len(df),
        "flagged_short_count": 0,
        "flagged_long_count": 0,
        "flagged_short_records": [],
        "flagged_long_records": [],
        "flagged_short_indexes": [],
        "flagged_long_indexes": [],
        "duration_stats": {}
    }

    try:
        start = pd.to_datetime(df[start_col], errors="coerce")
        end = pd.to_datetime(df[end_col], errors="coerce")
        duration_min = (end - start).dt.total_seconds() / 60

        valid = duration_min.dropna()
        if len(valid) > 0:
            result["duration_stats"] = {
                "mean_minutes": round(float(valid.mean()), 2),
                "median_minutes": round(float(valid.median()), 2),
                "min_minutes": round(float(valid.min()), 2),
                "max_minutes": round(float(valid.max()), 2)
            }

        short_mask = (duration_min < min_duration_minutes) & duration_min.notna()
        short_df = df.loc[short_mask].copy()
        short_df["calculated_duration_minutes"] = duration_min[short_mask].round(2)
        result["flagged_short_count"] = int(short_mask.sum())
        result["flagged_short_records"] = short_df.head(200).to_dict(orient="records")
        result["flagged_short_indexes"] = df.index[short_mask].tolist()

        long_mask = (duration_min > max_duration_minutes) & duration_min.notna()
        long_df = df.loc[long_mask].copy()
        long_df["calculated_duration_minutes"] = duration_min[long_mask].round(2)
        result["flagged_long_count"] = int(long_mask.sum())
        result["flagged_long_records"] = long_df.head(200).to_dict(orient="records")
        result["flagged_long_indexes"] = df.index[long_mask].tolist()
    except Exception as e:
        result["error"] = str(e)

    return result


def check_geographic_clusters(df: pd.DataFrame, lat_col: str, lon_col: str,
                              min_points: int = 5, radius_meters: float = 100.0) -> Dict[str, Any]:
    result = {
        "min_points": min_points,
        "radius_meters": radius_meters,
        "total_records": len(df),
        "n_clusters": 0,
        "flagged_count": 0,
        "flagged_indexes": [],
        "flagged_records": [],
        "cluster_summary": [],
        "clusters_detail": []
    }

    if lat_col not in df.columns or lon_col not in df.columns:
        result["error"] = "Latitude/Longitude columns not found"
        return result

    try:
        coords = df[[lat_col, lon_col]].copy()
        coords[lat_col] = pd.to_numeric(coords[lat_col], errors="coerce")
        coords[lon_col] = pd.to_numeric(coords[lon_col], errors="coerce")
        valid_mask = coords[lat_col].notna() & coords[lon_col].notna()
        valid_df = df.loc[valid_mask].copy()
        coords = coords.loc[valid_mask]

        if len(coords) < min_points:
            return result

        eps_degrees = radius_meters / 111320.0
        clustering = DBSCAN(eps=eps_degrees, min_samples=min_points, metric="euclidean").fit(
            coords[[lat_col, lon_col]].values
        )
        labels = clustering.labels_
        valid_df = valid_df.copy()
        valid_df["cluster_id"] = labels

        unique_clusters = [c for c in set(labels) if c >= 0]
        result["n_clusters"] = len(unique_clusters)

        flagged_mask = labels >= 0
        flagged_df = valid_df.loc[flagged_mask].copy()
        result["flagged_count"] = int(flagged_mask.sum())
        result["flagged_indexes"] = valid_df.index[flagged_mask].tolist()
        result["flagged_records"] = flagged_df.head(300).to_dict(orient="records")

        for cid in unique_clusters:
            members = valid_df[valid_df["cluster_id"] == cid]
            summary = {
                "cluster_id": int(cid),
                "n_points": len(members),
                "center_lat": round(float(members[lat_col].mean()), 6),
                "center_lon": round(float(members[lon_col].mean()), 6)
            }
            result["cluster_summary"].append(summary)
            result["clusters_detail"].append({
                "cluster_id": int(cid),
                "n_points": len(members),
                "records": members.head(50).to_dict(orient="records")
            })
    except Exception as e:
        result["error"] = str(e)

    return result


def build_pass_fail_table(df: pd.DataFrame, report: Dict, rules: Dict) -> pd.DataFrame:
    out = df.copy()
    reasons = {idx: [] for idx in out.index}

    for idx in report.get("duplicates", {}).get("exact", {}).get("indexes", []):
        if idx in reasons:
            reasons[idx].append("Exact duplicate")

    for idx in report.get("duration_check", {}).get("flagged_short_indexes", []):
        if idx in reasons:
            reasons[idx].append("Interview too short")
    for idx in report.get("duration_check", {}).get("flagged_long_indexes", []):
        if idx in reasons:
            reasons[idx].append("Interview too long")

    for idx in report.get("cluster_check", {}).get("flagged_indexes", []):
        if idx in reasons:
            reasons[idx].append("Geographic cluster")

    flagged_agents = set(report.get("patterns", {}).get("summary", {}).get("flagged_agents", []))
    agent_col = rules.get("agent_col")
    if agent_col and agent_col in out.columns and flagged_agents:
        for idx, agent in out[agent_col].astype(str).items():
            if agent in flagged_agents:
                reasons[idx].append("Suspicious agent pattern")

    pass_fail = []
    reason_text = []
    for idx in out.index:
        rlist = reasons.get(idx, [])
        if rlist:
            pass_fail.append("FAIL")
            reason_text.append("; ".join(rlist))
        else:
            pass_fail.append("PASS")
            reason_text.append("")

    out.insert(0, "Pass_Fail", pass_fail)
    out.insert(1, "Failure_Reason", reason_text)
    return out


def run_full_verification(df: pd.DataFrame, rules: Dict) -> Dict[str, Any]:
    report = {
        "n_rows": len(df),
        "n_cols": len(df.columns),
        "columns": list(df.columns),
        "duplicates": {},
        "demographics": {},
        "patterns": {},
        "duration_check": {},
        "cluster_check": {},
        "failed_indexes": set(),
        "map_ready": False
    }

    key_cols = rules.get("duplicate_keys") or []
    exact = find_exact_duplicates(df, key_cols)
    report["duplicates"]["exact"] = {
        "count": len(exact),
        "rows": exact.head(100).to_dict(orient="records") if len(exact) else [],
        "indexes": exact.index.tolist() if len(exact) else []
    }
    report["failed_indexes"].update(exact.index.tolist())

    text_candidates = [c for c in df.columns if df[c].dtype == object][:3]
    fuzzy = find_fuzzy_duplicates(df, text_candidates, threshold=rules.get("fuzzy_threshold", 90))
    report["duplicates"]["fuzzy"] = fuzzy

    gender_col = rules.get("gender_col")
    age_col = rules.get("age_col")
    state_col = rules.get("state_col")
    demo_by_state = rules.get("demographic_by_state") or {}

    if gender_col or age_col:
        report["demographics"] = check_demographic_distribution_counts(
            df,
            gender_col=gender_col,
            age_col=age_col,
            state_col=state_col,
            demographic_by_state=demo_by_state
        )

    agent_col = rules.get("agent_col")
    if agent_col:
        report["patterns"] = agent_pattern_analysis(
            df, agent_col=agent_col,
            timestamp_col=rules.get("timestamp_col"),
            rules=rules.get("pattern_checks")
        )
        flagged_agents = set(report["patterns"].get("summary", {}).get("flagged_agents", []))
        if flagged_agents and agent_col in df.columns:
            agent_failed = df[df[agent_col].astype(str).isin(flagged_agents)].index.tolist()
            report["failed_indexes"].update(agent_failed)

    start_col = rules.get("start_time_col")
    end_col = rules.get("end_time_col")
    if start_col and end_col:
        report["duration_check"] = check_interview_duration(
            df, start_col=start_col, end_col=end_col,
            min_duration_minutes=rules.get("min_duration_minutes", 5),
            max_duration_minutes=rules.get("max_duration_minutes", 120)
        )
        report["failed_indexes"].update(report["duration_check"].get("flagged_short_indexes", []))
        report["failed_indexes"].update(report["duration_check"].get("flagged_long_indexes", []))

    lat = rules.get("lat_col")
    lon = rules.get("lon_col")
    if rules.get("cluster_enabled", True) and lat and lon:
        report["cluster_check"] = check_geographic_clusters(
            df, lat_col=lat, lon_col=lon,
            min_points=rules.get("cluster_min_points", 5),
            radius_meters=rules.get("cluster_radius_meters", 100)
        )
        report["failed_indexes"].update(report["cluster_check"].get("flagged_indexes", []))

    report["failed_indexes"] = list(report["failed_indexes"])
    report["pass_fail_table"] = build_pass_fail_table(df, report, rules)

    if lat and lon and lat in df.columns and lon in df.columns:
        report["map_ready"] = True
        report["lat_col"] = lat
        report["lon_col"] = lon

    return report