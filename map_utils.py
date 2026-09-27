"""
Folium map helpers.
Failed verification points = RED markers + RED circles, clean points = GREEN.
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
    heat: bool = False,
    satellite: bool = False,
    failed_indexes: Optional[Set] = None
) -> folium.Map:

    clean = df[[lat_col, lon_col]].dropna().copy()
    clean[lat_col] = pd.to_numeric(clean[lat_col], errors="coerce")
    clean[lon_col] = pd.to_numeric(clean[lon_col], errors="coerce")
    clean = clean.dropna()

    if clean.empty:
        return folium.Map(location=[9.0, 8.0], zoom_start=6)

    center_lat = clean[lat_col].mean()
    center_lon = clean[lon_col].mean()

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
        heat_data = clean[[lat_col, lon_col]].values.tolist()
        HeatMap(heat_data, radius=15, blur=20).add_to(m)
    else:
        normal_cluster = MarkerCluster(name="Clean points (green)").add_to(m)
        failed_cluster = MarkerCluster(name="Failed verification (red)").add_to(m)
        popup_cols = popup_cols or []

        for idx, row in df.iterrows():
            try:
                lat = float(row[lat_col])
                lon = float(row[lon_col])
            except (TypeError, ValueError):
                continue

            is_failed = idx in failed_indexes

            popup_parts = []
            if is_failed:
                popup_parts.append("<b style='color:red'>FAILED VERIFICATION</b>")
            if agent_col and agent_col in df.columns:
                popup_parts.append(f"<b>Agent:</b> {row[agent_col]}")
            if state_col and state_col in df.columns:
                popup_parts.append(f"<b>State:</b> {row[state_col]}")
            for c in popup_cols:
                if c in df.columns and c not in (agent_col, state_col, lat_col, lon_col):
                    popup_parts.append(f"<b>{c}:</b> {row[c]}")
            popup = "<br>".join(popup_parts) if popup_parts else f"Row {idx}"

            color = "red" if is_failed else "green"
            icon = "exclamation-sign" if is_failed else "ok-sign"

            marker = folium.Marker(
                location=[lat, lon],
                popup=folium.Popup(popup, max_width=300),
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