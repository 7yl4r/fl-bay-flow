import sys
import datetime
import copernicusmarine

start, end, dst_dir = sys.argv[1], sys.argv[2], sys.argv[3]

# request one extra day on each side so hourly linear interpolation in
# prepro/build_forcing.py never needs to extrapolate past the daily-mean grid
start_pad = (datetime.date.fromisoformat(start) - datetime.timedelta(days=1)).isoformat()
end_pad = (datetime.date.fromisoformat(end) + datetime.timedelta(days=1)).isoformat()

copernicusmarine.subset(
    dataset_id="cmems_mod_glo_phy_my_0.083deg_P1D-m",
    variables=["zos", "uo", "vo"],
    minimum_longitude=-84.0, maximum_longitude=-79.0,
    minimum_latitude=23.0, maximum_latitude=26.0,
    start_datetime=f"{start_pad}T00:00:00",
    end_datetime=f"{end_pad}T00:00:00",
    minimum_depth=0.49, maximum_depth=0.5,
    output_directory=dst_dir,
    output_filename="cmems_glorys_surface.nc",
    overwrite=True,
)
print("CMEMS_DOWNLOAD_DONE")
