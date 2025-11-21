import rasterio
import numpy as np
from skimage.graph import MCP_Geometric
import os
import sys

# --- 0. Define Dirs and Get Task ID ---
# Get the directory where this script is located
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Define the main results directory
RESULTS_DIR = os.path.join(BASE_DIR, "Results")
# Define the temporary directory for storing intermediate .npy files
TEMP_DIR = os.path.join(RESULTS_DIR, "temp_traffic")
# Create the temp directory if it doesn't exist
os.makedirs(TEMP_DIR, exist_ok=True)

try:
    # Get the specific task ID for this worker (e.g., 0, 1, 2... 889)
    task_id = int(os.environ['SLURM_ARRAY_TASK_ID'])
    # Get the total number of tasks in the array (e.g., 890)
    num_tasks = int(os.environ['SLURM_ARRAY_TASK_COUNT']) 
except KeyError:
    print("Error: This script must be run as a SLURM job array.")
    print("It requires SLURM_ARRAY_TASK_ID and SLURM_ARRAY_TASK_COUNT.")
    sys.exit(1)

# --- 1. Define Paths and Settings ---
# Path to the final resistance raster created in a previous step
FINAL_RASTER = os.path.join(RESULTS_DIR, "final_resistance_surface.tif")
# Spacing for the start/end nodes in meters
GRID_SPACING_METERS = 1000  # 1km grid
# A high, but finite, cost for barrier pixels
EXTREME_BARRIER_COST = 10000.0

# --- 2. Load Final Resistance Raster (CRITICALLY CORRECTED) ---
print(f"Worker {task_id}: Loading raster: {FINAL_RASTER}")
with rasterio.open(FINAL_RASTER) as src:
    resistance_array = src.read(1).astype(np.float64)
    meta = src.meta.copy()
    nodata_val = meta['nodata']
    # Get pixel resolution from the raster's transform
    resolution = meta['transform'][0] 
    height, width = resistance_array.shape
    print(f"Worker {task_id}: Raster loaded. Dimensions: {height}x{width}")

    # --- THIS IS THE ROBUST CLEANING SECTION ---
    print(f"Worker {task_id}: Applying robust data cleaning (nan, inf, nodata, <=0)...")
    # Convert all NaN, +inf to the high barrier cost
    # Convert all -inf to a low cost (1.0)
    resistance_array = np.nan_to_num(
        resistance_array, 
        nan=EXTREME_BARRIER_COST,
        posinf=EXTREME_BARRIER_COST,
        neginf=1.0
    )
    # Convert the raster's specific 'nodata' value (if it has one)
    if nodata_val is not None:
        resistance_array[resistance_array == nodata_val] = EXTREME_BARRIER_COST
        
    # Ensure no costs are zero or negative
    resistance_array[resistance_array <= 0] = 1.0
    
    # --- CRITICAL FIX: Force type and memory layout ---
    # Force the array to be C-contiguous and float64
    # This fixes deep numpy/skimage type errors.
    # print(f"Worker {task_id}: Forcing array to float64 and C-contiguous memory.")
    # resistance_array = np.ascontiguousarray(resistance_array, dtype=np.float64)

    print(f'Data type after cleaning: {resistance_array.dtype}, C-contiguous: {resistance_array.flags["C_CONTIGUOUS"]}')

    print(f"Worker {task_id}: Data cleaning complete.")
    # --- END CLEANING ---

# --- 3. Create & Filter Nodes (CRITICALLY CORRECTED) ---
print(f"Worker {task_id}: Generating and filtering nodes...")
spacing_pixels = int(GRID_SPACING_METERS / resolution)
# Generate arrays of row and column indices
rows = np.arange(0, height, spacing_pixels)
cols = np.arange(0, width, spacing_pixels)
# Create a 2D grid of all possible node coordinates
xx, yy = np.meshgrid(cols, rows)
# Flatten the grid into a list of (row, col) tuples
all_grid_nodes_np = list(zip(yy.ravel(), xx.ravel()))

print(f"Worker {task_id}: Found {len(all_grid_nodes_np)} total grid points (before filtering).")

# Filter the list, CAST to int, and EXCLUDE BORDER PIXELS
valid_grid_nodes = [
    (int(r), int(c)) for r, c in all_grid_nodes_np 
    # 1. Check if the cost is valid
    if resistance_array[int(r), int(c)] < EXTREME_BARRIER_COST
    # 2. Check if the node is NOT on the 1-pixel border
    and int(r) > 0 
    and int(r) < height - 1 
    and int(c) > 0 
    and int(c) < width - 1
]
node_count = len(valid_grid_nodes)
print(f"Worker {task_id}: Total valid grid nodes (non-border) found: {node_count}")

# Safety check: if no nodes are found, exit cleanly
if node_count < 2:
    print(f"Worker {task_id}: FATAL: Node count is {node_count}, which is less than 2. LCP analysis cannot run. Exiting.")
    # Save an empty array so the aggregate step doesn't fail
    output_path = os.path.join(TEMP_DIR, f"worker_traffic_{task_id}.npy")
    # Use float64 for the empty array as well
    np.save(output_path, np.zeros((height, width), dtype=np.int32))
    sys.exit(0) # Exit cleanly


# --- 4. This Worker's Job (Chunking Logic - VERBOSE) ---

try:
    # Get the specific task ID for this worker (e.g., 0, 1, 2... 889)
    task_id = int(os.environ['SLURM_ARRAY_TASK_ID'])
    # Get the total number of tasks in the array (e.g., 890)
    num_tasks = int(os.environ['SLURM_ARRAY_TASK_COUNT']) 
except KeyError:
    print("Error: This script must be run as a SLURM job array.")
    print("It requires SLURM_ARRAY_TASK_ID and SLURM_ARRAY_TASK_COUNT.")
    sys.exit(1)

# Split all node indices (e.g., 0-1109) into 'num_tasks' (e.g., 890) chunks
all_node_indices = np.arange(node_count)
print(f"Worker {task_id}: Dividing {node_count} nodes into {num_tasks} chunks...")
# np.array_split divides the work as evenly as possible
node_chunks = np.array_split(all_node_indices, num_tasks)

# Get the specific list of node indices this worker is responsible for
my_node_indices = node_chunks[task_id]

# Safety check: if this worker has no nodes, exit cleanly
if my_node_indices.size == 0:
    print(f"Worker {task_id}: No nodes to process in this chunk. Exiting.")
    output_path = os.path.join(TEMP_DIR, f"worker_traffic_{task_id}.npy")
    # Use float64 for the empty array as well
    np.save(output_path, np.zeros((height, width), dtype=np.int32))
    sys.exit(0) # Exit cleanly

print(f"Worker {task_id}: Assigned {len(my_node_indices)} nodes (indices from {my_node_indices[0]} to {my_node_indices[-1]}).")

# Initialize this worker's traffic array as int32
worker_traffic_array = np.zeros((height, width), dtype=np.int32)
print(f"Worker {task_id}: Initialized traffic array with shape {worker_traffic_array.shape}.")

# Loop over each start_node this worker is responsible for
for i in my_node_indices:
    # Use the index 'i' to get the (row, col) tuple from the valid list
    start_node = valid_grid_nodes[i]
    print(f"Worker {task_id}: Processing start node index {i} at {start_node}...")
    
    # Create the Minimum Cost Path object
    # fully_connected=True allows 8-direction diagonal movement
    mcp = MCP_Geometric(resistance_array, fully_connected=True)
    
    try:
        # This is the (slower) call for older skimage versions.
        # It calculates the cost from 'start_node' to all other pixels.
        cost_surface = mcp.find_costs(starts=[start_node]) 
        # print(f"Worker {task_id}: Calculated cost surface from start node {i}.")
    except Exception as e:
        # This will fail if the start_node is on an isolated island
        print(f"Worker {task_id}: Could not calculate cost surface from {start_node}. Error: {e}. Skipping.")
        continue # Skip to the next start_node in this worker's chunk

    # --- THIS IS THE MODIFIED TRACEBACK LOOP ---
    path_count_for_this_node = 0
    # Loop through all valid end nodes AFTER this start node
    # The (i + 1) ensures we only calculate (A -> B) and not (B -> A)
# Now, loop through all valid end nodes AFTER this start node
    for j in range(i + 1, node_count):
        end_node = valid_grid_nodes[j]
        
        try:
            # This version of skimage only returns the indices
            indices = mcp.traceback(end_node) 

            # If a path was found (indices is not empty or None)
            if indices:
                # Unzip the list of (row, col) tuples
                rows, cols = zip(*indices)
                # Increment the traffic count for these pixels
                worker_traffic_array[rows, cols] += 1
                path_count_for_this_node += 1
        except Exception as e:
            # This will catch any remaining, unexpected errors
            if j < i + 20: 
                 print(f"Worker {task_id}: (Node {i} to {j}) FAILED to trace path to {end_node}. Error: {e}")
            elif j == i + 20:
                 print(f"Worker {task_id}: (Node {i} to {j}) ... (suppressing further traceback errors for this start node)")
            continue # Skip this pair and move to the next end_node          

    print(f"Worker {task_id}: Completed processing for start node {i}. Found {path_count_for_this_node} paths.")

print(f'Min and Max crossings in worker array before saving: {np.min(worker_traffic_array)}, {np.max(worker_traffic_array)}')

# --- 5. Save the result to a unique temp file ---
# This worker saves its own partial traffic map
print(f"Worker {task_id}: Finished chunk. Min crossings: {np.min(worker_traffic_array)}, Max crossings: {np.max(worker_traffic_array)}")
output_path = os.path.join(TEMP_DIR, f"worker_traffic_{task_id}.npy")
np.save(output_path, worker_traffic_array)

print(f"Worker {task_id}: Saved results to {output_path}")
