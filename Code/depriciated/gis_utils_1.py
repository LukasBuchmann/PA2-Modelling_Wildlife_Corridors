# gis_utils.py
import geopandas as gpd
import rasterio
from rasterio.transform import from_bounds
from rasterio.features import rasterize
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from rasterio.plot import plotting_extent
import pandas as pd

DEFAULT_NODATA = 0
UNIFIED_NODATA_CODE = 0  # NoData code for unified landcover types

def filter_canton(cantonname: str, buffer_m: float = 0) -> tuple[gpd.GeoDataFrame, tuple]:
    """
    Returns the geometry of a specified Swiss canton, buffered, and then
    clipped strictly to the Swiss national boundary, along with its bounding box.

    Parameters
    ----------
    cantonname : str
        Name of the canton to filter (e.g., "Schaffhausen").
    buffer_m : float, optional
        Buffer distance in meters around the canton geometry (default: 0).

    Returns
    -------
    aoi_clipped : GeoDataFrame
        Geometry of the buffered canton, strictly clipped to Switzerland.
    aoi_bbox : tuple
        Bounding box (xmin, ymin, xmax, ymax) of the final clipped AOI.
    """
    boundaries_path = "C:/ZHAW/5.Semester/PA2/data/swissBOUNDARIES3D_1_5_LV95_LN02.gpkg"
    
    # --- 1. Load Canton and Country Boundaries ---
    
    # Load Cantons
    layer_canton = "tlm_kantonsgebiet"
    print(f"Loading canton boundary for {cantonname}...")
    cantons = gpd.read_file(boundaries_path, layer=layer_canton)
    canton = cantons[cantons["name"] == cantonname]
    
    if canton.empty:
        raise ValueError(f"Canton '{cantonname}' not found.")
        
    # Load Switzerland (Country)
    layer_country = "tlm_landesgebiet"
    print("Loading national boundary (Switzerland)...")
    country = gpd.read_file(boundaries_path, layer=layer_country)

    # Ensure CRS alignment before buffering or clipping
    target_crs = canton.crs
    if country.crs != target_crs:
        country = country.to_crs(target_crs)

    # --- 2. Apply Buffer to Canton ---
    if buffer_m > 0:
        print(f"Applying {buffer_m}m buffer...")
        aoi_buffered = canton.copy()
        aoi_buffered["geometry"] = aoi_buffered.geometry.buffer(buffer_m)
    else:
        aoi_buffered = canton
    
    # --- 3. Clip Buffered Area to Swiss National Boundary ---
    # This ensures that any part of the buffer extending into Germany is cut off.
    print("Clipping buffered area to Swiss national boundary...")
    
    # Use gpd.clip to enforce the national border
    aoi_clipped = gpd.clip(aoi_buffered, country)
    
    # --- 4. Compute Bounding Box ---
    xmin, ymin, xmax, ymax = aoi_clipped.total_bounds
    aoi_bbox = (xmin, ymin, xmax, ymax)
    
    print(f"Final AOI clipped to Swiss territory. BBox computed.")
    return aoi_clipped, aoi_bbox

def load_and_clip_vector(filepath: str, layername: str, aoi_geom: gpd.GeoDataFrame, bbox: tuple = None) -> gpd.GeoDataFrame:
    """
    Loads a vector layer, optionally filters by bbox, and clips to AOI geometry.
    """
    print(f"Loading and clipping vector: {layername} from {filepath}")
    
    # Use BBOX for faster initial read if provided
    try:
        if bbox:
            gdf = gpd.read_file(filepath, layer=layername, bbox=bbox, engine="pyogrio")
        else:
            gdf = gpd.read_file(filepath, layer=layername, engine="pyogrio")
    except Exception as e:
         print(f"Pyogrio failed for {layername}, trying default engine. Error: {e}")
         if bbox:
             gdf = gpd.read_file(filepath, layer=layername, bbox=bbox)
         else:
             gdf = gpd.read_file(filepath, layer=layername)

    if gdf.empty:
        print(f"Warning: No features found for {layername} within BBOX.")
        return gdf

    # Ensure CRS match
    if gdf.crs != aoi_geom.crs:
        print(f"Reprojecting {layername} from {gdf.crs} to {aoi_geom.crs}")
        gdf = gdf.to_crs(aoi_geom.crs)
    
    # Perform precise clip
    print(f"Clipping {layername} to AOI geometry...")
    gdf_clipped = gpd.clip(gdf, aoi_geom)
    
    print(f"Loaded and clipped {len(gdf_clipped)} features from {layername}.")
    return gdf_clipped


def define_master_grid_meta(geometries, target_resolution_m, crs):
    """
    Calculates the master grid metadata based on combined geometry bounds.
    """
    print("Defining master grid metadata...")
    total_extent_gdf = gpd.pd.concat(geometries).unary_union
    xmin, ymin, xmax, ymax = total_extent_gdf.bounds

    width = int(np.ceil((xmax - xmin) / target_resolution_m))
    height = int(np.ceil((ymax - ymin) / target_resolution_m))

    master_transform = from_bounds(xmin, ymin, xmax, ymax, width, height)

    master_meta = {
        'driver': 'GTiff', 'dtype': 'float32', 'nodata': DEFAULT_NODATA,
        'width': width, 'height': height, 'count': 1, 'crs': crs,
        'transform': master_transform,
    }
    print(f"Master grid: {width}x{height} pixels at {target_resolution_m}m resolution.")
    return master_meta


def load_resistance_costs(csv_path: str) -> dict:
    """
    Loads resistance costs from a CSV file into a dictionary.
    CSV format: layer_type,objektart,resistance_cost
    """
    print(f"Loading resistance costs from {csv_path}...")
    df = pd.read_csv(csv_path)
    cost_maps = {}
    for layer_type in df['layer_type'].unique():
        cost_maps[layer_type] = df[df['layer_type'] == layer_type].set_index('objektart')['resistance_cost'].to_dict()
    print(f"Loaded costs for types: {list(cost_maps.keys())}")
    return cost_maps


def rasterize_layer(gdf: gpd.GeoDataFrame, master_meta: dict, cost_column: str, output_path: str):
    """
    Rasterizes a GDF onto the master grid using values from cost_column.
    """
    print(f"Rasterizing GDF to {output_path}...")
    
    # Filter out features with NoData cost before burning
    gdf_to_burn = gdf.dropna(subset=[cost_column])
    gdf_to_burn = gdf_to_burn[gdf_to_burn[cost_column] != DEFAULT_NODATA]

    if gdf_to_burn.empty:
        print(f"Warning: No valid features to burn for {output_path}. Creating empty raster.")
        # Create an empty array filled with nodata
        raster_array = np.full((master_meta['height'], master_meta['width']), 
                                master_meta['nodata'], 
                                dtype=master_meta['dtype'])
    else:
        shapes_to_burn = list(zip(gdf_to_burn.geometry, gdf_to_burn[cost_column]))
        print(f"Burning {len(shapes_to_burn)} features...")
        raster_array = rasterize(
            shapes=shapes_to_burn,
            out_shape=(master_meta['height'], master_meta['width']),
            transform=master_meta['transform'],
            fill=master_meta['nodata'],
            dtype=master_meta['dtype']
        )
    
    # Save the raster
    with rasterio.open(output_path, 'w', **master_meta) as dest:
        dest.write(raster_array, 1)
    print(f"Saved raster to {output_path}")


def combine_rasters_max_logic(input_rasters: list, output_path: str, min_valid_cost: float = 1.0):
    """
    Combines multiple rasters using MAXIMUM logic.
    Replaces NoData with min_valid_cost before combining.
    """
    if not input_rasters:
        raise ValueError("Input raster list cannot be empty.")

    print("Combining rasters using MAXIMUM logic...")
    # Read the first raster to establish metadata
    with rasterio.open(input_rasters[0]) as src:
        master_meta = src.meta.copy()
        nodata_val = src.nodata or DEFAULT_NODATA # Ensure nodata value
        
    arrays = []
    for path in input_rasters:
        with rasterio.open(path) as src:
            arr = src.read(1)
            # Replace nodata with the lowest valid cost
            arr[arr == nodata_val] = min_valid_cost
            arrays.append(arr)
            
    stacked_arrays = np.stack(arrays)
    final_array = np.maximum.reduce(stacked_arrays)
    
    # Save the final raster
    with rasterio.open(output_path, 'w', **master_meta) as dest:
        dest.write(final_array.astype(master_meta['dtype']), 1)
    print(f"Saved combined raster to {output_path}")


def plot_cost_surface(raster_path: str, title: str, 
                      min_cost: int = 1, max_cost: int = 1000, 
                      cmap_name: str = 'RdYlGn_r'):
    """
    Plots a single resistance cost surface raster with NoData as white.
    """
    print(f"Plotting: {title} from {raster_path}...")
    try:
        with rasterio.open(raster_path) as src:
            data = src.read(1)
            nodata_value = src.nodata or DEFAULT_NODATA
            data_masked = np.ma.masked_equal(data, nodata_value)
            extent = plotting_extent(src)
    except rasterio.errors.RasterioIOError:
        print(f"Error: Could not open {raster_path}.")
        return

    fig, ax = plt.subplots(figsize=(10, 10))
    norm = Normalize(vmin=min_cost, vmax=max_cost)
    
    base_cmap = plt.cm.get_cmap(cmap_name) 
    cmap = base_cmap.copy()
    cmap.set_bad('white') 

    image = ax.imshow(data_masked, cmap=cmap, norm=norm, extent=extent)
    fig.colorbar(image, ax=ax, shrink=0.7).set_label('Resistance Cost')
    ax.set_title(title, fontsize=16)
    ax.set_xlabel('Easting (m, LV95)')
    ax.set_ylabel('Northing (m, LV95)')
    plt.show()

def rasterize_landcover_types(gdf: gpd.GeoDataFrame, master_meta: dict, type_code_column: str, output_path: str):
    """ Rasterizes based on the unified landcover type codes (integers). """
    print(f"Rasterizing landcover types to {output_path}...")
    
    # --- Modify metadata for integer type codes ---
    type_meta = master_meta.copy()
    type_meta.update(dtype='uint16', nodata=UNIFIED_NODATA_CODE) # Use uint16 for codes 0-65535

    # Filter out features with NoData type code
    gdf_to_burn = gdf.dropna(subset=[type_code_column])
    gdf_to_burn = gdf_to_burn[gdf_to_burn[type_code_column] != UNIFIED_NODATA_CODE] # Assuming 0 is NoData

    if gdf_to_burn.empty:
        print(f"Warning: No valid features to burn for {output_path}. Creating empty raster.")
        raster_array = np.full((type_meta['height'], type_meta['width']), 
                                type_meta['nodata'], dtype=type_meta['dtype'])
    else:
        shapes_to_burn = list(zip(gdf_to_burn.geometry, gdf_to_burn[type_code_column]))
        print(f"Burning {len(shapes_to_burn)} features with type codes...")
        raster_array = rasterize(
            shapes=shapes_to_burn,
            out_shape=(type_meta['height'], type_meta['width']),
            transform=type_meta['transform'],
            fill=type_meta['nodata'], # Fill background with NoData code
            dtype=type_meta['dtype']
        )
    
    # Save the raster
    with rasterio.open(output_path, 'w', **type_meta) as dest:
        dest.write(raster_array, 1)
    print(f"Saved raster to {output_path}")

def combine_rasters_priority_fill(high_priority_path: str, low_priority_path: str, output_path: str):
    """
    Combines two type code rasters. Where high_priority has data, use its value,
    otherwise use the low_priority value.
    """
    print(f"Combining type rasters (Priority: {high_priority_path})...")
    with rasterio.open(high_priority_path) as high_src:
        high_arr = high_src.read(1)
        meta = high_src.meta.copy() # Use high-priority metadata
        nodata_val = high_src.nodata # Should be UNIFIED_NODATA_CODE

    with rasterio.open(low_priority_path) as low_src:
        low_arr = low_src.read(1)

    # Where high_arr has data (is not nodata), use it, otherwise use low_arr
    combined_arr = np.where(high_arr != nodata_val, high_arr, low_arr)

    # Save the harmonized type raster
    with rasterio.open(output_path, 'w', **meta) as dest:
        dest.write(combined_arr, 1)
    print(f"Saved harmonized landcover type raster to {output_path}")
    return combined_arr, meta # Return array and meta for next step

def apply_costs_to_type_raster(type_array: np.ndarray, type_meta: dict, 
                               cost_map: dict, default_cost: float, 
                               output_path: str):
    """ Applies resistance costs based on the unified type codes in the raster. """
    print(f"Applying resistance costs to harmonized type raster...")
    
    # Create the output resistance array, initialize with default cost
    resistance_array = np.full(type_array.shape, default_cost, dtype='float32')
    
    # Get the nodata code from the type raster metadata
    type_nodata_code = type_meta.get('nodata', UNIFIED_NODATA_CODE) 
                                     
    # Map costs based on the dictionary
    for type_code, cost in cost_map.items():
        resistance_array[type_array == type_code] = cost
        
    # --- IMPORTANT: Ensure NoData areas remain NoData ---
    # Find where the original type array WAS nodata
    nodata_mask = (type_array == type_nodata_code)
    # Reset those locations in the resistance array to the resistance NoData value
    resistance_meta = type_meta.copy()
    resistance_meta.update(dtype='float32', nodata=gu.DEFAULT_NODATA) # Use standard float NoData
    resistance_array[nodata_mask] = resistance_meta['nodata'] 
    
    # Save the final base resistance raster (before barriers)
    with rasterio.open(output_path, 'w', **resistance_meta) as dest:
        dest.write(resistance_array, 1)
    print(f"Saved base resistance raster (from types) to {output_path}")