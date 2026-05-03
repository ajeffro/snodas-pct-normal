"""
Configuration for SNODAS SWE Percent-of-Average tool.
Edit these settings for your deployment.
"""

import os

# =============================================================================
# PATHS
# =============================================================================

# Base directory for all data storage
DATA_DIR = os.environ.get(
    "SNODAS_DATA_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "snodas_data")
)

# Subdirectories (auto-created)
RAW_DIR = os.path.join(DATA_DIR, "raw")           # Downloaded tar.gz files
EXTRACTED_DIR = os.path.join(DATA_DIR, "extracted")  # Extracted binary files
GEOTIFF_DIR = os.path.join(DATA_DIR, "geotiff")     # Processed GeoTIFFs (daily SWE)
CLIM_DIR = os.path.join(DATA_DIR, "climatology")    # Day-of-year average grids
PCT_DIR = os.path.join(DATA_DIR, "pct_of_avg")      # Daily percent-of-average grids
TILE_DIR = os.path.join(DATA_DIR, "tiles")           # Pre-rendered map tiles

# =============================================================================
# SNODAS DATA SOURCE
# =============================================================================

# NSIDC HTTPS data access (masked = clipped to CONUS)
SNODAS_BASE_URL = "https://noaadata.apps.nsidc.org/NOAA/G02158/masked"

# SNODAS grid dimensions (CONUS masked product)
SNODAS_COLS = 6935
SNODAS_ROWS = 3351

# Spatial extent — post-Oct 2013 masked CONUS product
# Source: X/Y-axis coordinates from the .txt.gz header inside each SNODAS tar file
SNODAS_XMIN = -124.733333
SNODAS_XMAX =  -66.941667
SNODAS_YMIN =   24.950000
SNODAS_YMAX =   52.875000

# SWE product code in SNODAS filenames
SWE_PRODUCT_CODE = "1034"

# Scale factor: raw integer values / 1000 = meters SWE
SWE_SCALE_FACTOR = 1000.0

# No-data value in raw files
SNODAS_NODATA = -9999

# Maximum credible SWE in meters (filter for known SNODAS high-value errors)
# 10 meters = ~394 inches, well above any real-world value
MAX_CREDIBLE_SWE_M = 10.0

# =============================================================================
# REGIONAL CLIPPING (optional, saves disk space and processing time)
# =============================================================================

# Set to None to process full CONUS, or define bounds as (west, south, east, north)
# Default: Pacific Northwest (WA, OR, ID and surrounding area)
REGION_BOUNDS = (-126.0, 41.5, -110.0, 50.0)

# Human-readable name for the region (used in titles)
REGION_NAME = "Pacific Northwest"

# =============================================================================
# SEASON SETTINGS
# =============================================================================

# Months to download, process, and include in climatology (1=Jan, 12=Dec)
SEASON_MONTHS = [4, 5, 6, 7, 8]  # April through August

# =============================================================================
# CLIMATOLOGY SETTINGS
# =============================================================================

# Start/end years for computing the historical average
CLIMATOLOGY_START_YEAR = 2004
CLIMATOLOGY_END_YEAR = 2025  # Update annually or set to None for "through last complete year"

# Window size for day-of-year smoothing (centered, in days)
# e.g., 5 means DOY average uses DOY-2 through DOY+2
DOY_SMOOTHING_WINDOW = 5

# Minimum number of years with valid data required to compute an average for a cell/DOY
# Cells with fewer valid years get no-data in the climatology
MIN_YEARS_FOR_CLIMATOLOGY = 10

# =============================================================================
# PERCENT-OF-AVERAGE OUTPUT
# =============================================================================

# How to handle cells where the climatology average is zero or near-zero
# (e.g., low-elevation cells that rarely have snow on this date)
# If average SWE < this threshold (meters), mark as no-data in percent output
# This avoids meaningless 9999% values at low elevations
MIN_AVG_SWE_FOR_PCT = 0.005  # 5mm ≈ 0.2 inches

# =============================================================================
# MAP TILE SETTINGS
# =============================================================================

# Zoom levels to pre-render (5 = regional overview, 12 = drainage-level detail)
TILE_MIN_ZOOM = 5
TILE_MAX_ZOOM = 12

# Color scale for percent-of-average (value: hex color)
# Matches conventional snowpack color schemes
PCT_COLOR_SCALE = {
    0:   "#8B0000",   # 0%     - dark red (no snow where there should be)
    25:  "#FF0000",   # 25%    - red
    50:  "#FF6600",   # 50%    - orange
    70:  "#FFCC00",   # 70%    - yellow-orange
    80:  "#FFFF00",   # 80%    - yellow
    90:  "#CCFF66",   # 90%    - yellow-green
    100: "#00CC00",   # 100%   - green (normal)
    110: "#00CCCC",   # 110%   - teal
    120: "#0066FF",   # 120%   - blue
    150: "#0000CC",   # 150%   - dark blue
    200: "#660099",   # 200%+  - purple (exceptional)
}

# =============================================================================
# WEB APP SETTINGS
# =============================================================================

WEBAPP_HOST = "0.0.0.0"
WEBAPP_PORT = 8080
WEBAPP_DEBUG = False

# Default map center and zoom (centered on WA Cascades)
MAP_DEFAULT_CENTER = [47.5, -121.0]
MAP_DEFAULT_ZOOM = 8
