"""
ZHAW Project Work 2: Wildlife Corridor Resistance Surface Generation.

This script processes Corine Land Cover (CLC) and OpenStreetMap (OSM) data
to generate a resistance surface for Roe Deer connectivity analysis.
It strictly adheres to reproducibility standards.

Author: Lukas Buchmann
Date: November 2025
"""

import sys
import os
import gc
import requests
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
import osmnx as ox
import pyrosm
import rasterio
from rasterio import features
from rasterio.enums import MergeAlg
from rasterio.transform import Affine
from shapely.geometry import box

# --- CONFIGURATION & PATHS ---
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RESULTS_DIR = PROJECT_ROOT / "results"
TEMP_DIR = RESULTS_DIR / "temp_files"

# Inputs
OSM_COST_CSV = DATA_DIR / "osm_resistance_costs.csv"
CLC_COST_CSV = DATA_DIR / "clc_resistance_costs.csv"
CLC_VECTOR_RAW = DATA_DIR / "U2018_CLC2018_V2020_20u1.gpkg"
PBF_DE = DATA_DIR / "baden-wuerttemberg-latest.osm.pbf"
PBF_CH = DATA_DIR / "switzerland-latest.osm.pbf"

# Outputs (Final)
FINAL_RASTER = RESULTS_DIR / "final_resistance_surface.tif"

# Parameters
TARGET_CRS = "EPSG:32632"  # UTM 32N
AOI_NAME = "Kanton Schaffhausen"
BUFFER_METERS = 1000
PIXEL_SIZE = 10

# Ensure directories exist
for d in [DATA_DIR, RESULTS_DIR, TEMP_DIR]:
    d.mkdir(parents=True, exist_ok=True)


def define_aoi_and_grid(aoi_name, buffer_m, pixel_size, crs):
    """
    Defines the Area of Interest, calculates bounds, and creates raster metadata.
    """
    print(f"--- Step 1: Defining AOI for '{aoi_name}' ---")
    try:
        # Fetch and project boundary
        gdf_wgs = ox.geocode_to_gdf(aoi_name)
        gdf_proj = gdf_wgs.to_crs(crs)
        
        # Buffer and create bounding box
        buffered_poly = gdf_proj.buffer(buffer_m).iloc[0]
        bounds = buffered_poly.bounds  # (minx, miny, maxx, maxy)
        aoi_poly = box(*bounds)
        aoi_gdf = gpd.GeoDataFrame(geometry=[aoi_poly], crs=crs)

        # WGS84 bounds for PBF filtering
        aoi_wgs = aoi_gdf.to_crs("EPSG:4326").geometry.iloc[0]

        # Calculate Grid Dimensions
        width = int(np.ceil((bounds[2] - bounds[0]) / pixel_size))
        height = int(np.ceil((bounds[3] - bounds[1]) / pixel_size))
        transform = Affine.translation(bounds[0], bounds[3]) * Affine.scale(pixel_size, -pixel_size)

        meta = {
            'driver': 'GTiff', 'dtype': 'float32', 'nodata': None,
            'width': width, 'height': height, 'count': 1,
            'crs': crs, 'transform': transform
        }
        
        # Save AOI Vector for debugging
        aoi_gdf.to_file(TEMP_DIR / "debug_aoi_extent.gpkg", driver="GPKG")
        
        return aoi_gdf, aoi_wgs.bounds, meta, (height, width)

    except Exception as e:
        sys.exit(f"CRITICAL ERROR defining AOI: {e}")


def process_clc_layer(aoi_gdf, meta, shape, default_val=np.nan):
    """
    Processes Corine Land Cover: Loads, Clips, Merges Costs, Rasterizes.
    Saves intermediate vector and raster.
    """
    out_raster_path = TEMP_DIR / "intermediate_clc_base.tif"
    out_vector_path = TEMP_DIR / "intermediate_clc_clipped.gpkg"

    if out_raster_path.exists():
        print(f"--- Step 2: Found cached CLC raster. Skipping. ---")
        return out_raster_path

    print(f"--- Step 2: Processing Corine Land Cover ---")
    try:
        costs = pd.read_csv(CLC_COST_CSV)
        
        # Load and Clip
        clc = gpd.read_file(CLC_VECTOR_RAW)
        clc = clc.to_crs(meta['crs'])
        clc = gpd.clip(clc, aoi_gdf.geometry)

        if clc.empty: raise ValueError("CLC clipping resulted in empty data.")

        # Merge Costs
        clc['Code_18'] = clc['Code_18'].astype(int)
        clc = clc.merge(costs, left_on='Code_18', right_on='clc_code', how='inner')
        
        # Save Intermediate Vector
        clc.to_file(out_vector_path, driver="GPKG")
        
        # Rasterize
        shapes = ((geom, val) for geom, val in zip(clc.geometry, clc.resistance))
        raster = np.full(shape, default_val, dtype=np.float32)
        features.rasterize(shapes=shapes, out=raster, transform=meta['transform'], all_touched=True)

        with rasterio.open(out_raster_path, 'w', **meta) as dst:
            dst.write(raster, 1)
        
        # Cleanup
        del clc, raster
        gc.collect()
        return out_raster_path

    except Exception as e:
        sys.exit(f"Error processing CLC: {e}")


def fetch_process_osm_vectors(aoi_bounds_wgs, meta):
    """
    Downloads PBFs, extracts Germany/Swiss data, combines, cleans, and caches vector.
    """
    vector_cache = TEMP_DIR / "intermediate_osm_merged.gpkg"
    
    if vector_cache.exists():
        print("--- Step 3: Found cached OSM Vectors. Loading... ---")
        return gpd.read_file(vector_cache)

    print("--- Step 3: Processing OSM Vectors (This is slow) ---")
    
    # 1. Download PBFs if missing
    urls = {
        PBF_DE: "https://download.geofabrik.de/europe/germany/baden-wuerttemberg-latest.osm.pbf",
        PBF_CH: "https://download.geofabrik.de/europe/switzerland-latest.osm.pbf"
    }
    for path, url in urls.items():
        if not path.exists():
            print(f"Downloading {path.name}...")
            with requests.get(url, stream=True) as r, open(path, 'wb') as f:
                shutil.copyfileobj(r.raw, f)

    # 2. Define Filter
    res_df = pd.read_csv(OSM_COST_CSV)
    filter_keys = res_df['osm_key'].unique().tolist()
    custom_filter = {k: True for k in filter_keys}
    bbox = list(aoi_bounds_wgs)

    # 3. Extract & Combine using Pyrosm
    try:
        print("Parsing PBFs...")
        osm_de = pyrosm.OSM(str(PBF_DE), bounding_box=bbox).get_data_by_custom_criteria(custom_filter=custom_filter)
        osm_ch = pyrosm.OSM(str(PBF_CH), bounding_box=bbox).get_data_by_custom_criteria(custom_filter=custom_filter)
        
        osm = pd.concat([osm_de, osm_ch]).drop_duplicates(subset=['id'])
        
        # Explicit memory management
        del osm_de, osm_ch
        gc.collect()

        # Clean & Reproject
        cols = ['id', 'geometry'] + [c for c in filter_keys if c in osm.columns]
        osm = osm[cols].to_crs(meta['crs'])
        osm = osm[osm.geometry.geom_type.isin(['Polygon', 'LineString', 'MultiPolygon', 'MultiLineString'])]
        
        # Save Intermediate Vector
        osm.to_file(vector_cache, driver="GPKG")
        return osm

    except Exception as e:
        sys.exit(f"Error processing OSM vectors: {e}")


def rasterize_osm_features(osm_gdf, meta, shape):
    """
    Rasterizes OSM features key-by-key based on priority. 
    Saves individual rasters to TEMP_DIR.
    """
    print("--- Step 4: Rasterizing OSM Features ---")
    res_df = pd.read_csv(OSM_COST_CSV)
    raster_files = []
    
    # Prepare raster metadata (0 = NoData for overlays)
    meta_overlay = meta.copy()
    meta_overlay.update(nodata=0.0)

    for key in res_df['osm_key'].unique():
        if key not in osm_gdf.columns: continue

        # Sort rules by priority (important for overlapping features)
        rules = res_df[res_df['osm_key'] == key].sort_values('priority')
        
        # Filter GDF for this key
        valid_vals = rules['osm_value'].unique()
        if 'yes' in valid_vals:
            subset = osm_gdf[osm_gdf[key].notna()].copy()
        else:
            subset = osm_gdf[osm_gdf[key].isin(valid_vals)].copy()
            
        if subset.empty: continue

        # Map Resistance
        val_map = rules.set_index('osm_value')['resistance'].to_dict()
        if 'yes' in valid_vals:
            subset['resistance'] = val_map.get('yes', 0)
        else:
            subset['resistance'] = subset[key].map(val_map)

        # Rasterize
        out_path = TEMP_DIR / f"intermediate_raster_{key}.tif"
        raster = np.full(shape, 0.0, dtype=np.float32)
        
        # Iterate rules to burn in priority order
        for _, row in rules.iterrows():
            val = row['osm_value']
            # Select specific features for this rule
            if val == 'yes': geom_subset = subset
            else: geom_subset = subset[subset[key] == val]
            
            if geom_subset.empty: continue
            
            shapes = ((g, row['resistance']) for g in geom_subset.geometry)
            features.rasterize(shapes=shapes, out=raster, transform=meta['transform'], 
                               merge_alg=MergeAlg.replace, all_touched=True)

        # Save individual raster
        with rasterio.open(out_path, 'w', **meta_overlay) as dst:
            dst.write(raster, 1)
        raster_files.append(out_path)
        print(f"Saved: {out_path.name}")

    return raster_files


def combine_surfaces(clc_path, osm_paths):
    """
    Combines the Base CLC raster with OSM overlays using a Maximum rule.
    """
    print("--- Step 5: Combining Final Surface ---")
    
    # Load Base
    with rasterio.open(clc_path) as src:
        final_arr = src.read(1)
        meta = src.meta.copy()

    # Overlay OSM layers iteratively (Disk-based approach to save RAM)
    for p in osm_paths:
        with rasterio.open(p) as src:
            overlay = src.read(1)
            # 0 is NoData in overlays, convert to 0 for math
            overlay = np.nan_to_num(overlay, nan=0.0)
            # Barriers (high values) override background
            final_arr = np.maximum(final_arr, overlay)

    # Save Final
    meta.update(nodata=None) # Final product has no explicit nodata hole
    with rasterio.open(FINAL_RASTER, 'w', **meta) as dst:
        dst.write(final_arr, 1)
    
    print(f"SUCCESS: Final surface saved to {FINAL_RASTER}")


def main():
    # 1. Define Grid & AOI
    aoi_gdf, aoi_wgs_bounds, meta, shape = define_aoi_and_grid(
        AOI_NAME, BUFFER_METERS, PIXEL_SIZE, TARGET_CRS
    )

    # 2. Process Base Layer (Corine)
    clc_raster_path = process_clc_layer(aoi_gdf, meta, shape)

    # 3. Process Vectors (OSM)
    osm_gdf = fetch_process_osm_vectors(aoi_wgs_bounds, meta)

    # 4. Rasterize OSM Layers
    osm_raster_paths = rasterize_osm_features(osm_gdf, meta, shape)

    # 5. Combine
    combine_surfaces(clc_raster_path, osm_raster_paths)

if __name__ == "__main__":
    main()