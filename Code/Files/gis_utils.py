# gis_utils.py
import geopandas as gpd
import rasterio
from rasterio.transform import from_bounds
from rasterio.features import rasterize
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize, ListedColormap
from rasterio.plot import plotting_extent, show as rio_show # Import show
import pandas as pd
import os

NODATA_VALUE = float(0.0)


# --- Canton Filtering Function with Buffering ---
def filter_canton(name: str, boundaries_path: str, buffer_m: float = 0) -> tuple[gpd.GeoDataFrame, tuple]:
    """
    Returns the geometry of a Swiss canton optionally expanded by a 
    buffer, along with its bounding box.
    Clips buffered cantons to the national boundary.
    """
    # Determine target CRS
    target_crs = "EPSG:2056"

    # Load Switzerland boundary first for clipping later if needed
    country_layer_name = "tlm_landesgebiet"
    country = gpd.read_file(boundaries_path, layer=country_layer_name, engine="pyogrio")
    if country.crs != target_crs:
        country = country.to_crs(target_crs)

    # Load canton boundaries
    layer_name = "tlm_kantonsgebiet"
    boundaries = gpd.read_file(boundaries_path, layer=layer_name, engine="pyogrio")
    if boundaries.crs != target_crs:
        boundaries = boundaries.to_crs(target_crs)
    aoi = boundaries[boundaries["name"] == name]

    # Apply buffer
    if buffer_m > 0:
        aoi_buffered = aoi.copy()
        aoi_buffered["geometry"] = aoi_buffered.geometry.buffer(buffer_m)
        # Clip buffered canton to national boundary
        aoi_final = gpd.clip(aoi_buffered, country)
    else:
        aoi_final = aoi # No buffer

    xmin, ymin, xmax, ymax = aoi_final.total_bounds
    aoi_bbox = (xmin, ymin, xmax, ymax)

    return aoi_final, aoi_bbox


# --- Plotting single Vector Layer ---
def plot_vector_layer(gdf: gpd.GeoDataFrame, title: str, column_to_plot: str = None, cmap='tab20', figsize=(10,10)):
    """ Plots a GeoDataFrame, optionally coloring by a column. """
    fig, ax = plt.subplots(figsize=figsize)
    if column_to_plot and column_to_plot in gdf.columns:
        gdf.plot(column=column_to_plot, ax=ax, legend=True, cmap=cmap,
                 legend_kwds={'label': column_to_plot, 'orientation': "vertical", 'shrink': 0.6})
    else:
        gdf.plot(ax=ax, color='blue', edgecolor='black')
    ax.set_title(title, fontsize=16)
    ax.set_xlabel('Easting (m, LV95)')
    ax.set_ylabel('Northing (m, LV95)')
    plt.tight_layout()
    plt.show()


# --- Load and Clip Vector Layer ---
def load_and_clip_vector(filepath: str, layername: str, aoi_geom: gpd.GeoDataFrame, bbox: tuple = None) -> gpd.GeoDataFrame:
    """ Loads a vector layer and filters by bbox, and clips to AOI geometry. """

    read_args = {'layer': layername}
    if bbox: read_args['bbox'] = bbox
    gdf = gpd.read_file(filepath, engine="pyogrio", **read_args)

    if gdf.crs != aoi_geom.crs:
        gdf = gdf.to_crs(aoi_geom.crs)

    # Clipping layer to Canton geometry")
    gdf_clipped = gpd.clip(gdf, aoi_geom)
    print(f"Loaded and clipped {len(gdf_clipped)} features from {layername}.")
    return gdf_clipped


# --- Define Master Grid Metadata ---
def define_master_grid_meta(aoi_geometry: gpd.GeoDataFrame,
                                     target_resolution_m: float,
                                     crs) -> dict:
    """
    Calculates the master grid metadata directly based on the bounds
    of the provided Canton GeoDataFrame.
    """
    # Get bounds directly from the Canton geometry
    xmin, ymin, xmax, ymax = aoi_geometry.total_bounds

    # Calculate grid dimensions
    width = int(np.ceil((xmax - xmin) / target_resolution_m))
    height = int(np.ceil((ymax - ymin) / target_resolution_m))

    # Create transform and metadata
    master_transform = from_bounds(xmin, ymin, xmax, ymax, width, height)
    master_meta = {
        'driver': 'GTiff',
        'dtype': 'float32',
        'nodata': NODATA_VALUE,
        'width': width,
        'height': height,
        'count': 1,
        'crs': crs,
        'transform': master_transform,
    }
    print(f"Master grid: {width}x{height} pixels at {target_resolution_m}m resolution.")
    return master_meta


# --- Load Resistance Costs from CSV ---
def load_resistance_costs(csv_path: str) -> dict:
    """ Loads resistance costs from a CSV file into a dictionary. """

    df = pd.read_csv(csv_path)
    cost_maps = {}
    required_cols = ['layer_type', 'objektart', 'resistance_cost']
    if not all(col in df.columns for col in required_cols):
        raise ValueError(f"Cost CSV must contain columns: {required_cols}")

    for layer_type in df['layer_type'].unique():
        cost_maps[layer_type] = df[df['layer_type'] == layer_type].set_index('objektart')['resistance_cost'].to_dict()

    return cost_maps


# --- Rasterization Functions ---
def rasterize_layer(gdf: gpd.GeoDataFrame, master_meta: dict, cost_column: str, output_path: str, dtype='float32', nodata_val=NODATA_VALUE):
    """ Rasterizes a GDF onto the master grid using values from cost_column. """
    
    raster_meta = master_meta.copy()
    raster_meta.update(dtype=dtype, nodata=nodata_val)

    gdf_to_burn = gdf.dropna(subset=[cost_column])
    # # Also filter out rows where cost might be the float nodata value if applicable
    # if dtype == 'float32':
    #      gdf_to_burn = gdf_to_burn[gdf_to_burn[cost_column] != NODATA_VALUE]

    # if gdf_to_burn.empty:
    #     print(f"Warning: No valid features to burn for {output_path}. Creating empty raster.")
    #     raster_array = np.full((raster_meta['height'], raster_meta['width']),
    #                             raster_meta['nodata'], dtype=raster_meta['dtype'])
    # else:
    shapes_to_burn = list(zip(gdf_to_burn.geometry, gdf_to_burn[cost_column]))
    # print(f"Burning {len(shapes_to_burn)} features...")
    raster_array = rasterize(
        shapes=shapes_to_burn,
        out_shape=(raster_meta['height'], raster_meta['width']),
        transform=raster_meta['transform'],
        fill=raster_meta['nodata'],
        dtype=raster_meta['dtype']
        )
    
    with rasterio.open(output_path, 'w', **raster_meta) as dest:
        dest.write(raster_array, 1)
    print(f"Saved raster to {output_path}")


# --- Combine Rasters with MAXIMUM Logic ---
def combine_rasters_max_logic(input_rasters: list, output_path: str, min_valid_cost: float = 1.0):
    """ Combines multiple rasters using MAXIMUM logic. Replaces NoData with min_valid_cost. """

    with rasterio.open(input_rasters[0]) as src:
        master_meta = src.meta.copy()
        nodata_val = NODATA_VALUE
     
    arrays = []
    for path in input_rasters:
        with rasterio.open(path) as src:
            arr = src.read(1)
            current_nodata = src.nodata or nodata_val
            arr = np.where(arr == current_nodata, min_valid_cost, arr)
            arrays.append(arr)

    stacked_arrays = np.stack(arrays)
    final_array = np.maximum.reduce(stacked_arrays)
    
    master_meta.update(dtype=final_array.dtype, nodata=NODATA_VALUE)
    with rasterio.open(output_path, 'w', **master_meta) as dest:
        dest.write(final_array, 1)
    print(f"Saved combined raster to {output_path}")


# --- Plotting Raster Layers ---
def plot_raster_layer(raster_path: str, title: str, cmap='RdYlGn_r', nodata_color='white', vmin=None, vmax=None):
    """ Plots a single raster layer """
    print(f"Plotting raster layer: {title} from {os.path.basename(raster_path)}")

    with rasterio.open(raster_path) as src:
        data = src.read(1)
        nodata_value = src.nodata
        # Mask based on src.nodata or default if None
        if nodata_value is not None:
            data_masked = np.ma.masked_equal(data, nodata_value)
        else:
            # If no nodata set in file, assume NODATA_VALUE was used during creation
            data_masked = np.ma.masked_equal(data, NODATA_VALUE)

        extent = plotting_extent(src)

        fig, ax = plt.subplots(figsize=(10, 10))
            
        # Get the colormap and set the nodata color
        current_cmap = plt.cm.get_cmap(cmap).copy()
        current_cmap.set_bad(color=nodata_color)

        # Determine normalization range
        if vmin is None: vmin = data_masked.min()
        if vmax is None: vmax = data_masked.max()
        norm = Normalize(vmin=vmin, vmax=vmax) if vmin is not None and vmax is not None else None

        image = ax.imshow(data_masked, cmap=current_cmap, norm=norm, extent=extent)
        fig.colorbar(image, ax=ax, shrink=0.7).set_label('Pixel Value')
        ax.set_title(title, fontsize=16)
        ax.set_xlabel('Easting (m, LV95)')
        ax.set_ylabel('Northing (m, LV95)')
        plt.tight_layout()
        plt.show()


# # (Keep plot_cost_surface as is, as it's specifically for resistance values)
# def plot_cost_surface(raster_path: str, title: str,
#                       min_cost: int = 1, max_cost: int = 1000,
#                       cmap_name: str = 'RdYlGn_r', nodata_color='white'):
#     """ Plots a single resistance cost surface raster with NoData as specified color. """
#     print(f"Plotting cost surface: {title} from {os.path.basename(raster_path)}")
#     try:
#         with rasterio.open(raster_path) as src:
#             data = src.read(1)
#             nodata_value = src.nodata or NODATA_VALUE
#             data_masked = np.ma.masked_equal(data, nodata_value)
#             extent = plotting_extent(src)
#     except rasterio.errors.RasterioIOError:
#         print(f"Error: Could not open {raster_path}.")
#         return

#     fig, ax = plt.subplots(figsize=(10, 10))
#     norm = Normalize(vmin=min_cost, vmax=max_cost)

#     base_cmap = plt.cm.get_cmap(cmap_name)
#     cmap = base_cmap.copy()
#     cmap.set_bad(color=nodata_color)

#     image = ax.imshow(data_masked, cmap=cmap, norm=norm, extent=extent)
#     fig.colorbar(image, ax=ax, shrink=0.7).set_label('Resistance Cost')
#     ax.set_title(title, fontsize=16)
#     ax.set_xlabel('Easting (m, LV95)')
#     ax.set_ylabel('Northing (m, LV95)')
#     plt.tight_layout()
#     plt.show()

# def rasterize_landcover_types(gdf: gpd.GeoDataFrame, master_meta: dict, type_code_column: str, output_path: str):
#     """ Rasterizes based on the unified landcover type codes (integers). """
#     print(f"Rasterizing landcover types to {output_path}...")
#     type_meta = master_meta.copy()
#     type_meta.update(dtype='uint16', nodata=NODATA_VALUE) # Ensure integer type

#     gdf_to_burn = gdf.dropna(subset=[type_code_column])
#     gdf_to_burn = gdf_to_burn[gdf_to_burn[type_code_column] != NODATA_VALUE]

#     if gdf_to_burn.empty:
#         print(f"Warning: No valid features to burn for {output_path}. Creating empty raster.")
#         raster_array = np.full((type_meta['height'], type_meta['width']), type_meta['nodata'], dtype=type_meta['dtype'])
#     else:
#         shapes_to_burn = list(zip(gdf_to_burn.geometry, gdf_to_burn[type_code_column]))
#         print(f"Burning {len(shapes_to_burn)} features with type codes...")
#         raster_array = rasterize(
#             shapes=shapes_to_burn, out_shape=(type_meta['height'], type_meta['width']),
#             transform=type_meta['transform'], fill=type_meta['nodata'], dtype=type_meta['dtype']
#         )
#     with rasterio.open(output_path, 'w', **type_meta) as dest: dest.write(raster_array, 1)
#     print(f"Saved raster to {output_path}")


# # --- Combine Landcover Rasters with Priority Fill ---
def combine_cost_rasters_priority_fill(high_priority_path: str, low_priority_path: str, output_path: str) -> tuple[np.ndarray, dict]:
    """
    Combines two resistance cost rasters using priority fill logic.
    Where high_priority has data, use its value, otherwise use low_priority.
    """
    # Open high priority raster
    with rasterio.open(high_priority_path) as high_src:
        high_arr = high_src.read(1)
        meta = high_src.meta.copy() # Use high-priority metadata
        # # Ensure nodata is float
        # nodata_val = high_src.nodata or NODATA_VALUE
        # if meta['dtype'] != 'float32': meta['dtype'] = 'float32' # Ensure output is float
        # meta['nodata'] = NODATA_VALUE # Ensure output nodata is float

    # Open low priority raster
    with rasterio.open(low_priority_path) as low_src:
        low_arr = low_src.read(1)
        # low_nodata = low_src.nodata or NODATA_VALUE
        # # Ensure arrays are compatible
        # if high_arr.shape != low_arr.shape: raise ValueError("Input raster shapes do not match.")


    # Where high_arr is valid data (is not nodata), use it, otherwise use low_arr
    combined_arr = np.where(high_arr != NODATA_VALUE, high_arr, low_arr)

    # Ensure final output respects the primary nodata value if low_arr was also nodata
    combined_arr = np.where((high_arr == NODATA_VALUE) & (low_arr == NODATA_VALUE), NODATA_VALUE, combined_arr)

    # Save the harmonized cost raster
    with rasterio.open(output_path, 'w', **meta) as dest:
        dest.write(combined_arr.astype(meta['dtype']), 1)
    print(f"Saved harmonized landcover COST raster to {output_path}")





def apply_costs_to_type_raster(type_array: np.ndarray, type_meta: dict,
                               unified_cost_map: dict, default_cost: float,
                               output_path: str):
    """ Applies resistance costs based on the unified type codes in the raster. """
    print(f"Applying resistance costs to harmonized type raster...")
    resistance_array = np.full(type_array.shape, default_cost, dtype='float32')
    type_nodata_code = type_meta.get('nodata', NODATA_VALUE)

    # Vectorized mapping using pandas (often faster for large arrays)
    unique_types = np.unique(type_array[type_array != type_nodata_code])
    cost_vector_map = pd.Series(unified_cost_map)
    # Map costs only for existing types
    map_dict = cost_vector_map.reindex(unique_types).fillna(default_cost).to_dict()

    # Apply mapping
    temp_resistance_array = type_array.astype(np.float32) # Temp float array for mapping
    for type_code, cost in map_dict.items():
        temp_resistance_array[type_array == type_code] = cost

    resistance_array = temp_resistance_array

    # Ensure NoData areas remain NoData using standard float NoData value
    resistance_meta = type_meta.copy()
    resistance_meta.update(dtype='float32', nodata=NODATA_VALUE)
    resistance_array[type_array == type_nodata_code] = resistance_meta['nodata']

    with rasterio.open(output_path, 'w', **resistance_meta) as dest: dest.write(resistance_array, 1)
    print(f"Saved base resistance raster (from types) to {output_path}")


# --- Keep Barrier Rasterization & Combination ---
# Use the general rasterize_layer function for barriers (costs already assigned)
def rasterize_layer(gdf: gpd.GeoDataFrame, master_meta: dict, cost_column: str, output_path: str, dtype='float32', nodata_val=NODATA_VALUE):
    """ Rasterizes a GDF onto the master grid using values from cost_column. """
    # (Same function definition as in the previous 'resistance first' version)
    print(f"Rasterizing GDF to {output_path}...")
    raster_meta = master_meta.copy()
    raster_meta.update(dtype=dtype, nodata=nodata_val)
    gdf_to_burn = gdf.dropna(subset=[cost_column])
    if dtype == 'float32': gdf_to_burn = gdf_to_burn[gdf_to_burn[cost_column] != NODATA_VALUE]
    elif dtype == 'uint16': gdf_to_burn = gdf_to_burn[gdf_to_burn[cost_column] != NODATA_VALUE] # Check int nodata

    if gdf_to_burn.empty:
        print(f"Warning: No valid features to burn for {output_path}. Creating empty raster.")
        raster_array = np.full((raster_meta['height'], raster_meta['width']), raster_meta['nodata'], dtype=raster_meta['dtype'])
    else:
        shapes_to_burn = list(zip(gdf_to_burn.geometry, gdf_to_burn[cost_column]))
        print(f"Burning {len(shapes_to_burn)} features...")
        raster_array = rasterize( shapes=shapes_to_burn, out_shape=(raster_meta['height'], raster_meta['width']), transform=raster_meta['transform'], fill=raster_meta['nodata'], dtype=raster_meta['dtype'] )
    with rasterio.open(output_path, 'w', **raster_meta) as dest: dest.write(raster_array, 1)
    print(f"Saved raster to {output_path}")


# Keep combine_rasters_max_logic
def combine_rasters_max_logic(input_rasters: list, output_path: str, min_valid_cost: float = 1.0):
    """ Combines multiple rasters using MAXIMUM logic. Replaces NoData with min_valid_cost. """
    # (Same function definition as before)
    if not input_rasters: raise ValueError("Input raster list cannot be empty.")
    print("Combining rasters using MAXIMUM logic...")
    try:
        with rasterio.open(input_rasters[0]) as src: master_meta = src.meta.copy(); nodata_val = src.nodata or NODATA_VALUE
    except rasterio.errors.RasterioIOError: print(f"Error: Cannot open base raster {input_rasters[0]}."); raise
    arrays = []
    for path in input_rasters:
        try:
            with rasterio.open(path) as src: arr = src.read(1); current_nodata = src.nodata or nodata_val; arr = np.where(arr == current_nodata, min_valid_cost, arr); arrays.append(arr)
        except rasterio.errors.RasterioIOError: print(f"Warning: Could not open raster {path}. Skipping."); continue
    if not arrays: raise ValueError("No valid input rasters could be read.")
    stacked_arrays = np.stack(arrays); final_array = np.maximum.reduce(stacked_arrays)
    master_meta.update(dtype=final_array.dtype, nodata=NODATA_VALUE)
    with rasterio.open(output_path, 'w', **master_meta) as dest: dest.write(final_array, 1)
    print(f"Saved combined raster to {output_path}")


# --- Plotting Functions ---
# (Keep plot_vector_layer, plot_raster_layer, plot_cost_surface from previous version)
def plot_vector_layer(gdf: gpd.GeoDataFrame, title: str, column_to_plot: str = None, cmap='tab20', figsize=(10,10)):
    """ Plots a GeoDataFrame, optionally coloring by a column. """
    print(f"Plotting vector layer: {title}")
    fig, ax = plt.subplots(figsize=figsize)
    plot_args = {'ax': ax}
    if column_to_plot and column_to_plot in gdf.columns:
        # Check if column is numeric for continuous cmap, otherwise categorical
        if pd.api.types.is_numeric_dtype(gdf[column_to_plot]):
            plot_args['column'] = column_to_plot
            plot_args['legend'] = True
            plot_args['cmap'] = cmap
            plot_args['legend_kwds'] = {'label': column_to_plot, 'orientation': "vertical", 'shrink': 0.6}
        else: # Categorical plot
            plot_args['column'] = column_to_plot
            plot_args['legend'] = True
            plot_args['cmap'] = cmap # Use categorical map like tab20
            # Adjust legend location for categorical data if needed
            plot_args['legend_kwds'] = {'title': column_to_plot, 'loc': 'upper left', 'bbox_to_anchor': (1, 1)}
    else:
        plot_args['color'] = 'grey'
        plot_args['edgecolor'] = 'black'
    gdf.plot(**plot_args)
    ax.set_title(title, fontsize=16); ax.set_xlabel('Easting (m, LV95)'); ax.set_ylabel('Northing (m, LV95)')
    plt.tight_layout(); plt.show()

def plot_raster_layer(raster_path: str, title: str, cmap='viridis', nodata_color='white', vmin=None, vmax=None):
    """ Plots a single raster layer, handling NoData. """
    print(f"Plotting raster layer: {title} from {os.path.basename(raster_path)}")
    try:
        with rasterio.open(raster_path) as src:
            data = src.read(1); nodata_value = src.nodata
            if nodata_value is not None: data_masked = np.ma.masked_equal(data, nodata_value)
            # Use specific nodata for types if it's a type raster
            elif data.dtype in [np.uint8, np.uint16, np.int16, np.int32]: data_masked = np.ma.masked_equal(data, NODATA_VALUE)
            else: data_masked = np.ma.masked_equal(data, NODATA_VALUE)
            extent = plotting_extent(src)
            fig, ax = plt.subplots(figsize=(10, 10))
            current_cmap = plt.cm.get_cmap(cmap).copy(); current_cmap.set_bad(color=nodata_color)
            effective_vmin = vmin if vmin is not None else data_masked.min()
            effective_vmax = vmax if vmax is not None else data_masked.max()
            norm = Normalize(vmin=effective_vmin, vmax=effective_vmax) if effective_vmin is not None and effective_vmax is not None and effective_vmin != effective_vmax else None
            image = ax.imshow(data_masked, cmap=current_cmap, norm=norm, extent=extent)
            fig.colorbar(image, ax=ax, shrink=0.7).set_label('Pixel Value')
            ax.set_title(title, fontsize=16); ax.set_xlabel('Easting (m, LV95)'); ax.set_ylabel('Northing (m, LV95)')
            plt.tight_layout(); plt.show()
    except rasterio.errors.RasterioIOError: print(f"Error: Could not plot {raster_path}. File not found or invalid.")
    except Exception as e: print(f"An error occurred during plotting: {e}")


def plot_cost_surface(raster_path: str, title: str, min_cost: int = 1, max_cost: int = 1000, cmap_name: str = 'RdYlGn_r', nodata_color='white'):
    """ Plots a single resistance cost surface raster with NoData as specified color. """
    print(f"Plotting cost surface: {title} from {os.path.basename(raster_path)}")
    try:
        with rasterio.open(raster_path) as src:
            data = src.read(1); nodata_value = src.nodata or NODATA_VALUE
            data_masked = np.ma.masked_equal(data, nodata_value); extent = plotting_extent(src)
    except rasterio.errors.RasterioIOError: print(f"Error: Could not open {raster_path}."); return
    fig, ax = plt.subplots(figsize=(10, 10)); norm = Normalize(vmin=min_cost, vmax=max_cost)
    base_cmap = plt.cm.get_cmap(cmap_name); cmap = base_cmap.copy(); cmap.set_bad(color=nodata_color)
    image = ax.imshow(data_masked, cmap=cmap, norm=norm, extent=extent)
    fig.colorbar(image, ax=ax, shrink=0.7).set_label('Resistance Cost')
    ax.set_title(title, fontsize=16); ax.set_xlabel('Easting (m, LV95)'); ax.set_ylabel('Northing (m, LV95)')
    plt.tight_layout(); plt.show()