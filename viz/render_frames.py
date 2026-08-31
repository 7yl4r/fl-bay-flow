"""
Render one PNG frame per exported particle-tracking timestep: coastline +
source regions + colored particle scatter (colored by release source),
titled with the elapsed time since release.

Usage: python3 render_frames.py <particles_output_dir> <frames_output_dir>
"""
import os
import sys
import calendar
import datetime
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from osgeo import osr

sys.path.insert(0, os.path.dirname(__file__))
from read_particles_xdmf import read_particle_frames

MESH_DIR = os.path.join(os.path.dirname(__file__), "..", "mesh")
UTM17N_PROJ4 = "+proj=utm +zone=17 +datum=WGS84 +units=m +no_defs"

SOURCE_COLORS = ["#e63946", "#2a9d8f", "#457b9d", "#f4a261", "#8338ec"]

SOURCES_LATLON = {
    "0": (25.356689515427423, -81.12549882635247),
    "1": (25.148598989719044, -80.72098670504371),
    "2": (25.21309991153364, -80.52091888773012),
}


def load_coastline():
    mainland = np.load(os.path.join(MESH_DIR, "mainland_arc.npy"))
    islands = np.load(os.path.join(MESH_DIR, "islands_raw.npy"), allow_pickle=True)
    return mainland, islands


def utm_to_lonlat(xy):
    WGS84 = osr.SpatialReference(); WGS84.ImportFromEPSG(4326); WGS84.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    UTM = osr.SpatialReference(); UTM.ImportFromProj4(UTM17N_PROJ4); UTM.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    tx = osr.CoordinateTransformation(UTM, WGS84)
    pts = np.array([tx.TransformPoint(float(x), float(y))[:2] for x, y in xy])
    return pts


def main():
    part_dir, frames_dir = sys.argv[1], sys.argv[2]
    os.makedirs(frames_dir, exist_ok=True)

    osr.DontUseExceptions()
    mainland, islands = load_coastline()

    source_names = {}
    with open(os.path.join(part_dir, "sources.txt")) as f:
        for line in f:
            idx, name = line.strip().split("\t")
            source_names[float(idx)] = name

    frames = read_particle_frames(os.path.join(part_dir, "particles2d.xdmf"))
    print(f"{len(frames)} frames to render")

    t_release = frames[0]["t"]

    lon_min, lon_max = -82.2, -79.7
    lat_min, lat_max = 24.3, 25.9

    for i, frame in enumerate(frames):
        lonlat = utm_to_lonlat(frame["pos"])
        source_id = frame["source"]

        fig, ax = plt.subplots(figsize=(10, 7))
        ax.plot(mainland[:, 0], mainland[:, 1], color="#555555", linewidth=0.8, zorder=1)
        for poly in islands:
            if len(poly) < 3:
                continue
            ax.fill(poly[:, 0], poly[:, 1], color="#d8c9a3", edgecolor="#8a7a55", linewidth=0.3, zorder=1)

        for sid, name in source_names.items():
            mask = source_id == sid
            color = SOURCE_COLORS[int(sid) % len(SOURCE_COLORS)]
            ax.scatter(lonlat[mask, 0], lonlat[mask, 1], s=4, color=color, alpha=0.6, label=name, zorder=3)
            slat, slon = SOURCES_LATLON[str(int(sid))]
            ax.scatter([slon], [slat], marker="*", s=140, color=color, edgecolor="black", linewidth=0.6, zorder=4)

        ax.set_xlim(lon_min, lon_max)
        ax.set_ylim(lat_min, lat_max)
        ax.set_aspect(1.0 / np.cos(np.deg2rad(25.0)))
        ax.set_facecolor("#eaf4fb")

        elapsed_h = (frame["t"] - t_release) / 3600.0
        dt = datetime.datetime.fromtimestamp(frame["t"], datetime.timezone.utc)
        ax.set_title(f"{dt:%Y-%m-%d %H:%M} UTC   (+{elapsed_h:.0f} h since release)")
        ax.legend(loc="lower left", fontsize=8, framealpha=0.9)
        ax.set_xlabel("longitude"); ax.set_ylabel("latitude")

        fig.tight_layout()
        fig.savefig(os.path.join(frames_dir, f"frame_{i:04d}.png"), dpi=110)
        plt.close(fig)

    print(f"wrote {len(frames)} frames to {frames_dir}")


if __name__ == "__main__":
    main()
