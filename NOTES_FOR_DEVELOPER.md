# Developer Notes

## Things That Will Bite You

### SNODAS File Format
- **No header.** The .dat files are raw binary. You must know the dimensions (6935x3351) 
  and data type (big-endian int16) or you get garbage.
- **Product codes in filenames:** SWE = 1034, Snow Depth = 1036. The tar contains multiple 
  products; you need to grep for the right one.
- **HP001 vs HP000:** HP001 = data file, HP000 = header file (text). You want HP001.
- **The grid has a slight spatial shift on Oct 1, 2013.** The code handles this but if 
  you're comparing pre/post-2013 data at pixel level, be aware.
- **Known bad values:** Some high-elevation cells report SWE > 32 meters (clearly wrong). 
  The download script filters these but check your outputs.
- **Missing days:** Not every day has a file. The climatology builder handles gaps but 
  your cron should be tolerant of occasional download failures.

All of the above are handled in the current codebase.

### Disk Space
- Each raw SNODAS tar: ~10-20 MB
- Each processed GeoTIFF (full CONUS): ~25 MB
- Each processed GeoTIFF (PNW clip): ~3-5 MB
- Full archive 2004-present (PNW clip): ~30 GB
- Climatology (366 DOY files, PNW): ~1.5 GB
- Tiles (zoom 5-12, PNW): ~2-4 GB
- **Total for PNW deployment: ~40-50 GB**

### Performance
- Tile generation in `compute_daily_pct.py` calls `gdal2tiles.py` directly — this is
  fast enough for daily runs.
- The climatology build reads every historical GeoTIFF into memory per DOY. With 20+ 
  years × 5-day window = ~100 grids per DOY. For PNW clip this is fine; for full CONUS 
  you'll need chunked processing or dask.
- If pre-rendered tiles become a storage or latency problem, migrate to: 
  **TiTiler** serving tiles on-the-fly from Cloud-Optimized GeoTIFFs (COGs). See 
  Cloud-Native section below.

---

## Enhancement Ideas

### High-Priority

1. **Time slider.** ✏️ *Frontend-only change — no pipeline work needed.*  
   The tile directory is already date-organized (`tiles/swe_pct/YYYYMMDD/`). Add a 
   date-picker or range slider to `index.html` that rewrites the tile URL pattern. 
   The Flask app already serves tiles by date.

2. **SNOTEL overlay.** ✏️ *Small backend + ~30 lines of Leaflet JS.*  
   Plot SNOTEL stations on the map with their percent-of-median values so users can 
   cross-reference point measurements against the gridded model. NRCS provides a 
   JSON/CSV feed at `https://wcc.sc.egov.usda.gov/reportGenerator/`. Add a 
   `/api/snotel` Flask endpoint that proxies/caches the feed, then render markers 
   in JS with the same color scale as the raster.

3. **Elevation band display.** *Requires DEM + HUC8 boundaries.*  
   When the user clicks a watershed (HUC8), show a chart of SWE-vs-elevation for 
   that basin compared to the historical average at each elevation band (the 
   Hypsometric-SWE concept). Needs SRTM or NED 30m DEM and HUC8 boundary polygons.

4. **Seasonal animation.** *Frontend-only — data exists.*  
   "Play" button that animates SWE percent-of-average from Oct 1 through present, 
   one frame per week. Same tile URL rewriting as the time slider; add a JS 
   setInterval loop.

### Medium-Priority

5. **Basin-average summaries.** Overlay HUC6/HUC8 polygons showing the average 
   percent-of-normal for each basin (computed from the gridded data, not from SNOTEL).

6. **Snow line elevation.** For each basin, estimate the current elevation where snow 
   cover begins (where SWE transitions from 0 to >0). Compare to historical average 
   snow line for this date. Directly answers "how high do you have to go to find snow."

7. **Streamflow forecast overlay.** Pull NWRFC seasonal forecasts and overlay them on 
   the same map so users can see snowpack AND predicted runoff for each river.

### Nice-to-Have

8. **Percent of median** instead of percent of average. Premature until ~2030 when 
   the SNODAS record reaches 25-30 years minimum for median stability.

9. **Comparison mode.** Side-by-side view of this year vs a user-selected historical 
    year. Useful for "this looks like 2015" pattern-matching.

10. **Mobile-friendly.** The Leaflet map works on phones but the info panel and legend 
    need responsive CSS.

11. **Alert system.** Email notification when a user-defined basin crosses a threshold 
    (e.g., "notify me when Skykomish headwaters SWE drops below 70% of average").

---

## What Is Not Built Yet

- No unit or integration tests. The climatology builder and percent computation have 
  non-trivial edge cases (shape normalization, NaN handling, low-climatology masking) 
  that warrant at least smoke tests with synthetic data.
- None of the 12 enhancement ideas above have been implemented.
- Cloud-native architecture (see below) not yet adopted.

---

## Data Sources to Integrate

- **SNODAS daily grids:** https://noaadata.apps.nsidc.org/DATASETS/NOAA/G02158/masked/
- **SNOTEL current conditions:** https://wcc.sc.egov.usda.gov/reportGenerator/
- **HUC watershed boundaries:** https://www.usgs.gov/national-hydrography/watershed-boundary-dataset
- **NED/SRTM DEM:** https://www.usgs.gov/3d-elevation-program
- **NWRFC forecasts:** https://www.nwrfc.noaa.gov/water_supply/ws_report.cgi
- **USGS streamflow gauges:** https://waterdata.usgs.gov/nwis/

---

## Alternative Architecture: Cloud-Native

If pre-rendered tile storage becomes a problem, skip it entirely:

1. Store processed GeoTIFFs as **Cloud-Optimized GeoTIFFs (COGs)** in an S3 bucket 
   or Google Cloud Storage
2. Use **TiTiler** (https://github.com/developmentseed/titiler) to serve tiles 
   directly from the COGs — no pre-rendering, no tile storage
3. Host the Leaflet frontend on any static hosting (GitHub Pages, Netlify, etc.)
4. Use a GitHub Actions workflow or Cloud Function for the daily download + 
   climatology computation

Scales better and costs very little for modest traffic (~$5-20/month).