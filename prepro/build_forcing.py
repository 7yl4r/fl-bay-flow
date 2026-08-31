"""
Build SLIM4 CG-format forcing files (wind stress, open-boundary eta/uv,
Coriolis) for one cruise window, on the Florida Keys coarse mesh.

Open-boundary eta/uv = FES2014 tides (hourly, via slim4.tpxo.GridTPXO)
                        + CMEMS GLORYS12 daily-mean background (linearly
                          interpolated to hourly), interpolated onto every
                          mesh node (set_open_boundary only reads the
                          boundary-tagged subset at run time, so writing the
                          full-mesh field is simplest and harmless).
Wind stress = ERA5 10m u/v (hourly) via the Smith-Banke formula, interpolated
              onto every mesh node. Skipped if no ERA5 files are found yet
              (run_hydro.py falls back to zero wind stress in that case).
"""
import os
import sys
import glob
import calendar
import datetime
import numpy as np
import netCDF4 as nc
from scipy.interpolate import RegularGridInterpolator

sys.path.insert(0, os.path.dirname(__file__))
from slim4 import slim, slim2d
from slim4.tpxo import GridTPXO

MESH_FILE = os.path.join(os.path.dirname(__file__), "..", "mesh", "fl_keys_coarse.msh")
TIDES_H = os.path.join(os.path.dirname(__file__), "..", "data", "tides", "h_fes2014.nc")
TIDES_U = os.path.join(os.path.dirname(__file__), "..", "data", "tides", "u_fes2014.nc")
BATH_NPY = os.path.join(os.path.dirname(__file__), "..", "data", "bathy", "bath_fl_keys_coarse.npy")
WIND_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "wind")
CURRENTS_ROOT = os.path.join(os.path.dirname(__file__), "..", "data", "currents")


def parse_date(s):
    return calendar.timegm(datetime.date.fromisoformat(s).timetuple()[:6])


def smith_banke(uv_wind):
    atm_density = 1.25
    f0, f1, f2 = 0, 6.3e-4, 6.6e-5
    norm = np.linalg.norm(uv_wind, axis=0)
    coeff = f0 + f1 * norm + f2 * norm**2
    return atm_density * coeff[None, :] * uv_wind


def mesh_lonlat(mesh):
    return slim.proj_transform(mesh.projection, "+proj=latlong +ellps=WGS84", mesh.xnodes)[:2]


def build_coriolis(mesh, out_dir):
    lonlat = mesh_lonlat(mesh)
    f = 2 * 7.292e-5 * np.sin(lonlat[1] * np.pi / 180.0)
    path = os.path.join(out_dir, "coriolis")
    with slim.DataFileWriter(path, "CG") as w:
        w.append([("coriolis", f[None, :])], 0.0)
    print(f"wrote {path}")


def _relevant_wind_files(t0, t1):
    """Only the era5_wind_YYYYMM.nc files overlapping [t0, t1] -- data/wind/ is
    shared across concurrently-running cruises, so globbing everything risks
    picking up another cruise's file mid-download."""
    relevant = []
    for f in sorted(glob.glob(os.path.join(WIND_DIR, "era5_wind_??????.nc"))):
        tag = os.path.basename(f)[len("era5_wind_"):-len(".nc")]
        year, month = int(tag[:4]), int(tag[4:6])
        month_start = calendar.timegm((year, month, 1, 0, 0, 0))
        days_in_month = calendar.monthrange(year, month)[1]
        month_end = month_start + days_in_month * 86400.0
        if month_end >= t0 - 3600 and month_start <= t1 + 3600:
            relevant.append(f)
    return relevant


def build_wind(mesh, t0, t1, out_dir):
    files = _relevant_wind_files(t0, t1)
    if not files:
        print("no ERA5 wind files found -- skipping wind forcing (run_hydro will use zero wind)")
        return False

    lonlat = mesh_lonlat(mesh)
    node_pts = lonlat.T  # (n, 2) [lon, lat]

    path = os.path.join(out_dir, "wind")
    with slim.DataFileWriter(path, "CG") as writer:
        n_written = 0
        for f in files:
            with nc.Dataset(f) as ds:
                lat = ds["latitude"][:].astype(np.float64)
                lon = ds["longitude"][:].astype(np.float64)
                times = ds["valid_time"][:] if "valid_time" in ds.variables else ds["time"][:]
                time_units = (ds["valid_time"] if "valid_time" in ds.variables else ds["time"]).units
                times_unix = nc.num2date(times, time_units, only_use_cftime_datetimes=False)
                u10 = ds["u10"][:]
                v10 = ds["v10"][:]

                lat_order = np.argsort(lat)
                lat_s = lat[lat_order]

                for it, tdt in enumerate(times_unix):
                    t = calendar.timegm(tdt.timetuple())
                    if t < t0 - 3600 or t > t1 + 3600:
                        continue
                    u_interp = RegularGridInterpolator((lat_s, lon), u10[it][lat_order, :], bounds_error=False, fill_value=None)
                    v_interp = RegularGridInterpolator((lat_s, lon), v10[it][lat_order, :], bounds_error=False, fill_value=None)
                    u_node = u_interp(node_pts[:, ::-1])
                    v_node = v_interp(node_pts[:, ::-1])
                    tau = smith_banke(np.stack([u_node, v_node], axis=0))
                    writer.append([("tau", tau)], float(t))
                    n_written += 1
    print(f"wrote {path} ({n_written} timesteps)")
    return True


def build_open_boundary(mesh, t0, t1, out_dir, cmems_nc):
    lonlat = mesh_lonlat(mesh)
    node_pts = lonlat.T  # (n, 2)

    tides = GridTPXO(mesh, TIDES_H, TIDES_U)
    tides.set_points(lonlat)

    with nc.Dataset(cmems_nc) as ds:
        lat = ds["latitude"][:].astype(np.float64)
        lon = ds["longitude"][:].astype(np.float64)
        time_units = ds["time"].units
        times_unix = np.array([calendar.timegm(d.timetuple()) for d in nc.num2date(ds["time"][:], time_units, only_use_cftime_datetimes=False)])
        zos = np.ma.filled(ds["zos"][:], 0.0).astype(np.float64)  # (time, lat, lon)
        uo = np.ma.filled(ds["uo"][:], 0.0).astype(np.float64)[:, 0]  # (time, lat, lon)
        vo = np.ma.filled(ds["vo"][:], 0.0).astype(np.float64)[:, 0]

    lat_order = np.argsort(lat)
    lat_s = lat[lat_order]

    def cmems_interp_at(field_t, tarr, t):
        it = np.searchsorted(tarr, t)
        it0 = np.clip(it - 1, 0, len(tarr) - 1)
        it1 = np.clip(it, 0, len(tarr) - 1)
        if it0 == it1:
            frac = 0.0
        else:
            frac = (t - tarr[it0]) / (tarr[it1] - tarr[it0])
        interp0 = RegularGridInterpolator((lat_s, lon), field_t[it0][lat_order, :], bounds_error=False, fill_value=None)
        interp1 = RegularGridInterpolator((lat_s, lon), field_t[it1][lat_order, :], bounds_error=False, fill_value=None)
        v0 = interp0(node_pts[:, ::-1])
        v1 = interp1(node_pts[:, ::-1])
        return v0 * (1 - frac) + v1 * frac

    path_eta = os.path.join(out_dir, "eta")
    path_uv = os.path.join(out_dir, "uv")
    hourly_times = np.arange(t0, t1 + 3600.0, 3600.0)

    with slim.DataFileWriter(path_eta, "CG") as w_eta, slim.DataFileWriter(path_uv, "CG") as w_uv:
        for t in hourly_times:
            eta_tide = tides.get_eta(t)[0]
            u_tide, v_tide = tides.get_uv(t, False)
            u_tide, v_tide = u_tide[0], v_tide[0]

            eta_cm = cmems_interp_at(zos, times_unix, t)
            u_cm = cmems_interp_at(uo, times_unix, t)
            v_cm = cmems_interp_at(vo, times_unix, t)

            eta_total = (eta_tide + eta_cm)[None, :]
            uv_total = np.stack([u_tide + u_cm, v_tide + v_cm], axis=0)

            w_eta.append([("eta", eta_total)], float(t))
            w_uv.append([("u", uv_total)], float(t))

    print(f"wrote {path_eta}, {path_uv} ({len(hourly_times)} hourly timesteps)")


def main():
    window_start, window_end, spinup_days, out_dir, cruise_id = sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4], sys.argv[5]
    t_release = parse_date(window_start)
    t_end = parse_date(window_end)
    t0 = t_release - spinup_days * 86400.0
    cmems_nc = os.path.join(CURRENTS_ROOT, cruise_id, "cmems_glorys_surface.nc")

    os.makedirs(out_dir, exist_ok=True)
    mesh = slim2d.Mesh(MESH_FILE)

    build_coriolis(mesh, out_dir)
    build_wind(mesh, t0, t_end, out_dir)
    build_open_boundary(mesh, t0, t_end, out_dir, cmems_nc)

    with open(os.path.join(out_dir, "window.txt"), "w") as f:
        f.write(f"{t0}\n{t_release}\n{t_end}\n")
    print(f"forcing window: t0(spinup)={t0} t_release={t_release} t_end={t_end}")


if __name__ == "__main__":
    main()
