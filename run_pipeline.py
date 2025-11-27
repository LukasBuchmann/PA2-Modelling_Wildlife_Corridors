"""
ZHAW Project Work 2: Optimized Pipeline Orchestrator (Mamba).

This script automates the entire workflow:
1. Checks for 'mamba'.
2. Creates/Updates the 'pa2_env' environment automatically.
3. Auto-activates: If not in 'pa2_env', it re-launches itself inside it.
4. Runs the processing steps sequentially.

Author: Lukas Buchmann (Adapted by PA2)
Date: November 2025
"""

import subprocess
import sys
import os
import shutil
from pathlib import Path

# --- CONFIGURATION ---
SCRIPT_DIR = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_DIR.parent
ENV_FILE = PROJECT_ROOT / "environment.yml"
ENV_NAME = "pa2_env"

# Define the steps: (Filename, Description)
STEPS = [
    ("01_prepare_surface.py", "Step 1: Surface Preparation"),
    ("02_worker.py", "Step 2: Analysis & Aggregation"),
    ("03_aggregate.py", "Step 3: Visualization")
]

def get_executable(name):
    """Finds mamba or conda executable."""
    # Check for mamba first
    exe = shutil.which(name)
    if exe:
        return exe
    # Fallback to conda if mamba is missing but conda exists
    if name == "mamba":
        fallback = shutil.which("conda")
        if fallback:
            print(f"WARNING: 'mamba' not found. Falling back to 'conda'.")
            return fallback
    return None

def manage_environment(mgr_exe):
    """
    Creates or updates the environment using mamba/conda.
    """
    print(f"--- Checking Environment '{ENV_NAME}' with {Path(mgr_exe).name} ---")
    
    if not ENV_FILE.exists():
        print(f"CRITICAL: {ENV_FILE} not found.")
        sys.exit(1)

    # Use 'env update' which creates the env if it doesn't exist 
    # and updates it if it does. This is safe to run multiple times.
    cmd = [
        mgr_exe, "env", "update", 
        "-n", ENV_NAME, 
        "-f", str(ENV_FILE),
        "--prune"  # Removes dependencies no longer in the yaml
    ]
    
    # Use subprocess to call the environment manager
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError:
        print("CRITICAL: Failed to configure environment.")
        sys.exit(1)

def run_step(script_name, description):
    """Runs a single python script."""
    script_path = PROJECT_ROOT / "src" / script_name
    if not script_path.exists():
        print(f"CRITICAL: Script {script_name} missing at {script_path}")
        sys.exit(1)

    print(f"\n>>> {description} ({script_name})")
    try:
        # Use sys.executable to ensure the SAME python interpreter is used
        # that is running this orchestrator (which is now the env python)
        subprocess.check_call([sys.executable, str(script_path)])
    except subprocess.CalledProcessError as e:
        print(f"ERROR: {script_name} failed.")
        sys.exit(e.returncode)

def main():
    # 1. Detect Environment Manager
    mgr = get_executable("mamba")
    if not mgr:
        print("CRITICAL: Neither 'mamba' nor 'conda' found in PATH.")
        sys.exit(1)

    # 2. Check if we are already in the correct environment
    # CONDA_DEFAULT_ENV is set by conda/mamba upon activation
    current_env = os.environ.get('CONDA_DEFAULT_ENV', '')

    if current_env != ENV_NAME:
        print(f"Current Environment: '{current_env}' (Target: '{ENV_NAME}')")
        print("Initializing Auto-Setup...")
        
        # A. Setup/Update the environment
        manage_environment(mgr)
        
        # B. Relaunch this script INSIDE the environment
        # 'mamba run -n name command' executes the command in the activated env
        print(f"\n>>> Relaunching pipeline inside '{ENV_NAME}'...")
        relaunch_cmd = [mgr, "run", "-n", ENV_NAME, "python", str(Path(__file__).resolve())]
        
        try:
            # Replace the current process with the new one
            # On Windows, os.execv is flaky with conda wrappers, so we use subprocess and exit
            subprocess.check_call(relaunch_cmd)
        except subprocess.CalledProcessError as e:
            sys.exit(e.returncode)
        
        # Exit the "base" script instance so we don't run things twice
        sys.exit(0)

    # --- If we reach here, we are inside the target environment ---
    print(f"Confirmed: Running inside '{ENV_NAME}'. Pipeline starting.")
    
    # 3. Execute Pipeline Steps
    for script, desc in STEPS:
        run_step(script, desc)

    print("\n" + "="*60)
    print("PIPELINE COMPLETED SUCCESSFULLY")
    print(f"Outputs located in: {PROJECT_ROOT / 'results'}")
    print("="*60)

if __name__ == "__main__":
    main()