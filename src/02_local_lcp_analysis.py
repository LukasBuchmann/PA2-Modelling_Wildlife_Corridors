"""
Module: 02_local_lcp_analysis.py
Project: PA2 - Modelling Wildlife Corridors
Author: Lukas Buchmann (Adapted by PA2)
Date: December 2025
Institution: ZHAW, Institute of Computational Life Sciences

Description:
    This script performs the core computational modeling of wildlife connectivity.
    It replaces complex cluster/Slurm workflows with a streamlined local sequential process
    suitable for reproducing results on a standard workstation.

    Key Processes:
    1. Grid Sampling: Identifies potential start/end nodes on a regular grid (e.g., 2km).
    2. Node Validation: Filters nodes to ensure they originate in 'Core Habitat' (Resistance=1).
    3. LCP Analysis: Computes the Least-Cost Path between every valid node pair using 
       geometric pathfinding (skimage.graph.MCP_Geometric).
    4. Aggregation: Sums the trajectories to create a 'Traffic Density' raster.

Usage:
    Run this script after '01_resistance_surface_generation.py'.
    It outputs 'final_corridor_traffic.tif', which is the basis for the connectivity map.

Dependencies:
    - numpy, rasterio
    - scikit-image (skimage)
    - tqdm (for progress tracking)
"""

import sys
import os
import numpy as np
import rasterio
from skimage.graph import MCP_Geometric
from pathlib import Path
from tqdm import tqdm  # Recommended for local progress tracking

# --- CONFIGURATION & PATHS ---------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_DIR.parent.parent
RESULTS_DIR = PROJECT_ROOT / "results"

# Input / Output
FINAL_RASTER = RESULTS_DIR / "final_resistance_surface.tif"
OUTPUT_TRAFFIC = RESULTS_DIR / "final_corridor_traffic.tif"

# Model Parameters
GRID_SPACING_METERS = 2000      # Distance between sampling nodes
TARGET_RESISTANCE_VAL = 1.0     # Value representing 'Optimal Habitat'


# --- CORE FUNCTIONS ----------------------------------------------------------

def load_and_validate_surface(raster_path):
    """
    Loads the resistance surface and performs critical integrity checks.

    Ensures the raster exists, contains valid numerical data, and has no 
    negative or zero costs (which would break the pathfinding algorithm).

    Args:
        raster_path (Path): Path to the input resistance GeoTIFF.

    Returns:
        tuple: (data, res, meta)
            - data (np.ndarray): 2D array of resistance values.
            - res (float): Spatial resolution of the pixels (e.g., 10.0).
            - meta (dict): Rasterio metadata for exporting results later.
    
    Raises:
        SystemExit: If file is missing or data is invalid (NaNs/Inf/<=0).
    """
    if not raster_path.exists():
        sys.exit(f"CRITICAL ERROR: {raster_path} does not exist. Run 01_prepare_surface.py first.")

    try:
        with rasterio.open(raster_path) as src:
            data = src.read(1)
            transform = src.transform
            meta = src.meta.copy()
            res = transform[0]
    except Exception as e:
        sys.exit(f"CRITICAL ERROR: Could not read {raster_path}: {e}")

    # Validation Checks
    if np.isnan(data).any():
        sys.exit("Surface contains NaNs. Aborting.")
    if not np.isfinite(data).all():
        sys.exit("Surface contains Infinite values. Aborting.")
    # MCP requires strictly positive weights
    if (data <= 0).any():
        sys.exit("Surface contains zero or negative costs. Aborting.")

    return data, res, meta


def identify_core_nodes(resistance_data, pixel_res, spacing_m, target_val):
    """
    Generates a systematic grid of start/end nodes filtered by habitat suitability.

    Iterates over the landscape at fixed intervals. Only retains points that fall
    exactly on pixels matching the 'target_val' (Optimal Habitat).

    Args:
        resistance_data (np.ndarray): The landscape resistance matrix.
        pixel_res (float): Resolution of one pixel in meters.
        spacing_m (int): Desired grid spacing in meters.
        target_val (float): Resistance value required for a node to be valid.

    Returns:
        list: A list of (row, col) tuples representing valid node coordinates.
    """
    h, w = resistance_data.shape
    # Calculate step size in pixels
    step = int(spacing_m / pixel_res)
    
    rows = np.arange(0, h, step)
    cols = np.arange(0, w, step)
    
    nodes = []
    for r in rows:
        for c in cols:
            # Check if the sampled point is valid habitat
            if resistance_data[r, c] == target_val:
                nodes.append((r, c))
    return nodes


def calculate_and_aggregate_traffic(resistance_data, all_nodes):
    """
    Computes Least-Cost Paths (LCP) and aggregates them into a traffic density map.

    Uses the 'skimage.graph.MCP_Geometric' class to calculate Euclidean-weighted 
    paths. Iterates through node pairs efficiently to avoid duplicate calculations.

    Args:
        resistance_data (np.ndarray): The landscape cost surface.
        all_nodes (list): List of valid (row, col) start/end points.

    Returns:
        np.ndarray: A 2D integer array where each pixel value represents the 
                    number of LCPs traversing that cell.
    """
    h, w = resistance_data.shape
    # Use 32-bit int to prevent overflow if traffic is high
    total_traffic_map = np.zeros((h, w), dtype=np.int32)
    
    # Initialize MCP Graph
    # fully_connected=True enables 8-neighbor connectivity (diagonal movement)
    print("Initializing Cost Surface Graph...")
    mcp = MCP_Geometric(resistance_data, fully_connected=True)
    count = 0

    print(f"Processing {len(all_nodes)} nodes locally. This may take time...")
    
    # Progress bar for local feedback
    for idx, start_node in enumerate(tqdm(all_nodes, desc="Calculating Paths")):
        try:
            # 1. Compute cumulative cost from start_node to every pixel in the grid
            mcp.find_costs(starts=[start_node])
            
            # 2. Reconstruction Loop (Optimization)
            # Use a triangular matrix approach: only calculate paths to nodes 
            # further down the list. Path A->B is the same as B->A.
            for target_idx in range(idx + 1, len(all_nodes)):
                end_node = all_nodes[target_idx]
                
                path = mcp.traceback(end_node)
                if path:
                    # Convert list of tuples to numpy indexing arrays
                    r_idx, c_idx = zip(*path)
                    
                    # Increment the traffic counter for every pixel on this path
                    total_traffic_map[r_idx, c_idx] += 1
                    count += 1
                    
        except Exception as e:
            print(f"Warning on node {idx}: {e}")

    print(f"Analysis Complete. Total paths mapped: {count}")
    return total_traffic_map


# --- MAIN EXECUTION ----------------------------------------------------------

def main():
    """Main execution workflow."""
    # 1. Load Data
    resistance_data, resolution, meta = load_and_validate_surface(FINAL_RASTER)

    # 2. Identify Nodes
    all_nodes = identify_core_nodes(
        resistance_data, resolution, GRID_SPACING_METERS, TARGET_RESISTANCE_VAL
    )
    print(f"Found {len(all_nodes)} valid core habitat nodes.")

    # Check for minimum nodes required for a network
    if len(all_nodes) < 2:
        print("Not enough nodes to form a network.")
        sys.exit(0)

    # 3. Execute Analysis & Aggregation
    final_traffic = calculate_and_aggregate_traffic(resistance_data, all_nodes)

    # 4. Save Aggregated Result
    # Update metadata to Integer type for count data
    meta.update(dtype='int32', nodata=0, count=1)
    
    with rasterio.open(OUTPUT_TRAFFIC, 'w', **meta) as dst:
        dst.write(final_traffic, 1)
    
    print(f"Aggregated traffic density map saved to {OUTPUT_TRAFFIC}")


if __name__ == "__main__":
    main()