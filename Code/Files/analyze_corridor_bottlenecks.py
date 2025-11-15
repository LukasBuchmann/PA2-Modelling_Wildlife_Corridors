import rasterio
import numpy as np
import sys
from pathlib import Path

print("Starting corridor bottleneck analysis...")

# --- Directories ---
BASE_DIR = Path.cwd()
DATA_DIR = BASE_DIR / "data"
RESULTS_DIR = BASE_DIR / "results"

# --- 1. Define File Paths and Settings ---
RESISTANCE_RASTER = RESULTS_DIR / "final_resistance_surface.tif"
TRAFFIC_RASTER = RESULTS_DIR / "final_corridor_traffic.tif"
OUTPUT_RASTER = RESULTS_DIR / "corridor_bottlenecks.tif"

# --- Analysis Settings ---
# The "major routes" are defined as the top 10% (90th percentile)
TRAFFIC_THRESHOLD_PERCENTILE = 90.0
# We need to use the same barrier cost as your worker script
EXTREME_BARRIER_COST = 10000.0
# Set a new NoData value for our output map
NODATA_VALUE = -9999.0

# --- 2. Load Resistance Raster and Metadata ---
# We must apply the *exact same* cleaning steps as hpc_worker.py
# to ensure the data is 1:1 identical.
print(f"Loading and cleaning resistance raster: {RESISTANCE_RASTER}")
with rasterio.open(RESISTANCE_RASTER) as src:
    meta = src.meta.copy()
    resistance_array = src.read(1).astype(np.float32)
    nodata_val = meta['nodata']
    
    # Apply robust cleaning
    resistance_array = np.nan_to_num(
        resistance_array, 
        nan=EXTREME_BARRIER_COST,
        posinf=EXTREME_BARRIER_COST,
        neginf=1.0
    )
    if nodata_val is not None:
        resistance_array[resistance_array == nodata_val] = EXTREME_BARRIER_COST
    resistance_array[resistance_array <= 0] = 1.0
    
    # We don't need the float64/contiguous version, as we are just reading
    print("Resistance raster loaded.")

# --- 3. Load Traffic Raster and Find Threshold ---
print(f"Loading traffic raster: {TRAFFIC_RASTER}")
with rasterio.open(TRAFFIC_RASTER) as src:
    traffic_array = src.read(1).astype(np.float32) # Use float32 to match
    
    # Find the threshold value (e.g., P90)
    # We only look at non-zero pixels for the percentile
    non_zero_pixels = traffic_array[traffic_array > 0]
    if non_zero_pixels.size == 0:
        print("Error: No non-zero traffic pixels found. Exiting.")
        sys.exit(1)
        
    threshold_val = np.percentile(non_zero_pixels, TRAFFIC_THRESHOLD_PERCENTILE)
    print(f"Traffic threshold (P{TRAFFIC_THRESHOLD_PERCENTILE}) is: {threshold_val} crossings")

# --- 4. Create the Bottleneck Map ---
# Create a mask where traffic is BELOW our threshold
# These are the pixels we want to hide
mask = traffic_array < threshold_val

# Create our new output array by copying the resistance values
corridor_bottlenecks = resistance_array.copy()

# Apply the mask: where traffic is low, set to NoData
corridor_bottlenecks[mask] = NODATA_VALUE
print("Bottleneck mask applied.")

# --- 5. Save the New Raster ---
# Update the metadata for our new output file
meta.update({
    'dtype': 'float32',
    'nodata': NODATA_VALUE
})

print(f"Saving bottleneck map to {OUTPUT_RASTER}...")
with rasterio.open(OUTPUT_RASTER, 'w', **meta) as dst:
    dst.write(corridor_bottlenecks.astype(np.float32), 1)

print("Analysis complete.")