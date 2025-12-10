#!/bin/bash

# ==============================================================================
# ZHAW Project Work 2: Master Submission Pipeline (HPC)
#
# Description:
#   Orchestrates the complete wildlife corridor analysis workflow on Slurm.
#   1. Environment Check (Runs locally on login node)
#   2. Preparation (Surface Generation)
#   3. Parallel Worker Array (Least-Cost Path Analysis)
#   4. Aggregation (Result Compilation)
#   5. Cleanup (Intermediate file removal)
#
# Usage:
#   bash submit_workflow.sh
#
# Author: Lukas Buchmann
# Date:   November 2025
# ==============================================================================

# --- 1. CONFIGURATION & PATHS ---

# Determine absolute paths
SCRIPT_DIR=$(dirname "$(realpath "$0")")
PROJECT_ROOT=$(dirname "$SCRIPT_DIR")
LOG_DIR="${SCRIPT_DIR}/logs"
TEMP_TRAFFIC_DIR="${PROJECT_ROOT}/results/temp_traffic"

# Create logs directory if it doesn't exist
mkdir -p "$LOG_DIR"

# Environment Settings
ENV_NAME="pa2_clean"
ENV_YML="${SCRIPT_DIR}/environment.yml"

# Portable Environment Path (Created locally in your Code/Files folder)
ENV_PATH="${SCRIPT_DIR}/${ENV_NAME}"
PY_EXEC="${ENV_PATH}/bin/python"

# Slurm Job Parameters
PARTITION="earth-3"
ARRAY_SIZE="0-200%50"  # Process 201 chunks, max 50 concurrent
MODULES="USS/2022 gcc/9.4.0-pe5.34 lsfm-init-miniconda/1.0.0"

# --- 2. ENVIRONMENT SETUP (LOCAL) ---
# We do this directly on the login node to avoid OOM errors in jobs.

# Load Conda Module
module load lsfm-init-miniconda/1.0.0

echo "=========================================="
echo "   Starting Wildlife Corridor Pipeline    "
echo "=========================================="
echo "Project Root:  $PROJECT_ROOT"
echo "Environment:   $ENV_PATH"
echo "------------------------------------------"

if [ ! -f "$ENV_YML" ]; then
    echo "CRITICAL ERROR: environment.yml not found at $ENV_YML"
    exit 1
fi

echo "[Local] Checking Conda Environment..."

if [ -d "${ENV_PATH}" ]; then
    echo "   Environment exists. Updating..."
    # Update locally (uses login node RAM)
    conda env update -p "${ENV_PATH}" -f "${ENV_YML}" --prune
else
    echo "   Environment not found. Creating..."
    # Create locally (uses login node RAM)
    conda env create -p "${ENV_PATH}" -f "${ENV_YML}"
fi

echo "   Environment ready."
echo "------------------------------------------"


# --- 3. STEP 1: DATA PREPARATION ---
# Generates the resistance surface.

echo "[1/4] Submitting Preparation Job..."
PREP_JOB_ID=$(sbatch --parsable <<EOF
#!/bin/bash
#SBATCH --job-name=PA2_01_Prep
#SBATCH --output=${LOG_DIR}/01_prep_%j.out
#SBATCH --error=${LOG_DIR}/01_prep_%j.err
#SBATCH --time=01:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --partition=${PARTITION}

module load ${MODULES}

echo "Starting Surface Preparation..."
echo "Using Python: $PY_EXEC"
$PY_EXEC 01_prepare_surface.py
EOF
)
echo "   -> Job ID: $PREP_JOB_ID"


# --- 4. STEP 2: WORKER ARRAY ---
# Calculates LCPs in parallel. Depends on Step 1.

echo "[2/4] Submitting Worker Array..."
ARRAY_JOB_ID=$(sbatch --parsable --dependency=afterok:$PREP_JOB_ID <<EOF
#!/bin/bash
#SBATCH --job-name=PA2_02_Worker
#SBATCH --output=${LOG_DIR}/02_worker_%A_%a.out
#SBATCH --error=${LOG_DIR}/02_worker_%A_%a.err
#SBATCH --time=02:00:00
#SBATCH --array=${ARRAY_SIZE}
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --partition=${PARTITION}

module load ${MODULES}

echo "Starting LCP Analysis (Task ID: \$SLURM_ARRAY_TASK_ID)..."
$PY_EXEC 02_worker.py
EOF
)
echo "   -> Job ID: $ARRAY_JOB_ID"


# --- 5. STEP 3: AGGREGATION ---
# Combines partial results. Depends on Step 2.

echo "[3/4] Submitting Aggregation Job..."
AGG_JOB_ID=$(sbatch --parsable --dependency=afterok:$ARRAY_JOB_ID <<EOF
#!/bin/bash
#SBATCH --job-name=PA2_03_Agg
#SBATCH --output=${LOG_DIR}/03_agg_%j.out
#SBATCH --error=${LOG_DIR}/03_agg_%j.err
#SBATCH --time=00:30:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=32G
#SBATCH --partition=${PARTITION}

module load ${MODULES}

echo "Starting Aggregation..."
$PY_EXEC 03_aggregate.py
EOF
)
echo "   -> Job ID: $AGG_JOB_ID"


# --- 6. STEP 4: CLEANUP ---
# Removes temporary files. Depends on Step 3.

echo "[4/4] Submitting Cleanup Job..."
CLEAN_JOB_ID=$(sbatch --parsable --dependency=afterok:$AGG_JOB_ID <<EOF
#!/bin/bash
#SBATCH --job-name=PA2_04_Cleanup
#SBATCH --output=${LOG_DIR}/04_cleanup_%j.out
#SBATCH --error=${LOG_DIR}/04_cleanup_%j.err
#SBATCH --time=00:05:00
#SBATCH --ntasks=1
#SBATCH --mem=1G
#SBATCH --partition=${PARTITION}

# Use the absolute path calculated in the main script for safety
TARGET_DIR="${TEMP_TRAFFIC_DIR}"

echo "Starting Cleanup..."
if [ -d "\$TARGET_DIR" ]; then
    echo "Removing temporary files in: \$TARGET_DIR"
    rm -rf "\$TARGET_DIR"
    echo "Cleanup successful."
else
    echo "Warning: Temporary directory not found at \$TARGET_DIR"
fi
EOF
)
echo "   -> Job ID: $CLEAN_JOB_ID"

echo "------------------------------------------"
echo "All jobs submitted. Monitor with 'squeue -u \$USER'"