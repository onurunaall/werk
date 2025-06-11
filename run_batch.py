import subprocess
from multiprocessing import Pool
import os
import argparse

"""
================================================================================
Batch Processing Script for the AugmentA Pipeline
================================================================================

PURPOSE:
--------
This script is designed to run the main AugmentA pipeline on multiple input 
meshes in parallel. It significantly speeds up the total processing time when 
you have a large dataset (e.g., 20+ meshes) by utilizing multiple CPU cores.

HOW IT WORKS:
-------------
The script uses Python's `multiprocessing.Pool`. This creates a pool of worker
processes. Each worker is assigned one input mesh from the `MESH_FILES_TO_PROCESS`
list and executes the main pipeline for it by calling the command-line interface
of `main.py`. This allows multiple meshes to be processed simultaneously.

HOW TO USE:
-----------
1.  **Configure the `MESH_FILES_TO_PROCESS` list**: Add the full paths to all
    the input mesh files you want to process.
2.  **Configure `NUM_PARALLEL_JOBS`**: Set this to the number of pipelines
    you want to run at the same time. A good starting point is the number of 
    CPU cores on your machine, or slightly less (e.g., 4, 8).
3.  **Ensure Prerequisites**: This script runs the pipeline non-interactively.
    Therefore, you must provide the apex points via a file. For each input
    mesh (e.g., `/path/to/patientX.vtk`), you must have a corresponding
    CSV file (`/path/to/patientX_apex_ids.csv`) and use the `--apex-file`
    argument in the command below.
4.  **Run from the terminal**: 
    `python3 run_batch.py`

RELATIONSHIP WITH THE MULTI-STAGE WORKFLOW (`--start-at-stage`):
-----------------------------------------------------------------
This batch processing script and the staged execution feature are **independent
but complementary tools.**

-   **Is it necessary?** No. You can run a batch process on the *entire* pipeline, or you can run a single mesh through just one *stage*. They
    solve different problems.

-   **Can they be used together?** Yes. Combining them creates a highly
    powerful and flexible workflow. You can perform one stage of the pipeline
    on all meshes in parallel, pause for a manual step, and then run the
    next stage on all meshes in parallel.

    **Example Combined Workflow:**

    1.  **Goal: Resample 20 meshes, then manually check/edit the apex points.**

    2.  **Stage 1: Batch Resampling**
        - Modify the `command` in this script to include `--stop-after-stage prepare_surface`.
        - Run `python3 run_batch.py`.
        - The script will now run the preparation and resampling steps for all 20 
          meshes in parallel and then stop.

    3.  **Manual Step**
        - You now have 20 resampled meshes (`..._res.ply`).
        - Manually inspect them, pick the new apex points, and create the
          `..._res_apex_ids.csv` file for each one.

    4.  **Stage 2: Batch Fiber Generation**
        - Modify this script again:
          a. Update `MESH_FILES_TO_PROCESS` to point to the **newly created resampled meshes**.
          b. Change the `command` to include `--start-at-stage fiber_generation`
             and the `--apex-file` argument.
        - Run `python3 run_batch.py` again.
        - The script will now run the second half of the pipeline (fiber generation)
          for all 20 resampled meshes in parallel.

This combination of batch processing and staged execution gives you complete
control over complex, multi-step research workflows.
"""

# --- Configuration ---
MESH_FILES_TO_PROCESS = [
    "/headless/data/patient14/patient14.vtk",
    "/headless/data/patient15/patient15.vtk",
    "/headless/data/patient16/patient16.vtk",
    # ... add all mesh paths
]

# Number of pipelines to run at the same time
NUM_PARALLEL_JOBS = 4


def run_pipeline_for_single_mesh(mesh_path: str, start_stage: str, stop_stage: str):
    """
        This function defines and executes the command to run your pipeline
        for a single input mesh.
        """
    print(f"--- Starting pipeline for: {mesh_path} ---")
    # Preferable se text based apex info file using --apex-file argument for automation
    # Assuming the apex file is named consistently relative to the mesh
    apex_file = os.path.splitext(mesh_path)[0] + "_apex_ids.csv"
    command = [
        "python3",
        "/opt/project/main.py",
        "--mesh", mesh_path,
        "--apex-file", apex_file,
        "--atrium", "LA_RA",
        "--resample_input", "1",
        "--target_mesh_resolution", "0.4",
        "--debug", "0"
    ]

    # Add apex file argument if it exists
    if os.path.exists(apex_file):
        command.extend(["--apex-file", apex_file])

    # Add stage control arguments if provided
    if start_stage:
        command.extend(["--start-at-stage", start_stage])
    if stop_stage:
        command.extend(["--stop-after-stage", stop_stage])

    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        print(f"--- Finished successfully: {mesh_path} ---")
    except subprocess.CalledProcessError as e:
        print(f"--- ERROR processing: {mesh_path} ---")
        print(f"Return Code: {e.returncode}")
        print(f"Stdout:\n{e.stdout.strip()}")
        print(f"Stderr:\n{e.stderr.strip()}")


if __name__ == "__main__":
    # Add command-line parsing to the batch script itself for more flexibility
    parser = argparse.ArgumentParser(description="Batch runner for the AugmentA pipeline.")
    parser.add_argument('--start-stage', type=str, help="Stage to start at for all meshes.")
    parser.add_argument('--stop-stage', type=str, help="Stage to stop after for all meshes.")
    args = parser.parse_args()

    if not MESH_FILES_TO_PROCESS:
        print("ERROR: Please configure the MESH_FILES_TO_PROCESS list in this script.")
        exit(1)

    print(f"Starting batch processing for {len(MESH_FILES_TO_PROCESS)} meshes...")
    print(f"Running up to {NUM_PARALLEL_JOBS} jobs in parallel.")

    def worker_wrapper(mesh_path):
        run_pipeline_for_single_mesh(mesh_path, start_stage=args.start_stage, stop_stage=args.stop_stage)

    with Pool(processes=NUM_PARALLEL_JOBS) as pool:
        pool.map(worker_wrapper, MESH_FILES_TO_PROCESS)

    print("--- All batch processing complete. ---")
