"""
ZHAW Project Work 2: Local LCP Analysis and Aggregation.

This script performs the core pathfinding computations. 
It replaces the Slurm array job with a local sequential loop.
It calculates LCPs and aggregates the traffic density in real-time.

Author: Lukas Buchmann (Adapted by PA2)
"""

import sys
import os
import numpy as np
import rasterio
from skimage.graph import MCP_Geometric
from pathlib import Path
from tqdm import tqdm  # Recommended for local progress tracking

# --- CONFIGURATION ---
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
RESULTS_DIR = PROJECT_ROOT / "results"
FINAL_RASTER = RESULTS_DIR / "final_resistance_surface.tif"
OUTPUT_TRAFFIC = RESULTS_DIR / "final_corridor_traffic.tif"

# Parameters
GRID_SPACING_METERS = 2000
TARGET_RESISTANCE_VAL = 1.0


def load_and_validate_surface(raster_path):
    """Loads resistance raster and validates integrity."""
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

    # Validation
    if np.isnan(data).any():
        sys.exit("Surface contains NaNs. Aborting.")
    if not np.isfinite(data).all():
        sys.exit("Surface contains Infinite values. Aborting.")
    if (data <= 0).any():
        sys.exit("Surface contains zero or negative costs. Aborting.")

    return data, res, meta


def identify_core_nodes(resistance_data, pixel_res, spacing_m, target_val):
    """Generates grid nodes on core habitat."""
    h, w = resistance_data.shape
    step = int(spacing_m / pixel_res)
    
    rows = np.arange(0, h, step)
    cols = np.arange(0, w, step)
    
    nodes = []
    for r in rows:
        for c in cols:
            if resistance_data[r, c] == target_val:
                nodes.append((r, c))
    return nodes


def calculate_and_aggregate_traffic(resistance_data, all_nodes):
    """
    Computes LCPs for all node pairs and aggregates them into a single map.
    """
    h, w = resistance_data.shape
    # Use 32-bit int to prevent overflow if traffic is high
    total_traffic_map = np.zeros((h, w), dtype=np.int32)
    
    # Initialize MCP Graph
    print("Initializing Cost Surface Graph...")
    mcp = MCP_Geometric(resistance_data, fully_connected=True)
    count = 0

    print(f"Processing {len(all_nodes)} nodes locally. This may take time...")
    
    # Progress bar for local feedback
    for idx, start_node in enumerate(tqdm(all_nodes, desc="Calculating Paths")):
        try:
            # 1. Compute cumulative cost from start_node to everywhere
            mcp.find_costs(starts=[start_node])
            
            # 2. Traceback to subsequent nodes only (Triangular matrix)
            # This avoids calculating A->B and B->A separately
            for target_idx in range(idx + 1, len(all_nodes)):
                end_node = all_nodes[target_idx]
                
                path = mcp.traceback(end_node)
                if path:
                    # Convert list of tuples to numpy indexing arrays
                    r_idx, c_idx = zip(*path)
                    total_traffic_map[r_idx, c_idx] += 1
                    count += 1
                    
        except Exception as e:
            print(f"Warning on node {idx}: {e}")

    print(f"Analysis Complete. Total paths mapped: {count}")
    return total_traffic_map


def main():
    # 1. Load Data
    resistance_data, resolution, meta = load_and_validate_surface(FINAL_RASTER)

    # 2. Identify Nodes
    all_nodes = identify_core_nodes(
        resistance_data, resolution, GRID_SPACING_METERS, TARGET_RESISTANCE_VAL
    )
    print(f"Found {len(all_nodes)} valid core habitat nodes.")

    # 3. Execute Analysis & Aggregation
    if len(all_nodes) < 2:
        print("Not enough nodes to form a network.")
        sys.exit(0)

    final_traffic = calculate_and_aggregate_traffic(resistance_data, all_nodes)

    # 4. Save Aggregated Result
    # We save as GeoTIFF directly, removing the need for 03 to do data handling
    meta.update(dtype='int32', nodata=0, count=1)
    with rasterio.open(OUTPUT_TRAFFIC, 'w', **meta) as dst:
        dst.write(final_traffic, 1)
    
    print(f"aggregated traffic density map saved to {OUTPUT_TRAFFIC}")


if __name__ == "__main__":
    main()