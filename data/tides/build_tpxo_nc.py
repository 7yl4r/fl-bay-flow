"""
Convert FES2014 per-constituent NetCDF files (one file per tidal constituent,
separate archives for elevation / eastward velocity / northward velocity) into
the combined multi-constituent NetCDF format expected by slim4.tpxo.TPXO /
GridTPXO.

Elevation file needs: ha (m), hp (deg), lon_z, lat_z, con
Currents file needs:  ua, up, va, vp (cm/s, deg), hua, hva (placeholder,
                        unused since we run with uv_is_transport=False),
                        lon_u, lat_u, lon_v, lat_v, con
"""
import numpy as np
import netCDF4 as nc

CONSTITUENTS = ["m2", "s2", "n2", "k2", "k1", "o1", "p1", "q1"]

ELEV_DIR = "extracted/elevation/ocean_tide_extrapolated"
EAST_DIR = "extracted/eastward/eastward_velocity"
NORTH_DIR = "extracted/northward/northward_velocity"

# crop to a generous box around Florida (FES2014 lon convention is 0-360)
LON_MIN, LON_MAX = 260.0, 300.0
LAT_MIN, LAT_MAX = 15.0, 35.0


def crop_indices(lon, lat):
    ilon = np.where((lon >= LON_MIN) & (lon <= LON_MAX))[0]
    ilat = np.where((lat >= LAT_MIN) & (lat <= LAT_MAX))[0]
    return ilon, ilat


def write_con(ds, n_con):
    ds.createDimension("nc", 4)
    ds.createDimension("con", n_con)
    var = ds.createVariable("con", "S1", ("con", "nc"))
    chars = np.array(
        [[c.encode("ascii") for c in name.ljust(4)] for name in CONSTITUENTS]
    )
    var[:] = chars


def build_elevation():
    with nc.Dataset(f"{ELEV_DIR}/{CONSTITUENTS[0]}.nc") as ds0:
        lon = ds0["lon"][:].astype(np.float64)
        lat = ds0["lat"][:].astype(np.float64)
    ilon, ilat = crop_indices(lon, lat)
    lon_c, lat_c = lon[ilon], lat[ilat]
    nlon, nlat = len(lon_c), len(lat_c)
    print(f"elevation grid crop: {nlon} x {nlat}")

    lon2d, lat2d = np.meshgrid(lon_c, lat_c, indexing="ij")

    ha = np.zeros((len(CONSTITUENTS), nlon, nlat), dtype=np.float64)
    hp = np.zeros((len(CONSTITUENTS), nlon, nlat), dtype=np.float64)

    for i, cname in enumerate(CONSTITUENTS):
        with nc.Dataset(f"{ELEV_DIR}/{cname}.nc") as ds:
            amp = ds["amplitude"][:][np.ix_(ilat, ilon)]
            pha = ds["phase"][:][np.ix_(ilat, ilon)]
            amp = np.ma.filled(amp, 0.0).astype(np.float64).T  # (nlon, nlat)
            pha = np.ma.filled(pha, 0.0).astype(np.float64).T
            ha[i] = amp / 100.0  # cm -> m
            hp[i] = pha
        print(f"  {cname}: amp max {ha[i].max():.3f} m")

    with nc.Dataset("h_fes2014.nc", "w") as out:
        write_con(out, len(CONSTITUENTS))
        out.createDimension("nx", nlon)
        out.createDimension("ny", nlat)
        v = out.createVariable("ha", "f8", ("con", "nx", "ny"))
        v[:] = ha
        v = out.createVariable("hp", "f8", ("con", "nx", "ny"))
        v[:] = hp
        v = out.createVariable("lon_z", "f8", ("nx", "ny"))
        v[:] = lon2d
        v = out.createVariable("lat_z", "f8", ("nx", "ny"))
        v[:] = lat2d
    print("wrote h_fes2014.nc")


def build_currents():
    with nc.Dataset(f"{EAST_DIR}/{CONSTITUENTS[0]}.nc") as ds0:
        lon = ds0["lon"][:].astype(np.float64)
        lat = ds0["lat"][:].astype(np.float64)
    ilon, ilat = crop_indices(lon, lat)
    lon_c, lat_c = lon[ilon], lat[ilat]
    nlon, nlat = len(lon_c), len(lat_c)
    print(f"currents grid crop: {nlon} x {nlat}")
    lon2d, lat2d = np.meshgrid(lon_c, lat_c, indexing="ij")

    ua = np.zeros((len(CONSTITUENTS), nlon, nlat), dtype=np.float64)
    up = np.zeros((len(CONSTITUENTS), nlon, nlat), dtype=np.float64)
    va = np.zeros((len(CONSTITUENTS), nlon, nlat), dtype=np.float64)
    vp = np.zeros((len(CONSTITUENTS), nlon, nlat), dtype=np.float64)

    for i, cname in enumerate(CONSTITUENTS):
        with nc.Dataset(f"{EAST_DIR}/{cname}.nc") as ds:
            amp = np.ma.filled(ds["Ua"][:][np.ix_(ilat, ilon)], 0.0).astype(np.float64).T
            pha = np.ma.filled(ds["Ug"][:][np.ix_(ilat, ilon)], 0.0).astype(np.float64).T
            ua[i], up[i] = amp, pha
        with nc.Dataset(f"{NORTH_DIR}/{cname}.nc") as ds:
            amp = np.ma.filled(ds["Va"][:][np.ix_(ilat, ilon)], 0.0).astype(np.float64).T
            pha = np.ma.filled(ds["Vg"][:][np.ix_(ilat, ilon)], 0.0).astype(np.float64).T
            va[i], vp[i] = amp, pha
        print(f"  {cname}: |u| max {ua[i].max():.1f} cm/s, |v| max {va[i].max():.1f} cm/s")

    with nc.Dataset("u_fes2014.nc", "w") as out:
        write_con(out, len(CONSTITUENTS))
        out.createDimension("nx", nlon)
        out.createDimension("ny", nlat)
        for name, arr in [("ua", ua), ("up", up), ("va", va), ("vp", vp),
                           ("hua", ua), ("hva", va)]:
            v = out.createVariable(name, "f8", ("con", "nx", "ny"))
            v[:] = arr
        v = out.createVariable("lon_u", "f8", ("nx", "ny")); v[:] = lon2d
        v = out.createVariable("lat_u", "f8", ("nx", "ny")); v[:] = lat2d
        v = out.createVariable("lon_v", "f8", ("nx", "ny")); v[:] = lon2d
        v = out.createVariable("lat_v", "f8", ("nx", "ny")); v[:] = lat2d
    print("wrote u_fes2014.nc")


if __name__ == "__main__":
    build_elevation()
    build_currents()
    print("done")
