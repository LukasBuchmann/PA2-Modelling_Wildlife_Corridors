#!/bin/bash

# This script submits the LCP job array and the aggregation/cleanup jobs

# Define RESULTS_DIR relative to this script's location
BASE_DIR=$(dirname $(realpath $0))
RESULTS_DIR="${BASE_DIR}/Results"

# --- 1. Submit the Array Job ---
echo "Submitting LCP array job (1056 tasks, 32 at a time)..."
ARRAY_JOB_ID=$(sbatch --parsable <<EOF
#!/bin/bash
#SBATCH --job-name=LCP_Array_SH
#SBATCH --output=lcp_job_%A_%a.out  # %A = Job ID, %a = Task ID
#SBATCH --error=lcp_job_%A_%a.err
#SBATCH --time=02:00:00
#SBATCH --array=0-889%32
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1      # Each task is single-threaded
#SBATCH --mem=8G               # 8GB for each task
#SBATCH --partition=earth-3

echo "Job $SLURM_ARRAY_JOB_ID, Task $SLURM_ARRAY_TASK_ID started"
module load USS/2022
module load gcc/9.4.0-pe5.34
module load lsfm-init-miniconda/1.0.0
conda activate pa2_env
python hpc_worker.py
echo "Task $SLURM_ARRAY_TASK_ID finished."
EOF
)

if [ -z "$ARRAY_JOB_ID" ]; then
    echo "Error: Failed to submit array job."
    exit 1
fi
echo "Array Job submitted with ID: $ARRAY_JOB_ID"

# --- 2. Submit the Aggregation Job ---
echo "Submitting aggregation job, dependent on $ARRAY_JOB_ID"
AGG_JOB_ID=$(sbatch --parsable --dependency=afterok:$ARRAY_JOB_ID <<EOF
#!/bin/bash
#SBATCH --job-name=LCP_Aggregate
#SBATCH --output=lcp_aggregate_%j.out
#SBATCH --error=lcp_aggregate_%j.err
#SBATCH --time=01:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=32G
#SBATCH --partition=earth-3

echo "Job started on $(hostname) at $(date)"
module load USS/2022
module load gcc/9.4.0-pe5.34
module load lsfm-init-miniconda/1.0.0
conda activate pa2_env
echo "Starting aggregation..."
python aggregate.py
echo "Python script finished."
EOF
)

if [ -z "$AGG_JOB_ID" ]; then
    echo "Error: Failed to submit aggregation job."
    scancel $ARRAY_JOB_ID
    exit 1
fi
echo "Aggregation job submitted with ID: $AGG_JOB_ID"

# --- 3. Submit the Cleanup Job ---
echo "Submitting cleanup job, dependent on $AGG_JOB_ID"
CLEANUP_JOB_ID=$(sbatch --parsable --dependency=afterok:$AGG_JOB_ID <<EOF
#!/bin/bash
#SBATCH --job-name=LCP_Cleanup
#SBATCH --output=lcp_cleanup.out
#SBATCH --error=lcp_cleanup.err
#SBATCH --time=00:05:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=1G
#SBATCH --partition=earth-3

echo "Job started on $(hostname) at $(date)"
echo "Cleaning up log files..."
rm -f lcp_job_${ARRAY_JOB_ID}_*.out
rm -f lcp_job_${ARRAY_JOB_ID}_*.err



# Delete the aggregation job logs
rm -f lcp_aggregate_${AGG_JOB_ID}.out
rm -f lcp_aggregate_${AGG_JOB_ID}.err

echo "Cleanup complete."
EOF
)

if [ -z "$CLEANUP_JOB_ID" ]; then
    echo "Error: Failed to submit cleanup job."
    exit 1
fi

echo "Cleanup job submitted with ID: $CLEANUP_JOB_ID"
echo "---"
echo "All jobs submitted. Use 'squeue --me' to monitor."
