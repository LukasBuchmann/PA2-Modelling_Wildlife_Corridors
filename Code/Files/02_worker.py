"""
ZHAW Project Work 2: Parallel Least-Cost Path (LCP) Analysis Worker.

This script performs the core pathfinding computations. It is designed to be run 
as a Slurm Array Job. Each worker:
1. Loads the resistance surface.
2. Validates data integrity (Fails Fast on NaN/Inf).
3. Identifies a subset of core habitat nodes.
4. Calculates LCPs between assigned nodes and all other nodes.
5. Saves a partial traffic density map.

Author: Lukas Buchmann
Date: November 2025
"""

import sys
import os
import numpy as np
import rasterio
from skimage.graph import MCP_Geometric
from pathlib import Path

# --- CONFIGURATION ---
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
RESULTS_DIR = PROJECT_ROOT / "results"
TEMP_DIR = RESULTS_DIR / "temp_traffic"
FINAL_RASTER = RESULTS_DIR / "final_resistance_surface.tif"

# Parameters
GRID_SPACING_METERS = 2000
TARGET_RESISTANCE_VAL = 1.0


def get_worker_info():
    """Retrieves Slurm Task ID and Total Task count."""
    try:
        task_id = int(os.environ.get('SLURM_ARRAY_TASK_ID', 0))
        num_tasks = int(os.environ.get('SLURM_ARRAY_TASK_COUNT', 1))
        print(f"Worker {task_id}/{num_tasks}: Initializing...")
        return task_id, num_tasks
    except ValueError:
        return 0, 1


def load_and_validate_surface(raster_path):
    """
    Loads the resistance raster and performs strict validation.
    Raises ValueError immediately if invalid data (NaN, Inf, <=0) is found.
    """
    try:
        with rasterio.open(raster_path) as src:
            data = src.read(1)
            transform = src.transform
            res = transform[0]
    except Exception as e:
        sys.exit(f"CRITICAL ERROR: Could not read {raster_path}: {e}")

    # --- Strict Validation (Fail Fast) ---
    if np.isnan(data).any():
        count = np.isnan(data).sum()
        raise ValueError(f"CRITICAL ERROR: Surface contains {count} NaNs. Aborting.")
    
    if not np.isfinite(data).all():
        count = np.isinf(data).sum()
        raise ValueError(f"CRITICAL ERROR: Surface contains {count} Infinite values. Aborting.")

    if (data <= 0).any():
        raise ValueError("CRITICAL ERROR: Surface contains zero or negative costs. Aborting.")

    return data, res


def identify_core_nodes(resistance_data, pixel_res, spacing_m, target_val):
    """
    Generates a grid of nodes and filters them to keep only those
    falling strictly on core habitat (resistance == 1).
    """
    h, w = resistance_data.shape
    step = int(spacing_m / pixel_res)
    
    # Generate grid coordinates
    rows = np.arange(0, h, step)
    cols = np.arange(0, w, step)
    
    # Filter valid nodes
    nodes = []
    for r in rows:
        for c in cols:
            if resistance_data[r, c] == target_val:
                nodes.append((r, c))
    
    return nodes


def calculate_partial_traffic(resistance_data, all_nodes, my_indices, task_id):
    """
    Computes Least-Cost Paths for the subset of start nodes assigned to this worker.
    Returns a traffic density grid (heatmap).
    """
    h, w = resistance_data.shape
    traffic_map = np.zeros((h, w), dtype=np.int32)
    
    if len(my_indices) == 0:
        return traffic_map

    # Initialize MCP Graph (Diagonal movement allowed)
    mcp = MCP_Geometric(resistance_data, fully_connected=True)
    count = 0

    print(f"Worker {task_id}: Processing {len(my_indices)} start nodes...")

    for idx in my_indices:
        start_node = all_nodes[idx]
        
        try:
            # compute costs from this start node to EVERYWHERE
            # We don't need 'ends' argument here, traceback handles specific targets
            mcp.find_costs(starts=[start_node])
            
            # Trace back to every subsequent node (Triangular matrix approach)
            # Avoids double counting: A->B calculated by A, B->A skipped by B
            for target_idx in range(idx + 1, len(all_nodes)):
                end_node = all_nodes[target_idx]
                
                path = mcp.traceback(end_node)
                if path:
                    # Convert list of tuples to numpy indexing arrays
                    r_idx, c_idx = zip(*path)
                    traffic_map[r_idx, c_idx] += 1
                    count += 1
                    
        except Exception as e:
            print(f"Worker {task_id}: Warning on node {idx}: {e}")

    print(f"Worker {task_id}: Completed. Total paths mapped: {count}")
    return traffic_map


def main():
    # 1. Setup
    task_id, num_tasks = get_worker_info()
    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    # 2. Load Data
    resistance_data, resolution = load_and_validate_surface(FINAL_RASTER)

    # 3. Identify Nodes
    all_nodes = identify_core_nodes(
        resistance_data, resolution, GRID_SPACING_METERS, TARGET_RESISTANCE_VAL
    )
    total_nodes = len(all_nodes)
    print(f"Worker {task_id}: Found {total_nodes} valid core habitat nodes.")

    # 4. Distribute Work
    # Split the list of all node indices into N chunks, grab the one for this worker
    all_indices = np.arange(total_nodes)
    my_indices = np.array_split(all_indices, num_tasks)[task_id]

    # 5. Execute Analysis
    traffic_map = calculate_partial_traffic(
        resistance_data, all_nodes, my_indices, task_id
    )

    # 6. Save Results
    out_path = TEMP_DIR / f"worker_{task_id}.npy"
    np.save(out_path, traffic_map)
    print(f"Worker {task_id}: Partial results saved to {out_path}")


if __name__ == "__main__":
    main()