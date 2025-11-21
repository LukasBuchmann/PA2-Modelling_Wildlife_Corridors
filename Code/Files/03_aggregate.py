import numpy as np
import rasterio
import os, glob, sys
import matplotlib
matplotlib.use('Agg') # Essential for HPC (no screen)
import matplotlib.pyplot as plt
import matplotlib.colors as colors
from pathlib import Path

# --- 1. CONFIGURATION & PATHS ---
# Paths are defined relative to this script so it works regardless of where the folder is moved
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent 
RESULTS_DIR = PROJECT_ROOT / "results"
TEMP_DIR = RESULTS_DIR / "temp_traffic"

# Output Files
FINAL_TIF = RESULTS_DIR / "final_corridor_traffic.tif"
PLOT_RESISTANCE = RESULTS_DIR / "map_01_resistance_surface.png"
PLOT_NETWORK = RESULTS_DIR / "map_02_network_overview.png"
PLOT_BOTTLENECKS = RESULTS_DIR / "map_03_bottlenecks.png"

# Ecological Parameters (Must match what was used in the Worker script)
GRID_SPACING_METERS = 1000  # 1km Grid
TARGET_RESISTANCE = 1.0     # Core Habitat

# Check if input exists
RESISTANCE_TIF = RESULTS_DIR / "final_resistance_surface.tif"
if not RESISTANCE_TIF.exists():
    print(f"Error: Resistance surface not found at {RESISTANCE_TIF}")
    sys.exit(1)

# --- 2. DATA LOADING & AGGREGATION ---
print("Loading base resistance surface...")
with rasterio.open(RESISTANCE_TIF) as src:
    meta = src.meta.copy()
    # The data and the transform (for calculating coordinates) are read
    resistance_data = src.read(1).astype(np.float32)
    transform = src.transform
    nodata_val = src.nodata

# Robust cleaning: Nodata/Inf values are replaced with a high barrier value for plotting consistency
# This ensures the plots don't have white holes inside the study area
resistance_plot = resistance_data.copy()
resistance_plot = np.nan_to_num(resistance_plot, nan=10000.0, posinf=10000.0, neginf=1.0)
if nodata_val is not None:
    resistance_plot[resistance_plot == nodata_val] = 10000.0
# Strictly positive values are ensured for LogNorm plotting
resistance_plot[resistance_plot < 1.0] = 1.0

print("Aggregating worker results...")
traffic_sum = np.zeros(resistance_data.shape, dtype=np.int32)
worker_files = list(TEMP_DIR.glob("worker_*.npy"))

if not worker_files:
    print("Warning: No worker files found. The map will be empty.")
else:
    # All partial arrays from the workers are summed up
    for f in worker_files:
        try:
            traffic_sum += np.load(f)
        except Exception as e:
            print(f"Skipping corrupted file {f}: {e}")

print(f"Aggregation complete. Max crossings: {traffic_sum.max()}")

# The aggregated traffic is saved to a GeoTIFF for later use in QGIS
meta.update(dtype='int32', nodata=0, count=1)
with rasterio.open(FINAL_TIF, 'w', **meta) as dst:
    dst.write(traffic_sum, 1)
print(f"Saved traffic raster to {FINAL_TIF}")

# --- 3. PLOTTING ---

# Common Plot Settings
pixel_size = transform[0]
height, width = resistance_data.shape

# --- PLOT 1: Resistance Surface Alone (RdYlGn_r) ---
print("Generating Plot 1: Resistance Surface...")
fig, ax = plt.subplots(figsize=(12, 10))

# LogNorm is used because costs range from 1 to 10,000
# cmap 'RdYlGn_r' means: Red=High Cost, Green=Low Cost
im = ax.imshow(
    resistance_plot, 
    cmap='RdYlGn_r', 
    norm=colors.LogNorm(vmin=1, vmax=10000),
    interpolation='none'
)
cbar = fig.colorbar(im, ax=ax, shrink=0.7, label='Resistance Cost (Log Scale)')
ax.set_title("Ecological Resistance Surface (Green = Habitat, Red = Barrier)")
ax.set_xlabel("Easting (px)")
ax.set_ylabel("Northing (px)")

plt.savefig(PLOT_RESISTANCE, dpi=600, bbox_inches='tight')
plt.close()

# --- PLOT 2: Network Overview (Gray Base + Nodes + Traffic) ---
print("Generating Plot 2: Network Overview with Nodes...")
fig, ax = plt.subplots(figsize=(15, 12))

# A. Background: Gray Resistance
ax.imshow(
    resistance_plot, 
    cmap='Greys', 
    norm=colors.LogNorm(vmin=1, vmax=10000), 
    alpha=0.6
)

# B. Overlay: Traffic (Corridors)
# 0 values are masked so they are transparent
if traffic_sum.max() > 0:
    masked_traffic = np.ma.masked_equal(traffic_sum, 0)
    im_traffic = ax.imshow(masked_traffic, cmap='viridis', alpha=0.8)
    plt.colorbar(im_traffic, ax=ax, shrink=0.7, label='Path Density (Number of Crossings)')

# C. Overlay: Valid Nodes
# The logic from the Worker script is replicated to verify where nodes were placed
print("   Recalculating node positions for visualization...")
spacing_px = int(GRID_SPACING_METERS / pixel_size)
rows = np.arange(0, height, spacing_px)
cols = np.arange(0, width, spacing_px)
node_x, node_y = [], []

for r in rows:
    for c in cols:
        if 0 < r < height-1 and 0 < c < width-1:
            # It is checked if this grid point was actually a valid habitat (Resistance ~ 1.0)
            if resistance_plot[r, c] <= (TARGET_RESISTANCE + 0.01):
                node_x.append(c)
                node_y.append(r)

ax.scatter(node_x, node_y, c='red', s=15, marker='x', label=f'Start/End Nodes ({GRID_SPACING_METERS}m)')
ax.legend(loc='upper right')
ax.set_title(f"Connectivity Network: {len(node_x)} Core Habitat Nodes")

plt.savefig(PLOT_NETWORK, dpi=600, bbox_inches='tight')
plt.close()

# --- PLOT 3: Critical Bottlenecks ---
print("Generating Plot 3: Important Bottlenecks...")
# Definition: A bottleneck is a "High Usage" area (Top 5% of traffic)
# The threshold is defined for the top 5% of active corridor pixels
if traffic_sum.max() > 0:
    non_zero = traffic_sum[traffic_sum > 0]
    thresh_95 = np.percentile(non_zero, 95)
    print(f"   Bottleneck Threshold (Top 5%): > {thresh_95} crossings")
    
    # A mask is created for these high-traffic areas
    bottleneck_mask = np.ma.masked_less(traffic_sum, thresh_95)
    
    fig, ax = plt.subplots(figsize=(15, 12))
    
    # Base: Faded Resistance
    ax.imshow(resistance_plot, cmap='Greys', norm=colors.LogNorm(vmin=1, vmax=10000), alpha=0.4)
    
    # Layer: The Bottlenecks (Red/Orange/Yellow heatmap)
    im_bottle = ax.imshow(bottleneck_mask, cmap='hot_r', alpha=0.9)
    
    cbar = fig.colorbar(im_bottle, ax=ax, shrink=0.7, label='Traffic Intensity (Top 5%)')
    ax.set_title("Critical Bottlenecks (Highest Traffic Density)")
    
    # Optional: Areas are circled where high traffic meets high resistance (High Risk)
    # This identifies where animals are crossing roads/barriers frequently
    high_res_bottlenecks = (traffic_sum > thresh_95) & (resistance_plot > 100.0)
    if np.any(high_res_bottlenecks):
        y_risk, x_risk = np.where(high_res_bottlenecks)
        # Downsample for plotting clarity if there are too many
        if len(x_risk) > 1000:
            idx = np.random.choice(len(x_risk), 1000, replace=False)
            x_risk, y_risk = x_risk[idx], y_risk[idx]
            
        ax.scatter(x_risk, y_risk, facecolors='none', edgecolors='blue', s=50, alpha=0.6, label='High-Risk Crossing (Traffic + Barrier)')
        ax.legend(loc='upper right')

    plt.savefig(PLOT_BOTTLENECKS, dpi=600, bbox_inches='tight')
    plt.close()
else:
    print("   No traffic data found, skipping bottleneck plot.")

print("--- Processing Finished ---")