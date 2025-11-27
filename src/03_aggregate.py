"""
Module: 03_visualization.py
Project: PA2 - Modelling Wildlife Corridors (ZHAW Wädenswil)
Author: Lukas Buchmann
Date: November 2025

Description:
    This script handles the visualization and data extraction phase of the 
    ecological connectivity project. It loads the processed resistance surface 
    and the aggregated Least Cost Path (LCP) traffic raster to generate 
    cartographic figures for the written report.

    It specifically identifies "Critical Bottlenecks" by isolating pixels 
    with high traffic intensity in high-resistance zones.

Inputs:
    - final_resistance_surface.tif: The landscape resistance model.
    - final_corridor_traffic.tif: The cumulative path density raster.

Outputs:
    - map_01_resistance_surface.png: Visualizes landscape permeability.
    - map_02_network_overview.png: Visualizes the connectivity network.
    - map_03_bottlenecks.png: Visualizes top priority conflict zones.
    - bottlenecks_table.csv: Coordinates and intensity of top bottlenecks.

Dependencies:
    - numpy, pandas, rasterio, matplotlib, scipy
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd
import rasterio
from scipy import ndimage 

import matplotlib
# Use Agg backend for non-interactive saving (standard for reproducible pipelines)
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.colors as colors
import matplotlib.patheffects as pe 

# --- CONFIGURATION -----------------------------------------------------------
# Define paths relative to the script location for reproducibility
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
RESULTS_DIR = PROJECT_ROOT / "results"

# Input Files
RESISTANCE_TIF = RESULTS_DIR / "final_resistance_surface.tif"
FINAL_TRAFFIC_TIF = RESULTS_DIR / "final_corridor_traffic.tif"

# Output Files
PLOT_RESISTANCE = RESULTS_DIR / "map_01_resistance_surface.png"
PLOT_NETWORK = RESULTS_DIR / "map_02_network_overview.png"
PLOT_BOTTLENECKS = RESULTS_DIR / "map_03_bottlenecks.png"
OUTPUT_CSV = RESULTS_DIR / "bottlenecks_table.csv"

# Visualization Parameters
GRID_SPACING_METERS = 2000  # Spacing for node visualization overlay
TARGET_RESISTANCE = 1.0     # Value representing core habitat nodes
BOTTLENECK_PERCENTILE = 95  # Threshold for "Critical" traffic (Top 5%)
MIN_BARRIER_RESISTANCE = 3000 # Minimum resistance to be considered a bottleneck


# --- HELPER FUNCTIONS --------------------------------------------------------

def force_2d(data, name="Data"):
    """
    Ensures the input array is strictly 2-dimensional (Height, Width).
    
    Rasterio reads often return (1, H, W). This function removes the 
    singleton dimension to prevent broadcasting errors during analysis.
    """
    if data.ndim == 2:
        return data
    if data.ndim >= 3:
        # Take the first band if data is 3D
        return data[0]
    return data


def load_raster(path):
    """
    Loads raster data, metadata, and transform object.
    
    Args:
        path (Path): Filepath to the .tif file.
        
    Returns:
        tuple: (data_array, metadata, affine_transform, nodata_value)
    """
    if not path.exists():
        sys.exit(f"CRITICAL ERROR: Input file not found at {path}")
    
    with rasterio.open(path) as src:
        data = src.read(1)
        meta = src.meta.copy()
        transform = src.transform
        nodata = src.nodata
    
    # Pre-process to ensure correct shape for plotting
    data = force_2d(data, name=path.name)
    return data, meta, transform, nodata


def prepare_plot_data(data, nodata_val):
    """
    Converts data to float and handles NoData values for plotting.
    
    Sets NoData and Zeros to np.nan so they appear transparent 
    in Matplotlib overlays.
    """
    data = force_2d(data, "PlotData")
    plot_data = data.astype(float).copy()
    
    if nodata_val is not None:
        plot_data[plot_data == nodata_val] = np.nan
    
    # Mask zeros/negatives to avoid errors with Logarithmic scales
    mask = (plot_data <= 0) & (~np.isnan(plot_data))
    plot_data[mask] = np.nan
    
    return plot_data


# --- PLOTTING FUNCTIONS ------------------------------------------------------

def plot_resistance_map(resistance_plot, out_path):
    """
    Generates Map 01: The Ecological Resistance Surface.
    
    Uses a Logarithmic color scale because resistance values span 
    several orders of magnitude (1 to 10,000).
    """
    print(f"Generating Map 01 -> {out_path.name}...")
    resistance_plot = force_2d(resistance_plot, "ResistancePlot")

    fig, ax = plt.subplots(figsize=(12, 10))
    
    # Red-Yellow-Green colormap (Green = Low Cost, Red = High Cost)
    cmap = plt.cm.RdYlGn_r.copy()
    cmap.set_bad(color='white', alpha=0)

    im = ax.imshow(
        resistance_plot, 
        cmap=cmap, 
        norm=colors.LogNorm(vmin=1, vmax=5000),
        interpolation='none'
    )
    fig.colorbar(im, ax=ax, shrink=0.7, label='Resistance Cost (Log Scale)')
    ax.set_title("Ecological Resistance Surface")
    
    plt.axis('off')
    plt.savefig(out_path, dpi=300, bbox_inches='tight')
    plt.close()


def plot_network_overview(resistance_plot, traffic_data, transform, out_path):
    """
    Generates Map 02: Network Overview.
    
    Visualizes the cumulative path density. High density (Yellow) indicates
    corridors where movement is funneled.
    """
    print(f"Generating Map 02 -> {out_path.name}...")
    traffic_data = force_2d(traffic_data, "TrafficData")
    resistance_plot = force_2d(resistance_plot, "ResistancePlot")

    fig, ax = plt.subplots(figsize=(15, 12))
    
    # 1. Plot Background (Grey Resistance)
    cmap_base = plt.cm.Greys.copy()
    cmap_base.set_bad(alpha=0)
    ax.imshow(resistance_plot, cmap=cmap_base, norm=colors.LogNorm(vmin=1, vmax=5000), alpha=0.3)

    # 2. Plot Traffic (Path Density)
    if traffic_data.max() > 0:
        # Apply morphological dilation to visually thicken the lines.
        # This makes thin 1-pixel paths visible on a large map figure.
        thickened_traffic = ndimage.grey_dilation(traffic_data, size=(5,5))
        
        masked_traffic = np.ma.masked_equal(thickened_traffic, 0)
        im_traffic = ax.imshow(masked_traffic, cmap='viridis', alpha=1.0)
        fig.colorbar(im_traffic, ax=ax, shrink=0.7, label='Cumulative Flow Intensity')

    # 3. Plot Habitat Nodes (Red X)
    # Calculate grid positions for nodes based on spacing parameter
    h, w = resistance_plot.shape
    pixel_res = transform[0]
    step = int(GRID_SPACING_METERS / pixel_res)
    
    rows = np.arange(0, h, step)
    cols = np.arange(0, w, step)
    rr, cc = np.meshgrid(rows, cols, indexing='ij')
    
    # Filter for pixels that are actual nodes (Resistance == 1.0)
    valid_mask = (resistance_plot[rr, cc] == TARGET_RESISTANCE)
    node_y, node_x = rr[valid_mask], cc[valid_mask]

    ax.scatter(node_x, node_y, c='red', s=15, marker='x', label='Core Nodes')
    ax.legend(loc='upper right')
    ax.set_title("Connectivity Network & Path Density")
    
    plt.axis('off')
    plt.savefig(out_path, dpi=300, bbox_inches='tight')
    plt.close()


def plot_bottlenecks(resistance_plot, traffic_data, transform, out_path_map, out_path_csv):
    """
    Generates Map 03: Critical Bottlenecks (Single Pixels).
    
    Identifies specific pixels where:
    1. Traffic intensity is in the top percentile (High Movement).
    2. Resistance is high (Barrier).
    
    Exports coordinates to CSV for QGIS validation and reporting.
    """
    print(f"Generating Map 03 -> {out_path_map.name}...")
    traffic_data = force_2d(traffic_data, "TrafficData")
    resistance_plot = force_2d(resistance_plot, "ResistancePlot")
    
    if traffic_data.max() == 0:
        print("Skipping Map 03 (No Traffic).")
        return

    # 1. Define Criteria for "Bottleneck"
    non_zero = traffic_data[traffic_data > 0]
    thresh = np.percentile(non_zero, BOTTLENECK_PERCENTILE) 
    
    # Logic: It is a bottleneck if it's heavily used AND it's a barrier (e.g. road)
    binary_mask = (traffic_data >= thresh) & (resistance_plot >= MIN_BARRIER_RESISTANCE)
    
    # 2. Extract Single Pixels
    rows, cols = np.where(binary_mask)
    values = traffic_data[rows, cols]
    
    print(f"Found {len(values)} bottleneck pixels matching criteria.")

    # 3. Setup Plot
    fig, ax = plt.subplots(figsize=(15, 12))
    
    # Background
    cmap_base = plt.cm.Greys.copy()
    cmap_base.set_bad(alpha=0)
    ax.imshow(resistance_plot, cmap=cmap_base, norm=colors.LogNorm(vmin=1, vmax=5000), alpha=0.4)
    
    # Heatmap (Filtered)
    bottleneck_display = np.ma.masked_where(~binary_mask, traffic_data)
    im = ax.imshow(bottleneck_display, cmap='hot_r', alpha=0.9)
    fig.colorbar(im, ax=ax, shrink=0.7, label='Traffic Intensity (Filtered)')
    
    # 4. Process Data for CSV and Labeling
    bottleneck_data = []
    for r, c, val in zip(rows, cols, values):
        # Convert matrix coordinates to Real World Coordinates (LV95/UTM)
        real_x, real_y = rasterio.transform.xy(transform, r, c, offset='center')
        bottleneck_data.append({
            "Coords_E": int(real_x),
            "Coords_N": int(real_y),
            "Path_Intensity": int(val),
            "Pixel_Row": r,
            "Pixel_Col": c
        })
    
    df = pd.DataFrame(bottleneck_data)
    
    if not df.empty:
        # Sort by intensity to identify the most critical points
        df = df.sort_values(by="Path_Intensity", ascending=False)
        df.insert(0, 'ID', range(1, len(df) + 1))
        
        # 5. Label the Top 20 Pixels on the Map
        # We limit labeling to keep the map readable
        top_n = 20
        for _, row in df.head(top_n).iterrows():
            px, py = row['Pixel_Col'], row['Pixel_Row']
            
            # Draw red circle
            ax.add_patch(plt.Circle((px, py), radius=40, color='red', fill=False, linewidth=2))
            
            # Add numeric label
            ax.annotate(str(row['ID']), 
                        xy=(px, py), 
                        xytext=(15, 15), 
                        textcoords="offset points",
                        color='red', 
                        fontsize=12, 
                        fontweight='bold', 
                        path_effects=[pe.withStroke(linewidth=3, foreground="white")])

        # 6. Export Data
        # Save top 50 points to CSV for QGIS validation
        df.head(50).to_csv(out_path_csv, index=False)
        print(f"Top 50 bottleneck pixels saved to {out_path_csv}")

    ax.set_title("Top Critical Bottlenecks (Single Pixels)")
    plt.savefig(out_path_map, dpi=300, bbox_inches='tight')
    plt.close()


# --- MAIN EXECUTION ----------------------------------------------------------

def main():
    print("--- Starting Visualization Pipeline ---")
    
    # 1. Load Data
    # 'transform' is crucial for converting pixels to real-world coordinates for the CSV
    res_data, meta, transform, nodata = load_raster(RESISTANCE_TIF)
    traffic_data, _, _, _ = load_raster(FINAL_TRAFFIC_TIF) 

    # 2. Prepare Data
    res_plot = prepare_plot_data(res_data, nodata)

    # 3. Generate Visualizations
    plot_resistance_map(res_plot, PLOT_RESISTANCE)
    plot_network_overview(res_plot, traffic_data, transform, PLOT_NETWORK)
    plot_bottlenecks(res_plot, traffic_data, transform, PLOT_BOTTLENECKS, OUTPUT_CSV)
    
    print("\n--- Pipeline Finished Successfully ---")

if __name__ == "__main__":
    main()