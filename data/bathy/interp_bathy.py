import sys
import numpy as np
from slim4 import slim2d, tools

mesh_file = sys.argv[1] if len(sys.argv) > 1 else "/home/tylar/repos/fl-bay-flow/mesh/fl_keys_coarse.msh"
tif = "/home/tylar/Documents/bluetopo/fl_keys_bluetopo_cog.tif"

mesh = slim2d.Mesh(mesh_file)
x, y = mesh.xnodes[0], mesh.xnodes[1]

elevation = tools.interpolate_tif(tif, x, y, mesh.projection)
n_nan = np.isnan(elevation).sum()
print(f"{n_nan}/{len(elevation)} nodes outside raster coverage (NaN)")

min_depth = 1.5
bath = np.maximum(min_depth, -elevation)

nan_mask = np.isnan(elevation)
if nan_mask.any():
    from scipy.interpolate import NearestNDInterpolator
    valid = ~nan_mask
    filler = NearestNDInterpolator(np.column_stack([x[valid], y[valid]]), bath[valid])
    bath[nan_mask] = filler(x[nan_mask], y[nan_mask])

print(f"bathymetry (positive down): min={bath.min():.2f} max={bath.max():.2f} mean={bath.mean():.2f}")
np.save("bath_fl_keys_coarse.npy", bath)
print("saved bath_fl_keys_coarse.npy")
