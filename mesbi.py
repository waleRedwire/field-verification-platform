"""
MESBI Calculation Engine
Matches survey columns → scores responses → aggregates dimensions → weighted MESBI score
"""
from typing import Dict, List, Any, Optional
import pandas as pd
import numpy as np
import re
from rapidfuzz import fuzz


INDICATORS = {
    "S_general_perception": "How would you rate the current state of Nigeria’s economy (Excellent, good, fair, bad, very bad)?",
    "S_prices": "In the past month, have prices for essential goods and services, increased, decreased or stayed the same",
    "S_affordability": "How difficult is it for your household to afford basic necessities (food and water) compared to last month?",
    "S_govt": "Do you believe the government is doing enough to address the rising cost of living?",
    "S_employment_status": "Are you currently employed or earning a regular income? Describe your employment status?",
    "S_income_security": "Compared to last month, do you feel more or less secure in your job/income?",
    "S_income_disruption": "In the last month, have you experienced any disruptions in your salary/income?",
    "S_job_confidence": "If you lose your job today, how confident are you that you will get another job?",
    "S_major_purchases": "In the past month, have you made any major purchases (Car, Electronics, etc.)?",
    "S_spending_change": "Are you spending more, less or the same compared to last month?",
    "S_household_confidence": "On a scale of 1 - 5, how confident are you in your ability to manage your household expenses next month?",
    "S_type": "In the past month, what type of goods and services have you reduced your spending on the most?",
    "S_bank_account": "Do you currently have a personal bank account?",
    "S_source": "What is your main source of income?",
    "S_no_bank": "Why don’t you have a bank account?",
    "S_savings": "In the past month, have you saved any money?",
    "S_where_loan": "Where did you try to get the loan?",
    "S_loan_access": "Have you attempted to access a loan in the past 6months (whether from a bank or elsewhere). Please indicate if successful or not.",
    "S_bank_trust": "How much do you trust the banking system?",
    "S_cbn_trust": "On a scale of 1-5, how confident are you about the ability of CBN to stabilize the economy",
}

DIMENSION_MAP = {
    "D_inflation_cost": ["S_general_perception", "S_prices", "S_affordability", "S_govt"],
    "D_employment_confidence": ["S_employment_status", "S_income_security", "S_income_disruption", "S_job_confidence"],
    "D_consumer_confidence": ["S_major_purchases", "S_spending_change", "S_household_confidence", "S_type"],
    "D_consumer_finance": ["S_bank_account", "S_source", "S_no_bank", "S_savings"],
    "D_credit_access": ["S_where_loan", "S_loan_access"],
    "D_trust_institutions": ["S_bank_trust", "S_cbn_trust"],
}

DIMENSION_META = {
    "D_inflation_cost": {"name": "Economic Perception / Inflation & Cost", "weight": 0.20},
    "D_employment_confidence": {"name": "Employment Confidence", "weight": 0.20},
    "D_consumer_confidence": {"name": "Spending Behaviour / Consumer Confidence", "weight": 0.20},
    "D_consumer_finance": {"name": "Financial Perception / Consumer Finance", "weight": 0.20},
    "D_credit_access": {"name": "Credit Access", "weight": 0.10},
    "D_trust_institutions": {"name": "Trust in Financial Institutions", "weight": 0.10},
}


def _normalize(text: str) -> str:
    if text is None or (isinstance(text, float) and np.isnan(text)):
        return ""
    t = str(text).lower().strip()
    t = re.sub(r"^c_", "", t)
    t = re.sub(r"[_\-\s]+", " ", t)
    t = re.sub(r"[^\w\s]", "", t)
    return t.strip()


def match_columns_to_indicators(df_columns: List[str], threshold: int = 90) -> Dict[str, str]:
    mapping = {}
    used_indicators = set()
    normalized_questions = {code: _normalize(q) for code, q in INDICATORS.items()}

    for col in df_columns:
        col_norm = _normalize(col)
        if not col_norm:
            continue

        best_score = 0
        best_code = None

        for code, q_norm in normalized_questions.items():
            if code in used_indicators:
                continue
            score = max(
                fuzz.token_set_ratio(col_norm, q_norm),
                fuzz.partial_ratio(col_norm, q_norm)
            )
            if score > best_score:
                best_score = score
                best_code = code

        if best_code and best_score >= threshold:
            mapping[col] = best_code
            used_indicators.add(best_code)

    return mapping


def score_response(indicator_code: str, raw_value: Any) -> Optional[float]:
    if raw_value is None or (isinstance(raw_value, float) and np.isnan(raw_value)):
        return None

    val = str(raw_value).strip()
    if val == "" or val.lower() in ("nan", "none", "null", "-"):
        return None

    v = val.lower()

    if indicator_code == "S_general_perception":
        if "excellent" in v: return 1.00
        if "good" in v and "very" not in v: return 0.75
        if "fair" in v: return 0.50
        if "very bad" in v or "verybad" in v: return 0.00
        if "bad" in v: return 0.25
        return None

    if indicator_code == "S_prices":
        if "decreased" in v: return 1.00
        if "stayed the same" in v or "same" in v: return 0.50
        if "increased" in v: return 0.00
        return None

    if indicator_code == "S_affordability":
        if "less difficult" in v: return 1.00
        if "no change" in v: return 0.50
        if "more difficult" in v: return 0.00
        return None

    if indicator_code == "S_govt":
        if v in ("yes", "y"): return 1.00
        if v in ("no", "n"): return 0.00
        return None

    if indicator_code == "S_employment_status":
        positives = [
            "employed (full-time)", "employed (part-time/contract)",
            "entrepreneur", "self-employed", "business", "employed"
        ]
        for p in positives:
            if p in v:
                return 1.00
        return 0.00

    if indicator_code == "S_income_security":
        if "more secure" in v: return 1.00
        if "no change" in v: return 0.50
        if "less secure" in v: return 0.00
        return None

    if indicator_code == "S_income_disruption":
        if "no pay cuts" in v:
            return 1.00
        return 0.00

    if indicator_code in ("S_job_confidence", "S_household_confidence", "S_cbn_trust"):
        if "5" in v and ("very" in v or "highly" in v or "confident" in v): return 1.00
        if re.search(r"\b5\b", v): return 1.00
        if "4" in v and "confident" in v: return 0.75
        if re.search(r"\b4\b", v): return 0.75
        if "3" in v or "moderate" in v or "neutral" in v: return 0.50
        if re.search(r"\b3\b", v): return 0.50
        if "2" in v or "barely" in v: return 0.25
        if re.search(r"\b2\b", v): return 0.25
        if "1" in v or "no confidence" in v: return 0.00
        if re.search(r"\b1\b", v): return 0.00
        return None

    if indicator_code in ("S_major_purchases", "S_savings", "S_bank_account"):
        if v in ("yes", "y"): return 1.00
        if v in ("no", "n"): return 0.00
        return None

    if indicator_code == "S_spending_change":
        if "more" in v: return 1.00
        if "about the same" in v or "same" in v: return 0.50
        if "less" in v: return 0.00
        return None

    if indicator_code == "S_type":
        if "food" in v:
            return 0.50
        return 0.00

    if indicator_code == "S_source":
        if any(x in v for x in ("salary", "trading", "business")):
            return 1.00
        return 0.00

    if indicator_code == "S_no_bank":
        if "spouse" in v or "family" in v:
            return 0.50
        return 0.00

    if indicator_code == "S_where_loan":
        vu = val.upper()
        if any(x in vu for x in ("COMMERCIAL BANK", "MICROFINANCE BANK", "MOBILE APP")):
            return 1.00
        if "COOPERATIVE" in vu:
            return 0.50
        return 0.00

    if indicator_code == "S_loan_access":
        if "yes" in v and "successful" in v:
            return 1.00
        return 0.00

    if indicator_code == "S_bank_trust":
        if "5" in v or "trust completely" in v: return 1.00
        if "4" in v or "some trust" in v: return 0.75
        if "3" in v or "neutral" in v: return 0.50
        if "2" in v or "low trust" in v: return 0.25
        if "1" in v or "no trust" in v: return 0.00
        return None

    return None


def run_mesbi(df: pd.DataFrame, match_threshold: int = 90) -> Dict[str, Any]:
    report = {
        "matched_columns": {},
        "unmatched_indicators": [],
        "indicator_averages": {},
        "dimension_scores": {},
        "mesbi_score": None,
        "n_records": len(df),
        "scored_data_preview": None,
        "errors": []
    }

    mapping = match_columns_to_indicators(list(df.columns), threshold=match_threshold)
    report["matched_columns"] = mapping

    matched_codes = set(mapping.values())
    report["unmatched_indicators"] = [c for c in INDICATORS if c not in matched_codes]

    if not mapping:
        report["errors"].append("No columns could be matched to MESBI indicators. Check question text headers.")
        return report

    scored = pd.DataFrame(index=df.index)
    for orig_col, code in mapping.items():
        scored[code] = df[orig_col].apply(lambda x: score_response(code, x))

    indicator_avgs = {}
    for code in matched_codes:
        series = scored[code].dropna()
        if len(series) > 0:
            indicator_avgs[code] = round(float(series.mean()), 4)
        else:
            indicator_avgs[code] = None

    report["indicator_averages"] = indicator_avgs

    dim_scores = {}
    for dim_code, indicators in DIMENSION_MAP.items():
        vals = [indicator_avgs[i] for i in indicators if i in indicator_avgs and indicator_avgs[i] is not None]
        if vals:
            dim_scores[dim_code] = {
                "name": DIMENSION_META[dim_code]["name"],
                "score": round(float(np.mean(vals)), 4),
                "weight": DIMENSION_META[dim_code]["weight"],
                "n_indicators_used": len(vals),
                "indicators": {i: indicator_avgs.get(i) for i in indicators}
            }
        else:
            dim_scores[dim_code] = {
                "name": DIMENSION_META[dim_code]["name"],
                "score": None,
                "weight": DIMENSION_META[dim_code]["weight"],
                "n_indicators_used": 0,
                "indicators": {i: indicator_avgs.get(i) for i in indicators}
            }

    report["dimension_scores"] = dim_scores

    weighted_sum = 0.0
    total_weight = 0.0
    for dim_code, info in dim_scores.items():
        if info["score"] is not None:
            w = info["weight"]
            weighted_sum += info["score"] * w
            total_weight += w

    if total_weight > 0:
        report["mesbi_score"] = round(weighted_sum / total_weight, 4)
        report["mesbi_score_raw_weighted"] = round(weighted_sum, 4)
    else:
        report["mesbi_score"] = None

    report["scored_data_preview"] = scored.head(20).to_dict(orient="records")
    return report