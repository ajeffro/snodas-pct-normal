#!/usr/bin/env python3
"""
app.py - Web app serving the SNODAS SWE percent-of-average map.

A simple Flask app that serves:
  1. A Leaflet-based zoomable map with the percent-of-average tile overlay
  2. A JSON API endpoint for point queries (click a spot, get SWE info)
  3. Pre-rendered PNG tiles from the tile directory

Usage:
    python webapp/app.py
    
    # Production:
    gunicorn -w 4 -b 0.0.0.0:5000 webapp.app:app
"""

import json
import os
import sys
from datetime import date, timedelta

import numpy as np
import rasterio
from flask import Flask, render_template, send_from_directory, jsonify, request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

app = Flask(__name__, template_folder="templates", static_folder="static")


def get_latest_date() -> str:
    """Find the most recent date with processed tiles."""
    latest_link = os.path.join(config.TILE_DIR, "swe_pct", "latest")
    if os.path.islink(latest_link):
        return os.readlink(latest_link)
    
    # Fallback: scan directory
    tile_dir = os.path.join(config.TILE_DIR, "swe_pct")
    if os.path.exists(tile_dir):
        dates = [d for d in os.listdir(tile_dir) 
                 if os.path.isdir(os.path.join(tile_dir, d)) and d.isdigit()]
        if dates:
            return sorted(dates)[-1]
    
    return None


@app.route("/")
def index():
    """Serve the main map page."""
    latest = get_latest_date()
    if latest:
        display_date = f"{latest[:4]}-{latest[4:6]}-{latest[6:]}"
    else:
        display_date = "No data available"
    
    return render_template(
        "index.html",
        center_lat=config.MAP_DEFAULT_CENTER[0],
        center_lon=config.MAP_DEFAULT_CENTER[1],
        default_zoom=config.MAP_DEFAULT_ZOOM,
        data_date=display_date,
        region_name=config.REGION_NAME,
    )


@app.route("/tiles/<date_str>/<int:z>/<int:x>/<int:y>.png")
def serve_tile(date_str, z, x, y):
    """Serve a pre-rendered map tile."""
    if date_str == "latest":
        date_str = get_latest_date()
        if date_str is None:
            return "", 404
    
    tile_dir = os.path.join(config.TILE_DIR, "swe_pct", date_str, str(z), str(x))
    filename = f"{y}.png"
    
    if os.path.exists(os.path.join(tile_dir, filename)):
        return send_from_directory(tile_dir, filename)
    else:
        # Return transparent 1x1 PNG for missing tiles
        return send_from_directory(
            os.path.dirname(os.path.abspath(__file__)), 
            "static/transparent.png"
        )


@app.route("/api/point")
def point_query():
    """
    Query SWE data at a specific lat/lon point.
    
    Returns JSON with:
    - current SWE (inches)
    - average SWE for this DOY (inches)
    - percent of average
    - approximate elevation (from the DEM if available)
    
    Query params: lat, lon, date (optional, default=latest)
    """
    try:
        lat = float(request.args.get("lat"))
        lon = float(request.args.get("lon"))
    except (TypeError, ValueError):
        return jsonify({"error": "lat and lon parameters required"}), 400
    
    date_str = request.args.get("date")
    if not date_str:
        date_str = get_latest_date()
    if not date_str:
        return jsonify({"error": "No data available"}), 404
    
    result = {"lat": lat, "lon": lon, "date": date_str}
    
    # Read percent-of-average
    pct_path = os.path.join(config.PCT_DIR, f"swe_pct_{date_str}.tif")
    if os.path.exists(pct_path):
        val = _sample_raster(pct_path, lon, lat)
        result["pct_of_avg"] = round(val, 1) if val is not None else None
    
    # Read current SWE in inches
    swe_path = os.path.join(config.PCT_DIR, f"swe_inches_{date_str}.tif")
    if os.path.exists(swe_path):
        val = _sample_raster(swe_path, lon, lat)
        result["swe_inches"] = round(val, 1) if val is not None else None
    
    # Read climatological average SWE in inches
    clim_path = os.path.join(config.PCT_DIR, f"clim_inches_{date_str}.tif")
    if os.path.exists(clim_path):
        val = _sample_raster(clim_path, lon, lat)
        result["avg_swe_inches"] = round(val, 1) if val is not None else None
    
    return jsonify(result)


def _sample_raster(raster_path: str, lon: float, lat: float) -> float | None:
    """Sample a GeoTIFF at a geographic point. Returns value or None."""
    try:
        with rasterio.open(raster_path) as src:
            row, col = src.index(lon, lat)
            if 0 <= row < src.height and 0 <= col < src.width:
                val = src.read(1)[row, col]
                nodata = src.nodata
                if np.isnan(val) or (nodata is not None and val == nodata):
                    return None
                return float(val)
    except Exception:
        pass
    return None


if __name__ == "__main__":
    app.run(
        host=config.WEBAPP_HOST,
        port=config.WEBAPP_PORT,
        debug=config.WEBAPP_DEBUG,
    )
