import rasterio
import numpy as np
import matplotlib
matplotlib.use('Agg') # <-- Use non-interactive backend for HPC
import matplotlib.pyplot as plt
import matplotlib.colors as colors
from skimage.graph import MCP_Geometric
import os
from tqdm import tqdm # <-- Use standard tqdm
from joblib import Parallel, delayed # <-- Import for parallel processing
import lcp_utils # <-- Import your new worker file

# --- 0. Define Base Directory ---
# This makes the script run from its own location
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(BASE_DIR, "Results")
# Ensure Results directory exists
os.makedirs(RESULTS_DIR, exist_ok=True)

# --- 1. Define Paths and Settings ---
FINAL_RASTER = os.path.join(RESULTS_DIR, "final_resistance_surface.tif")
GRID_SPACING_METERS = 1000  # 1km grid
EXTREME_BARRIER_COST = 1000  # A very high cost

# --- 2. Load Final Resistance Raster ---
print(f"Loading FINAL cost surface from {FINAL_RASTER}...")
with rasterio.open(FINAL_RASTER) as src:
    resistance_array = src.read(1)
    meta = src.meta.copy()
    nodata_val = meta['nodata']
    resolution = meta['transform'][0] 
    resistance_array[resistance_array == nodata_val] = EXTREME_BARRIER_COST
    resistance_array[resistance_array <= 0] = 1 
    height, width = resistance_array.shape
print(f"Cost matrix loaded. Shape: {height}x{width}")

# --- 3. Create the Structured Grid of Nodes ---
spacing_pixels = int(GRID_SPACING_METERS / resolution)
print(f"Creating a node grid with {spacing_pixels}-pixel spacing...")
rows = np.arange(0, height, spacing_pixels)
cols = np.arange(0, width, spacing_pixels)
xx, yy = np.meshgrid(cols, rows)
all_grid_nodes = list(zip(yy.ravel(), xx.ravel()))

# --- 4. Filter Nodes ---
valid_grid_nodes = [
    (r, c) for r, c in all_grid_nodes 
    if resistance_array[r, c] < EXTREME_BARRIER_COST
]
print(f"Total nodes created: {len(all_grid_nodes)}")
print(f"Valid (reachable) nodes: {len(valid_grid_nodes)}")

# --- 5. All-Pairs Path Calculation (PARALLEL VERSION) ---
print(f"Calculating all-pairs paths between {len(valid_grid_nodes)} nodes...")
node_count = len(valid_grid_nodes)

# n_jobs=-1 tells joblib to use ALL cores you requested in your HPC job
print(f"Starting parallel processing on all available cores...")
results_list = Parallel(n_jobs=-1)(
    delayed(lcp_utils.process_single_node)(
        valid_grid_nodes[i],
        valid_grid_nodes,
        resistance_array,
        i,
        node_count
    ) 
    for i in tqdm(range(node_count), desc="Processing Start Nodes")
)

print("Parallel processing complete.")
print("Summing results from all workers...")
# Sum all the individual traffic arrays into one
traffic_array = np.sum(results_list, axis=0).astype(np.int32)
print("Path accumulation complete.")

# --- 6. Plot and Save the Final Traffic Map ---
print("Plotting results...")
traffic_masked = np.ma.masked_equal(traffic_array, 0)
max_crossings = traffic_array.max()
print(f"Maximum crossings on a single pixel: {max_crossings}")

fig, ax = plt.subplots(figsize=(12, 12))
cmap = plt.cm.get_cmap('RdYlGn').copy()
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
# plt.show() # <-- REMOVED

# --- 7. Plot and Save Composite Map ---
print("Plotting combined results map with enhanced highlighting...")
plot_resistance = resistance_array.copy().astype(float)
plot_resistance[plot_resistance == EXTREME_BARRIER_COST] = np.nan
node_rows, node_cols = zip(*valid_grid_nodes)

fig, ax = plt.subplots(figsize=(15, 15))
cmap_base = plt.cm.get_cmap('magma').copy() # Switched to 'magma'
cmap_base.set_bad(color='black')
im_base = ax.imshow(plot_resistance, cmap=cmap_base, norm=colors.LogNorm(vmin=1, vmax=1000), alpha=0.5)
cbar_base = fig.colorbar(im_base, ax=ax, shrink=0.7, pad=0.02, label='Resistance Cost (Log Scale)')

cmap_traffic = plt.cm.get_cmap('cool').copy() # Switched to 'cool' (cyan-magenta)
cmap_traffic.set_bad(color='none')

if max_crossings > 0:
    norm_traffic = colors.LogNorm(vmin=1, vmax=max_crossings) if max_crossings > 1 else colors.Normalize(vmin=1, vmax=1)
    im_traffic = ax.imshow(traffic_masked, cmap=cmap_traffic, norm=norm_traffic)

ax.scatter(node_cols, node_rows, s=75, c='red', marker='x', label='Grid Nodes (10km)')
ax.set_title("LCP Corridors on Resistance Surface (Highlighted)", fontsize=20)
ax.set_xlabel('Easting (Pixel Coordinates)')
ax.set_ylabel('Northing (Pixel Coordinates)')
ax.legend(loc='upper right', facecolor='white', framealpha=0.7)
plt.tight_layout()

PLOT_FILE_OUT_COMPOSITE = os.path.join(RESULTS_DIR, "final_composite_map_highlighted.png")
print(f"Saving composite plot to {PLOT_FILE_OUT_COMPOSITE}...")
plt.savefig(PLOT_FILE_OUT_COMPOSITE, dpi=300, bbox_inches='tight')
# plt.show() # <-- REMOVED

# --- 8. Save the Data as a GeoTIFF ---
traffic_meta = meta.copy()
traffic_meta.update(dtype='int32', nodata=0)
TRAFFIC_RASTER_OUT = os.path.join(RESULTS_DIR, "corridor_traffic_grid.tif")

print(f"Saving traffic raster to {TRAFFIC_RASTER_OUT}...")
with rasterio.open(TRAFFIC_RASTER_OUT, 'w', **traffic_meta) as dest:
    dest.write(traffic_array, 1)

print("Analysis and plotting complete.")