"""
Folium map helpers.
Failed = RED + circle, clean = GREEN.
Popup shows Agent, Submission date, Audio.
"""
from typing import Optional, Set
import pandas as pd
import folium
from folium.plugins import MarkerCluster, HeatMap


def create_data_map(
    df: pd.DataFrame,
    lat_col: str,
    lon_col: str,
    popup_cols: Optional[list] = None,
    agent_col: Optional[str] = None,
    state_col: Optional[str] = None,
    audio_col: Optional[str] = None,
    date_col: Optional[str] = None,
    heat: bool = False,
    satellite: bool = False,
    failed_indexes: Optional[Set] = None
) -> folium.Map:

    missing = [c for c in (lat_col, lon_col) if c not in df.columns]
    if missing:
        m = folium.Map(location=[9.0, 8.0], zoom_start=6)
        folium.Marker(
            [9.0, 8.0],
            popup=f"Map error: missing columns {missing}"
        ).add_to(m)
        return m

    clean = df[[lat_col, lon_col]].copy()
    clean[lat_col] = pd.to_numeric(clean[lat_col], errors="coerce")
    clean[lon_col] = pd.to_numeric(clean[lon_col], errors="coerce")
    clean = clean.dropna()

    if clean.empty:
        return folium.Map(location=[9.0, 8.0], zoom_start=6)

    center_lat = float(clean[lat_col].mean())
    center_lon = float(clean[lon_col].mean())

    if satellite:
        m = folium.Map(
            location=[center_lat, center_lon],
            zoom_start=7,
            tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            attr="Esri World Imagery"
        )
        folium.TileLayer(
            tiles="https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
            attr="Esri Boundaries",
            name="Labels",
            overlay=True
        ).add_to(m)
    else:
        m = folium.Map(location=[center_lat, center_lon], zoom_start=7, tiles="OpenStreetMap")

    failed_indexes = failed_indexes or set()

    if heat:
        HeatMap(clean[[lat_col, lon_col]].values.tolist(), radius=15, blur=20).add_to(m)
    else:
        normal_cluster = MarkerCluster(name="Clean points (green)").add_to(m)
        failed_cluster = MarkerCluster(name="Failed verification (red)").add_to(m)
        popup_cols = popup_cols or []

        for idx, row in df.iterrows():
            try:
                lat = float(row[lat_col])
                lon = float(row[lon_col])
            except (TypeError, ValueError, KeyError):
                continue

            is_failed = idx in failed_indexes
            parts = []

            if is_failed:
                parts.append("<b style='color:red'>FAILED VERIFICATION</b>")

            if agent_col and agent_col in df.columns:
                parts.append(f"<b>Agent:</b> {row[agent_col]}")

            if date_col and date_col in df.columns:
                parts.append(f"<b>Submission date:</b> {row[date_col]}")

            if state_col and state_col in df.columns:
                parts.append(f"<b>State:</b> {row[state_col]}")

            if audio_col and audio_col in df.columns:
                audio_url = row.get(audio_col)
                if audio_url is not None and str(audio_url).strip() not in ("", "nan", "None"):
                    url = str(audio_url).strip()
                    parts.append(
                        f"<b>Interview audio:</b><br>"
                        f"<a href='{url}' target='_blank'>Open audio link</a><br>"
                        f"<small>Use the panel below the map to play &amp; transcribe</small>"
                    )

            for c in popup_cols:
                if c in df.columns and c not in (agent_col, state_col, lat_col, lon_col, audio_col, date_col):
                    parts.append(f"<b>{c}:</b> {row[c]}")

            parts.append(f"<small>Row index: {idx}</small>")
            popup = "<br>".join(parts) if parts else f"Row {idx}"

            color = "red" if is_failed else "green"
            icon = "exclamation-sign" if is_failed else "ok-sign"

            # tooltip for quick info
            tip = []
            if agent_col and agent_col in df.columns:
                tip.append(str(row[agent_col]))
            if date_col and date_col in df.columns:
                tip.append(str(row[date_col]))
            tooltip = " | ".join(tip) if tip else f"Row {idx}"

            marker = folium.Marker(
                location=[lat, lon],
                popup=folium.Popup(popup, max_width=300),
                tooltip=tooltip,
                icon=folium.Icon(color=color, icon=icon)
            )

            if is_failed:
                marker.add_to(failed_cluster)
                folium.Circle(
                    location=[lat, lon],
                    radius=80,
                    color="red",
                    fill=True,
                    fill_color="red",
                    fill_opacity=0.25,
                    weight=2
                ).add_to(m)
            else:
                marker.add_to(normal_cluster)

    folium.LayerControl().add_to(m)
    return m


def find_nearest_row(df: pd.DataFrame, lat_col: str, lon_col: str, click_lat: float, click_lon: float):
    """Return index of nearest row to clicked map coordinates."""
    if lat_col not in df.columns or lon_col not in df.columns:
        return None
    work = df[[lat_col, lon_col]].copy()
    work[lat_col] = pd.to_numeric(work[lat_col], errors="coerce")
    work[lon_col] = pd.to_numeric(work[lon_col], errors="coerce")
    work = work.dropna()
    if work.empty:
        return None
    dist = (work[lat_col] - click_lat) ** 2 + (work[lon_col] - click_lon) ** 2
    return dist.idxmin()