"""Read a slim4 particles2d XDMF export (temporal collection of Polyvertex
grids, each backed by raw flat binary .abin arrays) without needing the
slim4 python bindings -- pure stdlib + numpy, so this can run independently
of PYTHONPATH/mpi setup.
"""
import os
import xml.etree.ElementTree as ET
import numpy as np

DTYPE_MAP = {("Float", 4): np.float32, ("Float", 8): np.float64}


def _read_dataitem(base_dir, item):
    dims = tuple(int(x) for x in item.attrib["Dimensions"].split())
    dtype = DTYPE_MAP[(item.attrib.get("DataType", "Float"), int(item.attrib.get("Precision", 4)))]
    seek = int(item.attrib.get("Seek", 0))
    path = os.path.join(base_dir, item.text.strip())
    count = int(np.prod(dims))
    arr = np.fromfile(path, dtype=dtype, count=count, offset=seek)
    return arr.reshape(dims)


def read_particle_frames(xdmf_path):
    """Returns a list of dicts: {"t": float, "pos": (n,2) array, attrs...}"""
    base_dir = os.path.dirname(os.path.abspath(xdmf_path))
    tree = ET.parse(xdmf_path)
    root = tree.getroot()
    frames = []
    for temporal_grid in root.iter("Grid"):
        if temporal_grid.attrib.get("CollectionType") != "Spatial":
            continue
        time_el = temporal_grid.find("Time")
        t = float(time_el.attrib["Value"]) if time_el is not None else None
        for grid in temporal_grid.findall("Grid"):
            geom = grid.find("Geometry")
            pos_item = geom.find("DataItem")
            pos = _read_dataitem(base_dir, pos_item)
            frame = {"t": t, "pos": pos}
            for attr in grid.findall("Attribute"):
                name = attr.attrib["Name"]
                item = attr.find("DataItem")
                frame[name] = _read_dataitem(base_dir, item)
            frames.append(frame)
    return frames
