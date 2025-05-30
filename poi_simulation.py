import streamlit as st
import pandas as pd
import geopandas as gpd
import folium
from shapely.ops import unary_union
import tempfile
import os
import math
from streamlit_folium import st_folium

st.set_page_config(layout="wide")

uploaded_csv = st.file_uploader("Upload CSV (POI)", type="csv")
uploaded_tab_files = st.file_uploader("Upload .TAB dan file pendukung (.tab, .map, .id, .ind, .dat)", type=["tab", "map", "id", "ind", "dat"], accept_multiple_files=True)

if uploaded_csv and uploaded_tab_files:
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, uploaded_csv.name)
        with open(csv_path, "wb") as f:
            f.write(uploaded_csv.read())

        data = pd.read_csv(csv_path)
        data = data.rename(columns={'distance_weighted': 'radius'})

        tab_path = ""
        for f in uploaded_tab_files:
            out_path = os.path.join(tmpdir, f.name)
            with open(out_path, "wb") as of:
                of.write(f.read())
            if f.name.lower().endswith(".tab"):
                tab_path = out_path

        if tab_path == "":
            st.error("File .TAB belum diunggah.")
        else:
            poly_df = gpd.read_file(tab_path)
            poly_naru = poly_df[poly_df['KETERANGAN_POI'].isin([
                'New POI NARU 2024', 'POI NARU 2024', 'NEW POI NARU 2024'
            ])]
            poly_naru['geometry'] = poly_naru['geometry'].buffer(0)
            external_poly = gpd.GeoSeries([unary_union(poly_naru['geometry'])], crs='EPSG:4326').to_crs(epsg=3857)

            batch_size = 100
            total_batches = math.ceil(len(data) / batch_size)
            all_gdfs = []

            for i in range(total_batches):
                batch = data.iloc[i*batch_size:(i+1)*batch_size].copy()
                gdf = gpd.GeoDataFrame(
                    batch,
                    geometry=gpd.points_from_xy(batch['longitude_fix'], batch['latitude_fix']),
                    crs='EPSG:4326'
                ).to_crs(epsg=3857)

                gdf['buffer'] = gdf.buffer(gdf['radius']).buffer(0)
                gdf['poi_final'] = None
                gdf.loc[gdf['priority'] == 'P1', 'poi_final'] = 'P1'

                p1_buffers = gdf[gdf['priority'] == 'P1']['buffer']
                p2_mask = gdf['priority'] == 'P2'

                def p2_recommendation(row):
                    geom = row['buffer']
                    if geom is None:
                        return None
                    if any(geom.touches(pb) or geom.intersects(pb) for pb in p1_buffers):
                        return 'P2'
                    if external_poly.iloc[0] is not None and geom.intersects(external_poly.iloc[0]):
                        return 'P2'
                    return None

                gdf.loc[p2_mask, 'poi_final'] = gdf.loc[p2_mask].apply(p2_recommendation, axis=1)
                gdf = gdf.to_crs(epsg=4326)
                gdf['buffer_wgs84'] = gdf['buffer'].to_crs(epsg=4326)
                all_gdfs.append(gdf)

            final_gdf = pd.concat(all_gdfs, ignore_index=True)
            final_gdf = final_gdf.to_crs(epsg=4326)
            final_gdf['buffer_wgs84'] = final_gdf['buffer'].to_crs(epsg=4326)

            m = folium.Map(location=[-6.22, 106.815], zoom_start=14)

            color_map = {'P1': 'red', 'P2': 'blue'}
            default_color = 'green'

            def style_function_factory(cat):
                def style_function(x):
                    return {
                        'fillColor': color_map.get(cat, default_color),
                        'color': 'black',
                        'weight': 1,
                        'fillOpacity': 0.3
                    }
                return style_function

            for poi_cat, group in final_gdf.groupby('poi_final'):
                buffers = list(group['buffer_wgs84'])
                if not buffers:
                    continue
                merged = unary_union(buffers)
                geoms = [merged] if merged.geom_type == 'Polygon' else merged.geoms
                for geom in geoms:
                    folium.GeoJson(
                        data=geom.__geo_interface__,
                        style_function=style_function_factory(poi_cat),
                        tooltip=f"POI Final: {poi_cat}"
                    ).add_to(m)

            if not external_poly.empty:
                folium.GeoJson(
                    external_poly.to_crs(epsg=4326).geometry.iloc[0],
                    style_function=lambda x: {
                        'fillColor': 'yellow',
                        'color': 'orange',
                        'weight': 3,
                        'fillOpacity': 0.4
                    }
                ).add_to(m)

            st_folium(m, width=1000, height=700)
