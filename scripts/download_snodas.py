#!/usr/bin/env python3
"""
download_snodas.py - Download and process SNODAS SWE data from NSIDC.

Downloads daily SNODAS tar files, extracts the SWE product, converts from 
headerless binary to GeoTIFF, and optionally clips to a regional extent.

Usage:
    # Download today's data:
    python scripts/download_snodas.py

    # Backfill all historical data:
    python scripts/download_snodas.py --backfill --start-year 2004

    # Download a specific date:
    python scripts/download_snodas.py --date 2026-03-01
"""

import argparse
import gzip
import logging
import os
import struct
import sys
import tarfile
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta

import numpy as np
import requests
import rasterio
from rasterio.transform import from_bounds
from rasterio.windows import from_bounds as window_from_bounds

# Add parent dir to path for config import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)


def ensure_dirs():
    """Create data directories if they don't exist."""
    for d in [config.RAW_DIR, config.EXTRACTED_DIR, config.GEOTIFF_DIR]:
        os.makedirs(d, exist_ok=True)


def snodas_url_for_date(dt: date) -> str:
    """
    Construct the NSIDC URL for a SNODAS daily tar file.
    
    URL pattern:
    https://noaadata.apps.nsidc.org/DATASETS/NOAA/G02158/masked/YYYY/MM_Mon/
        SNODAS_YYYYMMDD.tar
    
    Note: The month directory format is like '01_Jan', '02_Feb', etc.
    """
    month_names = [
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
    ]
    month_dir = f"{dt.month:02d}_{month_names[dt.month - 1]}"
    filename = f"SNODAS_{dt.strftime('%Y%m%d')}.tar"
    return f"{config.SNODAS_BASE_URL}/{dt.year}/{month_dir}/{filename}"


def download_file(url: str, dest_path: str) -> bool:
    """Download a file from URL to dest_path. Returns True if successful."""
    try:
        log.info(f"Downloading {url}")
        resp = requests.get(url, stream=True, timeout=120)
        resp.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
        return True
    except requests.RequestException as e:
        log.warning(f"Download failed for {url}: {e}")
        return False


def find_swe_file_in_tar(tar_path: str) -> str | None:
    """
    Find the SWE .dat.gz file inside a SNODAS tar archive.
    
    The SWE product is identified by product code 1034 in the filename.
    We want the file matching pattern: *ssmv11034tS__T0001TTNATS*HP001.dat.gz
    
    The 'HP001' suffix distinguishes it from the header file (HP000).
    """
    with tarfile.open(tar_path, "r") as tar:
        for member in tar.getmembers():
            name = member.name
            # Product code 1034 = SWE, HP001 = data file (not header)
            if config.SWE_PRODUCT_CODE in name and "HP001" in name and name.endswith(".dat.gz"):
                return name
    return None


def extract_swe_binary(tar_path: str, swe_member_name: str, output_path: str):
    """Extract and decompress the SWE .dat.gz file from the tar archive."""
    with tarfile.open(tar_path, "r") as tar:
        member = tar.getmember(swe_member_name)
        gz_fileobj = tar.extractfile(member)
        with gzip.open(gz_fileobj, "rb") as gz:
            data = gz.read()
    with open(output_path, "wb") as f:
        f.write(data)
    return output_path


def binary_to_geotiff(binary_path: str, geotiff_path: str, dt: date):
    """
    Convert SNODAS headerless binary SWE to GeoTIFF.
    
    The raw binary is:
    - 16-bit signed integer, big-endian
    - 6935 cols x 3351 rows
    - Values: SWE in integer units (divide by 1000 for meters)
    - No-data: -9999
    
    Output GeoTIFF:
    - Float32, SWE in meters
    - Properly georeferenced (WGS84)
    - Optionally clipped to REGION_BOUNDS
    """
    # Read raw binary
    raw = np.fromfile(binary_path, dtype=">i2")  # big-endian int16
    
    expected_size = config.SNODAS_COLS * config.SNODAS_ROWS
    if raw.size != expected_size:
        raise ValueError(
            f"Unexpected file size: got {raw.size} values, "
            f"expected {expected_size} ({config.SNODAS_COLS}x{config.SNODAS_ROWS})"
        )
    
    # Reshape to grid (row-major, top-left origin = NW corner)
    grid = raw.reshape((config.SNODAS_ROWS, config.SNODAS_COLS)).astype(np.float32)
    
    # Convert to meters SWE
    grid[grid == config.SNODAS_NODATA] = np.nan
    grid = grid / config.SWE_SCALE_FACTOR
    
    # Filter unrealistic values (known SNODAS issue at some high-elevation cells)
    grid[grid > config.MAX_CREDIBLE_SWE_M] = np.nan
    grid[grid < 0] = np.nan
    
    # Use post-2013 coordinates (adjust if processing pre-Oct-2013 data)
    if dt >= date(2013, 10, 1):
        xmin, ymin = config.SNODAS_XMIN, config.SNODAS_YMIN
        xmax, ymax = config.SNODAS_XMAX, config.SNODAS_YMAX
    else:
        # Pre-Oct 2013 masked product had a very slight grid offset
        # Source: header from SNODAS_20100415.tar
        xmin, ymin = -124.733750, 24.949583
        xmax, ymax =  -66.942083, 52.874583
    
    transform = from_bounds(xmin, ymin, xmax, ymax, config.SNODAS_COLS, config.SNODAS_ROWS)
    
    # Determine output path and whether to clip
    if config.REGION_BOUNDS:
        # Clip to regional extent
        rw, rs, re, rn = config.REGION_BOUNDS
        
        # Calculate pixel coordinates for the clip window
        # Transform maps pixel coords to geographic coords; we need the inverse
        col_start = max(0, int((rw - xmin) / (xmax - xmin) * config.SNODAS_COLS))
        col_end = min(config.SNODAS_COLS, int((re - xmin) / (xmax - xmin) * config.SNODAS_COLS))
        row_start = max(0, int((ymax - rn) / (ymax - ymin) * config.SNODAS_ROWS))
        row_end = min(config.SNODAS_ROWS, int((ymax - rs) / (ymax - ymin) * config.SNODAS_ROWS))
        
        grid = grid[row_start:row_end, col_start:col_end]
        clip_height, clip_width = grid.shape
        
        # Recompute transform for clipped extent
        clip_xmin = xmin + col_start * (xmax - xmin) / config.SNODAS_COLS
        clip_xmax = xmin + col_end * (xmax - xmin) / config.SNODAS_COLS
        clip_ymin = ymax - row_end * (ymax - ymin) / config.SNODAS_ROWS
        clip_ymax = ymax - row_start * (ymax - ymin) / config.SNODAS_ROWS
        
        transform = from_bounds(clip_xmin, clip_ymin, clip_xmax, clip_ymax, clip_width, clip_height)
        out_height, out_width = clip_height, clip_width
    else:
        out_height, out_width = config.SNODAS_ROWS, config.SNODAS_COLS
    
    # Write GeoTIFF
    profile = {
        "driver": "GTiff",
        "dtype": "float32",
        "width": out_width,
        "height": out_height,
        "count": 1,
        "crs": "EPSG:4326",
        "transform": transform,
        "nodata": -9999.0,
        "compress": "deflate",
        "predictor": 2,
        "tiled": True,
        "blockxsize": 256,
        "blockysize": 256,
    }

    grid[np.isnan(grid)] = -9999.0

    with rasterio.open(geotiff_path, "w", **profile) as dst:
        dst.write(grid, 1)
        dst.update_tags(
            date=dt.isoformat(),
            variable="SWE",
            units="meters",
            source="NOAA/NOHRSC SNODAS",
        )
    
    log.info(f"Wrote GeoTIFF: {geotiff_path} ({out_width}x{out_height})")


def process_date(dt: date, force: bool = False) -> bool:
    """
    Full pipeline for a single date: download, extract, convert to GeoTIFF.
    Returns True if successful, False otherwise.
    """
    # Check if already processed
    geotiff_path = os.path.join(config.GEOTIFF_DIR, f"swe_{dt.strftime('%Y%m%d')}.tif")
    if os.path.exists(geotiff_path) and not force:
        log.debug(f"Already processed: {dt}")
        return True
    
    # Download
    url = snodas_url_for_date(dt)
    tar_path = os.path.join(config.RAW_DIR, f"SNODAS_{dt.strftime('%Y%m%d')}.tar")
    
    if not os.path.exists(tar_path):
        if not download_file(url, tar_path):
            return False
    
    # Find SWE file in tar
    swe_member = find_swe_file_in_tar(tar_path)
    if swe_member is None:
        log.error(f"Could not find SWE product (code {config.SWE_PRODUCT_CODE}) in {tar_path}")
        return False
    
    # Extract to temp file
    with tempfile.NamedTemporaryFile(suffix=".dat", delete=False) as tmp:
        tmp_path = tmp.name
    
    try:
        extract_swe_binary(tar_path, swe_member, tmp_path)
        binary_to_geotiff(tmp_path, geotiff_path, dt)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
    
    # Optionally delete the tar to save space (keep GeoTIFF)
    # Uncomment next line if disk space is tight:
    # os.unlink(tar_path)
    
    return True


def main():
    parser = argparse.ArgumentParser(description="Download and process SNODAS SWE data")
    parser.add_argument("--date", type=str, help="Process specific date (YYYY-MM-DD)")
    parser.add_argument("--backfill", action="store_true", help="Download full historical archive")
    parser.add_argument("--start-year", type=int, default=2004, help="Start year for backfill")
    parser.add_argument("--end-date", type=str, help="End date for backfill (default: yesterday)")
    parser.add_argument("--force", action="store_true", help="Reprocess even if output exists")
    parser.add_argument("--workers", type=int, default=4, help="Parallel download workers for backfill (default: 4)")
    args = parser.parse_args()
    
    ensure_dirs()
    
    if args.date:
        # Process a specific date
        dt = datetime.strptime(args.date, "%Y-%m-%d").date()
        success = process_date(dt, force=args.force)
        sys.exit(0 if success else 1)
    
    elif args.backfill:
        # Process full historical range
        start = date(args.start_year, 10, 1)  # Water year start
        end = datetime.strptime(args.end_date, "%Y-%m-%d").date() if args.end_date else date.today() - timedelta(days=1)

        dates = []
        current = start
        while current <= end:
            if current.month in config.SEASON_MONTHS:
                dates.append(current)
            current += timedelta(days=1)

        log.info(f"Backfilling {len(dates)} dates with {args.workers} workers")
        success_count = 0
        fail_count = 0

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(process_date, dt, args.force): dt for dt in dates}
            for future in as_completed(futures):
                if future.result():
                    success_count += 1
                else:
                    fail_count += 1

        log.info(f"Backfill complete: {success_count} succeeded, {fail_count} failed")
    
    else:
        # Default: process yesterday (today's data may not be available yet)
        dt = date.today() - timedelta(days=1)
        success = process_date(dt, force=args.force)
        
        # Also try today in case it's available
        process_date(date.today(), force=args.force)
        
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
