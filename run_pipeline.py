"""
Module: run_pipeline.py
Project: PA2 - Modelling Wildlife Corridors
Author: Lukas Buchmann (Adapted by PA2)
Date: December 2025
Institution: ZHAW, Institute of Computational Life Sciences

Description:
    This script serves as the central automation engine for the project. 
    It ensures reproducibility by enforcing the correct software environment 
    before executing the analysis pipeline.

    Key Features:
    1. Environment Management: Automatically creates or updates the Conda/Mamba 
       environment ('pa2_env') defined in 'environment.yml'.
    2. Auto-Activation: Detects if the script is running in the correct environment. 
       If not, it re-launches itself inside 'pa2_env' using 'mamba run'.
    3. Sequential Execution: Runs the data processing, analysis, and result extraction 
       scripts in the strict order required for data dependency.

Usage:
    Run this script from the root or src directory. It will handle everything.
    $ python src/00_pipeline_orchestrator.py

Dependencies:
    - Must have Mamba (preferred) or Conda installed on the system PATH.
"""

import subprocess
import sys
import os
import shutil
from pathlib import Path

# --- CONFIGURATION -----------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_DIR.parent
ENV_FILE = PROJECT_ROOT / "environment.yml"
ENV_NAME = "pa2_env"

# Define the pipeline steps: (Filename, Description)
STEPS = [
    ("01_resistance_surface_generation.py", "Step 1: Resistance Surface Generation"),
    ("02_local_lcp_analysis.py",            "Step 2: Local LCP Analysis & Aggregation"),
    ("03_extract_bottlenecks.py",           "Step 3: Bottleneck Extraction & Visualization")
]


# --- HELPER FUNCTIONS --------------------------------------------------------

def get_executable(name):
    """
    Locates the executable path for a given command (e.g., 'mamba').

    Args:
        name (str): The name of the executable to find.

    Returns:
        str: Path to the executable, or None if not found.
    """
    # Check for mamba first (faster/preferred)
    exe = shutil.which(name)
    if exe:
        return exe
    
    # Fallback to conda if mamba is requested but missing
    if name == "mamba":
        fallback = shutil.which("conda")
        if fallback:
            print(f"WARNING: 'mamba' not found. Falling back to 'conda'.")
            return fallback
            
    return None


def manage_environment(mgr_exe):
    """
    Ensures the target environment exists and is up-to-date.

    Uses 'env update' which is idempotent: it creates the env if missing 
    or updates dependencies if 'environment.yml' has changed.

    Args:
        mgr_exe (str): Path to the package manager (mamba/conda).
    """
    print(f"--- Checking Environment '{ENV_NAME}' using {Path(mgr_exe).name} ---")
    
    if not ENV_FILE.exists():
        print(f"CRITICAL ERROR: Environment file not found at {ENV_FILE}")
        sys.exit(1)

    # Command: mamba env update -n pa2_env -f environment.yml --prune
    cmd = [
        mgr_exe, "env", "update", 
        "-n", ENV_NAME, 
        "-f", str(ENV_FILE),
        "--prune"  # Removes dependencies that were deleted from the yaml
    ]
    
    try:
        # Check_call waits for the process to complete and raises error on failure
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError:
        print("CRITICAL ERROR: Failed to configure environment.")
        print("Check internet connection or yaml syntax.")
        sys.exit(1)


def run_step(script_name, description):
    """
    Executes a single Python script within the current process.

    Args:
        script_name (str): Filename of the script in the 'src' directory.
        description (str): Log message describing the step.
    """
    script_path = SCRIPT_DIR.parent / "src" / script_name
    
    if not script_path.exists():
        print(f"CRITICAL ERROR: Script {script_name} missing at {script_path}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f">>> {description}")
    print(f"    Running: {script_name}")
    print(f"{'='*60}\n")
    
    try:
        # Use sys.executable to ensure we use the ACTIVE python interpreter 
        # (the one inside the environment) to run the sub-script.
        subprocess.check_call([sys.executable, str(script_path)])
    except subprocess.CalledProcessError as e:
        print(f"ERROR: {script_name} failed with exit code {e.returncode}.")
        sys.exit(e.returncode)


# --- MAIN LOGIC --------------------------------------------------------------

def main():
    """Main orchestration logic."""
    
    # 1. Detect Package Manager
    mgr = get_executable("mamba")
    if not mgr:
        print("CRITICAL: Neither 'mamba' nor 'conda' found in PATH.")
        print("Please install Miniforge or Anaconda.")
        sys.exit(1)

    # 2. Environment Auto-Detection
    # CONDA_DEFAULT_ENV is an environment variable set by conda upon activation
    current_env = os.environ.get('CONDA_DEFAULT_ENV', '')

    if current_env != ENV_NAME:
        print(f"Current Environment: '{current_env}' (Target: '{ENV_NAME}')")
        print("Initializing Auto-Setup Sequence...")
        
        # A. Setup/Update the environment based on yaml
        manage_environment(mgr)
        
        # B. Relaunch this script INSIDE the target environment
        # 'mamba run -n name command' executes the command in the context of the env
        print(f"\n>>> Relaunching pipeline inside '{ENV_NAME}'...")
        
        relaunch_cmd = [mgr, "run", "-n", ENV_NAME, "python", str(Path(__file__).resolve())]
        
        try:
            # We use subprocess call here instead of os.execv because os.execv 
            # behaves inconsistently with Conda shims on Windows.
            subprocess.check_call(relaunch_cmd)
        except subprocess.CalledProcessError as e:
            sys.exit(e.returncode)
        
        # Exit the "base" (outer) script instance so we don't run the pipeline twice
        sys.exit(0)

    # --- EXECUTION PHASE ---
    # If we reach this line, we are strictly inside 'pa2_env'.
    
    print(f"Confirmed: Running inside active environment '{ENV_NAME}'.")
    
    # 3. Execute Pipeline Steps sequentially
    for script, desc in STEPS:
        run_step(script, desc)

    print("\n" + "="*60)
    print("PIPELINE COMPLETED SUCCESSFULLY")
    print(f"Results available in: {PROJECT_ROOT / 'results'}")
    print("="*60)

if __name__ == "__main__":
    main()