"""
Top-level driver: run the full forward-drift pipeline (forcing download +
build, hydro simulation, forward particle tracking, frame rendering, HTML
viewer) for one or all 8 cruise windows.

Each cruise's pipeline is a sequential chain of subprocess steps; different
cruises run concurrently (one process each, since the mesh is small and each
step is single-core -- see mesh/dirk2_test.py notes on why MPI-per-cruise was
dropped in favor of parallelizing across cruises instead).

Usage:
  python3 run_all_cruises.py WS23011        # one cruise
  python3 run_all_cruises.py --all          # all 8, up to N concurrent
  python3 run_all_cruises.py --all -j 4
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.abspath(__file__))
VENV_PY = os.path.join(ROOT, "venv", "bin", "python3")
BUILD_DIR = os.path.join(ROOT, "build")
SPINUP_DAYS = 1

ENV = dict(os.environ)
ENV["PYTHONPATH"] = BUILD_DIR
ENV["LD_LIBRARY_PATH"] = BUILD_DIR + ":" + ENV.get("LD_LIBRARY_PATH", "")


def load_windows():
    with open(os.path.join(ROOT, "data", "keys_checkpoints.json")) as f:
        entries = json.load(f)
    return {e["cruise_id"]: (e["model_window_start"], e["model_window_end"]) for e in entries}


def run_step(name, cmd, log_path):
    with open(log_path, "a") as log:
        log.write(f"\n=== {name} @ {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        log.flush()
        result = subprocess.run(cmd, cwd=ROOT, env=ENV, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        raise RuntimeError(f"step '{name}' failed (see {log_path})")


def run_cruise(cruise_id, window_start, window_end):
    forcing_dir = os.path.join(ROOT, "data", "forcing", cruise_id)
    currents_dir = os.path.join(ROOT, "data", "currents", cruise_id)
    hydro_dir = os.path.join(ROOT, "run", "output", cruise_id)
    particles_dir = os.path.join(ROOT, "particles", "output", cruise_id)
    frames_dir = os.path.join(ROOT, "viz", "frames", cruise_id)
    viewer_html = os.path.join(ROOT, "viz", f"viewer_{cruise_id}.html")
    log_path = os.path.join(ROOT, "run", f"pipeline_{cruise_id}.log")

    for d in [forcing_dir, currents_dir, hydro_dir, particles_dir, frames_dir]:
        os.makedirs(d, exist_ok=True)

    spinup_start = (datetime.date.fromisoformat(window_start) - datetime.timedelta(days=SPINUP_DAYS)).isoformat()

    try:
        # ERA5 wind: best-effort, tolerate license/queue failures (build_forcing
        # will fall back to zero wind and run_hydro logs that clearly).
        try:
            run_step(
                "era5",
                [VENV_PY, "data/wind/download_era5.py", spinup_start, window_end, "data/wind"],
                log_path,
            )
        except RuntimeError as e:
            with open(log_path, "a") as log:
                log.write(f"ERA5 download failed, continuing without wind: {e}\n")

        run_step(
            "cmems",
            [VENV_PY, "data/currents/download_cmems.py", spinup_start, window_end, currents_dir],
            log_path,
        )
        run_step(
            "forcing",
            [VENV_PY, "prepro/build_forcing.py", window_start, window_end, str(SPINUP_DAYS), forcing_dir, cruise_id],
            log_path,
        )
        run_step(
            "hydro",
            [VENV_PY, "run/run_hydro.py", forcing_dir, hydro_dir],
            log_path,
        )
        run_step(
            "particles",
            [VENV_PY, "particles/forward_track.py", hydro_dir, forcing_dir, particles_dir],
            log_path,
        )
        run_step(
            "frames",
            [VENV_PY, "viz/render_frames.py", particles_dir, frames_dir],
            log_path,
        )
        run_step(
            "viewer",
            [VENV_PY, "viz/build_viewer.py", frames_dir, particles_dir, cruise_id, viewer_html],
            log_path,
        )
        return cruise_id, True, viewer_html
    except Exception as e:
        return cruise_id, False, str(e)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("cruise_id", nargs="?", help="single cruise id, e.g. WS23011")
    parser.add_argument("--all", action="store_true", help="run all 8 cruise windows")
    parser.add_argument("-j", type=int, default=4, help="max concurrent cruises (default 4)")
    args = parser.parse_args()

    windows = load_windows()

    if args.all:
        targets = list(windows.items())
    elif args.cruise_id:
        targets = [(args.cruise_id, windows[args.cruise_id])]
    else:
        parser.error("pass a cruise_id or --all")
        return

    print(f"running {len(targets)} cruise(s), up to {args.j} concurrently")
    with ProcessPoolExecutor(max_workers=args.j) as pool:
        futures = {
            pool.submit(run_cruise, cid, start, end): cid
            for cid, (start, end) in targets
        }
        for fut in as_completed(futures):
            cid, ok, info = fut.result()
            status = "OK" if ok else "FAILED"
            print(f"[{status}] {cid}: {info}")


if __name__ == "__main__":
    main()
