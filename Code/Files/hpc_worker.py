import rasterio
import numpy as np
from skimage.graph import route_through_array
import os
import sys

# --- 0. Define Dirs and Get Task ID ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(BASE_DIR, "Results")
TEMP_DIR = os.path.join(RESULTS_DIR, "temp_traffic")
os.makedirs(TEMP_DIR, exist_ok=True)

try:
    task_id = int(os.environ['SLURM_ARRAY_TASK_ID'])
except KeyError:
    print("Error: This script must be run as a SLURM job array.")
    sys.exit(1)

# --- 1. Define Paths and Settings ---
FINAL_RASTER = os.path.join(RESULTS_DIR, "final_resistance_surface.tif")
GRID_SPACING_METERS = 1000  # 1km grid
EXTREME_BARRIER_COST = 1000.0

# --- 2. Load Final Resistance Raster ---
with rasterio.open(FINAL_RASTER) as src:
    resistance_array = src.read(1).astype(np.float32)
    meta = src.meta.copy()
    nodata_val = meta['nodata']
    resolution = meta['transform'][0] 
    resistance_array[resistance_array == nodata_val] = EXTREME_BARRIER_COST
    resistance_array[resistance_array <= 0] = 1.0
    height, width = resistance_array.shape

# --- 3. Create & Filter Nodes (This is fast, OK to repeat) ---
spacing_pixels = int(GRID_SPACING_METERS / resolution)
rows = np.arange(0, height, spacing_pixels)
cols = np.arange(0, width, spacing_pixels)
xx, yy = np.meshgrid(cols, rows)
all_grid_nodes = list(zip(yy.ravel(), xx.ravel()))
valid_grid_nodes = [
    (r, c) for r, c in all_grid_nodes 
    if resistance_array[r, c] < EXTREME_BARRIER_COST
]
node_count = len(valid_grid_nodes)

# --- 4. This Worker's Job ---
i = task_id
if i >= node_count:
    sys.exit(0) # Exit silently if task ID is too high

start_node = valid_grid_nodes[i]
worker_traffic_array = np.zeros((height, width), dtype=np.int32)
print(f"Worker {i}: Processing paths from {start_node}...")

for j in range(i + 1, node_count):
    end_node = valid_grid_nodes[j]
    
    try:
        indices, cost = route_through_array(
            resistance_array,
            start=start_node,
            end=end_node,
            fully_connected=True,
            geometric=True
        )
        
        if indices:
            rows, cols = zip(*indices)
            worker_traffic_array[rows, cols] += 1
            
    except Exception as e:
        continue # Skip this pair

# --- 5. Save the result to a unique temp file ---
output_path = os.path.join(TEMP_DIR, f"worker_traffic_{i}.npy")
np.save(output_path, worker_traffic_array)

print(f"Worker {i}: Finished. Saved results to {output_path}")
