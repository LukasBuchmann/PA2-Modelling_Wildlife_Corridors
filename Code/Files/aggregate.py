import numpy as np
import matplotlib
matplotlib.use('Agg') # Use non-interactive backend for HPC
import matplotlib.pyplot as plt
import matplotlib.colors as colors
import os
from tqdm import tqdm
import glob
import rasterio
import sys
import shutil

print("Starting aggregation and plotting...")

# --- 0. Define Dirs ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(BASE_DIR, "Results")
TEMP_DIR = os.path.join(RESULTS_DIR, "temp_traffic")

# --- 1. Load Metadata ---
FINAL_RASTER = os.path.join(RESULTS_DIR, "final_resistance_surface.tif")
GRID_SPACING_METERS = 1000
EXTREME_BARRIER_COST = 10000.0

try:
    with rasterio.open(FINAL_RASTER) as src:
        meta = src.meta.copy()
        resistance_array = src.read(1).astype(np.float32)
        nodata_val = meta['nodata']
        resolution = meta['transform'][0]
        height, width = resistance_array.shape
        resistance_array = np.nan_to_num(
            resistance_array, 
            nan=EXTREME_BARRIER_COST,
            posinf=EXTREME_BARRIER_COST,
            neginf=1.0 
        )
        if nodata_val is not None:
            resistance_array[resistance_array == nodata_val] = EXTREME_BARRIER_COST    
        resistance_array[resistance_array <= 0] = 1.0

except rasterio.errors.RasterioIOError:
    print(f"Error: Could not open {FINAL_RASTER} to get metadata.")
    sys.exit(1)

# --- 2. Aggregate Results ---
print(f"Aggregating results from {TEMP_DIR}...")
all_worker_files = glob.glob(os.path.join(TEMP_DIR, "worker_traffic_*.npy"))
if not all_worker_files:
    print(f"Error: No worker files found in {TEMP_DIR}. Did the array job fail?")
    sys.exit(1)
    
traffic_array = np.zeros((height, width), dtype=np.int32)

for f in tqdm(all_worker_files, desc="Aggregating Files"):
    try:
        worker_array = np.load(f)
        traffic_array += worker_array
    except Exception as e:
        print(f"Warning: Could not load file {f}: {e}")
print("Aggregation complete.")

# --- 3. Save the Final Traffic GeoTIFF ---
print("Saving final aggregated traffic array to GeoTIFF...")

# Update metadata for the new traffic raster
# The traffic array is int32 and 0 represents 'no crossings'.
output_meta = meta.copy()
output_meta.update({
    'dtype': np.int32,
    'count': 1,
    'nodata': 0, 
    # Ensure the dimensions match the aggregated array
    'height': height,
    'width': width
})

FINAL_TRAFFIC_TIF = os.path.join(RESULTS_DIR, "final_corridor_traffic.tif")

try:
    with rasterio.open(FINAL_TRAFFIC_TIF, 'w', **output_meta) as dst:
        dst.write(traffic_array.astype(np.int32), 1)
    print(f"GeoTIFF saved successfully to {FINAL_TRAFFIC_TIF}")
except Exception as e:
    print(f"Error saving GeoTIFF: {e}")
    sys.exit(1)

# --- 4. Plot and Save the Final Traffic Map ---
print("Plotting results...")
traffic_masked = np.ma.masked_equal(traffic_array, 0)
max_crossings = traffic_array.max()
print(f"Maximum crossings on a single pixel: {max_crossings}")

fig, ax = plt.subplots(figsize=(12, 12))
cmap = plt.colormaps.get('RdYlGn').copy()
cmap.set_bad(color='black')
if max_crossings == 0:
    print("ANALYSIS RESULT: No paths were accumulated.")
    im = ax.imshow(traffic_masked, cmap=cmap)
elif max_crossings == 1:
    print("Warning: Max crossings is 1. Switching to a linear scale.")
    norm = colors.Normalize(vmin=1, vmax=1)
    im = ax.imshow(traffic_masked, cmap=cmap, norm=norm)
    cbar = fig.colorbar(im, ax=ax, shrink=0.7, ticks=[1])
    cbar.set_label('Number of LCP Crossings (Linear Scale)')
else:
    print("Using logarithmic scale for plotting.")
    norm = colors.LogNorm(vmin=1, vmax=max_crossings)
    im = ax.imshow(traffic_masked, cmap=cmap, norm=norm)
    cbar = fig.colorbar(im, ax=ax, shrink=0.7)
    cbar.set_label('Number of LCP Crossings (Log Scale)')
ax.set_title("Accumulated LCP Traffic (Corridor Hotspots)", fontsize=16)
ax.set_xlabel('Easting (Pixel Coordinates)')
ax.set_ylabel('Northing (Pixel Coordinates)')
plt.tight_layout()
PLOT_FILE_OUT = os.path.join(RESULTS_DIR, "corridor_traffic_map_grid.png")
print(f"Saving plot to {PLOT_FILE_OUT}...")
plt.savefig(PLOT_FILE_OUT, dpi=300)

# --- 5. Plot and Save Composite Map ---

print("Plotting combined results map with enhanced highlighting...")
plot_resistance = resistance_array.copy().astype(float)
plot_resistance[plot_resistance == EXTREME_BARRIER_COST] = np.nan

# Re-calculate nodes *and filter them* for plotting
spacing_pixels = int(GRID_SPACING_METERS / resolution)
rows = np.arange(0, height, spacing_pixels)
cols = np.arange(0, width, spacing_pixels)
xx, yy = np.meshgrid(cols, rows)
all_grid_nodes = list(zip(yy.ravel(), xx.ravel()))

# This line filters out the "wrong" nodes and CASTS to int
valid_grid_nodes = [
    (int(r), int(c)) for r, c in all_grid_nodes 
    if resistance_array[int(r), int(c)] < EXTREME_BARRIER_COST
]

# This line plots ONLY the valid nodes
node_rows, node_cols = zip(*valid_grid_nodes)

fig, ax = plt.subplots(figsize=(15, 15))
cmap_base = plt.colormaps.get('Blues').copy()
cmap_base.set_bad(color='white')
# Calculate a reasonable max, e.g., the 99th percentile
vmax_resistance = np.nanpercentile(plot_resistance, 99) 
if vmax_resistance <= 1: # Handle edge case
     vmax_resistance = 1000 
im_base = ax.imshow(plot_resistance, cmap=cmap_base, norm=colors.LogNorm(vmin=1, vmax=vmax_resistance), alpha=0.5)

cbar_base = fig.colorbar(im_base, ax=ax, shrink=0.7, pad=0.02, label='Resistance Cost (Log Scale)')
cmap_traffic = plt.colormaps.get('RdYlGn').copy()
cmap_traffic.set_bad(color='none')

if max_crossings > 0:
    norm_traffic = colors.LogNorm(vmin=1, vmax=max_crossings) if max_crossings > 1 else colors.Normalize(vmin=1, vmax=1)
    im_traffic = ax.imshow(traffic_masked, cmap=cmap_traffic, norm=norm_traffic)

ax.scatter(node_cols, node_rows, s=75, c='red', marker='x', label='Grid Nodes (1km)') # <-- This now plots the correct nodes
ax.set_title("LCP Corridors on Resistance Surface (Highlighted)", fontsize=20)
ax.set_xlabel('Easting (Pixel Coordinates)')
ax.set_ylabel('Northing (Pixel Coordinates)')
ax.legend(loc='upper right', facecolor='white', framealpha=0.7)
plt.tight_layout()
PLOT_FILE_OUT_COMPOSITE = os.path.join(RESULTS_DIR, "final_composite_map_highlighted.png")
print(f"Saving composite plot to {PLOT_FILE_OUT_COMPOSITE}...")
plt.savefig(PLOT_FILE_OUT_COMPOSITE, dpi=300, bbox_inches='tight')

print("Analysis and plotting complete.")
