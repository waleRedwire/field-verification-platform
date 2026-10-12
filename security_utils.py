"""
Security helpers: HTML escape, Excel formula sanitization, size limits.
"""
import html
from typing import Any, Optional
import pandas as pd

# Defaults — adjust if needed
MAX_UPLOAD_BYTES = 25 * 1024 * 1024   # 25 MB
MAX_ROWS = 15_000


def escape_text(value: Any) -> str:
    """Safe text for UI / Folium HTML."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return html.escape(str(value), quote=True)


def sanitize_excel_cell(value: Any) -> Any:
    """
    Prevent formula injection when exporting to Excel.
    Prefix dangerous leading characters so Excel treats value as text.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return value
    if isinstance(value, (int, float, bool)):
        return value
    s = str(value)
    if not s:
        return s
    # Excel formula / command triggers
    if s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return s


def sanitize_dataframe_for_excel(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        out[col] = out[col].map(sanitize_excel_cell)
    return out


def check_upload_limits(file_obj, df: Optional[pd.DataFrame] = None) -> Optional[str]:
    """
    Returns error message or None if OK.
    file_obj: Streamlit UploadedFile (has .size) or None if only df check.
    """
    if file_obj is not None:
        size = getattr(file_obj, "size", None)
        if size is not None and size > MAX_UPLOAD_BYTES:
            mb = MAX_UPLOAD_BYTES / (1024 * 1024)
            return f"File too large ({size / (1024*1024):.1f} MB). Maximum is {mb:.0f} MB."
    if df is not None and len(df) > MAX_ROWS:
        return f"Too many rows ({len(df):,}). Maximum is {MAX_ROWS:,} for online verification."
    return None


def safe_error_message(exc: Exception) -> str:
    """User-facing error without paths / internal detail."""
    return "Something went wrong while processing your request. Please try again or contact support."