import rasterio
import numpy as np
import skimage.graph
import matplotlib.pyplot as plt
from rasterio.plot import plotting_extent
import random
import time 
from matplotlib.colors import Normalize

# --- Settings ---
FINAL_RESISTANCE_RASTER = "C:/ZHAW/5.Semester/PA2/PA2-Modelling_Wildlife_Corridors/Results/final_resistance_surface.tif"
TRAVERSAL_COUNT_RASTER = "C:/ZHAW/5.Semester/PA2/PA2-Modelling_Wildlife_Corridors/Results/traversal_count_map.tif"
DEFAULT_NODATA = 0
ABSOLUTE_BARRIER_COST = 500 # Cost value used for absolute barriers

# --- Sampling Parameters ---
# How many random pairs of points to calculate paths between?
# Start small (e.g., 100-1000) and increase if needed. More pairs = longer runtime.
num_pairs_to_sample = 500 

# Minimum resistance value to consider a pixel a potential start/end node
# Avoids starting/ending directly on high barriers. Adjust as needed.
max_cost_for_nodes = 250 

# --- 1. Load Resistance Raster ---
print(f"Loading resistance surface: {FINAL_RESISTANCE_RASTER}")
try:
    with rasterio.open(FINAL_RESISTANCE_RASTER) as src:
        resistance_array = src.read(1)
        profile = src.profile # Metadata for saving later
        # Use the actual nodata value from the file if available
        nodata_val = src.nodata or DEFAULT_NODATA 
except rasterio.errors.RasterioIOError:
    print(f"Error: Could not open {FINAL_RESISTANCE_RASTER}")
    raise

# --- 2. Identify Potential Node Locations ---
print(f"Identifying potential node locations (pixels with cost <= {max_cost_for_nodes})...")
# Find coordinates (row, col) of pixels that are NOT NoData and below the threshold
valid_pixels_indices = np.argwhere(
    (resistance_array != nodata_val) & 
    (resistance_array <= max_cost_for_nodes)
)

if len(valid_pixels_indices) < 2:
    print("Error: Not enough valid pixels found to create node pairs. Check max_cost_for_nodes or raster.")
    exit()

print(f"Found {len(valid_pixels_indices)} potential node locations.")

# --- 3. Initialize Traversal Count Raster ---
traversal_count_array = np.zeros_like(resistance_array, dtype=np.uint32)

# --- 4. Sample Node Pairs ---
print(f"Sampling {num_pairs_to_sample} random node pairs...")
# Ensure we don't sample more pairs than possible unique pairs
max_possible_pairs = len(valid_pixels_indices) * (len(valid_pixels_indices) - 1) // 2
num_pairs_to_sample = min(num_pairs_to_sample, max_possible_pairs) 
print(f"Adjusted sample size to {num_pairs_to_sample} based on available nodes.")

# Efficiently sample pairs without replacement
sampled_indices = random.sample(range(len(valid_pixels_indices)), k=min(num_pairs_to_sample * 2, len(valid_pixels_indices)))
node_pairs_indices = []
# Create pairs from the sampled indices
for i in range(0, len(sampled_indices) -1, 2):
     idx1 = sampled_indices[i]
     idx2 = sampled_indices[i+1]
     # Ensure start != end
     if idx1 != idx2:
        node_pairs_indices.append( (valid_pixels_indices[idx1], valid_pixels_indices[idx2]) )

# Ensure we have the requested number of pairs if possible
node_pairs_indices = node_pairs_indices[:num_pairs_to_sample]

if not node_pairs_indices:
     print("Error: Could not generate any node pairs for sampling.")
     exit()

print(f"Generated {len(node_pairs_indices)} pairs for LCP calculation.")

# --- 5. Calculate LCPs and Accumulate Traversal Counts (REVISED) ---
print("Calculating LCPs and accumulating traversal counts...")
start_time = time.time()
paths_calculated_count = 0
path_calculation_errors = 0

# --- MODIFICATION: Use a very large number instead of np.inf ---
# Replace NoData with this large value
VERY_LARGE_COST = 1e12 # Or adjust based on your cost scale
cost_surface_for_mcp = np.where(resistance_array == nodata_val, VERY_LARGE_COST, resistance_array.astype(np.float64)) # Ensure float64 for large numbers
# Also apply to absolute barriers
cost_surface_for_mcp = np.where(cost_surface_for_mcp >= ABSOLUTE_BARRIER_COST, VERY_LARGE_COST, cost_surface_for_mcp)

# --- Add check for min/max values ---
min_cost_in_mcp = np.min(cost_surface_for_mcp[cost_surface_for_mcp != VERY_LARGE_COST]) if np.any(cost_surface_for_mcp != VERY_LARGE_COST) else 'N/A'
max_cost_in_mcp = np.max(cost_surface_for_mcp[cost_surface_for_mcp != VERY_LARGE_COST]) if np.any(cost_surface_for_mcp != VERY_LARGE_COST) else 'N/A'
print(f"  Cost surface prepared for MCP: Min Cost={min_cost_in_mcp}, Max Cost (excl. barriers)={max_cost_in_mcp}, Barrier Cost={VERY_LARGE_COST}")

# Initialize MCP object *once* outside the loop for efficiency
# fully_connected=True means diagonal movement is allowed (8 neighbors)
print("  Initializing MCP object...")
try:
    mcp = skimage.graph.MCP_Geometric(cost_surface_for_mcp, fully_connected=True)
    print("  MCP object initialized successfully.")
except Exception as init_e:
    print(f"  FATAL ERROR: Could not initialize MCP object. Check cost surface values (NaNs, Infs?). Error: {init_e}")
    # Cannot proceed if MCP fails to initialize
    exit() 

for i, (start_node_rc, end_node_rc) in enumerate(node_pairs_indices):
    if (i + 1) % 50 == 0: # Print progress update every 50 pairs
        elapsed = time.time() - start_time
        print(f"  Processed {i+1}/{len(node_pairs_indices)} pairs... ({paths_calculated_count} successful paths, {path_calculation_errors} errors, {elapsed:.1f} seconds)")
        
    # --- MODIFICATION: More detailed error handling ---
    try:
        # Calculate cumulative cost from the start node
        cumulative_costs, traceback_pts = mcp.find_costs(starts=[start_node_rc])
        
        # Check if end node is reachable (cost is not infinite/very large)
        if cumulative_costs[tuple(end_node_rc)] >= VERY_LARGE_COST:
            # print(f"  Warning: End node {end_node_rc} unreachable from start node {start_node_rc} for pair {i+1}.")
            path_calculation_errors += 1
            continue # Skip to next pair
            
        # Trace the path from the end node back to the start
        path_indices = mcp.traceback(end_node_rc)
        
        # Check if path is valid (non-empty)
        if path_indices is None or len(path_indices[0]) == 0:
             # print(f"  Warning: Traceback returned empty path for pair {i+1}.")
             path_calculation_errors += 1
             continue

        # Increment the traversal count for each pixel in the path
        rows, cols = np.array(path_indices)
        # --- Add boundary check ---
        valid_rows = rows < traversal_count_array.shape[0]
        valid_cols = cols < traversal_count_array.shape[1]
        valid_indices = valid_rows & valid_cols
        
        if np.any(valid_indices):
             traversal_count_array[rows[valid_indices], cols[valid_indices]] += 1
             paths_calculated_count += 1
        else:
             # print(f"  Warning: Path indices out of bounds for pair {i+1}.")
             path_calculation_errors += 1
             
    except ValueError as ve:
        # Catch specific errors like start/end outside cost surface
        # print(f"  ERROR calculating path for pair {i+1} (Start: {start_node_rc}, End: {end_node_rc}). ValueError: {ve}")
        path_calculation_errors += 1
    except IndexError as ie:
        # Catch errors if traceback goes wrong
        # print(f"  ERROR during traceback for pair {i+1} (Start: {start_node_rc}, End: {end_node_rc}). IndexError: {ie}")
        path_calculation_errors += 1
    # except Exception as e: 
        # Catch any other unexpected errors, but be cautious with broad exceptions
        # print(f"  UNEXPECTED ERROR for pair {i+1} (Start: {start_node_rc}, End: {end_node_rc}). Error: {e}")
        # path_calculation_errors += 1


total_time = time.time() - start_time
print(f"\nFinished LCP calculations in {total_time:.2f} seconds.")
print(f"  Total successful paths: {paths_calculated_count}")
print(f"  Total path calculation errors/unreachable: {path_calculation_errors}")

# --- Check if traversal array was updated ---
if np.max(traversal_count_array) == 0:
    print("\nWARNING: The traversal count array is still all zeros.")
    print("Possible reasons:")
    print(" - No paths were successfully calculated (check error count).")
    print(" - Start/End nodes might be isolated by high costs/barriers.")
    print(f" - Check 'max_cost_for_nodes' ({max_cost_for_nodes}) setting.")
    print(" - Inspect the intermediate cost surface for unexpected large barrier areas.")
else:
    print(f"\nTraversal count array updated. Max count: {np.max(traversal_count_array)}")

# --- 6. Save Traversal Count Raster ---
print(f"Saving traversal count map to: {TRAVERSAL_COUNT_RASTER}")
profile.update(dtype=traversal_count_array.dtype, nodata=0) # Update profile for the count data
with rasterio.open(TRAVERSAL_COUNT_RASTER, 'w', **profile) as dst:
    dst.write(traversal_count_array, 1)

# --- 7. Visualize Traversal Count Map ---
print("Plotting traversal count map...")

# Mask zero values for better visualization (optional)
traversal_masked = np.ma.masked_equal(traversal_count_array, 0)

fig, ax = plt.subplots(figsize=(10, 10))

# Use a sequential colormap like 'viridis' or 'plasma' where bright colors indicate high counts
cmap = plt.cm.get_cmap('plasma') 
cmap.set_bad('white') # Color for masked (zero or NoData) areas

# Normalize based on the max count found
norm = Normalize(vmin=1, vmax=np.ma.max(traversal_masked) if traversal_masked.count() > 0 else 1)

try:
    with rasterio.open(FINAL_RESISTANCE_RASTER) as src_for_extent: # Use original raster for extent
        extent = plotting_extent(src_for_extent)
except Exception:
    extent = None # Fallback if original raster can't be opened

image = ax.imshow(traversal_masked, cmap=cmap, norm=norm, extent=extent)

cbar = fig.colorbar(image, ax=ax, shrink=0.7)
cbar.set_label('Traversal Frequency (Number of Paths)')

ax.set_title(f'Path Density Map ({len(node_pairs_indices)} Sampled Paths)')
ax.set_xlabel('Easting (m, LV95)')
ax.set_ylabel('Northing (m, LV95)')
plt.show()

print("\n--- Path Density Analysis Complete ---")