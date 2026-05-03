# SNODAS SWE Percent-of-Average Viewer

## What This Does

Generates a **zoomable, interactive web map** showing gridded Snow Water Equivalent (SWE) 
as a **percent of historical average** for any area in the western US, at 1 km resolution, 
updated daily during the snowmelt season (April–August by default). This fills the gap 
left by SNOTEL (point data at limited elevations) by using NOAA's SNODAS modeled data 
across ALL elevations.

The core question this answers: **"What is the snowpack doing above 5,000 feet where 
there are no SNOTEL stations?"** — expressed as percent of normal so you can compare 
to your mental model from past years.

## Architecture

```
1. DOWNLOAD:  Daily SNODAS SWE grids from NSIDC (1 km, CONUS)
2. STORE:     GeoTIFF archive organized by date
3. CLIMATOLOGY: Compute day-of-year average SWE per grid cell (2004-present)
4. DAILY:     Divide today's SWE by climatology → percent-of-average grid
5. SERVE:     Tile the result and display on a Leaflet web map
```

## Data Source

**SNODAS** (Snow Data Assimilation System) from NOAA/NOHRSC
- ~1 km spatial resolution (30 arc-seconds)
- Daily updates
- CONUS coverage (masked version)
- Archive starts October 2003
- Free, public domain (no restrictions on use)
- FTP: https://noaadata.apps.nsidc.org/DATASETS/NOAA/G02158/masked/

### SNODAS SWE File Format Details
- **Format:** Headerless flat binary, 16-bit signed integer, big-endian
- **Grid dimensions:** 6935 columns × 3351 rows
- **Scale factor:** Values in file ÷ 1000 = meters of SWE
- **Spatial extent (masked):**
  - After Oct 1, 2013: (-130.516667, 24.0999167) to (-62.2499167, 58.2329167)
  - Before Oct 1, 2013: (-130.517083, 24.0995833) to (-62.2504167, 58.2329167)
- **Projection:** Geographic (lat/lon), WGS84 datum
- **No-data:** Typically -9999 in raw file
- **File naming pattern in tar:**  
  `us_ssmv11034tS__T0001TTNATS2026030105HP001.dat.gz` (SWE product code = 1034)
  The `1034` in the filename identifies the SWE product (vs 1036 for snow depth, etc.)

## Quick Start

Run the full pipeline from scratch with one command:

```bash
./run.sh
```

This downloads the historical archive (several hours on first run), builds the climatology, fetches the latest data, generates tiles, and starts the web viewer at http://localhost:8080. Progress is saved — you can Ctrl+C and resume.

For subsequent daily updates:
```bash
python scripts/download_snodas.py
python scripts/compute_daily_pct.py
```

---

## Setup

### Requirements
- Python 3.9+
- Disk space: ~40-50 GB for PNW regional clip; ~500 GB for full CONUS archive
- A server or VM with cron capability for daily updates

### Install
```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Configuration
Edit `config.py` to set:
- `DATA_DIR`: Where to store raw and processed SNODAS files
- `REGION_BOUNDS`: Optional geographic clip (default: Pacific Northwest)
- `SEASON_MONTHS`: Which months to process (default: `[4, 5, 6, 7, 8]` = April–August)
- `CLIMATOLOGY_START_YEAR` / `CLIMATOLOGY_END_YEAR`: Reference period
- `TILE_DIR`: Where to write map tiles

## Usage

### Step 1: Backfill Historical Data
Downloads SNODAS SWE grids for all season months (April–August by default) from 2004 to
present. This is the slow part — expect it to take several hours on first run.
```bash
python scripts/download_snodas.py --backfill --start-year 2004
```

### Step 2: Build Climatology
Computes average SWE for each grid cell for each day of the year.
```bash
python scripts/build_climatology.py
```

### Step 3: Compute Today's Percent of Average and Generate Tiles
Tile generation is included by default. Use `--skip-tiles` if you only want the GeoTIFF.
```bash
python scripts/compute_daily_pct.py
```

### Step 4: Run the Web Viewer
```bash
python webapp/app.py
```
Then open http://localhost:8080 in your browser.

### Automate with Cron
```cron
# Download new SNODAS data daily at 8am (data usually available by ~6am EST)
# Scripts skip automatically outside the configured SEASON_MONTHS (default: April–August)
0 8 * * * cd /path/to/snodas-pct-normal && python scripts/download_snodas.py

# Recompute percent-of-average and tiles (tile generation is built into compute_daily_pct.py)
30 8 * * * cd /path/to/snodas-pct-normal && python scripts/compute_daily_pct.py
```

## Output

The web map displays:
- **Color scale:** 11-step ramp from dark red (0%) through green (90–110%) to purple (≥200%)
- **Click any point** to see: current SWE (inches), historical average SWE for that date (inches), and percent of average
- **Base layer toggle** between OpenTopoMap, OpenStreetMap, and Esri satellite imagery
- **Opacity slider** to adjust the SWE overlay transparency

## Key Design Decisions

1. **Percent of average, not percent of median.** SNODAS only goes back to 2004 (~22 years),
   which is a marginal sample size for computing a robust median. Average is more stable with
   this record length. If the archive grows, switching to median would be better (it's what 
   NRCS uses for SNOTEL, which has 30+ year records).

2. **Regional clipping.** Processing the full CONUS grid daily is expensive. The default config
   clips to the Pacific Northwest (WA/OR/ID plus adjacent areas) to keep it manageable. 
   Adjust `REGION_BOUNDS` in config.py for other areas.

3. **Day-of-year smoothing.** The climatology uses a 5-day centered window for each DOY to 
   smooth out noise from the relatively short (2004-present) record. This prevents a single 
   anomalous historical storm from distorting the "average" for that specific calendar date.

4. **Tile generation.** Rather than serving raw rasters through a WMS, we pre-render PNG tiles 
   at zoom levels 5-12 for fast web display. This trades disk space for speed. For a PNW 
   regional clip at zoom 5-12, expect ~2-4 GB of tiles.

## Limitations

- SNODAS is **modeled output**, not direct measurement. It assimilates SNOTEL and satellite 
  data but has known biases, especially in alpine terrain above treeline where wind 
  redistribution of snow is poorly captured.
- The climatology baseline (2004-present) is shorter than the SNOTEL 30-year normals, so 
  the "average" is less stable — especially for individual grid cells.
- SNODAS can have erroneously high SWE values at some high-elevation cells (known issue 
  documented by NSIDC). The processing scripts include a filter to cap unrealistic values.
- Updates depend on NOHRSC processing; occasionally a day may be missing.

## Credits

- SNODAS data: NOAA/NOHRSC via NSIDC
- Inspired by Colorado's CDSS SNODAS tool (https://snodas.cdss.state.co.us/)
- Built because nobody made this for Washington and Idaho yet.
