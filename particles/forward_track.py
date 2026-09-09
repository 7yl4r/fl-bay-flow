"""
Forward Lagrangian particle tracking, seeded near three Everglades outflow
sites, tracked forward through a previously-run hydro simulation's exported
eta/uv fields for the length of the cruise's model window.

Usage: python3 forward_track.py <hydro_output_dir> <forcing_dir> <particles_output_dir>
"""
import os
import sys
import numpy as np
from osgeo import osr
from slim4 import slim, slim2d
import slim4.particles2d as sp2d

osr.DontUseExceptions()

MESH_FILE = os.path.join(os.path.dirname(__file__), "..", "mesh", "fl_keys_coarse.msh")
BATH_NPY = os.path.join(os.path.dirname(__file__), "..", "data", "bathy", "bath_fl_keys_coarse.npy")

SOURCES = {
    "Shark River": (25.356689515427423, -81.12549882635247),
    "Mccormick Creek": (25.148598989719044, -80.72098670504371),
    "Trout Creek": (25.21309991153364, -80.52091888773012),
}
N_PER_SOURCE = 200
DT_MAX = 900.0  # integration substep target
EXPORT_DT = 900.0  # uniform 15-min export cadence for the full run
KH = float(os.environ.get("FORWARD_TRACK_KH", 2.0))  # background horizontal diffusivity (m^2/s)
# "direct" (KH used as a fixed constant) rather than "okubo" (KH scaled by local
# velocity shear): the shear-scaled formula amplifies any velocity-gradient
# artifact in the hydro field into an outsized random-walk kick -- see
# README.md ("Known artifact: localized spurious velocity spikes"). "direct"
# gives the same nominal background dispersion without that vulnerability.
KH_FORMULA = os.environ.get("FORWARD_TRACK_KH_FORMULA", "direct")


def build_export_times(t_release, t_end):
    times = list(np.arange(t_release, t_end + 1.0, EXPORT_DT))
    times = sorted(set(round(t, 3) for t in times))
    if times[-1] < t_end:
        times.append(t_end)
    return times


def main():
    hydro_dir, forcing_dir, out_dir = sys.argv[1], sys.argv[2], sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)

    with open(os.path.join(forcing_dir, "window.txt")) as f:
        t0, t_release, t_end = [float(x) for x in f.read().split()]

    mesh = slim2d.Mesh(MESH_FILE)
    bath_arr = np.load(BATH_NPY)
    bath = slim.DataStatic(mesh, nfields=1)
    bath.set(bath_arr[None, :])
    kh = slim.DataStatic.create_constant(mesh, KH)

    eta = slim.DataOutput(os.path.join(hydro_dir, "hydro"), "eta", mesh)
    uv = slim.DataOutput(os.path.join(hydro_dir, "hydro"), "uv", mesh)

    tracker = sp2d.Tracker2d(mesh, eta, uv, bath, kh, KH_FORMULA)
    print(f"diffusivity: formula={KH_FORMULA} kh={KH}")
    parray = sp2d.ParticleArrays2d(mesh, ["source"])

    WGS84 = osr.SpatialReference(); WGS84.ImportFromEPSG(4326); WGS84.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    proj = osr.SpatialReference(); proj.ImportFromProj4(mesh.projection)
    tx = osr.CoordinateTransformation(WGS84, proj)

    source_names = list(SOURCES.keys())
    for i, name in enumerate(source_names):
        lat, lon = SOURCES[name]
        x, y, _ = tx.TransformPoint(lon, lat)
        xy = np.tile(np.array([[x], [y]]), (1, N_PER_SOURCE))
        xy += np.random.normal(0, 50.0, size=xy.shape)  # small jitter so particles don't all sit on one node
        attrs = {"source": np.full(N_PER_SOURCE, float(i))}
        tracker.add_particles(parray, xy, t_release, attrs)
        print(f"seeded {N_PER_SOURCE} particles at {name} ({x:.0f},{y:.0f})")

    with open(os.path.join(out_dir, "sources.txt"), "w") as f:
        for i, name in enumerate(source_names):
            f.write(f"{i}\t{name}\n")

    export_name = os.path.join(out_dir, "particles2d")
    sp2d.ParticleArrays2d.create_xdmf(export_name)

    export_times = build_export_times(t_release, t_end)
    print(f"{len(export_times)} export checkpoints ({EXPORT_DT/60:.0f}-min cadence throughout)")

    t = t_release
    sp2d.ParticleArrays2d.append_to_xdmf(parray, export_name, t, fields=["source"])
    print(f"export 0 @ t={t:.0f}  n_particles={parray.size}")
    for iexport, t_next in enumerate(export_times[1:], start=1):
        gap = t_next - t
        nsub = max(1, int(np.ceil(gap / DT_MAX)))
        dt = gap / nsub
        for _ in range(nsub):
            t = tracker.move(parray, t, dt)
        parray.remove_inactive()
        sp2d.ParticleArrays2d.append_to_xdmf(parray, export_name, t, fields=["source"])
        print(f"export {iexport} @ t={t:.0f}  n_particles={parray.size}")

    print("forward LPT done")


if __name__ == "__main__":
    main()
