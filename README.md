# Modelling Wildlife Corridors: Spatial Analysis of Topographic and Landscape Barriers

**Student:** Lukas Buchmann  
**Supervisor:** Nils Ratnaweera  
**Institution:** ZHAW Institute of Computational Life Sciences (ICLS)  
**Course:** Project Work 2 (HS25)  
**Specialisation:** Digital Environment  

---

## 📌 Project Overview

Habitat fragmentation caused by human infrastructure and land use change is a primary driver of biodiversity loss in Switzerland. This project focuses on the **Roe Deer (*Capreolus capreolus*)** in the **Canton of Schaffhausen**.

The project implements a reproducibility-focused workflow on the ZHAW HPC infrastructure. It utilizes open-source geospatial data, primarily **OpenStreetMap (OSM)**, combined with **Corine Land Cover** to calculate resistance surfaces and perform Least-Cost Path (LCP) analysis to identify potential wildlife corridors.

### Objectives
1.  **Resistance Surface Creation:** Combine OSM features (roads, buildings, fences) and Corine land-cover classifications to represent movement constraints.
2.  **Least-Cost Path Analysis:** Compute cumulative costs to identify optimal corridors between habitat patches.
3.  **Bottleneck Identification:** Locate key obstacles limiting ecological connectivity.

---

## 📂 Repository Structure

This project adheres to the **Statement of Reproducibility, Reusability, and Collaboration**.

```text
├── Code/
│   ├── depriciated/               # Outdated code files
│   └── Files/                     # Main analysis pipeline
│       ├── 01_prepare_surface.py  # Preprocessing & resistance surface calculation
│       ├── 02_worker.py           # Parallel LCP analysis
│       ├── 03_aggregate.py        # Aggregation of results
│       ├── environment.yml        # Conda environment definition
│       └── submit_workflow.sh     # HPC batch submission script
├── data/                          # Input data & lookup tables
│   ├── U2018_CLC2018...gpkg       # Preclipped Corine Land Cover (Vector) data
│   ├── clc_resistance_costs.csv   # Resistance values for CLC classes
│   └── osm_resistance_costs.csv   # Resistance values for OSM tags
├── results/                       # Generated visualizations
│   ├── map_01_resistance_surface.png
│   ├── map_02_network_overview.png
│   └── map_03_bottlenecks.png
├── Report_PA2_Buchmann/           # Scientific Report (Quarto source & output)
├── Literatur/                     # Literature and references
├── Presentations/                 # Intermediate presentation slides
├── Disposition_PA2_Buchmann.pdf   # Project disposition
├── Project Plan.pdf               # Timeline and planning
└── README.md                      # Project overview
```

---

## 🛠️ Data Sources
This project utilizes the following open-source geospatial datasets:

* **[OpenStreetMap (OSM)](https://www.openstreetmap.org/#map=11/47.7100/8.5165&layers=Y):** (Primary Source) Used for detailed infrastructure extraction (roads, railways, fences, waterways) and precise land use features.
* **[Corine Land Cover (CLC)](https://land.copernicus.eu/en/products/corine-land-cover):** (Secondary Source) Used for broad-scale habitat classification and filling gaps where OSM land use data may be sparse.

---

## ⚙️ Environment & HPC Setup
This workflow is designed to run on the **ZHAW HPC** using **Miniconda**.

### Dependencies
The `environment.yml` defines the necessary Python geospatial stack. Key libraries include:
* [`osmnx`](https://osmnx.readthedocs.io/en/stable/) (loading OSM data)
* [`pyrosm`](https://pyrosm.readthedocs.io/en/latest/) (processing OSM data)
* [`geopandas`](https://geopandas.org/en/stable/) (vector operations)
* [`rasterio`](https://rasterio.readthedocs.io/en/stable/) (raster operations)
* [`scikit-image`](https://scikit-image.org/docs/stable/) (Least Cost Path Analysis)

---

## 🚀 Usage
The entire analysis pipeline is automated via a single batch script to ensure reproducibility.

### Execution
To reproduce the results on the HPC:

1. Clone this Github on the ZHAW HPC
```bash
git clone https://github.zhaw.ch/buchmluk/PA2-Modelling_Wildlife_Corridors
```
2. Navigate to the HPC batch submission script
```bash
cd Code/Files
```
3. Run the HPC batch submission script
```bash
bash submit_workflow.sh
```

### Workflow Description
The `submit_workflow.sh` script performs the following steps automatically:

1.  **Environment Setup:** Creates a temporary Miniconda environment based on `environment.yml`.
2.  **Surface Preparation (`01_prepare_surface.py`):**
    * Extracts vector features from OSM data.
    * Rasterizes vectors and merges them with Corine Land Cover.
    * Calculates the base resistance surface.
3.  **Path Analysis (`02_worker.py`):**
    * Executes Least-Cost Path analysis.
    * (Optimized for parallel execution on HPC nodes).
4.  **Aggregation (`03_aggregate.py`):**
    * Combines individual paths into a connectivity density map.
    * Generates final statistics and plots.
5.  **Cleanup:** Removes intermediate files to save resources.

---

## 📜 Reproducibility Statement
This project strictly follows the "Guide to Reproducibility, Reusability, and Collaboration". The code is structured to ensure that identical results can be recreated from the raw data using the provided batch script.
