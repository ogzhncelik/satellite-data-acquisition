# satellite-data-acquisition

Scripts for acquiring Sentinel-2 satellite imagery and turning raw scenes into ready-to-use images.

## Scripts

| Script | What it does |
|---|---|
| `sentinel2_data_download_copernicus.py` | Searches the Copernicus Data Space Ecosystem catalogue for Sentinel-2 Level-2A scenes by tile ID, years, months and maximum cloud cover, then downloads them. Handles pagination, automatic token refresh, skips files that already exist and downloads to a temporary file first so interrupted downloads never leave broken zips. |
| `sentinel2_rgb_composite.py` | Takes downloaded `.SAFE.zip` scenes, sorts them by acquisition date into numbered folders, extracts only the 10 m bands and metadata (instead of the full ~1 GB archive), aligns B04/B03/B02 and writes a contrast-stretched 8-bit natural-color RGB GeoTIFF for each scene. |

## Installation

```bash
pip install -r requirements.txt
```

GDAL can be hard to install with pip on Windows. Using conda is recommended:

```bash
conda install -c conda-forge gdal rasterio
```

## Usage

1. Create a free account at [Copernicus Data Space](https://dataspace.copernicus.eu/).
2. Enter your username and password in `sentinel2_data_download_copernicus.py`. **Never commit your credentials.**
3. Set the tile ID, years, months and output folder, then run:

```bash
python sentinel2_data_download_copernicus.py
python sentinel2_rgb_composite.py
```

## License

MIT
