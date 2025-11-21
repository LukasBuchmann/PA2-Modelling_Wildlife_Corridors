#!/bin/bash

# ==========================================
# Master Submission Script (Absolute Path Fix + Cleanup)
# ==========================================

# Define paths
BASE_DIR=$(dirname $(realpath $0))
LOG_DIR="${BASE_DIR}/logs"
mkdir -p $LOG_DIR

# --- CONFIGURATION ---
# PASTE YOUR PATH HERE from Step 1
# Example: PY_EXEC="/cfs/earth/scratch/buchmluk/.conda/envs/pa2_clean/bin/python"
PY_EXEC="/cfs/earth/scratch/buchmluk/.conda/envs/pa2_clean/bin/python"

# Check if path is set
if [[ "$PY_EXEC" == *INSERT_PATH* ]]; then
    echo "Error: You forgot to paste the python path in the script!"
    exit 1
fi

echo "--- Step 1: Data Preparation (High Memory) ---"
PREP_JOB_ID=$(sbatch --parsable <<EOF
#!/bin/bash
#SBATCH --job-name=Prep_Surface
#SBATCH --output=${LOG_DIR}/prep_%j.out
#SBATCH --error=${LOG_DIR}/prep_%j.err
#SBATCH --time=01:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --partition=earth-3

module load USS/2022
module load gcc/9.4.0-pe5.34
module load lsfm-init-miniconda/1.0.0

echo "Using Python: $PY_EXEC"
$PY_EXEC 01_prepare_surface.py
EOF
)

echo "Preparation Job ID: $PREP_JOB_ID"

echo "--- Step 2: LCP Array (Dependent on Prep) ---"
ARRAY_JOB_ID=$(sbatch --parsable --dependency=afterok:$PREP_JOB_ID <<EOF
#!/bin/bash
#SBATCH --job-name=LCP_Array
#SBATCH --output=${LOG_DIR}/lcp_%A_%a.out
#SBATCH --error=${LOG_DIR}/lcp_%A_%a.err
#SBATCH --time=02:00:00
#SBATCH --array=0-200%50
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --partition=earth-3

module load USS/2022
module load gcc/9.4.0-pe5.34
module load lsfm-init-miniconda/1.0.0

echo "Running LCP Worker..."
$PY_EXEC 02_worker.py
EOF
)

echo "Array Job ID: $ARRAY_JOB_ID"

echo "--- Step 3: Aggregation (Dependent on Array) ---"
AGG_JOB_ID=$(sbatch --parsable --dependency=afterok:$ARRAY_JOB_ID <<EOF
#!/bin/bash
#SBATCH --job-name=Agg_Results
#SBATCH --output=${LOG_DIR}/agg_%j.out
#SBATCH --error=${LOG_DIR}/agg_%j.err
#SBATCH --time=00:30:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=32G
#SBATCH --partition=earth-3

module load USS/2022
module load gcc/9.4.0-pe5.34
module load lsfm-init-miniconda/1.0.0

echo "Running Aggregation..."
$PY_EXEC 03_aggregate.py
EOF
)

echo "Aggregation Job ID: $AGG_JOB_ID"

echo "--- Step 4: Cleanup (Dependent on Aggregation) ---"
CLEAN_JOB_ID=$(sbatch --parsable --dependency=afterok:$AGG_JOB_ID <<EOF
#!/bin/bash
#SBATCH --job-name=Cleanup
#SBATCH --output=${LOG_DIR}/cleanup_%j.out
#SBATCH --error=${LOG_DIR}/cleanup_%j.err
#SBATCH --time=00:05:00
#SBATCH --ntasks=1
#SBATCH --mem=1G
#SBATCH --partition=earth-3

# Calculate path to temp_traffic relative to this script location (Code/Files)
# We go up two levels (Code -> Root) then into results
TEMP_DIR="../../results/temp_traffic"

echo "Starting cleanup..."
if [ -d "\$TEMP_DIR" ]; then
    echo "Removing temporary files in: \$TEMP_DIR"
    rm -rf "\$TEMP_DIR"
    echo "Cleanup successful."
else
    echo "Warning: Temporary directory not found at \$TEMP_DIR"
fi
EOF
)

echo "Cleanup Job ID: $CLEAN_JOB_ID"
echo "Workflow submitted successfully."