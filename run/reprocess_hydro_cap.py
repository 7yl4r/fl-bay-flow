"""
Retroactively apply the velocity cap (velocity_cap.py) to an already-computed
hydro run's exported eta/uv, without re-running the (expensive) shallow-water
solve. Reads the existing hydro/xdmf export, writes a corrected copy, then
swaps it in.

Usage: python3 reprocess_hydro_cap.py <hydro_output_dir>
"""
import os
import sys
import shutil
import numpy as np
from slim4 import slim, slim2d

sys.path.insert(0, os.path.dirname(__file__))
from velocity_cap import cap_speed

MESH_FILE = os.path.join(os.path.dirname(__file__), "..", "mesh", "fl_keys_coarse.msh")


def main():
    hydro_dir = sys.argv[1]
    mesh = slim2d.Mesh(MESH_FILE)

    eta_out = slim.DataOutput(os.path.join(hydro_dir, "hydro"), "eta", mesh)
    uv_out = slim.DataOutput(os.path.join(hydro_dir, "hydro"), "uv", mesh)
    times = eta_out.time

    tmp_prefix = os.path.join(hydro_dir, "hydro_capped")
    mesh.create_xdmf(tmp_prefix)

    n_capped_total = 0
    for iexport, t in enumerate(times):
        eta_val = eta_out.eval_mesh(float(t))[0]
        uv_val = uv_out.eval_mesh(float(t))[:2]

        speed_before = np.hypot(uv_val[0], uv_val[1])
        uv_capped = cap_speed(uv_val)
        speed_after = np.hypot(uv_capped[0], uv_capped[1])
        n_capped_total += int((speed_before > speed_after + 1e-9).sum())

        mesh.append_to_xdmf(tmp_prefix, iexport, float(t), [("eta", eta_val), ("uv", uv_capped)])

    print(f"{hydro_dir}: {n_capped_total} (timestep, DG-node) values capped across {len(times)} exports")

    # swap in place: drop the DataOutput handles first so the old files aren't held open
    del eta_out, uv_out
    old_prefix = os.path.join(hydro_dir, "hydro")
    for path in [old_prefix, old_prefix + ".xdmf"]:
        if os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.exists(path):
            os.remove(path)
    os.rename(tmp_prefix, old_prefix)
    os.rename(tmp_prefix + ".xdmf", old_prefix + ".xdmf")
    print(f"{hydro_dir}: swapped in capped hydro export")


if __name__ == "__main__":
    main()
