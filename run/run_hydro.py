"""
Run the 2D depth-averaged forward hydro simulation for one cruise window,
using the forcing files built by prepro/build_forcing.py. Exports eta/uv
hourly to XDMF for the forward particle tracker.

Usage: mpirun -np N python3 run_hydro.py <forcing_dir> <output_dir>
"""
import os
import sys
import time
import numpy as np
from slim4 import slim, slim2d, mpi

sys.path.insert(0, os.path.dirname(__file__))
from velocity_cap import cap_speed

MESH_FILE = os.path.join(os.path.dirname(__file__), "..", "mesh", "fl_keys_coarse.msh")
BATH_NPY = os.path.join(os.path.dirname(__file__), "..", "data", "bathy", "bath_fl_keys_coarse.npy")

RAMP = 86400.0  # 1 day ramp on open boundary + wind forcing
EXPORT_DT = 3600.0  # hourly export, matches forcing temporal resolution


def log(*a, **kw):
    if mpi.rank == 0:
        print(*a, flush=True, **kw)


def main():
    forcing_dir, output_dir = sys.argv[1], sys.argv[2]
    os.makedirs(output_dir, exist_ok=True)

    with open(os.path.join(forcing_dir, "window.txt")) as f:
        t0, t_release, t_end = [float(x) for x in f.read().split()]

    if mpi.size > 1:
        partname = slim2d.partition_mesh(MESH_FILE)
        mesh = slim2d.Mesh(partname)
    else:
        mesh = slim2d.Mesh(MESH_FILE)

    bath_arr = np.load(BATH_NPY)
    bath = slim.DataStatic(mesh, nfields=1)
    bath.set(bath_arr[None, :])
    h_dg = bath.eval_mesh()

    g = 9.80616
    rho_0 = 1000.0
    sw = slim2d.ShallowWater(mesh, g, bath, rho_0, wave_only=False)

    coriolis = slim.DataFile(os.path.join(forcing_dir, "coriolis"), "coriolis", mesh)
    sw.set_coriolis(coriolis)

    coeff = slim.DataStatic.create_constant(mesh, 2.5e-3)
    sw.add_dissipation(coeff, formula="bulk")

    kappa = slim.DataStatic.create_constant(mesh, 0.01)
    sw.set_viscosity(kappa, formula="smagorinsky")

    wind_path = os.path.join(forcing_dir, "wind")
    if os.path.exists(wind_path):
        tau = slim.DataFile(wind_path, "tau", mesh)
        tau.set_ramp(t0, RAMP)
        sw.set_surface_stress(tau)
        log("wind stress forcing enabled")
    else:
        log("no wind forcing found -- running with tides+currents only")

    eta_bnd = slim.DataFile(os.path.join(forcing_dir, "eta"), "eta", mesh)
    eta_bnd.set_ramp(t0, RAMP)
    uv_bnd = slim.DataFile(os.path.join(forcing_dir, "uv"), "u", mesh)
    uv_bnd.set_ramp(t0, RAMP)
    sw.set_open_boundary("open", eta=eta_bnd, u=uv_bnd, uv_is_transport=False)
    sw.set_wall_boundary("coast")
    sw.enable_wetting_drying(0.2)

    CFL_SAFETY = 0.8

    def recompute_dt(solution, ratio_prev):
        sol_cpu = solution.get()
        cfl_dt = sw.compute_cfl(sol_cpu[[0]])
        cfl_dt = mpi.min_scalar(cfl_dt) if hasattr(mpi, "min_scalar") else cfl_dt
        dt = cfl_dt * CFL_SAFETY
        ratio = max(1, round(EXPORT_DT / dt))
        ratio = max(ratio, ratio_prev)  # never allow a looser (larger) step than before
        return EXPORT_DT / ratio, ratio, cfl_dt

    solution = sw.new_vector()
    dt, ratio, cfl_dt = recompute_dt(solution, 1)
    log(f"CFL dt={cfl_dt:.3f}s -> using dt={dt:.3f}s")

    n_export = int(round((t_end - t0) / EXPORT_DT))

    mesh.create_xdmf(os.path.join(output_dir, "hydro"))

    t = t0
    tic = time.time()
    for iexport in range(n_export + 1):
        sol = solution.get()
        eta_out = sol[0]
        uv_out = cap_speed(sol[1:] / (sol[[0]] + h_dg))
        mesh.append_to_xdmf(os.path.join(output_dir, "hydro"), iexport, t, [("eta", eta_out), ("uv", uv_out)])
        if iexport % 24 == 0:
            if iexport > 0:
                dt, ratio, cfl_dt = recompute_dt(solution, ratio)
            if mpi.rank == 0:
                elapsed = time.time() - tic
                log(f"export {iexport}/{n_export}  t={t:.0f}  eta[{eta_out.min():.3f},{eta_out.max():.3f}]  "
                    f"cfl_dt={cfl_dt:.3f} dt={dt:.3f} elapsed={elapsed:.0f}s")

        if iexport == n_export:
            break
        for _ in range(ratio):
            t = slim.iterate_low_storage_runge_kutta(sw, solution, t, dt, 2 / 13, 1)
            if solution.has_nan():
                raise RuntimeError(f"NaN at export {iexport}, t={t}")

    log(f"hydro run done in {time.time()-tic:.0f}s, wrote {n_export+1} exports to {output_dir}/hydro")


if __name__ == "__main__":
    main()
