"""
Module: 03_extract_bottlenecks.py
Project: PA2 - Modelling Wildlife Corridors
Author: Lukas Buchmann (Modified)
Date: December 2025
Institution: ZHAW, Institute of Computational Life Sciences

Description:
    This script performs post-processing analysis to identify critical bottlenecks 
    and generates methodological visualizations for the final report.

    Key Tasks:
    1. Method Visualization: Generates three figures illustrating the model workflow:
       - Grid Overlay (Sampling strategy).
       - Valid Node Selection (Habitat vs. Matrix).
       - Trajectory Simulation (Example Least-Cost Paths).
    
    2. Bottleneck Extraction:
       - Filters the cumulative traffic raster to identify high-use corridors.
       - Intersects these corridors with high-resistance areas to find conflict points.
       - Clusters adjacent pixels into distinct 'Bottleneck Zones' using morphological operations.
       - Calculates statistics (Average Intensity) and exports a ranked CSV list.

Usage:
    Run this script after '02_local_lcp_analysis.py'.
    It requires 'final_resistance_surface.tif' and 'final_corridor_traffic.tif'.

Dependencies:
    - numpy, pandas, rasterio, scipy.ndimage
    - matplotlib
    - skimage (scikit-image) for morphological operations and MCP visualization
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd
import rasterio
from scipy import ndimage
import matplotlib.pyplot as plt
import matplotlib.colors as colors
from skimage.graph import MCP_Geometric  # Required for calculating example paths

# --- CONFIGURATION & PATHS ---------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_DIR.parent.parent
RESULTS_DIR = PROJECT_ROOT / "results"

# Input Files
RESISTANCE_TIF = RESULTS_DIR / "final_resistance_surface.tif"
FINAL_TRAFFIC_TIF = RESULTS_DIR / "final_corridor_traffic.tif"

# Output Files
OUTPUT_CSV = RESULTS_DIR / "clustered_bottlenecks.csv"
FIG_GRID = RESULTS_DIR / "method_01_grid.png"
FIG_NODES = RESULTS_DIR / "method_02_valid_nodes.png"
FIG_PATHS = RESULTS_DIR / "method_03_trajectories.png"

# Analysis Parameters
BOTTLENECK_PERCENTILE = 95      # Top 5% of traffic intensity defines a 'Corridor'
MIN_BARRIER_RESISTANCE = 3000   # Minimum cost to be considered a 'Barrier' (e.g., Road)
CLUSTER_GAP_TOLERANCE = 2       # Pixel radius to merge nearby bottlenecks

# Visualization Parameters
GRID_SPACING_METERS = 2000      # Space nodes exactly 2km apart for the demo grid
NUM_EXAMPLE_PATHS = 8           # Number of random paths to draw for Figure 3


# --- HELPER FUNCTIONS --------------------------------------------------------

def load_raster(path):
    """
    Loads raster data and returns the array and transform object.

    Args:
        path (Path): File path to the GeoTIFF.

    Returns:
        tuple: (data, transform)
            - data (np.ndarray): The raster data array.
            - transform (Affine): The spatial transform matrix.
    
    Raises:
        SystemExit: If the file is not found.
    """
    if not path.exists():
        sys.exit(f"CRITICAL ERROR: Input file not found at {path}")
    
    with rasterio.open(path) as src:
        data = src.read(1)
        transform = src.transform
        nodata = src.nodata
    
    # Handle NoData: Convert to 0 for analysis consistency
    if nodata is not None:
        data[data == nodata] = 0
        
    return data, transform


def get_cluster_centroid(labeled_array, label_id):
    """
    Calculates the geometric center (Row, Col) of a specific cluster ID.
    
    Args:
        labeled_array (np.ndarray): The array containing labeled regions.
        label_id (int): The specific ID to locate.

    Returns:
        tuple: (mean_row, mean_col)
    """
    rows, cols = np.where(labeled_array == label_id)
    return np.mean(rows), np.mean(cols)


# --- VISUALIZATION FUNCTIONS -------------------------------------------------

def generate_methodology_figures(res_data, transform):
    """
    Generates three step-by-step visualizations to explain the model methodology 
    in the report (Grid -> Selection -> Pathfinding).

    Args:
        res_data (np.ndarray): The resistance surface array.
        transform (Affine): The spatial transform for calculating pixel distances.
    """
    print("Generating methodology figures...")
    
    # --- 1. CALCULATE GRID SPACING ---
    # transform[0] holds the pixel width (resolution) in meters
    pixel_res = transform[0] 
    step_px = int(GRID_SPACING_METERS / pixel_res)
    
    print(f" -> Grid Spacing: {GRID_SPACING_METERS}m = {step_px} pixels (Resolution: {pixel_res:.2f}m)")

    # Prepare base plot data dimensions
    h, w = res_data.shape
    
    # Create Grid Indices (rows, cols)
    rows = np.arange(0, h, step_px)
    cols = np.arange(0, w, step_px)
    rr, cc = np.meshgrid(rows, cols, indexing='ij')
    
    # Flatten for scatter plotting
    grid_y = rr.flatten()
    grid_x = cc.flatten()
    
    # --- FIGURE A: THE GRID OVERLAY ---
    print(f" -> Creating {FIG_GRID.name}")
    fig, ax = plt.subplots(figsize=(10, 8))
    # Display resistance surface in background
    ax.imshow(res_data, cmap='Greys', alpha=0.5, norm=colors.LogNorm(vmin=1, vmax=5000))
    # Overlay grid points
    ax.scatter(grid_x, grid_y, c='black', s=5, alpha=1.0)
    ax.set_title(f"Initial Grid Overlay ({GRID_SPACING_METERS/1000}km spacing)", fontsize=14)
    ax.axis('off')
    plt.savefig(FIG_GRID, dpi=150, bbox_inches='tight')
    plt.close()

    # --- FIGURE B: VALID VS INVALID NODES ---
    print(f" -> Creating {FIG_NODES.name}")
    
    # Safety Check: Ensure indices fit within image dimensions
    valid_indices = (grid_y < h) & (grid_x < w)
    grid_y = grid_y[valid_indices]
    grid_x = grid_x[valid_indices]

    # Sample resistance values at grid points
    grid_vals = res_data[grid_y, grid_x]
    
    # Logic: "Valid" nodes are in optimal habitat (Resistance = 1)
    valid_mask = (grid_vals == 1) 
    
    fig, ax = plt.subplots(figsize=(10, 8))
    ax.imshow(res_data, cmap='Greys', alpha=0.3)
    
    # Plot Invalid Nodes (Red X)
    ax.scatter(grid_x[~valid_mask], grid_y[~valid_mask], c='red', marker='x', s=30, alpha=1.0, label='Blocked (Settlement/Water)')
    # Plot Valid Nodes (Green Circle)
    ax.scatter(grid_x[valid_mask], grid_y[valid_mask], c="#25a23eff", s=20, alpha=1.0, label='Valid Start Nodes (Habitat)')
    
    ax.legend(loc='upper right')
    ax.set_title("Identification of Valid Habitat Nodes", fontsize=14)
    ax.axis('off')
    plt.savefig(FIG_NODES, dpi=150, bbox_inches='tight')
    plt.close()

    # --- FIGURE C: TRAJECTORIES (Example LCPs) ---
    print(f" -> Creating {FIG_PATHS.name} (Calculated LCPs)...")
    
    # Setup MCP Graph for path calculation
    mcp_cost_surface = res_data.copy().astype(float)
    mcp_cost_surface[mcp_cost_surface <= 0] = np.inf
    mcp = MCP_Geometric(mcp_cost_surface)
    
    # Select random start/end points from the VALID node set
    valid_y = grid_y[valid_mask]
    valid_x = grid_x[valid_mask]
    
    if len(valid_x) < NUM_EXAMPLE_PATHS * 2:
        print("Warning: Not enough valid nodes for paths.")
        return

    # Randomly select indices for start/end pairs
    indices = np.random.choice(len(valid_x), NUM_EXAMPLE_PATHS * 2, replace=False)
    starts = list(zip(valid_y[indices[:NUM_EXAMPLE_PATHS]], valid_x[indices[:NUM_EXAMPLE_PATHS]]))
    ends = list(zip(valid_y[indices[NUM_EXAMPLE_PATHS:]], valid_x[indices[NUM_EXAMPLE_PATHS:]]))

    fig, ax = plt.subplots(figsize=(10, 8))
    # Background: Darker to ensure "glowing" paths are visible
    ax.imshow(res_data, cmap='gray', norm=colors.LogNorm(vmin=1, vmax=5000), alpha=0.8)
    
    # Calculate and plot each path
    for i, (start, end) in enumerate(zip(starts, ends)):
        try:
            # 1. Compute Cost Surface
            cumulative_costs, traceback = mcp.find_costs(starts=[start], ends=[end])
            # 2. Reconstruct Path
            path_indices = mcp.traceback(end)
            
            # Unzip coordinates
            py, px = zip(*path_indices)
            
            # Plot Path (Neon Cyan)
            ax.plot(px, py, color='cyan', linewidth=2, alpha=0.8)
            # Plot Endpoints
            ax.scatter([start[1], end[1]], [start[0], end[0]], c='magenta', s=40, zorder=5)
            
        except Exception as e:
            print(f"Could not calculate path {i}: {e}")

    ax.set_title(f"Calculation of individual trajectories (n={NUM_EXAMPLE_PATHS})", fontsize=14)
    ax.axis('off')
    plt.savefig(FIG_PATHS, dpi=150, bbox_inches='tight')
    plt.close()


# --- MAIN LOGIC --------------------------------------------------------------

def main():
    """Main execution workflow."""
    print("--- Starting Method Visualization & Bottleneck Extraction ---")

    # 1. Load Data
    print("Loading rasters...")
    res_data, transform = load_raster(RESISTANCE_TIF)
    traffic_data, _ = load_raster(FINAL_TRAFFIC_TIF)

    # --- PART A: GENERATE METHOD FIGURES ---
    # Fulfills the requirement for documenting the methodological steps
    try:
        generate_methodology_figures(res_data, transform)
    except ImportError:
        print("WARNING: 'scikit-image' not installed. Skipping trajectory visualization.")
        print("Run 'pip install scikit-image' to fix this.")

    # --- PART B: EXTRACT CLUSTERED BOTTLENECKS ---
    if traffic_data.max() == 0:
        print("Error: Traffic raster is empty.")
        return

    # 1. Thresholding: Filter for high-traffic pixels
    non_zero_traffic = traffic_data[traffic_data > 0]
    traffic_thresh = np.percentile(non_zero_traffic, BOTTLENECK_PERCENTILE)
    
    print(f"Bottleneck Extraction -> Traffic Threshold (> {traffic_thresh:.2f})")

    # 2. Binary Mask Logic:
    # A Bottleneck is defined as: High Traffic AND High Resistance (Barrier)
    binary_mask = (traffic_data >= traffic_thresh) & (res_data >= MIN_BARRIER_RESISTANCE)

    # 3. Morphological Closing:
    # Merge nearby pixels into single cohesive bottleneck clusters
    structure_size = CLUSTER_GAP_TOLERANCE * 2 + 1
    closed_mask = ndimage.binary_closing(binary_mask, structure=np.ones((structure_size, structure_size)))

    # 4. Label Clusters
    labeled_array, num_features = ndimage.label(closed_mask, structure=np.ones((3,3)))

    print(f"Found {num_features} distinct bottleneck clusters.")

    # 5. Extract Statistics per Cluster
    cluster_list = []
    objects = ndimage.find_objects(labeled_array)

    for i, slice_obj in enumerate(objects):
        label_id = i + 1
        cluster_mask = (labeled_array[slice_obj] == label_id)
        traffic_slice = traffic_data[slice_obj]
        
        # Calculate Total Intensity (Sum of all path crossings)
        total_intensity = np.sum(traffic_slice[cluster_mask])
        
        # Calculate Pixel Count (Spatial Area)
        pixel_count = np.sum(cluster_mask)
        
        # Calculate Average Intensity (Density)
        # Higher density = More critical constriction (more paths per meter width)
        avg_intensity = total_intensity / pixel_count if pixel_count > 0 else 0
        
        # Determine Geometric Center
        local_rows, local_cols = np.where(cluster_mask)
        r_center = np.mean(local_rows) + slice_obj[0].start
        c_center = np.mean(local_cols) + slice_obj[1].start

        # Convert Grid Coordinates to Projected Map Coordinates
        real_x, real_y = rasterio.transform.xy(transform, r_center, c_center, offset='center')

        cluster_list.append({
            "Cluster_ID": label_id,
            "Easting": int(real_x),
            "Northing": int(real_y),
            "Average_Intensity": int(avg_intensity),
            "Total_Intensity": int(total_intensity),
            "Pixel_Count": int(pixel_count)
        })

    # 6. Export to CSV
    if cluster_list:
        df = pd.DataFrame(cluster_list)
        
        # Sorting Strategy: Rank by AVERAGE INTENSITY (Density)
        # This prioritizes narrow, high-traffic points over large diffuse areas
        df = df.sort_values(by="Average_Intensity", ascending=False)
        
        df['Rank'] = range(1, len(df) + 1)
        
        # Reorder columns for final output
        cols = ['Rank', 'Easting', 'Northing', 'Average_Intensity', 'Total_Intensity', 'Pixel_Count', 'Cluster_ID']
        df[cols].to_csv(OUTPUT_CSV, index=False)
        print(f"SUCCESS: Exported CSV to {OUTPUT_CSV}")
        print(f"SUCCESS: Generated Method Figures in {RESULTS_DIR}")
    else:
        print("No bottlenecks found.")

if __name__ == "__main__":
    main()