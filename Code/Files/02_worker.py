import rasterio
import numpy as np
from skimage.graph import MCP_Geometric
import os
import sys
from pathlib import Path

# --- 1. CONFIGURATION & PARAMETERS ---
# The grid spacing is defined as 1km to capture connectivity at a cantonal scale
GRID_SPACING_METERS = 1000 
# Corridor start/end points are strictly limited to core habitat (Resistance = 1.0)
TARGET_RESISTANCE_VAL = 1.0 

# --- 2. PATH SETUP ---
# Relative paths are used to ensure the script works regardless of the root directory location
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent 
RESULTS_DIR = PROJECT_ROOT / "results"
TEMP_DIR = RESULTS_DIR / "temp_traffic"
FINAL_RASTER = RESULTS_DIR / "final_resistance_surface.tif"

# The temporary directory is ensured to exist to avoid write errors later
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# --- 3. HPC ENVIRONMENT SETUP ---
# The Task ID is retrieved from the SLURM environment to determine which chunk of work this script should perform
try:
    task_id = int(os.environ['SLURM_ARRAY_TASK_ID'])
    num_tasks = int(os.environ['SLURM_ARRAY_TASK_COUNT'])
except KeyError:
    # Fallback for local testing or debugging outside the scheduler
    print("Warning: SLURM environment not detected. Defaulting to single-task mode.")
    task_id = 0
    num_tasks = 1

print(f"Worker {task_id}: Starting initialization...")

# --- 4. DATA LOADING & PREPROCESSING ---
# The final resistance surface is loaded to serve as the cost landscape
try:
    with rasterio.open(FINAL_RASTER) as src:
        resistance_data = src.read(1)
        transform = src.transform
        pixel_resolution = transform[0]
        nodata_val = src.nodata
except Exception as e:
    print(f"Worker {task_id} Error: Could not open raster at {FINAL_RASTER}: {e}")
    sys.exit(1)

# Robust data cleaning is performed to prevent infinite costs or NaNs from breaking the pathfinding algorithm
# NaNs and Infinite values are treated as absolute barriers (Cost = 10,000)
resistance_data = np.nan_to_num(
    resistance_data, 
    nan=10000.0, 
    posinf=10000.0, 
    neginf=1.0
)
# Explicit NoData values are also treated as barriers
if nodata_val is not None: 
    resistance_data[resistance_data == nodata_val] = 10000.0

# A minimum cost of 1.0 is enforced to ensure mathematical stability
resistance_data[resistance_data < 1.0] = 1.0

# --- 5. NODE SELECTION (The "New Logic") ---
# A grid of potential nodes is generated based on the defined spacing
print(f"Worker {task_id}: Identifying valid core habitat nodes...")
spacing_pixels = int(GRID_SPACING_METERS / pixel_resolution)
height, width = resistance_data.shape

rows = np.arange(0, height, spacing_pixels)
cols = np.arange(0, width, spacing_pixels)
valid_nodes = []

# The grid is iterated through and filtered for nodes that fall exactly on Core Habitat
for r in rows:
    for c in cols:
        # Boundary Check: Pixels on the very edge of the map are excluded
        if 0 < r < height - 1 and 0 < c < width - 1:
            # Resistance Check: Only nodes where resistance is ~1.0 are selected
            # A small tolerance (+0.01) is used to handle floating point variations
            if resistance_data[r, c] <= (TARGET_RESISTANCE_VAL + 0.01):
                valid_nodes.append((r, c))

total_nodes = len(valid_nodes)
print(f"Worker {task_id}: Found {total_nodes} valid nodes in total.")

# --- 6. WORKLOAD DISTRIBUTION ---
# The total list of valid nodes is divided into chunks, one for each HPC worker
# This ensures parallel processing across the cluster
my_node_indices = np.array_split(np.arange(total_nodes), num_tasks)[task_id]

# An empty array is initialized to store the traffic counts for this specific worker
worker_traffic_map = np.zeros((height, width), dtype=np.int32)

# --- 7. LEAST COST PATH ANALYSIS ---
if my_node_indices.size > 0:
    # The Minimum Cost Path (MCP) algorithm is initialized allowing for 8-neighbor movement
    mcp = MCP_Geometric(resistance_data, fully_connected=True)
    
    count_paths = 0
    
    for i in my_node_indices:
        start_node = valid_nodes[i]
        
        try:
            # The cumulative cost surface is calculated from the current start node to all other pixels
            cost_surface = mcp.find_costs(starts=[start_node])
            
            # The start node is connected to every SUBSEQUENT node in the list
            # Using 'range(i + 1, ...)' prevents calculating the same path twice (A->B and B->A)
            for j in range(i + 1, total_nodes):
                end_node = valid_nodes[j]
                
                try:
                    # The least cost path is traced back from the end node to the start node
                    path = mcp.traceback(end_node)
                    
                    # If a valid path is found, the traffic counter is incremented for those pixels
                    if path:
                        rows_idx, cols_idx = zip(*path)
                        worker_traffic_map[rows_idx, cols_idx] += 1
                        count_paths += 1
                except Exception:
                    # If a specific path fails (e.g., isolated island), it is skipped to keep the worker running
                    pass
                    
        except Exception as e:
            print(f"Worker {task_id}: Error processing start node {i}: {e}")

    print(f"Worker {task_id}: Finished processing. Calculated {count_paths} paths.")

# --- 8. SAVING RESULTS ---
# The partial traffic map from this worker is saved as a numpy file
output_filename = TEMP_DIR / f"worker_{task_id}.npy"
np.save(output_filename, worker_traffic_map)
print(f"Worker {task_id}: Results saved to {output_filename}")