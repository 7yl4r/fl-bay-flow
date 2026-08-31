"""Download ERA5 hourly 10m wind (u,v) for a date window over the Florida
Keys domain, via the CDS API. One request per calendar day (CDS handles
that natively as separate "day" list entries within one month/year request
if the window doesn't cross a month boundary; for simplicity here we just
issue one request per (year, month) pair covering the needed days).
"""
import os
import sys
import calendar
import datetime
import cdsapi

AREA = [26.0, -84.0, 23.0, -79.0]  # N, W, S, E


def daterange_by_month(start: datetime.date, end: datetime.date):
    cur = start.replace(day=1)
    out = {}
    d = start
    while d <= end:
        key = (d.year, d.month)
        out.setdefault(key, []).append(d.day)
        d += datetime.timedelta(days=1)
    return out


def download(start_str, end_str, dst_dir):
    os.makedirs(dst_dir, exist_ok=True)
    start = datetime.date.fromisoformat(start_str)
    end = datetime.date.fromisoformat(end_str)
    months = daterange_by_month(start, end)

    c = cdsapi.Client()
    files = []
    for (year, month), days in months.items():
        dst = os.path.join(dst_dir, f"era5_wind_{year}{month:02d}.nc")
        if os.path.exists(dst):
            print(f"{dst} already present")
            files.append(dst)
            continue
        print(f"requesting ERA5 wind {year}-{month:02d} days={days}")
        c.retrieve(
            "reanalysis-era5-single-levels",
            {
                "product_type": "reanalysis",
                "variable": ["10m_u_component_of_wind", "10m_v_component_of_wind"],
                "year": str(year),
                "month": f"{month:02d}",
                "day": [f"{d:02d}" for d in days],
                "time": [f"{h:02d}:00" for h in range(24)],
                "area": AREA,
                "format": "netcdf",
            },
            dst,
        )
        files.append(dst)
    return files


if __name__ == "__main__":
    start_str, end_str, dst_dir = sys.argv[1], sys.argv[2], sys.argv[3]
    download(start_str, end_str, dst_dir)
