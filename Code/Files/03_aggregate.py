"""
ZHAW Project Work 2: Aggregation and Visualization.

This script aggregates the partial results from the parallel workers and generates
the final connectivity maps and statistics.

Outputs:
1. Final Traffic Raster (GeoTIFF)
2. Map 01: Resistance Surface
3. Map 02: Network Overview
4. Map 03: Critical Bottlenecks

Author: Lukas Buchmann
Date: November 2025
"""

import sys
import numpy as np
import rasterio
import matplotlib
matplotlib.use('Agg')  # Essential for HPC (Headless)
import matplotlib.pyplot as plt
import matplotlib.colors as colors
from pathlib import Path
import copy

# --- CONFIGURATION ---
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
RESULTS_DIR = PROJECT_ROOT / "results"
TEMP_DIR = RESULTS_DIR / "temp_traffic"

# Inputs
RESISTANCE_TIF = RESULTS_DIR / "final_resistance_surface.tif"

# Outputs
FINAL_TRAFFIC_TIF = RESULTS_DIR / "final_corridor_traffic.tif"
PLOT_RESISTANCE = RESULTS_DIR / "map_01_resistance_surface.png"
PLOT_NETWORK = RESULTS_DIR / "map_02_network_overview.png"
PLOT_BOTTLENECKS = RESULTS_DIR / "map_03_bottlenecks.png"

# Parameters
GRID_SPACING_METERS = 2000
TARGET_RESISTANCE = 1.0


def load_resistance_surface(path):
    """Loads resistance data and metadata."""
    if not path.exists():
        sys.exit(f"CRITICAL ERROR: Input file not found at {path}")
    
    with rasterio.open(path) as src:
        data = src.read(1).astype(np.float32)
        meta = src.meta.copy()
        transform = src.transform
        nodata = src.nodata
    return data, meta, transform, nodata


def aggregate_worker_results(shape, temp_dir):
    """Sums up all partial .npy files from workers."""
    print("--- Aggregating Worker Results ---")
    traffic_sum = np.zeros(shape, dtype=np.int32)
    files = list(temp_dir.glob("worker_*.npy"))
    
    if not files:
        print("WARNING: No worker output found. Result will be empty.")
        return traffic_sum

    for f in files:
        try:
            traffic_sum += np.load(f)
        except Exception as e:
            print(f"Skipping corrupted file {f.name}: {e}")
            
    print(f"Aggregation complete. Max crossings: {traffic_sum.max()}")
    return traffic_sum


def save_traffic_raster(traffic_data, meta, out_path):
    """Saves the aggregated traffic map to GeoTIFF."""
    meta.update(dtype='int32', nodata=0, count=1)
    with rasterio.open(out_path, 'w', **meta) as dst:
        dst.write(traffic_data, 1)
    print(f"Saved traffic raster to {out_path}")


def prepare_plot_data(data, nodata_val):
    """
    Prepares data for plotting:
    1. Copies data to avoid mutation.
    2. Converts NoData to NaN (for transparency).
    3. Handles strict zeros for LogNorm safety.
    """
    plot_data = data.copy()
    
    # Handle explicit NoData
    if nodata_val is not None:
        plot_data[plot_data == nodata_val] = np.nan
        
    # Safety for LogNorm (values <= 0 become NaN)
    # We use 'where' to safely ignore existing NaNs during comparison
    mask = (plot_data <= 0) & (~np.isnan(plot_data))
    plot_data[mask] = np.nan
    
    return plot_data


def plot_resistance_map(resistance_plot, out_path):
    """Generates Map 01: The Resistance Surface."""
    print("Generating Map 01...")
    fig, ax = plt.subplots(figsize=(12, 10))
    
    # Create transparent colormap for NaNs
    cmap = copy.copy(plt.cm.RdYlGn_r)
    cmap.set_bad(color='white', alpha=0)

    im = ax.imshow(
        resistance_plot, 
        cmap=cmap, 
        norm=colors.LogNorm(vmin=1, vmax=5000),
        interpolation='none'
    )
    fig.colorbar(im, ax=ax, shrink=0.7, label='Resistance Cost (Log Scale)')
    ax.set_title("Ecological Resistance Surface")
    ax.set_xlabel("Easting (px)")
    ax.set_ylabel("Northing (px)")
    
    plt.savefig(out_path, dpi=300, bbox_inches='tight')
    plt.close()


def plot_network_overview(resistance_plot, traffic_data, transform, out_path):
    """Generates Map 02: Network Overview with Nodes."""
    print("Generating Map 02...")
    fig, ax = plt.subplots(figsize=(15, 12))
    
    # Base: Grey Resistance
    cmap_base = copy.copy(plt.cm.Greys)
    cmap_base.set_bad(alpha=0)
    ax.imshow(resistance_plot, cmap=cmap_base, norm=colors.LogNorm(vmin=1, vmax=5000), alpha=0.3)

    # Overlay: Traffic
    if traffic_data.max() > 0:
        # Buffer and Smooth Traffic Data for Visualization
        # Simple smoothing using NumPy (3×3 mean filter)
        kernel_size = 3
        pad = kernel_size // 2

        # Pad array to avoid border issues
        padded = np.pad(traffic_data, pad, mode='edge')

        # Prepare output
        smoothed = np.zeros_like(traffic_data, dtype=float)

        # Manual 3×3 convolution
        for i in range(traffic_data.shape[0]):
            for j in range(traffic_data.shape[1]):
                window = padded[i:i+kernel_size, j:j+kernel_size]
                smoothed[i, j] = window.mean()
 

        masked_traffic = np.ma.masked_equal(smoothed, 0)
        im_traffic = ax.imshow(masked_traffic, cmap='viridis', alpha=1.0)
        fig.colorbar(im_traffic, ax=ax, shrink=0.7, label='Path Density')
    

    # Overlay: Nodes (Visual verification)
    h, w = resistance_plot.shape
    pixel_res = transform[0]
    step = int(GRID_SPACING_METERS / pixel_res)
    
    # Efficient Node Calculation
    rows = np.arange(0, h, step)
    cols = np.arange(0, w, step)
    # Use meshgrid for vectorized coordinate generation
    rr, cc = np.meshgrid(rows, cols, indexing='ij')
    # Valid nodes check (must not be NaN and match target)
    # Note: resistance_plot has NaNs where data was missing/invalid
    valid_mask = (resistance_plot[rr, cc] == TARGET_RESISTANCE)
    node_y, node_x = rr[valid_mask], cc[valid_mask]

    ax.scatter(node_x, node_y, c='red', s=15, marker='x', label='Nodes')
    ax.legend(loc='upper right')
    ax.set_title(f"Connectivity Network ({len(node_x)} Nodes)")
    
    plt.savefig(out_path, dpi=300, bbox_inches='tight')
    plt.close()


def plot_bottlenecks(resistance_plot, traffic_data, out_path):
    """Generates Map 03: Critical Bottlenecks."""
    print("Generating Map 03...")
    if traffic_data.max() == 0:
        print("Skipping Map 03 (No Traffic).")
        return

    # Identify Top 5% Traffic
    non_zero = traffic_data[traffic_data > 0]
    thresh = np.percentile(non_zero, 95)
    bottleneck_mask = np.ma.masked_less(traffic_data, thresh)
    
    fig, ax = plt.subplots(figsize=(15, 12))
    
    # Base
    cmap_base = copy.copy(plt.cm.Greys)
    cmap_base.set_bad(alpha=0)
    ax.imshow(resistance_plot, cmap=cmap_base, norm=colors.LogNorm(vmin=1, vmax=5000), alpha=0.4)
    
    # Bottlenecks
    im = ax.imshow(bottleneck_mask, cmap='hot_r', alpha=0.9)
    fig.colorbar(im, ax=ax, shrink=0.7, label='Traffic Intensity (Top 5%)')
    ax.set_title("Critical Bottlenecks")

    # High Risk Circles (High Traffic + High Resistance)
    # Compare raw data, not plot data (to avoid NaN issues)
    risk_mask = (traffic_data > thresh) & (resistance_plot > 2000)
    # Fill NaNs in risk_mask with False
    risk_mask = np.nan_to_num(risk_mask, nan=False)
    
    if np.any(risk_mask):
        y_risk, x_risk = np.where(risk_mask)
        # Downsample
        if len(x_risk) > 1000:
            idx = np.random.choice(len(x_risk), 1000, replace=False)
            x_risk, y_risk = x_risk[idx], y_risk[idx]
        
        ax.scatter(x_risk, y_risk, facecolors='none', edgecolors='red', s=50, alpha=0.6, label='High Risk')
        ax.legend(loc='upper right')

    plt.savefig(out_path, dpi=300, bbox_inches='tight')
    plt.close()


def main():
    # 1. Load Data
    res_data, meta, transform, nodata = load_resistance_surface(RESISTANCE_TIF)

    # 2. Aggregate Results
    traffic_data = aggregate_worker_results(res_data.shape, TEMP_DIR)
    save_traffic_raster(traffic_data, meta, FINAL_TRAFFIC_TIF)

    # 3. Prepare Data for Plotting (Handle Transparency)
    # Transform the data ONCE for visualization purposes
    res_plot = prepare_plot_data(res_data, nodata)

    # 4. Generate Maps
    plot_resistance_map(res_plot, PLOT_RESISTANCE)
    plot_network_overview(res_plot, traffic_data, transform, PLOT_NETWORK)
    plot_bottlenecks(res_plot, traffic_data, PLOT_BOTTLENECKS)


if __name__ == "__main__":
    main()