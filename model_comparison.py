import geopandas as gpd
import pandas as pd
import matplotlib.pyplot as plt

# 1. Load your Bottlenecks
df_bottlenecks = pd.read_csv("Results/bottlenecks_table.csv")

# Convert to GeoDataFrame (Points)
gdf_bottlenecks = gpd.GeoDataFrame(
    df_bottlenecks,
    geometry=gpd.points_from_xy(df_bottlenecks.Coords_E, df_bottlenecks.Coords_N),
    crs="EPSG:2056" # LV95
)

# 2. Load Supervisor's Data (KER Layer)
supervisor_gpkg = "data/Wildtierunfaelle_auf_Verkehrsinfrastruktur_SH.gpkg"
# Note: 'KER' is the layer name
gdf_ker = gpd.read_file(supervisor_gpkg, layer='KER')

# Ensure CRS match
if gdf_ker.crs != gdf_bottlenecks.crs:
    gdf_ker = gdf_ker.to_crs(gdf_bottlenecks.crs)

# 3. Spatial Join (Nearest Segment)
# We find the road segment closest to each bottleneck (within e.g., 50m)
# 'sjoin_nearest' is perfect for this.
joined = gpd.sjoin_nearest(gdf_bottlenecks, gdf_ker, distance_col="dist_m", max_distance=50)

# 4. Analyze the Match
# Assuming the KER layer has a column like 'RiskClass' or 'Klasse' (Check the column names!)
# Let's assume the column is named 'Klasse' (1 to 5)
print("Comparison Results:")
print(joined[['ID', 'Path_Intensity', 'Klasse']].sort_values(by='Path_Intensity', ascending=False))

# Calculate stats
high_risk_matches = joined[joined['Klasse'] >= 4] # Assuming 4 and 5 are high
print(f"Percentage of Bottlenecks on High-Risk Segments: {len(high_risk_matches) / len(joined) * 100:.1f}%")

# 5. Visualization (Optional Histogram)
plt.figure(figsize=(8,6))
joined['Klasse'].value_counts().sort_index().plot(kind='bar', color='darkred')
plt.title("Risk Classification of Identified Bottlenecks")
plt.xlabel("KER Risk Class (Supervisor Data)")
plt.ylabel("Number of Bottlenecks")
plt.grid(axis='y', alpha=0.3)
plt.savefig("results/validation_histogram.png")