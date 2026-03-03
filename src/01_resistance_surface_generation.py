"""
Module: 01_resistance_surface_generation.py
Project: PA2 - Modelling Wildlife Corridors
Author: Lukas Buchmann
Date: December 2025
Institution: ZHAW, Institute of Computational Life Sciences

Description:
    This script generates a high-resolution resistance surface for wildlife connectivity modeling 
    (specifically for Capreolus capreolus) in the Canton of Schaffhausen and surrounding areas.

    It integrates two primary data sources:
    1. Corine Land Cover (CLC): Acts as the continuous background layer (Base Matrix).
    2. OpenStreetMap (OSM): Provides high-resolution infrastructure and barrier data (Overlays).

    The script adheres to reproducibility standards by automating data acquisition (OSM), 
    rasterization, and surface combination using a 'maximum resistance' rule.

Usage:
    Run this script directly to generate the 'final_resistance_surface.tif' in the results folder.
    Ensure all required input files (CLC gpkg, OSM .pbf) are present in the 'data' directory.

Dependencies:
    - numpy, pandas, geopandas
    - rasterio, shapely
    - osmnx, pyrosm
"""

import sys
import os
import gc
from tqdm import tqdm
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

ox.settings.use_cache = False

# --- CONFIGURATION & PATHS ---------------------------------------------------
# Using pathlib for OS-agnostic path handling
SCRIPT_DIR = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RESULTS_DIR = PROJECT_ROOT / "results"
TEMP_DIR = RESULTS_DIR / "temp_files"

# Input Files
OSM_COST_CSV = DATA_DIR / "osm_resistance_costs.csv"
CLC_COST_CSV = DATA_DIR / "clc_resistance_costs.csv"
CLC_VECTOR_RAW = DATA_DIR / "U2018_CLC2018_V2020_20u1.gpkg"
PBF_DE = DATA_DIR / "baden-wuerttemberg-latest.osm.pbf"
PBF_CH = DATA_DIR / "switzerland-latest.osm.pbf"

# Outputs (Final)
FINAL_RASTER = RESULTS_DIR / "final_resistance_surface.tif"

# Parameters
TARGET_CRS = "EPSG:32632"  # Coordinate Reference System: UTM 32N
AOI_NAME = "Kanton Schaffhausen"
BUFFER_METERS = 1000       # Buffer to minimize edge effects
PIXEL_SIZE = 10            # Spatial resolution in meters

# Ensure output directories exist
for d in [DATA_DIR, RESULTS_DIR, TEMP_DIR]:
    d.mkdir(parents=True, exist_ok=True)


# --- CORE FUNCTIONS ----------------------------------------------------------

def define_aoi_and_grid(aoi_name, buffer_m, pixel_size, crs):
    """
    Defines the Area of Interest (AOI) and the target raster grid properties.

    Retrieves the administrative boundary from OpenStreetMap, projects it to the 
    target CRS, applies a buffer, and calculates the affine transform for the raster.

    Args:
        aoi_name (str): Name of the place to retrieve (e.g., "Kanton Schaffhausen").
        buffer_m (int): Buffer distance in meters.
        pixel_size (int): Resolution of the output raster in meters.
        crs (str): Target Coordinate Reference System (e.g., "EPSG:32632").

    Returns:
        tuple: (aoi_gdf, aoi_wgs_bounds, meta, (height, width))
            - aoi_gdf (GeoDataFrame): Buffered AOI polygon in target CRS.
            - aoi_wgs_bounds (tuple): Bounding box in WGS84 (minx, miny, maxx, maxy).
            - meta (dict): Rasterio metadata dictionary for the output raster.
            - shape (tuple): Dimensions of the raster (height, width).
    """
    print(f"--- Step 1: Defining AOI for '{aoi_name}' ---")
    try:
        # Retrieve boundary from OSM
        gdf_wgs = ox.geocode_to_gdf(aoi_name)
        
        # Reproject to metric system for accurate buffering
        gdf_proj = gdf_wgs.to_crs(crs)
        buffered_poly = gdf_proj.buffer(buffer_m).iloc[0]
        
        # Create bounding box (Extent)
        bounds = buffered_poly.bounds
        aoi_poly = box(*bounds)
        aoi_gdf = gpd.GeoDataFrame(geometry=[aoi_poly], crs=crs)
        
        # Get WGS84 bounds for Pyrosm (which requires Lat/Lon)
        aoi_wgs = aoi_gdf.to_crs("EPSG:4326").geometry.iloc[0]

        # Calculate Raster Dimensions
        width = int(np.ceil((bounds[2] - bounds[0]) / pixel_size))
        height = int(np.ceil((bounds[3] - bounds[1]) / pixel_size))
        
        # Define Affine Transform (Top-Left origin, standard for GeoTIFF)
        transform = Affine.translation(bounds[0], bounds[3]) * Affine.scale(pixel_size, -pixel_size)

        meta = {
            'driver': 'GTiff', 
            'dtype': 'float32', 
            'nodata': None,
            'width': width, 
            'height': height, 
            'count': 1,
            'crs': crs, 
            'transform': transform
        }
        
        return aoi_gdf, aoi_wgs.bounds, meta, (height, width)
    
    except Exception as e:
        sys.exit(f"CRITICAL ERROR defining AOI: {e}")


def process_clc_layer(aoi_gdf, meta, shape, default_val=np.nan):
    """
    Processes the Corine Land Cover (CLC) dataset to create the base resistance raster.

    Clips the CLC vector data to the AOI, joins resistance values from CSV, 
    and rasterizes the result. Uses caching to speed up subsequent runs.

    Args:
        aoi_gdf (GeoDataFrame): The AOI polygon for clipping.
        meta (dict): Raster metadata for the output.
        shape (tuple): Dimensions of the target raster.
        default_val (float, optional): Fill value for the raster initialization.

    Returns:
        Path: File path to the generated intermediate CLC raster.
    """
    out_raster_path = TEMP_DIR / "intermediate_clc_base.tif"
    
    # Check for cache
    if out_raster_path.exists():
        print(f"--- Step 2: Found cached CLC raster. Skipping. ---")
        return out_raster_path

    print(f"--- Step 2: Processing Corine Land Cover ---")
    try:
        # Load cost table and vector data
        costs = pd.read_csv(CLC_COST_CSV)
        clc = gpd.read_file(CLC_VECTOR_RAW)
        
        # Reproject and Clip
        clc = clc.to_crs(meta['crs'])
        clc = gpd.clip(clc, aoi_gdf.geometry)

        # Join Resistance Values (Code_18 matches CLC code)
        clc['Code_18'] = clc['Code_18'].astype(int)
        clc = clc.merge(costs, left_on='Code_18', right_on='clc_code', how='inner')
        
        # Rasterize
        shapes = ((geom, val) for geom, val in zip(clc.geometry, clc.resistance))
        raster = np.full(shape, default_val, dtype=np.float32)
        features.rasterize(shapes=shapes, out=raster, transform=meta['transform'], all_touched=True)

        # Save Result
        with rasterio.open(out_raster_path, 'w', **meta) as dst:
            dst.write(raster, 1)
        
        # Cleanup memory
        del clc, raster
        gc.collect()
        
        return out_raster_path
    
    except Exception as e:
        sys.exit(f"Error processing CLC: {e}")


def fetch_process_osm_vectors(aoi_bounds_wgs, meta):
    """
    Downloads and parses OpenStreetMap (OSM) PBF data for the study area.

    Handles downloading large PBF files (DE and CH) if missing, then uses Pyrosm 
    to filter and extract features based on the resistance cost CSV.

    Args:
        aoi_bounds_wgs (tuple): Bounding box in WGS84 coordinates.
        meta (dict): Metadata containing the target CRS.

    Returns:
        GeoDataFrame: A combined, cleaned, and reprojected GeoDataFrame of OSM features.
    """
    vector_cache = TEMP_DIR / "intermediate_osm_merged.gpkg"
    
    # Check for cache
    if vector_cache.exists():
        print("--- Step 3: Found cached OSM Vectors. Loading... ---")
        return gpd.read_file(vector_cache)

    print("--- Step 3: Processing OSM Vectors (5-20 min) ---")
    
    # Define source URLs for PBF files
    urls = {
        PBF_DE: "https://download.geofabrik.de/europe/germany/baden-wuerttemberg-latest.osm.pbf",
        PBF_CH: "https://download.geofabrik.de/europe/switzerland-latest.osm.pbf"
    }

    # 1. DOWNLOAD
    for path, url in urls.items():
        if not path.exists():
            print(f"Downloading {path.name}...")
            try:
                response = requests.get(url, stream=True)
                response.raise_for_status()
                total_size = int(response.headers.get('content-length', 0))
                
                with open(path, 'wb') as f, tqdm(
                    desc=path.name,
                    total=total_size,
                    unit='iB',
                    unit_scale=True,
                    unit_divisor=1024,
                ) as bar:
                    for chunk in response.iter_content(chunk_size=8192):
                        size = f.write(chunk)
                        bar.update(size)
            except Exception as e:
                # Remove partially downloaded file if error occurs
                if path.exists():
                    path.unlink()
                sys.exit(f"Error downloading {path.name}: {e}")

    # 2. PARSING (Pyrosm)
    # Define custom filter based on CSV keys (e.g., highway, landuse)
    res_df = pd.read_csv(OSM_COST_CSV)
    filter_keys = res_df['osm_key'].unique().tolist()
    custom_filter = {k: True for k in filter_keys}
    bbox = list(aoi_bounds_wgs)

    try:
        print(f"Parsing Germany Data ({PBF_DE.name})...")
        osm_de = pyrosm.OSM(str(PBF_DE), bounding_box=bbox).get_data_by_custom_criteria(custom_filter=custom_filter)
        
        print(f"Parsing Switzerland Data ({PBF_CH.name})...")
        osm_ch = pyrosm.OSM(str(PBF_CH), bounding_box=bbox).get_data_by_custom_criteria(custom_filter=custom_filter)
        
        print("Merging and cleaning datasets...")
        osm = pd.concat([osm_de, osm_ch]).drop_duplicates(subset=['id'])
        
        # Cleanup RAM immediately
        del osm_de, osm_ch
        gc.collect()

        # Filter columns and reproject
        cols = ['id', 'geometry'] + [c for c in filter_keys if c in osm.columns]
        osm = osm[cols].to_crs(meta['crs'])
        
        # Keep only relevant geometries (Lines/Polygons)
        osm = osm[osm.geometry.geom_type.isin(['Polygon', 'LineString', 'MultiPolygon', 'MultiLineString'])]
        
        print(f"Saving merged vectors to {vector_cache.name}...")
        osm.to_file(vector_cache, driver="GPKG")
        return osm

    except Exception as e:
        sys.exit(f"Error processing OSM vectors: {e}")


def rasterize_osm_features(osm_gdf, meta, shape):
    """
    Rasterizes OSM vectors into separate overlay layers for each feature key.

    Iterates through OSM keys (e.g., 'highway', 'waterway'), assigns resistance values,
    and rasterizes them. Prioritizes features based on the CSV configuration.

    Args:
        osm_gdf (GeoDataFrame): The processed OSM vector data.
        meta (dict): Raster metadata.
        shape (tuple): Target raster dimensions.

    Returns:
        list: A list of file paths to the generated intermediate raster files.
    """
    print("--- Step 4: Rasterizing OSM Features ---")
    res_df = pd.read_csv(OSM_COST_CSV)
    raster_files = []
    
    # Update metadata for overlays (0.0 is transparent/no resistance yet)
    meta_overlay = meta.copy()
    meta_overlay.update(nodata=0.0)

    for key in res_df['osm_key'].unique():
        if key not in osm_gdf.columns: continue
        
        # Get rules for this key, sorted by priority (e.g., Motorway > Path)
        rules = res_df[res_df['osm_key'] == key].sort_values('priority')
        
        # Filter GDF for this key
        valid_vals = rules['osm_value'].unique()
        if 'yes' in valid_vals: # Handle generic tags
            subset = osm_gdf[osm_gdf[key].notna()].copy()
        else:
            subset = osm_gdf[osm_gdf[key].isin(valid_vals)].copy()
        
        if subset.empty: continue

        # Map resistance values
        val_map = rules.set_index('osm_value')['resistance'].to_dict()
        if 'yes' in valid_vals:
            subset['resistance'] = val_map.get('yes', 0)
        else:
            subset['resistance'] = subset[key].map(val_map)

        # Init empty raster
        out_path = TEMP_DIR / f"intermediate_raster_{key}.tif"
        raster = np.full(shape, 0.0, dtype=np.float32)
        
        # Rasterize by priority groups
        for _, row in rules.iterrows():
            val = row['osm_value']
            # Select features matching specific value or generic 'yes'
            geom_subset = subset if val == 'yes' else subset[subset[key] == val]
            if geom_subset.empty: continue
            
            shapes = ((g, row['resistance']) for g in geom_subset.geometry)
            
            # Burn into raster (MergeAlg.replace overwrites lower priority pixels)
            features.rasterize(shapes=shapes, out=raster, transform=meta['transform'], 
                               merge_alg=MergeAlg.replace, all_touched=True)

        # Save intermediate file
        with rasterio.open(out_path, 'w', **meta_overlay) as dst:
            dst.write(raster, 1)
        
        raster_files.append(out_path)

    return raster_files


def combine_surfaces(clc_path, osm_paths):
    """
    Combines the CLC base layer and all OSM overlays into the final resistance surface.

    Uses a 'maximum' logic: The final pixel value is the maximum of the base layer
    and any overlaying infrastructure. This ensures barriers (high cost) overwrite
    habitat (low cost).

    Args:
        clc_path (Path): Path to the base CLC raster.
        osm_paths (list): List of paths to OSM overlay rasters.
    """
    print("--- Step 5: Combining Final Surface ---")
    
    # Load Base Layer
    with rasterio.open(clc_path) as src:
        final_arr = src.read(1)
        meta = src.meta.copy()

    # Overlay OSM Layers
    for p in osm_paths:
        with rasterio.open(p) as src:
            overlay = src.read(1)
            # Treat NoData as 0 so it doesn't affect the maximum
            overlay = np.nan_to_num(overlay, nan=0.0)
            
            # Apply Maximum Rule: Barrier > Habitat
            final_arr = np.maximum(final_arr, overlay)

    # Save Final Result
    meta.update(nodata=None)
    with rasterio.open(FINAL_RASTER, 'w', **meta) as dst:
        dst.write(final_arr, 1)
    
    print(f"SUCCESS: Final surface saved to {FINAL_RASTER}")


# --- MAIN EXECUTION ----------------------------------------------------------

def main():
    """Main execution workflow."""
    # 1. Setup
    aoi_gdf, aoi_wgs_bounds, meta, shape = define_aoi_and_grid(AOI_NAME, BUFFER_METERS, PIXEL_SIZE, TARGET_CRS)
    
    # 2. Process Base Layer
    clc_raster_path = process_clc_layer(aoi_gdf, meta, shape)
    
    # 3. Process Vector Overlays
    osm_gdf = fetch_process_osm_vectors(aoi_wgs_bounds, meta)
    osm_raster_paths = rasterize_osm_features(osm_gdf, meta, shape)
    
    # 4. Combine
    combine_surfaces(clc_raster_path, osm_raster_paths)

if __name__ == "__main__":
    main()