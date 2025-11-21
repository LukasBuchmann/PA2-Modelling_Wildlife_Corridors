import os
import math
import requests
import sys
import gc
import pandas as pd
import geopandas as gpd
import osmnx as ox
import pyrosm
import rasterio
from rasterio import features
from rasterio.enums import MergeAlg
from rasterio.transform import Affine
import numpy as np
from shapely.geometry import box
from pathlib import Path

# --- 1. PATH & PARAMETER SETUP ---
print("Start")

# I identify the directory of this script to ensure relative paths work
SCRIPT_DIR = Path(__file__).resolve().parent
# I determine the project root by moving two levels up
PROJECT_ROOT = SCRIPT_DIR.parent.parent 

# I define the main subdirectories for data and results
DATA_DIR = PROJECT_ROOT / "data"
RESULTS_DIR = PROJECT_ROOT / "results"
TEMP_DIR = RESULTS_DIR / "temp_files"

# I ensure all necessary directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# I define the paths for input cost tables
OSM_COST_CSV_PATH = DATA_DIR / "osm_resistance_costs.csv"
CLC_COST_CSV_PATH = DATA_DIR / "clc_resistance_costs.csv"

# I define the paths for the raw OpenStreetMap PBF files
PBF_PATH_DE = DATA_DIR / "baden-wuerttemberg-latest.osm.pbf"
PBF_PATH_CH = DATA_DIR / "switzerland-latest.osm.pbf"

# I define paths for processed cache files to speed up re-runs
PROCESSED_OSM_CACHE = DATA_DIR / "processed_osm_data.gpkg"
CLC_RECLASSIFIED_PATH = TEMP_DIR / "temp_raster_clc_reclassified.tif"
CLC_PRECLIPPED_VECTOR_PATH = DATA_DIR / "U2018_CLC2018_V2020_20u1.gpkg" 

# I define the path for the final output raster
FINAL_RASTER = RESULTS_DIR / "final_resistance_surface.tif"

print("All packages imported successfully.")
print(f"Base Directory:    {PROJECT_ROOT}")
print(f"Data Directory:    {DATA_DIR}")
print(f"Results Directory: {RESULTS_DIR}")
print(f"Temp Directory:    {TEMP_DIR}")

# I set the core parameters for the spatial analysis
TARGET_CRS = "EPSG:32632"
AOI_NAME = "Kanton Schaffhausen"
BUFFER_METERS = 1000
PIXEL_SIZE = 10

# --- 2. GRID DEFINITION ---
print(f"--- Step 1: Data Preparation ---")
print("1. Defining Grid...")

try:
    # I define the Area of Interest (AOI)
    print(f"   Defining AOI from '{AOI_NAME}'...")

    # I fetch the boundary of Schaffhausen using OSMnx
    gdf_sh_wgs = ox.geocode_to_gdf(AOI_NAME)

    # I reproject the boundary to the target metric CRS (UTM 32N)
    gdf_sh_proj = gdf_sh_wgs.to_crs(TARGET_CRS)

    # I add a buffer to the polygon to avoid edge effects
    print(f"   Buffering polygon by {BUFFER_METERS}m...")
    buffered_polygon = gdf_sh_proj.buffer(BUFFER_METERS)
    bounds = buffered_polygon.total_bounds

    # I create a rectangular box around the buffered area
    aoi_poly = box(*bounds)
    print(f"   Final rectangular AOI defined.")

    # I also create a WGS84 version of the bounding box for PBF data filtering
    aoi_poly_wgs = gpd.GeoSeries([aoi_poly], crs=TARGET_CRS).to_crs("EPSG:4326").iloc[0]
    aoi_bounds_wgs = aoi_poly_wgs.bounds

    # I create a GeoDataFrame for the AOI to use in clipping operations
    aoi_gdf = gpd.GeoDataFrame(geometry=[aoi_poly], crs=TARGET_CRS)

except Exception as e:
    print(f"Error defining AOI: {e}")
    sys.exit(1)

# I calculate the master grid dimensions based on the AOI and pixel size
print("2. Defining Master Grid from AOI...")
min_x, min_y, max_x, max_y = aoi_poly.bounds

width = math.ceil((max_x - min_x) / PIXEL_SIZE)
height = math.ceil((max_y - min_y) / PIXEL_SIZE)

# I define the affine transform for the raster
transform = Affine.translation(min_x, max_y) * Affine.scale(PIXEL_SIZE, -PIXEL_SIZE)

# I store the master grid metadata for all subsequent raster operations
master_grid_meta = {
    'crs': TARGET_CRS,
    'transform': transform,
    'height': height,
    'width': width,
    'driver': 'GTiff'
}
master_shape = (height, width)

print(f"   Master Grid defined:")
print(f"   Shape (h, w): {master_shape}")
print(f"   Resolution: {PIXEL_SIZE}m")

# --- 3. DATA DOWNLOAD ---
print("3. Checking for required .pbf files...")

PBF_URL_DE = "https://download.geofabrik.de/europe/germany/baden-wuerttemberg-latest.osm.pbf"
PBF_URL_CH = "https://download.geofabrik.de/europe/switzerland-latest.osm.pbf"
files_to_download = [(PBF_PATH_DE, PBF_URL_DE), (PBF_PATH_CH, PBF_URL_CH)]

def download_file(url, local_path):
    """I use this helper function to download large files in chunks."""
    print(f"   Downloading {local_path.name}... (This may take 2-10 minutes)")
    try:
        with requests.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            with open(local_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192): 
                    f.write(chunk)
        print(f"   Download complete: {local_path.name}")
    except Exception as e:
        print(f"!!! ERROR downloading {url}: {e}")
        if local_path.exists(): os.remove(local_path)
        raise

for path, url in files_to_download:
    if not path.exists():
        print(f"   '{path.name}' not found.")
        download_file(url, path)
    else:
        print(f"   Found '{path.name}'.")

print("   All required .pbf files are present.")

# --- 4. CORINE LAND COVER PROCESSING ---
print(f"4. Checking for processed Corine file ('{CLC_RECLASSIFIED_PATH.name}')...")

if CLC_RECLASSIFIED_PATH.exists():
    print(f"   Found '{CLC_RECLASSIFIED_PATH.name}'. Skipping processing.")
else:
    print(f"   Processing Corine data (Simple Vector Workflow)...")
    DEFAULT_CLC_RESISTANCE = np.nan

    if not CLC_PRECLIPPED_VECTOR_PATH.exists():
        print(f"!!! ERROR: Pre-clipped CLC Vector file not found at '{CLC_PRECLIPPED_VECTOR_PATH}'")
        raise FileNotFoundError(f"Missing pre-clipped CLC file: {CLC_PRECLIPPED_VECTOR_PATH}")

    try:
        # I load the resistance lookup table
        clc_res_map_df = pd.read_csv(CLC_COST_CSV_PATH)
        clc_res_map_df['clc_code'] = clc_res_map_df['clc_code'].astype(int)
        print(f"   Loaded {len(clc_res_map_df)} resistance rules.")

        # I load the pre-clipped Corine vector data
        print(f"   Loading pre-clipped CLC vector: '{CLC_PRECLIPPED_VECTOR_PATH.name}'...")
        clc_gdf = gpd.read_file(CLC_PRECLIPPED_VECTOR_PATH)
        print(f"   ...Loaded {len(clc_gdf)} polygons.")

        # I reproject the data to match the project CRS
        clc_proj = clc_gdf.to_crs(master_grid_meta['crs'])
        del clc_gdf
        gc.collect()

        # I clip the data to the exact AOI
        print("   Clipping reprojected CLC to precise AOI geometry...")
        clc_clipped = gpd.clip(clc_proj, aoi_gdf.geometry)
        print(f"   ...Clipping complete. {len(clc_clipped)} polygons remaining.")
        del clc_proj
        gc.collect()
        
        if clc_clipped.empty:
            raise ValueError("CLC clipping resulted in empty dataframe.")

        # I merge the resistance values onto the vector data
        print("   Merging resistance values...")
        clc_clipped['Code_18'] = clc_clipped['Code_18'].astype(int)
        clc_with_costs = clc_clipped.merge(clc_res_map_df, left_on='Code_18', right_on='clc_code')
        
        if clc_with_costs.empty:
            raise ValueError("CLC resistance merge failed (no matches found).")

        # I save the intermediate vector for inspection
        temp_vector_path = TEMP_DIR / "temp_vector_clc_reclassified.gpkg"
        clc_with_costs[['Code_18', 'clc_code', 'resistance', 'geometry']].to_file(temp_vector_path, driver="GPKG")
        print(f"   ...Intermediate vector saved to '{temp_vector_path}'")

        # I rasterize the vector polygons into a resistance surface
        print("   Rasterizing vector polygons...")
        shapes = [(row.geometry, row.resistance) for row in clc_with_costs.itertuples() if row.geometry]
        clc_reclassified_data = np.full(master_shape, DEFAULT_CLC_RESISTANCE, dtype=np.float32)

        features.rasterize(
            shapes=shapes,
            out=clc_reclassified_data,
            transform=master_grid_meta['transform'],
            all_touched=True,
            fill=DEFAULT_CLC_RESISTANCE,
            dtype=np.float32
        )
        
        # I save the final CLC raster
        meta_to_save = master_grid_meta.copy()
        meta_to_save.update(dtype=np.float32, count=1, nodata=None)
        with rasterio.open(CLC_RECLASSIFIED_PATH, 'w', **meta_to_save) as dst:
            dst.write(clc_reclassified_data, 1)
        print(f"   ...Corine fallback raster saved to '{CLC_RECLASSIFIED_PATH.name}'")

    except Exception as e:
        print(f"!!! Error processing Corine vector data: {e} !!!")
        raise

# --- 5. OPENSTREETMAP PROCESSING ---
print(f"5. Checking for processed OSM cache ('{PROCESSED_OSM_CACHE.name}')...")

if PROCESSED_OSM_CACHE.exists():
    print(f"   Found fast-loading cache file. Loading...")
    osm_gdf = gpd.read_file(PROCESSED_OSM_CACHE)
    print(f"   ...Cache loaded. Fetched {len(osm_gdf)} features.")
else:
    print(f"   Cache file not found. Starting full data processing...")
    
    # I load the resistance rules to determine which keys to extract
    resistance_df = pd.read_csv(OSM_COST_CSV_PATH)
    needed_keys = resistance_df['osm_key'].unique().tolist()
    tags_filter = {key: True for key in needed_keys}
    bbox_wgs_list = [aoi_bounds_wgs[0], aoi_bounds_wgs[1], aoi_bounds_wgs[2], aoi_bounds_wgs[3]]

    # I extract data for the German part of the AOI
    print("   Processing German data (Baden-Württemberg)... THIS IS SLOW.")
    osm_de = pyrosm.OSM(str(PBF_PATH_DE), bounding_box=bbox_wgs_list) 
    osm_gdf_de = osm_de.get_data_by_custom_criteria(custom_filter=tags_filter)
    print("   ...German data complete.")

    # I extract data for the Swiss part of the AOI
    print("   Processing Swiss data... THIS IS SLOW.")
    osm_ch = pyrosm.OSM(str(PBF_PATH_CH), bounding_box=bbox_wgs_list)
    osm_gdf_ch = osm_ch.get_data_by_custom_criteria(custom_filter=tags_filter)
    print("   ...Swiss data complete.")

    # I combine and clean the datasets
    print("   Combining and cleaning data...")
    osm_gdf_wgs = pd.concat([osm_gdf_de, osm_gdf_ch]).drop_duplicates(subset=['id'])
    del osm_gdf_de, osm_gdf_ch, osm_de, osm_ch
    gc.collect()

    # I keep only the necessary columns
    needed_cols = ['id', 'geometry'] + needed_keys
    cols_to_keep = [col for col in needed_cols if col in osm_gdf_wgs.columns]
    osm_gdf_wgs = osm_gdf_wgs[cols_to_keep]

    # I reproject the data to the target CRS
    print("   Reprojecting OSM data...")
    osm_gdf = osm_gdf_wgs.to_crs(TARGET_CRS)

    # I filter for valid geometries
    osm_gdf = osm_gdf[osm_gdf.geometry.notna()]
    osm_gdf = osm_gdf[osm_gdf.geometry.geom_type.isin(['Polygon', 'LineString', 'MultiPolygon', 'MultiLineString'])]
    print(f"   Fetched and processed {len(osm_gdf)} relevant OSM features.")
    
    # I cache the result to the disk
    print(f"   Saving processed data to cache file: '{PROCESSED_OSM_CACHE.name}'")
    osm_gdf.to_file(PROCESSED_OSM_CACHE, driver="GPKG")
    print("   ...Cache file saved.")

# --- 6. INTERMEDIATE OSM RASTERS ---
print("6. Generating intermediate rasters for OSM features...")

# I load the rules again to ensure I have the priority info
resistance_df = pd.read_csv(OSM_COST_CSV_PATH)
meta_to_save = master_grid_meta.copy()
meta_to_save.update(dtype=np.float32, count=1, nodata=0.0)

all_osm_keys = resistance_df['osm_key'].unique()

for osm_key in all_osm_keys:
    print(f"   Processing key: '{osm_key}'")
    
    # I get the rules specific to this key, sorted by priority
    key_rules = resistance_df[resistance_df['osm_key'] == osm_key].sort_values('priority', ascending=True)
    
    if key_rules.empty or osm_key not in osm_gdf.columns:
        continue
        
    # I filter the GeoDataFrame for features containing this key
    relevant_values = key_rules['osm_value'].unique()
    if 'yes' in relevant_values:
        features_for_key_gdf = osm_gdf[osm_gdf[osm_key].notna()].copy()
    else:
        features_for_key_gdf = osm_gdf[osm_gdf[osm_key].isin(relevant_values)].copy()

    if features_for_key_gdf.empty:
        continue
        
    # I map the resistance values to the features
    value_resistance_map = key_rules.set_index('osm_value')['resistance'].to_dict()
    if 'yes' in relevant_values:
         features_for_key_gdf['resistance'] = value_resistance_map.get('yes', 0)
    else:
         features_for_key_gdf['resistance'] = features_for_key_gdf[osm_key].map(value_resistance_map)

    # I save an intermediate vector file for debugging
    temp_vector_path = TEMP_DIR / f"temp_vector_{osm_key}.gpkg"
    try:
        cols_to_save = ['id', osm_key, 'geometry', 'resistance']
        features_for_key_gdf[cols_to_save].to_file(temp_vector_path, driver="GPKG")
    except Exception as e:
        print(f"   ...Warning: Could not save debug vector {temp_vector_path}: {e}")

    # I create an empty raster for this key
    key_raster = np.full(master_shape, 0.0, dtype=np.float32)
    temp_raster_path = TEMP_DIR / f"temp_raster_{osm_key}.tif"

    # I burn the features into the raster based on priority
    for _, row in key_rules.iterrows():
        key, value, resistance = row['osm_key'], row['osm_value'], row['resistance']
        
        if value == 'yes':
            features_to_rasterize = features_for_key_gdf
        else:
            features_to_rasterize = features_for_key_gdf[features_for_key_gdf[key] == value]
        
        if features_to_rasterize.empty:
            continue

        shapes = [(geom, resistance) for geom in features_to_rasterize.geometry]
        
        features.rasterize(
            shapes=shapes,
            out=key_raster,
            transform=master_grid_meta['transform'],
            merge_alg=MergeAlg.replace,
            all_touched=True,
            dtype=np.float32
        )
    
    # I save the raster for this key
    with rasterio.open(temp_raster_path, 'w', **meta_to_save) as dst:
        dst.write(key_raster, 1)
    print(f"   ...Saved raster: {temp_raster_path.name}")

# --- 7. FINAL COMBINATION ---
print("7. Combining all layers into the final resistance surface...")

try:
    # I load the background Corine raster
    print(f"   Loading background: {CLC_RECLASSIFIED_PATH.name}")
    with rasterio.open(CLC_RECLASSIFIED_PATH) as src:
        final_raster = src.read(1).astype(np.float32)
        meta = src.meta.copy()
        meta.update(dtype=np.float32, nodata=None)
    
    # I find all the OSM intermediate rasters
    osm_raster_files = list(TEMP_DIR.glob("temp_raster_*.tif"))
    print(f"   Found {len(osm_raster_files)} overlay layers.")

    # I loop through and merge them onto the background
    for raster_file in osm_raster_files:
        print(f"   Merging: {raster_file.name}")
        with rasterio.open(raster_file) as src:
            osm_layer = src.read(1)
            # I handle NoData by setting it to 0
            osm_layer = np.nan_to_num(osm_layer, nan=0.0)
            # I use the maximum value to ensure barriers override lower costs
            final_raster = np.maximum(final_raster, osm_layer)

    # I save the final result
    with rasterio.open(FINAL_RASTER, 'w', **meta) as dst:
        dst.write(final_raster, 1)
        
    print(f"\n   SUCCESS: Final resistance surface saved to '{FINAL_RASTER}'")

except Exception as e:
    print(f"!!! Critical Error during combination: {e}")
    raise