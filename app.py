"""
FIELD VERIFICATION PLATFORM – Light Professional UI + MESBI Analysis
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
from map_utils import create_data_map
from mesbi import run_mesbi, INDICATORS

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
    .app-header h1 { margin: 0; font-size: 1.55rem; font-weight: 700; color: #ffffff; letter-spacing: 0.5px; }
    .app-header .subtitle { color: #bfdbfe; font-size: 0.9rem; margin-top: 0.3rem; }

    section[data-testid="stSidebar"] { background-color: #ffffff !important; border-right: 1px solid #e2e8f0; }
    section[data-testid="stSidebar"] .stMarkdown { color: #334155; }

    div[data-testid="stMetric"] {
        background: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px;
        padding: 1rem 1.2rem; box-shadow: 0 1px 4px rgba(0,0,0,0.06);
    }
    div[data-testid="stMetric"] label { color: #64748b !important; font-size: 0.85rem !important; }
    div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
        color: #0f172a !important; font-size: 1.55rem !important; font-weight: 700 !important;
    }

    .streamlit-expanderHeader {
        background-color: #ffffff !important; border-radius: 8px !important;
        color: #1e293b !important; font-weight: 600 !important; border: 1px solid #e2e8f0 !important;
    }
    .streamlit-expanderContent {
        background-color: #ffffff !important; border: 1px solid #e2e8f0 !important;
        border-top: none !important; border-radius: 0 0 8px 8px !important;
    }

    .stButton > button { border-radius: 8px !important; font-weight: 600 !important; transition: all 0.2s ease !important; }
    .stButton > button[kind="primary"] {
        background: linear-gradient(90deg, #2563eb, #1d4ed8) !important; border: none !important; color: white !important;
    }
    .stButton > button[kind="primary"]:hover {
        background: linear-gradient(90deg, #1d4ed8, #1e40af) !important;
        box-shadow: 0 4px 12px rgba(37, 99, 235, 0.35) !important;
    }
    .stButton > button[kind="secondary"] {
        background: #ffffff !important; border: 1px solid #cbd5e1 !important; color: #334155 !important;
    }

    .stTabs [data-baseweb="tab-list"] {
        gap: 6px; background-color: #ffffff; padding: 6px; border-radius: 10px; border: 1px solid #e2e8f0;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: transparent; border-radius: 8px; color: #475569 !important;
        font-weight: 500; padding: 8px 16px;
    }
    .stTabs [aria-selected="true"] {
        background-color: #eff6ff !important; color: #1e40af !important;
        border: 1px solid #bfdbfe !important; font-weight: 600 !important;
    }

    .stDataFrame { border-radius: 10px; overflow: hidden; border: 1px solid #e2e8f0; }

    .stSelectbox > div > div, .stTextInput > div > div > input, .stNumberInput > div > div > input {
        background-color: #ffffff !important; border: 1px solid #cbd5e1 !important;
        border-radius: 8px !important; color: #1e293b !important;
    }

    .stSuccess { background-color: #ecfdf5 !important; border: 1px solid #a7f3d0 !important; border-radius: 8px !important; color: #065f46 !important; }
    .stError { background-color: #fef2f2 !important; border: 1px solid #fecaca !important; border-radius: 8px !important; color: #991b1b !important; }
    .stWarning { background-color: #fffbeb !important; border: 1px solid #fde68a !important; border-radius: 8px !important; color: #92400e !important; }
    .stInfo { background-color: #eff6ff !important; border: 1px solid #bfdbfe !important; border-radius: 8px !important; color: #1e40af !important; }

    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
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
st.sidebar.caption("FIELD VERIFICATION PLATFORM  v1.1")

# ---------- Main ----------
if st.session_state.current_project_id is None:
    st.markdown("""
    <div class="app-header">
        <div>
            <h1>FIELD VERIFICATION PLATFORM</h1>
            <div class="subtitle">Create or select a project to begin</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    st.info("Use the sidebar to create a new project or select an existing one.")
    st.stop()

project = get_project(st.session_state.current_project_id)
rules = get_rules(st.session_state.current_project_id)

if not st.session_state.demo_by_state and rules.get("demographic_by_state"):
    st.session_state.demo_by_state = rules.get("demographic_by_state", {})

st.markdown(f"""
<div class="app-header">
    <div>
        <h1>FIELD VERIFICATION PLATFORM</h1>
        <div class="subtitle">{project['name']}{(' — ' + project['description']) if project.get('description') else ''}</div>
    </div>
</div>
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
            st.error("Google libraries not installed. Run: `pip install gspread google-auth google-api-python-client`")
        else:
            st.info("Share the Google Sheet with your Service Account email (Editor access).")
            sa_file = st.text_input("Path to Service Account JSON key", value="service_account.json")
            sheet_url = st.text_input("Google Sheet URL or Spreadsheet ID",
                                      placeholder="https://docs.google.com/spreadsheets/d/......../edit")
            worksheet_name = st.text_input("Worksheet name (leave blank for first sheet)", value="")
            if st.button("Load from Google Sheet", type="primary"):
                if not Path(sa_file).exists():
                    st.error(f"Service account file not found: {sa_file}")
                elif not sheet_url.strip():
                    st.error("Please paste the Google Sheet URL or ID")
                else:
                    try:
                        with st.spinner("Loading Google Sheet..."):
                            df = load_google_sheet(sa_file, sheet_url.strip(), worksheet_name.strip() or None)
                        st.session_state.df = df
                        st.success(f"Loaded **{len(df):,}** rows × **{len(df.columns)}** columns from Google Sheet")
                        st.dataframe(df.head(20), use_container_width=True)
                    except Exception as e:
                        st.error(f"Failed to load Google Sheet: {e}")

    if st.session_state.df is not None:
        st.caption("Current columns: " + ", ".join(list(st.session_state.df.columns)))

# ========== 2. VERIFICATION RULES ==========
with tab_rules:
    st.subheader("Verification Settings")
    all_cols = list(st.session_state.df.columns) if st.session_state.df is not None else []

    with st.expander("Geographic and Agent Columns", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            lat_col = st.selectbox("Latitude column", options=[None] + all_cols,
                index=([None] + all_cols).index(rules.get("lat_col")) if rules.get("lat_col") in ([None] + all_cols) else 0)
            agent_col = st.selectbox("Agent / Enumerator column", options=[None] + all_cols,
                index=([None] + all_cols).index(rules.get("agent_col")) if rules.get("agent_col") in ([None] + all_cols) else 0)
        with c2:
            lon_col = st.selectbox("Longitude column", options=[None] + all_cols,
                index=([None] + all_cols).index(rules.get("lon_col")) if rules.get("lon_col") in ([None] + all_cols) else 0)
            state_col = st.selectbox("State column", options=[None] + all_cols,
                index=([None] + all_cols).index(rules.get("state_col")) if rules.get("state_col") in ([None] + all_cols) else 0)

    with st.expander("Duplicate Detection"):
        key_cols = st.multiselect("Exact-duplicate key columns", options=all_cols,
            default=[c for c in rules.get("duplicate_keys", []) if c in all_cols])
        fuzzy_thresh = st.slider("Fuzzy match threshold", 70, 100, rules.get("fuzzy_threshold", 90))

    with st.expander("Interview Duration Settings"):
        c1, c2 = st.columns(2)
        with c1:
            start_col = st.selectbox("Start Time column", options=[None] + all_cols,
                index=([None] + all_cols).index(rules.get("start_time_col")) if rules.get("start_time_col") in ([None] + all_cols) else 0)
            min_duration = st.number_input("Minimum duration (minutes)", 0.5, 180.0,
                float(rules.get("min_duration_minutes", 5)), 0.5)
        with c2:
            end_col = st.selectbox("End Time column", options=[None] + all_cols,
                index=([None] + all_cols).index(rules.get("end_time_col")) if rules.get("end_time_col") in ([None] + all_cols) else 0)
            max_duration = st.number_input("Maximum duration (minutes)", 1.0, 480.0,
                float(rules.get("max_duration_minutes", 120)), 1.0)

    with st.expander("Geographic Cluster Settings"):
        cluster_enabled = st.checkbox("Enable cluster detection", value=rules.get("cluster_enabled", True))
        c1, c2 = st.columns(2)
        with c1:
            min_points = st.number_input("Minimum points to form a cluster", 2, 50,
                int(rules.get("cluster_min_points", 5)), 1)
        with c2:
            radius_m = st.number_input("Radius (meters)", 10, 5000,
                int(rules.get("cluster_radius_meters", 100)), 10)

    with st.expander("Agent Pattern / Fraud Thresholds"):
        min_ent = st.number_input("Minimum answer entropy", 0.5, 5.0,
            rules.get("pattern_checks", {}).get("min_entropy", 1.5), 0.1)
        max_same = st.slider("Max same-answer percentage", 0.3, 1.0,
            rules.get("pattern_checks", {}).get("max_same_answer_pct", 0.6), 0.05)
        short_sec = st.number_input("Flag fill interval shorter than (seconds)", 5, 300,
            rules.get("pattern_checks", {}).get("flag_short_fill_time_seconds", 30))
        ts_col = st.selectbox("Timestamp column (for fill-speed check)", options=[None] + all_cols,
            index=([None] + all_cols).index(rules.get("timestamp_col")) if rules.get("timestamp_col") in ([None] + all_cols) else 0)

    with st.expander("Demographic Targets (Gender and Age) – Per State", expanded=True):
        st.markdown("Set target **numbers** (not percentages) for each state individually.")
        c1, c2 = st.columns(2)
        with c1:
            gender_col = st.selectbox("Gender column", options=[None] + all_cols,
                index=([None] + all_cols).index(rules.get("gender_col")) if rules.get("gender_col") in ([None] + all_cols) else 0,
                key="gender_col_select")
        with c2:
            age_col = st.selectbox("Age / Age-group column", options=[None] + all_cols,
                index=([None] + all_cols).index(rules.get("age_col")) if rules.get("age_col") in ([None] + all_cols) else 0,
                key="age_col_select")

        if st.session_state.df is None:
            st.info("Upload data first so the system can detect states and age groups.")
        elif not state_col:
            st.warning("Please select a State column in the Geographic section above.")
        else:
            states = sorted(st.session_state.df[state_col].dropna().astype(str).unique().tolist())
            age_values = []
            if age_col and age_col in st.session_state.df.columns:
                age_values = sorted(st.session_state.df[age_col].dropna().astype(str).unique().tolist())

            st.markdown(f"#### Set targets for each of the {len(states)} state(s)")
            for state in states:
                with st.expander(f"State: {state}", expanded=False):
                    current = st.session_state.demo_by_state.get(state, {})
                    current_gender = current.get("gender", {})
                    current_age = current.get("age", {})
                    st.markdown("**Gender targets**")
                    g1, g2 = st.columns(2)
                    with g1:
                        male = st.number_input(f"{state} – Male", 0, 100000, int(current_gender.get("Male", 0)), 1, key=f"male_{state}")
                    with g2:
                        female = st.number_input(f"{state} – Female", 0, 100000, int(current_gender.get("Female", 0)), 1, key=f"female_{state}")
                    age_targets = {}
                    if age_values:
                        st.markdown("**Age group targets**")
                        age_cols = st.columns(min(4, len(age_values)))
                        for i, val in enumerate(age_values):
                            with age_cols[i % len(age_cols)]:
                                age_targets[val] = st.number_input(f"{state} – {val}", 0, 100000, int(current_age.get(val, 0)), 1, key=f"age_{state}_{val}")
                    else:
                        age_targets = current_age
                    st.session_state.demo_by_state[state] = {"gender": {"Male": male, "Female": female}, "age": age_targets}

            if st.session_state.demo_by_state:
                st.success(f"Targets configured for {len(st.session_state.demo_by_state)} state(s).")
                with st.expander("Preview all per-state targets"):
                    st.json(st.session_state.demo_by_state)

    if st.button("Save All Rules", type="primary"):
        new_rules = {
            "duplicate_keys": key_cols, "fuzzy_threshold": fuzzy_thresh,
            "lat_col": lat_col, "lon_col": lon_col, "agent_col": agent_col, "state_col": state_col,
            "timestamp_col": ts_col, "start_time_col": start_col, "end_time_col": end_col,
            "min_duration_minutes": min_duration, "max_duration_minutes": max_duration,
            "cluster_enabled": cluster_enabled, "cluster_min_points": min_points, "cluster_radius_meters": radius_m,
            "pattern_checks": {"min_entropy": min_ent, "max_same_answer_pct": max_same, "flag_short_fill_time_seconds": short_sec},
            "gender_col": gender_col, "age_col": age_col,
            "demographic_targets": {"gender": {}, "age": {}},
            "demographic_by_state": st.session_state.get("demo_by_state", {})
        }
        save_rules(st.session_state.current_project_id, new_rules)
        st.success("All verification rules saved successfully!")
        st.rerun()

# ========== 3. RUN VERIFICATION ==========
with tab_verify:
    st.subheader("Run Full Verification")
    if st.session_state.df is None:
        st.warning("Upload a dataset first.")
    else:
        if st.button("Run Full Verification", type="primary"):
            with st.spinner("Running all checks..."):
                report = run_full_verification(st.session_state.df, rules)
                st.session_state.last_report = report
                save_run(st.session_state.current_project_id, None, report)
            st.success("Verification complete! Go to the Report tab.")

        if st.session_state.last_report:
            r = st.session_state.last_report
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Rows", r["n_rows"])
            c2.metric("Exact Duplicates", r["duplicates"]["exact"]["count"])
            c3.metric("Flagged Agents", r.get("patterns", {}).get("summary", {}).get("n_flagged", 0))
            c4.metric("Short Interviews", r.get("duration_check", {}).get("flagged_short_count", 0))
            c5.metric("Clustered Points", r.get("cluster_check", {}).get("flagged_count", 0))

# ========== 4. MAP ==========
with tab_map:
    st.subheader("Geographic Map")
    if st.session_state.df is None:
        st.warning("Upload data first.")
    else:
        lat = rules.get("lat_col")
        lon = rules.get("lon_col")
        if not lat or not lon:
            st.info("Set Latitude and Longitude columns in Verification Rules first.")
        else:
            df_map = st.session_state.df.copy()
            failed_indexes = set()
            if st.session_state.last_report:
                failed_indexes = set(st.session_state.last_report.get("failed_indexes", []))

            col_f1, col_f2, col_f3 = st.columns(3)
            with col_f1:
                agent_col = rules.get("agent_col")
                if agent_col and agent_col in df_map.columns:
                    agents = sorted(df_map[agent_col].dropna().astype(str).unique().tolist())
                    selected_agents = st.multiselect("Filter by Agent", agents, default=agents)
                    if selected_agents:
                        df_map = df_map[df_map[agent_col].astype(str).isin(selected_agents)]
            with col_f2:
                state_col = rules.get("state_col")
                if state_col and state_col in df_map.columns:
                    states = sorted(df_map[state_col].dropna().astype(str).unique().tolist())
                    selected_states = st.multiselect("Filter by State", states, default=states)
                    if selected_states:
                        df_map = df_map[df_map[state_col].astype(str).isin(selected_states)]
            with col_f3:
                heat = st.checkbox("Heatmap")
                satellite = st.checkbox("Satellite")

            st.caption(f"Showing **{len(df_map)}** records  |  Red = failed  |  Green = clean")
            if len(df_map) > 0:
                m = create_data_map(
                    df_map, lat_col=lat, lon_col=lon,
                    agent_col=rules.get("agent_col"), state_col=rules.get("state_col"),
                    heat=heat, satellite=satellite, failed_indexes=failed_indexes
                )
                try:
                    from streamlit_folium import st_folium
                    st_folium(m, width=1200, height=650, returned_objects=[])
                except ImportError:
                    st.components.v1.html(m._repr_html_(), height=650)

# ========== 5. REPORT ==========
with tab_report:
    st.subheader("Verification Report")
    if not st.session_state.last_report:
        st.info("Run verification first.")
    else:
        r = st.session_state.last_report
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Exact Duplicates", r["duplicates"]["exact"]["count"])
        c2.metric("Short Interviews", r.get("duration_check", {}).get("flagged_short_count", 0))
        c3.metric("Clustered Points", r.get("cluster_check", {}).get("flagged_count", 0))
        c4.metric("Suspicious Agents", r.get("patterns", {}).get("summary", {}).get("n_flagged", 0))

        st.markdown("### Full Data with Pass / Fail")
        pass_fail_df = r.get("pass_fail_table")
        if pass_fail_df is not None:
            st.dataframe(pass_fail_df, use_container_width=True)

        st.markdown("### Demographic Distribution Tables (Per State)")
        demo = r.get("demographics", {})
        if demo.get("gender_table"):
            st.markdown("#### Gender by State")
            st.dataframe(pd.DataFrame(demo["gender_table"]), use_container_width=True)
        if demo.get("age_table"):
            st.markdown("#### Age Group by State")
            st.dataframe(pd.DataFrame(demo["age_table"]), use_container_width=True)
        if not demo.get("gender_table") and not demo.get("age_table"):
            st.info("No demographic tables. Set Gender, Age and State columns + targets in Rules.")

        with st.expander("Geographic Clusters – Full List"):
            cl = r.get("cluster_check", {})
            st.write(f"Clusters found: **{cl.get('n_clusters', 0)}**  |  Points flagged: **{cl.get('flagged_count', 0)}**")
            if cl.get("cluster_summary"):
                st.dataframe(pd.DataFrame(cl["cluster_summary"]))
            if cl.get("clusters_detail"):
                for cluster in cl["clusters_detail"]:
                    st.markdown(f"**Cluster {cluster['cluster_id']} ({cluster['n_points']} points)**")
                    st.dataframe(pd.DataFrame(cluster["records"]), use_container_width=True)

        with st.expander("Duration Flags"):
            dur = r.get("duration_check", {})
            if dur.get("flagged_short_records"):
                st.error("Short interviews")
                st.dataframe(pd.DataFrame(dur["flagged_short_records"]).head(30))
            if dur.get("flagged_long_records"):
                st.warning("Long interviews")
                st.dataframe(pd.DataFrame(dur["flagged_long_records"]).head(30))

        with st.expander("Agent Patterns"):
            patterns = r.get("patterns", {})
            st.write("Flagged agents:", patterns.get("summary", {}).get("flagged_agents", []))
            for agent, info in list(patterns.get("agents", {}).items())[:15]:
                st.write(f"**{agent}** ({info.get('n_records')} records) – flags: {info.get('flags')}")

        st.markdown("---")
        st.markdown("### Download / Export")
        if pass_fail_df is not None:
            excel_bytes = build_colour_coded_excel(pass_fail_df)
            st.download_button(
                label="Download Excel Report (local)",
                data=excel_bytes,
                file_name=f"verification_report_{project['name']}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            if GOOGLE_AVAILABLE:
                st.markdown("#### Export to Google Drive Folder")
                sa_file = st.text_input("Service Account JSON path", value="service_account.json", key="drive_sa")
                folder_id = st.text_input("Google Drive Folder ID", placeholder="e.g. 1aBcDeFgHiJkLmNoPqRsTuVwXyZ")
                export_name = st.text_input("File name on Drive", value=f"verification_report_{project['name']}.xlsx")
                if st.button("Upload report to Google Drive", type="primary"):
                    if not Path(sa_file).exists():
                        st.error(f"Service account file not found: {sa_file}")
                    elif not folder_id.strip():
                        st.error("Please enter the Google Drive Folder ID")
                    else:
                        try:
                            with st.spinner("Uploading to Google Drive..."):
                                link = upload_file_to_drive_folder(sa_file, folder_id.strip(), export_name, excel_bytes)
                            st.success("Uploaded successfully!")
                            st.markdown(f"[Open file in Google Drive]({link})")
                        except Exception as e:
                            st.error(f"Upload failed: {e}")

        st.download_button(
            label="Download full JSON report",
            data=json.dumps(r, indent=2, default=str),
            file_name=f"verification_report_{project['name']}.json",
            mime="application/json"
        )

# ========== 6. ANALYSIS ==========
with tab_analysis:
    st.subheader("Project Analysis")

    if st.session_state.df is None:
        st.warning("Upload a dataset first.")
    else:
        st.markdown("### Available Analyses")
        analysis_choice = st.selectbox(
            "Select analysis to run",
            options=["MESBI – Macro Economic Sentiment & Behaviour Index"]
        )

        if analysis_choice.startswith("MESBI"):
            st.markdown("""
            **MESBI** calculates a weighted index from survey responses on:
            Inflation & Cost, Employment Confidence, Consumer Confidence,
            Consumer Finance, Credit Access, and Trust in Institutions.
            """)

            match_thresh = st.slider(
                "Column matching threshold (%)", 70, 100, 90,
                help="How closely the uploaded column header must match the question text"
            )

            if st.button("Run MESBI Analysis", type="primary"):
                with st.spinner("Matching columns, scoring responses, calculating MESBI..."):
                    mesbi_result = run_mesbi(st.session_state.df, match_threshold=match_thresh)
                    st.session_state.mesbi_result = mesbi_result

            if st.session_state.mesbi_result:
                r = st.session_state.mesbi_result

                if r.get("errors"):
                    for e in r["errors"]:
                        st.error(e)
                else:
                    score = r.get("mesbi_score")
                    if score is not None:
                        st.markdown(f"""
                        <div style="background:#eff6ff;border:2px solid #3b82f6;border-radius:12px;
                                    padding:1.5rem;text-align:center;margin:1rem 0;">
                            <div style="font-size:0.95rem;color:#1e40af;font-weight:600;">MESBI SCORE</div>
                            <div style="font-size:2.8rem;font-weight:800;color:#1e3a8a;">{score:.4f}</div>
                            <div style="font-size:0.85rem;color:#64748b;">Scale 0 – 1 (higher = more positive sentiment)</div>
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        st.warning("Could not compute MESBI score (no valid dimension data).")

                    with st.expander("Matched Columns (Uploaded header → Indicator code)", expanded=False):
                        if r["matched_columns"]:
                            match_df = pd.DataFrame([
                                {"Uploaded Column": k, "Indicator Code": v, "Question": INDICATORS.get(v, "")}
                                for k, v in r["matched_columns"].items()
                            ])
                            st.dataframe(match_df, use_container_width=True)
                        if r["unmatched_indicators"]:
                            st.warning(
                                f"Unmatched indicators ({len(r['unmatched_indicators'])}): " +
                                ", ".join(r["unmatched_indicators"])
                            )

                    st.markdown("#### Indicator Averages")
                    ind_rows = []
                    for code, avg in r["indicator_averages"].items():
                        ind_rows.append({
                            "Indicator Code": code,
                            "Average Score": avg if avg is not None else "—",
                            "Question (short)": (INDICATORS.get(code, "")[:80] + "...") if INDICATORS.get(code) else ""
                        })
                    st.dataframe(pd.DataFrame(ind_rows), use_container_width=True)

                    st.markdown("#### Dimension Scores (before weighting)")
                    dim_rows = []
                    for dim_code, info in r["dimension_scores"].items():
                        dim_rows.append({
                            "Dimension Code": dim_code,
                            "Dimension Name": info["name"],
                            "Score (avg of indicators)": info["score"] if info["score"] is not None else "—",
                            "Weight": info["weight"],
                            "Indicators Used": info["n_indicators_used"]
                        })
                    st.dataframe(pd.DataFrame(dim_rows), use_container_width=True)

                    st.markdown("---")
                    export = {
                        "mesbi_score": r.get("mesbi_score"),
                        "indicator_averages": r.get("indicator_averages"),
                        "dimension_scores": {
                            k: {"name": v["name"], "score": v["score"], "weight": v["weight"]}
                            for k, v in r.get("dimension_scores", {}).items()
                        },
                        "matched_columns": r.get("matched_columns")
                    }
                    st.download_button(
                        "Download MESBI Results (JSON)",
                        data=json.dumps(export, indent=2, default=str),
                        file_name=f"MESBI_{project['name']}.json",
                        mime="application/json"
                    )