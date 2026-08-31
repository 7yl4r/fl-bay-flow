import numpy as np
from osgeo import osr
import shapely.geometry as sg
import seamsh
from seamsh.geometry import Domain, CurveType

osr.DontUseExceptions()

WGS84 = osr.SpatialReference()
WGS84.ImportFromEPSG(4326)
WGS84.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

UTM17N = osr.SpatialReference()
UTM17N.ImportFromEPSG(32617)
UTM17N.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

mainland = np.load("mainland_arc.npy")
open_arc = np.load("open_arc.npy")
islands_raw = np.load("islands_raw.npy", allow_pickle=True)

# simplify with shapely (tolerances in degrees)
def simplify(pts, tol, closed=False):
    if closed:
        geom = sg.LinearRing(pts)
    else:
        geom = sg.LineString(pts)
    out = np.array(geom.simplify(tol, preserve_topology=True).coords)
    return out

mainland_s = simplify(mainland, 0.0015)
open_arc_s = simplify(open_arc, 0.02)

islands_s = []
for p in islands_raw:
    if len(p) < 4:
        continue
    s = simplify(p, 0.0006, closed=True)
    if len(s) < 4:
        continue
    # drop slivers (bounding box smaller than ~40m)
    if (s[:, 0].max() - s[:, 0].min()) < 4e-4 and (s[:, 1].max() - s[:, 1].min()) < 4e-4:
        continue
    islands_s.append(s)

print(f"mainland: {len(mainland)} -> {len(mainland_s)} pts")
print(f"open arc: {len(open_arc)} -> {len(open_arc_s)} pts")
print(f"islands: {len(islands_raw)} -> {len(islands_s)} kept, "
      f"{sum(len(p) for p in islands_raw)} -> {sum(len(p) for p in islands_s)} pts")

domain = Domain(UTM17N)
domain.add_boundary_curve(mainland_s, "coast", WGS84, CurveType.POLYLINE)
domain.add_boundary_curve(open_arc_s, "open", WGS84, CurveType.POLYLINE)
for s in islands_s:
    domain.add_boundary_curve(s, "coast", WGS84, CurveType.POLYLINE)

dist = seamsh.field.Distance(domain, 200.0, tags=["coast"])

def mesh_size(x, proj):
    d = dist(x, proj)
    size = 400.0 + 0.35 * d
    return np.clip(size, 400.0, 6000.0)

seamsh.gmsh.mesh(domain, "fl_keys_coarse.msh", mesh_size, smoothness=0.3)
print("mesh written: fl_keys_coarse.msh")
