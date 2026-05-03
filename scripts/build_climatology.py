#!/usr/bin/env python3
"""
build_climatology.py - Compute day-of-year average SWE from historical SNODAS GeoTIFFs.

For each day of the year (1-366), computes the mean SWE at each grid cell across
all available years. Uses a configurable smoothing window to reduce noise from the
relatively short SNODAS record.

Output: 366 GeoTIFF files (one per DOY) in the climatology directory, each containing
the average SWE in meters for that calendar day.

Usage:
    python scripts/build_climatology.py
    python scripts/build_climatology.py --start-year 2005 --end-year 2024
"""

import argparse
import glob
import logging
import os
import sys
from datetime import date, datetime, timedelta

import numpy as np
import rasterio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def get_available_dates() -> list[date]:
    """Scan the GeoTIFF directory and return sorted list of available dates."""
    pattern = os.path.join(config.GEOTIFF_DIR, "swe_*.tif")
    files = glob.glob(pattern)
    dates = []
    for f in files:
        basename = os.path.basename(f)
        # swe_YYYYMMDD.tif
        datestr = basename.replace("swe_", "").replace(".tif", "")
        try:
            dt = datetime.strptime(datestr, "%Y%m%d").date()
            dates.append(dt)
        except ValueError:
            continue
    return sorted(dates)


def get_reference_profile() -> dict:
    """Read the rasterio profile from a post-Oct-2013 GeoTIFF to use as reference.

    Post-2013 files are 1768×1020; pre-2013 are 1767×1021. We use a post-2013
    file as canonical so all grids are normalized to that shape.
    """
    pattern = os.path.join(config.GEOTIFF_DIR, "swe_*.tif")
    files = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError("No GeoTIFF files found. Run download_snodas.py first.")
    # Pick the most recent file, which is guaranteed to be post-2013
    with rasterio.open(files[-1]) as src:
        profile = src.profile.copy()
    return profile


def normalize_grid(data: np.ndarray, target_h: int, target_w: int) -> np.ndarray:
    """Crop or pad a grid to exactly (target_h, target_w).

    Handles the 1-pixel shape difference between pre-2013 (1767×1021)
    and post-2013 (1768×1020) SNODAS masked product grids.
    """
    # Crop excess rows/cols from the south/east edge
    data = data[:target_h, :target_w]
    # Pad if still short (fill with nodata so nanmean ignores these cells)
    if data.shape != (target_h, target_w):
        padded = np.full((target_h, target_w), np.nan, dtype=np.float32)
        padded[:data.shape[0], :data.shape[1]] = data
        return padded
    return data


def read_swe_grid(dt: date, target_h: int = None, target_w: int = None) -> np.ndarray | None:
    """Read a daily SWE GeoTIFF and return as numpy array (NaN for nodata)."""
    path = os.path.join(config.GEOTIFF_DIR, f"swe_{dt.strftime('%Y%m%d')}.tif")
    if not os.path.exists(path):
        return None
    with rasterio.open(path) as src:
        data = src.read(1).astype(np.float32)
    # Replace nodata sentinel with NaN before stacking
    data[data == -9999.0] = np.nan
    if target_h is not None and target_w is not None:
        data = normalize_grid(data, target_h, target_w)
    return data


def build_climatology(start_year: int, end_year: int):
    """
    Build day-of-year average SWE grids.
    
    For each DOY (1-366):
      1. Collect grids from all years within the DOY smoothing window
      2. Compute nanmean across years
      3. Write as GeoTIFF
    """
    os.makedirs(config.CLIM_DIR, exist_ok=True)
    
    available_dates = get_available_dates()
    available_dates = [d for d in available_dates
                       if start_year <= d.year <= end_year
                       and d.month in config.SEASON_MONTHS]
    
    if not available_dates:
        log.error(f"No data found for {start_year}-{end_year}")
        return
    
    log.info(f"Building climatology from {len(available_dates)} daily grids "
             f"({start_year}-{end_year})")
    
    # Get reference profile for output files
    ref_profile = get_reference_profile()
    ref_profile.update(dtype="float32", nodata=-9999.0)
    
    # Get grid dimensions from reference
    height = ref_profile["height"]
    width = ref_profile["width"]
    
    # Organize dates by day-of-year
    half_window = config.DOY_SMOOTHING_WINDOW // 2
    
    # Index all available dates by DOY for fast lookup
    dates_by_doy = {}
    for dt in available_dates:
        doy = dt.timetuple().tm_yday
        dates_by_doy.setdefault(doy, []).append(dt)
    
    # Pre-compute which DOYs fall within SEASON_MONTHS (use a non-leap reference year)
    ref_year = 2001
    season_doys = {
        (date(ref_year, 1, 1) + timedelta(days=d - 1)).timetuple().tm_yday
        for d in range(1, 366)
        if (date(ref_year, 1, 1) + timedelta(days=d - 1)).month in config.SEASON_MONTHS
    }

    for target_doy in range(1, 367):
        if target_doy not in season_doys:
            continue
        log.info(f"Processing DOY {target_doy}/366")
        
        # Collect all dates within the smoothing window across all years
        candidate_doys = []
        for offset in range(-half_window, half_window + 1):
            adj_doy = target_doy + offset
            # Handle year wraparound
            if adj_doy < 1:
                adj_doy += 365
            elif adj_doy > 366:
                adj_doy -= 366
            candidate_doys.append(adj_doy)
        
        # Gather all grids for these DOYs, normalizing to reference shape
        grids = []
        for doy in candidate_doys:
            if doy in dates_by_doy:
                for dt in dates_by_doy[doy]:
                    data = read_swe_grid(dt, target_h=height, target_w=width)
                    if data is not None:
                        grids.append(data)
        
        if len(grids) < config.MIN_YEARS_FOR_CLIMATOLOGY:
            log.warning(f"DOY {target_doy}: only {len(grids)} grids available "
                       f"(need {config.MIN_YEARS_FOR_CLIMATOLOGY}), writing nodata")
            avg_grid = np.full((height, width), -9999.0, dtype=np.float32)
        else:
            # Stack and compute mean, ignoring NaN
            stack = np.stack(grids, axis=0)

            # Count valid (non-NaN) values per cell
            valid_count = np.sum(~np.isnan(stack), axis=0)

            # Compute mean
            with np.errstate(all="ignore"):
                avg_grid = np.nanmean(stack, axis=0).astype(np.float32)

            # Mask cells with insufficient valid years
            avg_grid[valid_count < config.MIN_YEARS_FOR_CLIMATOLOGY] = np.nan
            avg_grid[np.isnan(avg_grid)] = -9999.0

        # Write climatology GeoTIFF
        clim_path = os.path.join(config.CLIM_DIR, f"swe_clim_doy{target_doy:03d}.tif")
        with rasterio.open(clim_path, "w", **ref_profile) as dst:
            dst.write(avg_grid, 1)
            dst.update_tags(
                doy=str(target_doy),
                variable="SWE_climatology",
                units="meters",
                period=f"{start_year}-{end_year}",
                smoothing_window=str(config.DOY_SMOOTHING_WINDOW),
            )
    
    log.info("Climatology build complete.")


def main():
    parser = argparse.ArgumentParser(description="Build SNODAS SWE day-of-year climatology")
    parser.add_argument("--start-year", type=int, 
                       default=config.CLIMATOLOGY_START_YEAR)
    parser.add_argument("--end-year", type=int,
                       default=config.CLIMATOLOGY_END_YEAR or date.today().year - 1)
    args = parser.parse_args()
    
    build_climatology(args.start_year, args.end_year)


if __name__ == "__main__":
    main()
