"""
FIELD VERIFICATION PLATFORM
Map click → Agent + Date + Interview audio → auto play & English transcript
"""
import streamlit as st
import pandas as pd
import json
from io import BytesIO
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font
from openpyxl.utils.dataframe import dataframe_to_rows

from db import (
    create_project, list_projects, get_project,
    get_rules, save_rules, save_dataset, save_run
)
from verification import run_full_verification
from map_utils import create_data_map, find_nearest_row
from mesbi import run_mesbi, INDICATORS
from audio import download_audio_bytes, transcribe_english

try:
    from google_utils import load_google_sheet, upload_file_to_drive_folder
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False

st.set_page_config(
    page_title="FIELD VERIFICATION PLATFORM",
    page_icon="✅",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .stApp { background-color: #f8fafc; color: #1e293b; }
    .main .block-container { padding-top: 1.5rem; padding-bottom: 2rem; max-width: 1400px; }
    .app-header {
        background: linear-gradient(90deg, #1e40af 0%, #1e3a8a 100%);
        border-radius: 12px; padding: 1.2rem 1.8rem; margin-bottom: 1.5rem;
        color: white; box-shadow: 0 4px 12px rgba(30, 64, 175, 0.25);
    }
    .app-header h1 { margin: 0; font-size: 1.55rem; font-weight: 700; color: #ffffff; }
    .app-header .subtitle { color: #bfdbfe; font-size: 0.9rem; margin-top: 0.3rem; }
    section[data-testid="stSidebar"] { background-color: #ffffff !important; border-right: 1px solid #e2e8f0; }
    div[data-testid="stMetric"] {
        background: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px;
        padding: 1rem 1.2rem; box-shadow: 0 1px 4px rgba(0,0,0,0.06);
    }
    .stButton > button[kind="primary"] {
        background: linear-gradient(90deg, #2563eb, #1d4ed8) !important; border: none !important; color: white !important;
    }
    .stTabs [data-baseweb="tab"] { color: #475569 !important; }
    .stTabs [aria-selected="true"] {
        background-color: #eff6ff !important; color: #1e40af !important; font-weight: 600 !important;
    }
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} 
</style>
""", unsafe_allow_html=True)

if "current_project_id" not in st.session_state:
    st.session_state.current_project_id = None
if "df" not in st.session_state:
    st.session_state.df = None
if "last_report" not in st.session_state:
    st.session_state.last_report = None
if "demo_by_state" not in st.session_state:
    st.session_state.demo_by_state = {}
if "mesbi_result" not in st.session_state:
    st.session_state.mesbi_result = None
if "selected_point_idx" not in st.session_state:
    st.session_state.selected_point_idx = None
if "point_audio_bytes" not in st.session_state:
    st.session_state.point_audio_bytes = None
if "point_audio_format" not in st.session_state:
    st.session_state.point_audio_format = None
if "point_audio_url" not in st.session_state:
    st.session_state.point_audio_url = None
if "point_transcript" not in st.session_state:
    st.session_state.point_transcript = None


def load_data(uploaded_file) -> pd.DataFrame:
    if uploaded_file.name.endswith((".xlsx", ".xls")):
        return pd.read_excel(uploaded_file)
    return pd.read_csv(uploaded_file)


def build_colour_coded_excel(pass_fail_df: pd.DataFrame) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Verification Results"
    for r_idx, row in enumerate(dataframe_to_rows(pass_fail_df, index=False, header=True), 1):
        for c_idx, value in enumerate(row, 1):
            cell = ws.cell(row=r_idx, column=c_idx, value=value)
            if r_idx > 1 and c_idx == 1:
                if str(value).upper() == "FAIL":
                    cell.fill = PatternFill(start_color="FF6B6B", end_color="FF6B6B", fill_type="solid")
                    cell.font = Font(bold=True, color="FFFFFF")
                else:
                    cell.fill = PatternFill(start_color="6BCB77", end_color="6BCB77", fill_type="solid")
    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


def load_and_transcribe_point(audio_url: str, use_api: bool, api_key, model_size: str):
    data, suffix, err = download_audio_bytes(audio_url)
    if err:
        st.session_state.point_audio_bytes = None
        st.session_state.point_transcript = {"error": err, "text": None}
        return
    st.session_state.point_audio_bytes = data
    st.session_state.point_audio_format = (suffix or ".mp3").lstrip(".")
    st.session_state.point_audio_url = audio_url
    out = transcribe_english(
        audio_url,
        model_size=model_size,
        use_openai_api=use_api,
        openai_api_key=api_key
    )
    st.session_state.point_transcript = out


# ---------- Sidebar ----------
st.sidebar.markdown("### Projects")
projects = list_projects()
project_names = {p["name"]: p["id"] for p in projects}
selected_name = st.sidebar.selectbox(
    "Select project",
    options=["— create new —"] + list(project_names.keys()),
    label_visibility="collapsed"
)

if selected_name == "— create new —":
    with st.sidebar.form("new_project"):
        new_name = st.text_input("Project name")
        new_desc = st.text_area("Description", height=80)
        if st.form_submit_button("Create Project"):
            if new_name.strip():
                pid = create_project(new_name.strip(), new_desc.strip())
                st.session_state.current_project_id = pid
                st.rerun()
            else:
                st.sidebar.error("Name required")
else:
    st.session_state.current_project_id = project_names[selected_name]

st.sidebar.markdown("---")
st.sidebar.caption("FIELD VERIFICATION PLATFORM  v1.4")

if st.session_state.current_project_id is None:
    st.markdown("""
    <div class="app-header"><div>
        <h1>FIELD VERIFICATION PLATFORM</h1>
        <div class="subtitle">Create or select a project to begin</div>
    </div></div>
    """, unsafe_allow_html=True)
    st.info("Use the sidebar to create or select a project.")
    st.stop()

project = get_project(st.session_state.current_project_id)
rules = get_rules(st.session_state.current_project_id)

if not st.session_state.demo_by_state and rules.get("demographic_by_state"):
    st.session_state.demo_by_state = rules.get("demographic_by_state", {})

st.markdown(f"""
<div class="app-header"><div>
    <h1>FIELD VERIFICATION PLATFORM</h1>
    <div class="subtitle">{project['name']}{(' — ' + project['description']) if project.get('description') else ''}</div>
</div></div>
""", unsafe_allow_html=True)

tab_upload, tab_rules, tab_verify, tab_map, tab_report, tab_analysis = st.tabs([
    "1. Upload Data",
    "2. Verification Rules",
    "3. Run Verification",
    "4. Map",
    "5. Report",
    "6. Analysis"
])

# ========== 1. UPLOAD ==========
with tab_upload:
    st.subheader("Load Data")
    source = st.radio("Data source", options=["Upload Excel / CSV", "Google Sheet"], horizontal=True)
    if source == "Upload Excel / CSV":
        uploaded = st.file_uploader("Choose file", type=["csv", "xlsx", "xls"])
        if uploaded:
            try:
                df = load_data(uploaded)
                st.session_state.df = df
                st.success(f"Loaded **{len(df):,}** rows × **{len(df.columns)}** columns")
                st.dataframe(df.head(20), use_container_width=True)
                if st.button("Save dataset to project", type="secondary"):
                    ds_id = save_dataset(st.session_state.current_project_id, uploaded.name, df)
                    st.success(f"Dataset saved (id={ds_id})")
            except Exception as e:
                st.error(f"Failed to read file: {e}")
    else:
        if not GOOGLE_AVAILABLE:
            st.error("Google libraries not installed.")
        else:
            sa_file = st.text_input("Service Account JSON path", value="service_account.json")
            sheet_url = st.text_input("Google Sheet URL or ID")
            worksheet_name = st.text_input("Worksheet name (blank = first)", value="")
            if st.button("Load from Google Sheet", type="primary"):
                try:
                    with st.spinner("Loading..."):
                        df = load_google_sheet(sa_file, sheet_url.strip(), worksheet_name.strip() or None)
                    st.session_state.df = df
                    st.success(f"Loaded **{len(df):,}** rows")
                    st.dataframe(df.head(20), use_container_width=True)
                except Exception as e:
                    st.error(str(e))
    if st.session_state.df is not None:
        st.caption("Columns: " + ", ".join(list(st.session_state.df.columns)))

# ========== 2. RULES ==========
with tab_rules:
    st.subheader("Verification Settings")
    all_cols = list(st.session_state.df.columns) if st.session_state.df is not None else []

    with st.expander("Geographic and Agent Columns", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            lat_col = st.selectbox(
                "Latitude column", options=[None] + all_cols,
                index=([None] + all_cols).index(rules.get("lat_col")) if rules.get("lat_col") in ([None] + all_cols) else 0
            )
            agent_col = st.selectbox(
                "Agent / Enumerator column", options=[None] + all_cols,
                index=([None] + all_cols).index(rules.get("agent_col")) if rules.get("agent_col") in ([None] + all_cols) else 0
            )
            audio_col = st.selectbox(
                "Audio / Interview URL column", options=[None] + all_cols,
                index=([None] + all_cols).index(rules.get("audio_col")) if rules.get("audio_col") in ([None] + all_cols) else 0
            )
        with c2:
            lon_col = st.selectbox(
                "Longitude column", options=[None] + all_cols,
                index=([None] + all_cols).index(rules.get("lon_col")) if rules.get("lon_col") in ([None] + all_cols) else 0
            )
            state_col = st.selectbox(
                "State column", options=[None] + all_cols,
                index=([None] + all_cols).index(rules.get("state_col")) if rules.get("state_col") in ([None] + all_cols) else 0
            )
            submission_date_col = st.selectbox(
                "Submission / interview date column",
                options=[None] + all_cols,
                index=([None] + all_cols).index(rules.get("submission_date_col"))
                if rules.get("submission_date_col") in ([None] + all_cols) else 0
            )

    with st.expander("Duplicate Detection"):
        key_cols = st.multiselect(
            "Exact-duplicate key columns", options=all_cols,
            default=[c for c in rules.get("duplicate_keys", []) if c in all_cols]
        )
        fuzzy_thresh = st.slider("Fuzzy match threshold", 70, 100, rules.get("fuzzy_threshold", 90))

    with st.expander("Interview Duration Settings"):
        c1, c2 = st.columns(2)
        with c1:
            start_col = st.selectbox(
                "Start Time column", options=[None] + all_cols,
                index=([None] + all_cols).index(rules.get("start_time_col")) if rules.get("start_time_col") in ([None] + all_cols) else 0
            )
            min_duration = st.number_input(
                "Minimum duration (minutes)", 0.5, 180.0,
                float(rules.get("min_duration_minutes", 5)), 0.5
            )
        with c2:
            end_col = st.selectbox(
                "End Time column", options=[None] + all_cols,
                index=([None] + all_cols).index(rules.get("end_time_col")) if rules.get("end_time_col") in ([None] + all_cols) else 0
            )
            max_duration = st.number_input(
                "Maximum duration (minutes)", 1.0, 480.0,
                float(rules.get("max_duration_minutes", 120)), 1.0
            )

    with st.expander("Geographic Cluster Settings"):
        cluster_enabled = st.checkbox("Enable cluster detection", value=rules.get("cluster_enabled", True))
        c1, c2 = st.columns(2)
        with c1:
            min_points = st.number_input(
                "Minimum points to form a cluster", 2, 50,
                int(rules.get("cluster_min_points", 5)), 1
            )
        with c2:
            radius_m = st.number_input(
                "Radius (meters)", 10, 5000,
                int(rules.get("cluster_radius_meters", 100)), 10
            )

    with st.expander("Agent Pattern / Fraud Thresholds"):
        min_ent = st.number_input(
            "Minimum answer entropy", 0.5, 5.0,
            rules.get("pattern_checks", {}).get("min_entropy", 1.5), 0.1
        )
        max_same = st.slider(
            "Max same-answer percentage", 0.3, 1.0,
            rules.get("pattern_checks", {}).get("max_same_answer_pct", 0.6), 0.05
        )
        short_sec = st.number_input(
            "Flag fill interval shorter than (seconds)", 5, 300,
            rules.get("pattern_checks", {}).get("flag_short_fill_time_seconds", 30)
        )
        ts_col = st.selectbox(
            "Timestamp column (fill-speed)", options=[None] + all_cols,
            index=([None] + all_cols).index(rules.get("timestamp_col")) if rules.get("timestamp_col") in ([None] + all_cols) else 0
        )

    with st.expander("Demographic Targets – Per State", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            gender_col = st.selectbox(
                "Gender column", options=[None] + all_cols,
                index=([None] + all_cols).index(rules.get("gender_col")) if rules.get("gender_col") in ([None] + all_cols) else 0,
                key="gcol"
            )
        with c2:
            age_col = st.selectbox(
                "Age column", options=[None] + all_cols,
                index=([None] + all_cols).index(rules.get("age_col")) if rules.get("age_col") in ([None] + all_cols) else 0,
                key="acol"
            )
        if st.session_state.df is not None and state_col:
            states = sorted(st.session_state.df[state_col].dropna().astype(str).unique().tolist())
            age_values = (
                sorted(st.session_state.df[age_col].dropna().astype(str).unique().tolist())
                if age_col and age_col in st.session_state.df.columns else []
            )
            for state in states:
                with st.expander(f"State: {state}", expanded=False):
                    current = st.session_state.demo_by_state.get(state, {})
                    cg, ca = current.get("gender", {}), current.get("age", {})
                    g1, g2 = st.columns(2)
                    with g1:
                        male = st.number_input(
                            f"{state} Male", 0, 100000, int(cg.get("Male", 0)), 1, key=f"m_{state}"
                        )
                    with g2:
                        female = st.number_input(
                            f"{state} Female", 0, 100000, int(cg.get("Female", 0)), 1, key=f"f_{state}"
                        )
                    age_targets = {}
                    if age_values:
                        cols = st.columns(min(4, len(age_values)))
                        for i, val in enumerate(age_values):
                            with cols[i % len(cols)]:
                                age_targets[val] = st.number_input(
                                    f"{state} {val}", 0, 100000, int(ca.get(val, 0)), 1, key=f"a_{state}_{val}"
                                )
                    else:
                        age_targets = ca
                    st.session_state.demo_by_state[state] = {
                        "gender": {"Male": male, "Female": female},
                        "age": age_targets
                    }

    if st.button("Save All Rules", type="primary"):
        new_rules = {
            "duplicate_keys": key_cols,
            "fuzzy_threshold": fuzzy_thresh,
            "lat_col": lat_col,
            "lon_col": lon_col,
            "agent_col": agent_col,
            "audio_col": audio_col,
            "submission_date_col": submission_date_col,
            "state_col": state_col,
            "timestamp_col": ts_col,
            "start_time_col": start_col,
            "end_time_col": end_col,
            "min_duration_minutes": min_duration,
            "max_duration_minutes": max_duration,
            "cluster_enabled": cluster_enabled,
            "cluster_min_points": min_points,
            "cluster_radius_meters": radius_m,
            "pattern_checks": {
                "min_entropy": min_ent,
                "max_same_answer_pct": max_same,
                "flag_short_fill_time_seconds": short_sec
            },
            "gender_col": gender_col,
            "age_col": age_col,
            "demographic_targets": {"gender": {}, "age": {}},
            "demographic_by_state": st.session_state.get("demo_by_state", {})
        }
        save_rules(st.session_state.current_project_id, new_rules)
        st.success("Rules saved.")
        st.rerun()

# ========== 3. VERIFY ==========
with tab_verify:
    st.subheader("Run Full Verification")
    if st.session_state.df is None:
        st.warning("Upload data first.")
    else:
        if st.button("Run Full Verification", type="primary"):
            with st.spinner("Running..."):
                report = run_full_verification(st.session_state.df, rules)
                st.session_state.last_report = report
                save_run(st.session_state.current_project_id, None, report)
            st.success("Done — open Report tab.")
        if st.session_state.last_report:
            r = st.session_state.last_report
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Rows", r["n_rows"])
            c2.metric("Duplicates", r["duplicates"]["exact"]["count"])
            c3.metric("Flagged Agents", r.get("patterns", {}).get("summary", {}).get("n_flagged", 0))
            c4.metric("Short Interviews", r.get("duration_check", {}).get("flagged_short_count", 0))
            c5.metric("Clusters", r.get("cluster_check", {}).get("flagged_count", 0))

# ========== 4. MAP ==========
with tab_map:
    st.subheader("Geographic Map")
    st.caption(
        "Click a point on the map to see **Agent**, **Submission date**, and **Interview audio** "
        "(downloads, plays, and auto-transcribes below)."
    )

    if st.session_state.df is None:
        st.warning("Upload data first.")
    else:
        lat = rules.get("lat_col")
        lon = rules.get("lon_col")
        audio_col = rules.get("audio_col")
        agent_col = rules.get("agent_col")
        date_col = rules.get("submission_date_col") or rules.get("timestamp_col")
        state_col = rules.get("state_col")

        if not lat or not lon:
            st.info("Set Latitude and Longitude in Verification Rules.")
        elif lat not in st.session_state.df.columns or lon not in st.session_state.df.columns:
            st.error(f"Lat/lon columns not in data: `{lat}`, `{lon}`. Re-save rules.")
            st.write("Available:", list(st.session_state.df.columns))
        else:
            df_map = st.session_state.df.copy()
            failed_indexes = set()
            if st.session_state.last_report:
                failed_indexes = set(st.session_state.last_report.get("failed_indexes", []))

            f1, f2, f3 = st.columns(3)
            with f1:
                if agent_col and agent_col in df_map.columns:
                    agents = sorted(df_map[agent_col].dropna().astype(str).unique().tolist())
                    sel_a = st.multiselect("Filter Agent", agents, default=agents)
                    if sel_a:
                        df_map = df_map[df_map[agent_col].astype(str).isin(sel_a)]
            with f2:
                if state_col and state_col in df_map.columns:
                    states = sorted(df_map[state_col].dropna().astype(str).unique().tolist())
                    sel_s = st.multiselect("Filter State", states, default=states)
                    if sel_s:
                        df_map = df_map[df_map[state_col].astype(str).isin(sel_s)]
            with f3:
                heat = st.checkbox("Heatmap")
                satellite = st.checkbox("Satellite")
                use_api = st.checkbox(
                    "Whisper via OpenAI API",
                    value=False,
                    help="Better on Streamlit Cloud"
                )
                model_size = st.selectbox("Local model", ["base", "tiny", "small"], index=0)

            api_key = None
            if use_api:
                try:
                    api_key = st.secrets.get("OPENAI_API_KEY")
                except Exception:
                    api_key = None
                if not api_key:
                    api_key = st.text_input("OpenAI API key", type="password")

            st.caption(f"**{len(df_map)}** points | Red = failed | Green = clean")

            if len(df_map) > 0:
                m = create_data_map(
                    df_map, lat_col=lat, lon_col=lon,
                    agent_col=agent_col, state_col=state_col,
                    audio_col=audio_col, date_col=date_col,
                    heat=heat, satellite=satellite,
                    failed_indexes=failed_indexes
                )
                try:
                    from streamlit_folium import st_folium
                    map_state = st_folium(
                        m, width=1200, height=600,
                        returned_objects=["last_object_clicked", "last_clicked"]
                    )
                except ImportError:
                    st.components.v1.html(m._repr_html_(), height=600)
                    map_state = None

                click_lat = click_lon = None
                if map_state:
                    obj = map_state.get("last_object_clicked") or {}
                    if obj.get("lat") is not None:
                        click_lat = obj.get("lat")
                        click_lon = obj.get("lng") or obj.get("lon")
                    elif map_state.get("last_clicked"):
                        click_lat = map_state["last_clicked"].get("lat")
                        click_lon = map_state["last_clicked"].get("lng")

                if click_lat is not None and click_lon is not None:
                    nearest = find_nearest_row(df_map, lat, lon, float(click_lat), float(click_lon))
                    if nearest is not None and nearest != st.session_state.selected_point_idx:
                        st.session_state.selected_point_idx = nearest
                        st.session_state.point_audio_bytes = None
                        st.session_state.point_transcript = None
                        st.session_state.point_audio_url = None
                        row = df_map.loc[nearest]
                        if audio_col and audio_col in df_map.columns:
                            url = str(row.get(audio_col, "")).strip()
                            if url and url.lower() not in ("nan", "none", ""):
                                with st.spinner("Loading interview audio & transcribing (English)..."):
                                    load_and_transcribe_point(url, use_api, api_key, model_size)
                        st.rerun()

            # Selected interview card
            idx = st.session_state.selected_point_idx
            if idx is not None and idx in st.session_state.df.index:
                row = st.session_state.df.loc[idx]
                st.markdown("#### Selected interview")
                d1, d2, d3 = st.columns(3)
                with d1:
                    agent_val = row[agent_col] if agent_col and agent_col in row.index else "—"
                    st.markdown(f"**Agent**  \n{agent_val}")
                with d2:
                    date_val = row[date_col] if date_col and date_col in row.index else "—"
                    st.markdown(f"**Submission date**  \n{date_val}")
                with d3:
                    state_val = row[state_col] if state_col and state_col in row.index else "—"
                    st.markdown(f"**State**  \n{state_val}")

                if audio_col and audio_col in row.index:
                    url = str(row.get(audio_col, "")).strip()
                    if url and url.lower() not in ("nan", "none", ""):
                        st.markdown(f"**Interview** · [source link]({url})")
                        if st.session_state.point_audio_bytes and st.session_state.point_audio_url == url:
                            fmt = st.session_state.point_audio_format or "mp3"
                            st.audio(st.session_state.point_audio_bytes, format=f"audio/{fmt}")
                        else:
                            st.info("Click the map point again if audio did not load, or check the URL.")

                        if st.session_state.point_transcript:
                            tr = st.session_state.point_transcript
                            if tr.get("error"):
                                st.error(tr["error"])
                            else:
                                st.markdown("**English transcript**")
                                st.text_area(
                                    "Transcript",
                                    value=tr.get("text") or "",
                                    height=200,
                                    label_visibility="collapsed"
                                )
                    else:
                        st.warning("No audio link for this point.")
                else:
                    st.info("Set Audio URL column in Verification Rules to play interviews.")
            else:
                st.info("Click a point on the map to open the interview.")

# ========== 5. REPORT ==========
with tab_report:
    st.subheader("Verification Report")
    if not st.session_state.last_report:
        st.info("Run verification first.")
    else:
        r = st.session_state.last_report
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Duplicates", r["duplicates"]["exact"]["count"])
        c2.metric("Short Interviews", r.get("duration_check", {}).get("flagged_short_count", 0))
        c3.metric("Clusters", r.get("cluster_check", {}).get("flagged_count", 0))
        c4.metric("Suspicious Agents", r.get("patterns", {}).get("summary", {}).get("n_flagged", 0))
        pass_fail_df = r.get("pass_fail_table")
        if pass_fail_df is not None:
            st.dataframe(pass_fail_df, use_container_width=True)
        demo = r.get("demographics", {})
        if demo.get("gender_table"):
            st.markdown("#### Gender by State")
            st.dataframe(pd.DataFrame(demo["gender_table"]), use_container_width=True)
        if demo.get("age_table"):
            st.markdown("#### Age by State")
            st.dataframe(pd.DataFrame(demo["age_table"]), use_container_width=True)
        if pass_fail_df is not None:
            st.download_button(
                "Download Excel",
                data=build_colour_coded_excel(pass_fail_df),
                file_name=f"verification_report_{project['name']}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

# ========== 6. ANALYSIS ==========
with tab_analysis:
    st.subheader("Analysis")
    if st.session_state.df is None:
        st.warning("Upload data first.")
    else:
        if st.button("Run MESBI", type="primary"):
            with st.spinner("MESBI..."):
                st.session_state.mesbi_result = run_mesbi(st.session_state.df, match_threshold=90)
        if st.session_state.mesbi_result:
            r = st.session_state.mesbi_result
            if r.get("mesbi_score") is not None:
                st.metric("MESBI Score", f"{r['mesbi_score']:.4f}")
            if r.get("indicator_averages"):
                st.dataframe(pd.DataFrame([
                    {"Indicator": k, "Average": v} for k, v in r["indicator_averages"].items()
                ]), use_container_width=True)
            if r.get("dimension_scores"):
                st.dataframe(pd.DataFrame([
                    {
                        "Dimension": k,
                        "Name": v["name"],
                        "Score": v["score"],
                        "Weight": v["weight"]
                    }
                    for k, v in r["dimension_scores"].items()
                ]), use_container_width=True)