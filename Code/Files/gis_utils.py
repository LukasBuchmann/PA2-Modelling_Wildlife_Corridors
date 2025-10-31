import geopandas as gpd
import rasterio
from rasterio.transform import from_bounds
from rasterio.features import rasterize
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize, ListedColormap
from rasterio.plot import plotting_extent
import pandas as pd
import os

# --- Constants ---
DEFAULT_NODATA_FLOAT = -9999.0 # Explicitly float for float rasters (costs)
TARGET_CRS = "EPSG:2056"     # Standard Swiss projection

# --- Core Functions ---

# --- Canton Filtering Function with Buffering ---
def filter_canton(name: str, boundaries_path: str, buffer_m: float = 0) -> tuple[gpd.GeoDataFrame, tuple]:
    """
    Returns the geometry of a Swiss canton optionally expanded by a 
    buffer, along with its bounding box.
    Clips buffered cantons to the national boundary.
    """
    # Determine target CRS
    target_crs = "EPSG:2056"

    # Load Switzerland boundary first for clipping later
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


# --- Load and Clip Vector Layer ---
def load_and_clip_vector(filepath: str, layername: str, aoi_geom: gpd.GeoDataFrame, bbox: tuple = None) -> gpd.GeoDataFrame:
    """ Loads a vector layer and filters by bbox, and clips to AOI geometry. """

    # Loading layer with bbox filtering for efficiency
    read_args = {'layer': layername}
    if bbox: read_args['bbox'] = bbox
    gdf = gpd.read_file(filepath, engine="pyogrio", **read_args)

    if gdf.crs != aoi_geom.crs:
        gdf = gdf.to_crs(aoi_geom.crs)

    # Clipping layer to Canton geometry")
    gdf_clipped = gpd.clip(gdf, aoi_geom)
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
    master_meta = {'driver': 'GTiff', 'dtype': 'float32', 'nodata': DEFAULT_NODATA_FLOAT,
        'width': width, 'height': height, 'count': 1, 'crs': crs,
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
def rasterize_layer(gdf: gpd.GeoDataFrame, master_meta: dict, cost_column: str, output_path: str, nodata_val=DEFAULT_NODATA_FLOAT):
    """ Rasterizes a GDF onto the master grid using values from cost_column. """
    
    raster_meta = master_meta.copy()
    raster_meta.update(nodata=nodata_val)

    gdf_to_burn = gdf.dropna(subset=[cost_column])

    shapes_to_burn = list(zip(gdf_to_burn.geometry, gdf_to_burn[cost_column]))
    
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
        nodata_val = DEFAULT_NODATA_FLOAT
     
    arrays = []
    for path in input_rasters:
        with rasterio.open(path) as src:
            arr = src.read(1)
            current_nodata = src.nodata or nodata_val
            arr = np.where(arr == current_nodata, min_valid_cost, arr)
            arrays.append(arr)

    stacked_arrays = np.stack(arrays)
    final_array = np.maximum.reduce(stacked_arrays)
    
    master_meta.update(dtype=final_array.dtype, nodata=DEFAULT_NODATA_FLOAT)
    with rasterio.open(output_path, 'w', **master_meta) as dest:
        dest.write(final_array, 1)
    print(f"Saved combined raster to {output_path}")


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

    # Open low priority raster
    with rasterio.open(low_priority_path) as low_src:
        low_arr = low_src.read(1)

    # Where high_arr is valid data (is not nodata), use it, otherwise use low_arr
    combined_arr = np.where(high_arr != DEFAULT_NODATA_FLOAT, high_arr, low_arr)

    # Save the harmonized cost raster
    with rasterio.open(output_path, 'w', **meta) as dest:
        dest.write(combined_arr.astype(meta['dtype']), 1)
    print(f"Saved harmonized landcover COST raster to {output_path}")


# # # --- Rasterization Function ---
# def rasterize_layer(gdf: gpd.GeoDataFrame, master_meta: dict, cost_column: str, output_path: str, dtype='float64', nodata_val=DEFAULT_NODATA_FLOAT):
#     """ Rasterizes a GDF onto the master grid using values from cost_column. """
#     # (Same function definition as in the previous 'resistance first' version)
#     print(f"Rasterizing GDF to {output_path}...")
#     raster_meta = master_meta.copy()
#     raster_meta.update(dtype=dtype, nodata=nodata_val)
#     gdf_to_burn = gdf.dropna(subset=[cost_column])
#     if dtype == 'float64': gdf_to_burn = gdf_to_burn[gdf_to_burn[cost_column] != DEFAULT_NODATA_FLOAT]
#     elif dtype == 'uint16': gdf_to_burn = gdf_to_burn[gdf_to_burn[cost_column] != DEFAULT_NODATA_FLOAT] # Check int nodata

#     if gdf_to_burn.empty:
#         print(f"Warning: No valid features to burn for {output_path}. Creating empty raster.")
#         raster_array = np.full((raster_meta['height'], raster_meta['width']), raster_meta['nodata'], dtype=raster_meta['dtype'])
#     else:
#         shapes_to_burn = list(zip(gdf_to_burn.geometry, gdf_to_burn[cost_column]))
#         print(f"Burning {len(shapes_to_burn)} features...")
#         raster_array = rasterize( shapes=shapes_to_burn, out_shape=(raster_meta['height'], raster_meta['width']), transform=raster_meta['transform'], fill=raster_meta['nodata'], dtype=raster_meta['dtype'] )
#     with rasterio.open(output_path, 'w', **raster_meta) as dest: dest.write(raster_array, 1)
#     print(f"Saved raster to {output_path}")


# # # --- Combine Rasters with MAXIMUM Logic ---
# def combine_rasters_max_logic(valid_paths: list, output_path: str):
#     """ Combines multiple rasters using MAXIMUM logic. 
#     Replaces NoData with min_valid_cost. """

#     with rasterio.open(valid_paths[0]) as src:
#         master_meta = src.meta.copy()
#         # Ensure output metadata uses the standard float NoData value and dtype
#         nodata_val = src.nodata if src.nodata is not None else DEFAULT_NODATA_FLOAT
#         master_meta.update(nodata=DEFAULT_NODATA_FLOAT, dtype='float32')

#     arrays = []
#     all_nodata_mask = np.ones((master_meta['height'], master_meta['width']), dtype=bool)

#     for path in valid_paths:
#         with rasterio.open(path) as src:
#             arr = src.read(1)
#             current_nodata = src.nodata if src.nodata is not None else nodata_val
#             # Update the mask: a pixel is NOT all NoData if the current layer is valid
#             all_nodata_mask = all_nodata_mask & (arr == current_nodata)
#             arrays.append(arr)

#     stacked_arrays = np.stack(arrays)
#     nodata_numeric = nodata_val
#     stacked_arrays_masked = np.where(stacked_arrays == nodata_numeric, -np.inf, stacked_arrays)
#     # Calculate the maximum, ignoring the -np.inf where possible
#     final_array = np.maximum.reduce(stacked_arrays_masked, axis=0)
#     # Where ALL original inputs were NoData, force the output back to NoData
#     final_array[all_nodata_mask] = DEFAULT_NODATA_FLOAT # Use the standard output NoData

    # # Save the final raster
    # with rasterio.open(output_path, 'w', **master_meta) as dest:
    #     dest.write(final_array.astype(master_meta['dtype']), 1) # Ensure correct dtype
    # print(f"Saved combined MAX raster (preserving NoData) to {output_path}")


# --- Plotting Functions ---
# --- Plotting single Vector Layer ---
def plot_vector_layer(gdf: gpd.GeoDataFrame, title: str, column_to_plot: str = None, cmap='tab20', figsize=(10,10)):
    """ Plots a GeoDataFrame, optionally coloring by a column. """
    fig, ax = plt.subplots(figsize=figsize)
    if column_to_plot and column_to_plot in gdf.columns:
        gdf.plot(column=column_to_plot, ax=ax, legend=True, cmap=cmap,
                 legend_kwds={'title': column_to_plot, 'loc': 'upper left', 'bbox_to_anchor': (1, 1)})
    else:
        gdf.plot(ax=ax, color='blue', edgecolor='black')
    ax.set_title(title, fontsize=16)
    ax.set_xlabel('Easting (m, LV95)')
    ax.set_ylabel('Northing (m, LV95)')
    plt.tight_layout()
    plt.show()


# --- Plotting Raster Layers ---
def plot_raster_layer(raster_path: str, title: str, cmap='RdYlGn_r', nodata_color='white', vmin=None, vmax=None):
    """ Plots a single raster layer """
    print(f"Plotting raster layer: {title} from {os.path.basename(raster_path)}")

    with rasterio.open(raster_path) as src:
        data = src.read(1)
        DEFAULT_NODATA_FLOAT = src.nodata
        # Mask based on src.nodata or default if None
        if DEFAULT_NODATA_FLOAT is not None:
            data_masked = np.ma.masked_equal(data, DEFAULT_NODATA_FLOAT)
        else:
            # If no nodata set in file, assume DEFAULT_NODATA_FLOAT was used during creation
            data_masked = np.ma.masked_equal(data, DEFAULT_NODATA_FLOAT)

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

# def plot_vector_layer(gdf: gpd.GeoDataFrame, title: str, column_to_plot: str = None, cmap='tab20', figsize=(10,10)):
#     """ Plots a GeoDataFrame, optionally coloring by a column. """
#     print(f"Plotting vector layer: {title}")
#     fig, ax = plt.subplots(figsize=figsize)
#     plot_args = {'ax': ax}
#     if column_to_plot and column_to_plot in gdf.columns:
#         # Check if column is numeric for continuous cmap, otherwise categorical
#         if pd.api.types.is_numeric_dtype(gdf[column_to_plot]):
#             plot_args['column'] = column_to_plot
#             plot_args['legend'] = True
#             plot_args['cmap'] = cmap
#             plot_args['legend_kwds'] = {'label': column_to_plot, 'orientation': "vertical", 'shrink': 0.6}
#         else: # Categorical plot
#             plot_args['column'] = column_to_plot
#             plot_args['legend'] = True
#             plot_args['cmap'] = cmap # Use categorical map like tab20
#             # Adjust legend location for categorical data if needed
#             plot_args['legend_kwds'] = {'title': column_to_plot, 'loc': 'upper left', 'bbox_to_anchor': (1, 1)}
#     else:
#         plot_args['color'] = 'grey'
#         plot_args['edgecolor'] = 'black'
#     gdf.plot(**plot_args)
#     ax.set_title(title, fontsize=16); ax.set_xlabel('Easting (m, LV95)'); ax.set_ylabel('Northing (m, LV95)')
#     plt.tight_layout(); plt.show()

# def plot_raster_layer(raster_path: str, title: str, cmap='viridis', nodata_color='white', vmin=None, vmax=None):
#     """ Plots a single raster layer, handling NoData. """

#     with rasterio.open(raster_path) as src:
#         data = src.read(1); DEFAULT_NODATA_FLOAT = src.nodata
#         if DEFAULT_NODATA_FLOAT is not None: data_masked = np.ma.masked_equal(data, DEFAULT_NODATA_FLOAT)
#         # Use specific nodata for types if it's a type raster
#         elif data.dtype in [np.uint8, np.uint16, np.int16, np.int32]: data_masked = np.ma.masked_equal(data, DEFAULT_NODATA_FLOAT)
#         else: data_masked = np.ma.masked_equal(data, DEFAULT_NODATA_FLOAT)
#         extent = plotting_extent(src)
#         fig, ax = plt.subplots(figsize=(10, 10))
#         current_cmap = plt.cm.get_cmap(cmap).copy(); current_cmap.set_bad(color=nodata_color)
#         effective_vmin = vmin if vmin is not None else data_masked.min()
#         effective_vmax = vmax if vmax is not None else data_masked.max()
#         norm = Normalize(vmin=effective_vmin, vmax=effective_vmax) if effective_vmin is not None and effective_vmax is not None and effective_vmin != effective_vmax else None
#         image = ax.imshow(data_masked, cmap=current_cmap, norm=norm, extent=extent)
#         fig.colorbar(image, ax=ax, shrink=0.7).set_label('Pixel Value')
#         ax.set_title(title, fontsize=16); ax.set_xlabel('Easting (m, LV95)'); ax.set_ylabel('Northing (m, LV95)')
#         plt.tight_layout(); plt.show()




# In gis_utils.py
import rasterio

def world_to_pixel(raster_path: str, x_coord: float, y_coord: float) -> tuple[int, int]:
    """
    Converts a real-world (map) coordinate to a raster's (row, col)
    pixel coordinate.
    """
    with rasterio.open(raster_path) as src:
        # Use the 'index' method to get the row and column
        row, col = src.index(x_coord, y_coord)
    return row, col