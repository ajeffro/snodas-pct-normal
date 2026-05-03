#!/usr/bin/env python3
"""
compute_daily_pct.py - Compute SWE percent-of-average for a given date.

Divides today's SWE grid by the climatological average for this day-of-year,
producing a percent-of-average GeoTIFF. Then generates PNG map tiles for 
the web viewer.

Usage:
    python scripts/compute_daily_pct.py                    # Yesterday
    python scripts/compute_daily_pct.py --date 2026-03-12  # Specific date
"""

import argparse
import logging
import os
import subprocess
import sys
from datetime import date, datetime, timedelta

import numpy as np
import rasterio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def compute_pct_of_avg(dt: date) -> str | None:
    """
    Compute percent-of-average SWE for a given date.
    
    Returns path to output GeoTIFF, or None if inputs are missing.
    """
    os.makedirs(config.PCT_DIR, exist_ok=True)
    
    # Load today's SWE grid
    swe_path = os.path.join(config.GEOTIFF_DIR, f"swe_{dt.strftime('%Y%m%d')}.tif")
    if not os.path.exists(swe_path):
        log.error(f"No SWE data for {dt}. Run download_snodas.py first.")
        return None
    
    # Load climatology for this day-of-year
    doy = dt.timetuple().tm_yday
    clim_path = os.path.join(config.CLIM_DIR, f"swe_clim_doy{doy:03d}.tif")
    if not os.path.exists(clim_path):
        log.error(f"No climatology for DOY {doy}. Run build_climatology.py first.")
        return None
    
    with rasterio.open(swe_path) as src:
        swe_data = src.read(1).astype(np.float32)
        swe_nodata = src.nodata
        profile = src.profile.copy()

    with rasterio.open(clim_path) as src:
        clim_data = src.read(1).astype(np.float32)
        clim_nodata = src.nodata

    # Convert nodata sentinels to NaN before arithmetic
    if swe_nodata is not None:
        swe_data[swe_data == swe_nodata] = np.nan
    if clim_nodata is not None:
        clim_data[clim_data == clim_nodata] = np.nan

    # Compute percent of average
    with np.errstate(divide="ignore", invalid="ignore"):
        pct = (swe_data / clim_data) * 100.0

    # Handle edge cases:
    # - Where climatology is near-zero: mark as nodata (avoids inf/huge values
    #   at low elevations where snow is rare for this date)
    low_avg_mask = (clim_data < config.MIN_AVG_SWE_FOR_PCT) | np.isnan(clim_data)
    pct[low_avg_mask] = np.nan

    # - Where current SWE is 0 but climatology is non-trivial: that's 0%
    zero_current = swe_data == 0
    nonzero_clim = ~np.isnan(clim_data) & (clim_data >= config.MIN_AVG_SWE_FOR_PCT)
    pct[zero_current & nonzero_clim] = 0.0

    # - Where SWE is nodata (NaN) but clim is valid: mark as nodata
    pct[np.isnan(swe_data) & nonzero_clim] = np.nan
    
    # Cap extreme values for display
    pct = np.clip(pct, 0, 500)
    pct = pct.astype(np.float32)
    pct[np.isnan(pct)] = -9999.0

    # Write output
    output_path = os.path.join(config.PCT_DIR, f"swe_pct_{dt.strftime('%Y%m%d')}.tif")
    profile.update(dtype="float32", nodata=-9999.0)

    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(pct, 1)
        dst.update_tags(
            date=dt.isoformat(),
            doy=str(doy),
            variable="SWE_percent_of_average",
            units="percent",
            source="SNODAS / computed climatology",
        )

    log.info(f"Percent-of-average written: {output_path}")

    # Also write the raw SWE in inches for the popup/click info
    swe_inches_path = os.path.join(config.PCT_DIR, f"swe_inches_{dt.strftime('%Y%m%d')}.tif")
    swe_inches = swe_data * 39.3701  # meters to inches
    swe_inches[np.isnan(swe_inches)] = -9999.0
    with rasterio.open(swe_inches_path, "w", **profile) as dst:
        dst.write(swe_inches, 1)

    clim_inches_path = os.path.join(config.PCT_DIR, f"clim_inches_{dt.strftime('%Y%m%d')}.tif")
    clim_inches = clim_data * 39.3701
    clim_inches[np.isnan(clim_inches)] = -9999.0
    with rasterio.open(clim_inches_path, "w", **profile) as dst:
        dst.write(clim_inches, 1)
    
    return output_path


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def colorize_pct_geotiff(pct_path: str, output_path: str):
    """
    Colorize a float32 percent-of-average GeoTIFF into an RGBA GeoTIFF.

    Reads the source spatial reference directly via rasterio so the output
    has byte-for-byte identical CRS and transform — no gdaldem involved.
    nodata cells become fully transparent (alpha=0).
    """
    breakpoints = sorted(config.PCT_COLOR_SCALE.items())

    with rasterio.open(pct_path) as src:
        pct = src.read(1).astype(np.float32)
        profile = src.profile.copy()
        nodata_val = src.nodata  # -9999.0

    h, w = pct.shape
    r = np.zeros((h, w), dtype=np.uint8)
    g = np.zeros((h, w), dtype=np.uint8)
    b = np.zeros((h, w), dtype=np.uint8)
    a = np.zeros((h, w), dtype=np.uint8)

    valid = pct != nodata_val

    for i in range(len(breakpoints) - 1):
        v0, hex0 = breakpoints[i]
        v1, hex1 = breakpoints[i + 1]
        rgb0 = _hex_to_rgb(hex0)
        rgb1 = _hex_to_rgb(hex1)
        mask = valid & (pct >= v0) & (pct < v1)
        if not np.any(mask):
            continue
        frac = (pct[mask] - v0) / (v1 - v0)
        for arr, c0, c1 in zip([r, g, b], rgb0, rgb1):
            arr[mask] = np.clip(c0 + frac * (c1 - c0), 0, 255).astype(np.uint8)
        a[mask] = 200

    # Cells at or above the last breakpoint get the final color
    v_last, hex_last = breakpoints[-1]
    mask_top = valid & (pct >= v_last)
    if np.any(mask_top):
        rl, gl, bl = _hex_to_rgb(hex_last)
        r[mask_top] = rl
        g[mask_top] = gl
        b[mask_top] = bl
        a[mask_top] = 200

    profile.update(count=4, dtype="uint8", nodata=None)
    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(r, 1)
        dst.write(g, 2)
        dst.write(b, 3)
        dst.write(a, 4)

    log.info(f"Colorized GeoTIFF written: {output_path}")


def generate_tiles(pct_geotiff_path: str, dt: date):
    """
    Generate slippy-map PNG tiles from the percent-of-average GeoTIFF.

    Colorizes the float GeoTIFF with rasterio (preserving CRS/transform exactly),
    then calls gdal2tiles to render TMS-convention PNG tiles.

    Tiles are written to: TILE_DIR/swe_pct/YYYYMMDD/{z}/{x}/{y}.png
    """
    date_str = dt.strftime("%Y%m%d")
    tile_base = os.path.join(config.TILE_DIR, "swe_pct", date_str)
    os.makedirs(tile_base, exist_ok=True)

    colored_path = os.path.join(config.PCT_DIR, f"swe_pct_colored_{date_str}.tif")

    try:
        colorize_pct_geotiff(pct_geotiff_path, colored_path)

        log.info(f"Generating tiles (zoom {config.TILE_MIN_ZOOM}-{config.TILE_MAX_ZOOM})")
        subprocess.run(
            [
                "gdal2tiles.py",
                f"--zoom={config.TILE_MIN_ZOOM}-{config.TILE_MAX_ZOOM}",
                "--resampling=near",
                "--processes=4",
                colored_path,
                tile_base,
            ],
            check=True,
        )
    finally:
        if os.path.exists(colored_path):
            os.unlink(colored_path)

    latest_link = os.path.join(config.TILE_DIR, "swe_pct", "latest")
    if os.path.islink(latest_link):
        os.unlink(latest_link)
    os.symlink(date_str, latest_link)

    log.info(f"Tile generation complete. Latest -> {date_str}")


def main():
    parser = argparse.ArgumentParser(description="Compute SWE percent-of-average and generate tiles")
    parser.add_argument("--date", type=str, help="Date to process (YYYY-MM-DD)")
    parser.add_argument("--skip-tiles", action="store_true", help="Skip tile generation")
    args = parser.parse_args()
    
    if args.date:
        dt = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        dt = date.today() - timedelta(days=1)
    
    pct_path = compute_pct_of_avg(dt)
    if pct_path is None:
        sys.exit(1)
    
    if not args.skip_tiles:
        generate_tiles(pct_path, dt)


if __name__ == "__main__":
    main()
