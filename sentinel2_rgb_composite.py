import os, pyproj
proj_dir = pyproj.datadir.get_data_dir()
os.environ["PROJ_LIB"] = proj_dir
os.environ["PROJ_DATA"] = proj_dir
import rasterio
from rasterio.enums import Resampling, ColorInterp
import glob
from osgeo import gdal
from rasterio.warp import reproject
import numpy as np
import shutil
import re
import zipfile
import traceback
from datetime import datetime
import warnings
warnings.filterwarnings("ignore")
gdal.PushErrorHandler("CPLQuietErrorHandler")
# =====================================================================
# SETTINGS
# =====================================================================
ZIP_SOURCE_DIR  = r"path\to\input"    # folder containing the .SAFE.zip files
OUTPUT_BASE_DIR = r"path\to\output"   # parent folder where the numbered folders will be created
START_NUMBER    = 1                # starting folder number


# =====================================================================
# STEP 1: MOVE ZIP FILES INTO NUMBERED FOLDERS IN DATE ORDER
# =====================================================================

def organize_sentinel_zips(source_dir, output_base, start_num):
    """
    Finds the S2*_MSIL2A_*.SAFE.zip files in source_dir,
    sorts them by date from NEWEST -> OLDEST,
    creates numbered folders starting from start_num and
    moves each zip into its corresponding folder.
    """
    zip_files = glob.glob(os.path.join(source_dir, "S2*_MSIL2A_*.SAFE.zip")) # Example filename: S2A_MSIL2A_20230815T104031_N0509_R008_T31TGL_20230815T123456.SAFE.zip

    if not zip_files:
        print("[Organize] WARNING: No S2*_MSIL2A_*.SAFE.zip files found in the given folder!")
        print(f"           Searched folder: {source_dir}")
        return []

    print(f"[Organize] {len(zip_files)} .SAFE.zip files found.")

    # Extract the date from each zip
    zip_date_pairs = []
    for zf in zip_files:
        basename = os.path.basename(zf)
        match = re.search(r"_MSIL2A_(\d{8}T\d{6})_", basename)
        if match:
            date_str = match.group(1)
            dt = datetime.strptime(date_str, "%Y%m%dT%H%M%S")
            zip_date_pairs.append((zf, dt, basename))
        else:
            print(f"  [Organize] WARNING: Could not parse the date, skipping -> {basename}")

    if not zip_date_pairs:
        print("[Organize] ERROR: No date could be extracted from any file!")
        return []

    # Sort from the newest date to the oldest date (descending)
    zip_date_pairs.sort(key=lambda x: x[1], reverse=True)

    print("\n[Organize] In date order (newest -> oldest):")
    for i, (zf, dt, bn) in enumerate(zip_date_pairs):
        folder_num = start_num + i
        print(f"  {folder_num} <- {bn}  (Date: {dt.strftime('%Y-%m-%d %H:%M:%S')})")

    # Create the folders and move the zips
    created_folders = []
    for i, (zf, dt, bn) in enumerate(zip_date_pairs):
        folder_num = start_num + i
        folder_path = os.path.join(output_base, str(folder_num))
        os.makedirs(folder_path, exist_ok=True)

        dest_path = os.path.join(folder_path, bn)
        if os.path.abspath(zf) != os.path.abspath(dest_path):
            shutil.move(zf, dest_path)
            print(f"  [Moved] {bn} -> {folder_path}")
        else:
            print(f"  [Already in place] {bn} -> {folder_path}")

        created_folders.append(folder_path)

    print(f"\n[Organize] Done! {len(created_folders)} folders created: "
          f"{start_num} - {start_num + len(created_folders) - 1}")

    return created_folders


# =====================================================================
# STEP 2: EXTRACT THE ZIP IN EACH FOLDER
# =====================================================================

def extract_zips_in_folder(folder_path):
    """
    Finds the .SAFE.zip file in the folder and extracts only the R10m bands
    and the MTD_MSIL2A.xml metadata file.
    """
    zip_files = glob.glob(os.path.join(folder_path, "*.SAFE.zip"))
    if not zip_files:
        print(f"  [Extract] No .SAFE.zip found in {folder_path}, skipping.")
        return False

    for zf in zip_files:
        basename = os.path.basename(zf)
        base_name = basename.rsplit(".zip", 1)[0]
        extract_base = os.path.join(folder_path, base_name)
        r10m_dir = os.path.join(extract_base, "R10m")

        print(f"  [Extract] Selectively extracting: {basename} -> {folder_path}")
        try:
            with zipfile.ZipFile(zf, 'r') as z:
                # Find the files in the R10m folder
                r10m_files = [
                    f for f in z.namelist()
                    if "GRANULE/" in f
                    and "/IMG_DATA/R10m/" in f
                    and not f.endswith("/")
                ]

                # Find the MTD_MSIL2A.xml file
                mtd_files = [
                    f for f in z.namelist()
                    if f.endswith("MTD_MSIL2A.xml")
                    and f.count("/") <= 1
                ]

                if not r10m_files:
                    print(f"  [Extract] R10m not found: {zf}")
                    return False

                # Extract the R10m files
                os.makedirs(r10m_dir, exist_ok=True)
                for member in r10m_files:
                    filename = os.path.basename(member)
                    target_path = os.path.join(r10m_dir, filename)
                    with z.open(member) as src, open(target_path, "wb") as dst:
                        dst.write(src.read())

                # Extract the MTD_MSIL2A.xml file
                for member in mtd_files:
                    target_path = os.path.join(extract_base, "MTD_MSIL2A.xml")
                    with z.open(member) as src, open(target_path, "wb") as dst:
                        dst.write(src.read())

                print(f"  [Extract] Extracted successfully: R10m ({len(r10m_files)} files) + MTD_MSIL2A.xml")
        except Exception as e:
            print(f"  [Extract] ERROR: {e}")
            return False

    return True


# =====================================================================
# STEP 3: RUN ALL PROCESSES FOR A SINGLE FOLDER (NDWI + SHP + RGB)
# =====================================================================

def process_single_folder(INPUT_DIR):
    """
    Finds the Sentinel-2 bands in the given folder and
    creates an RGB GeoTIFF.
    """
    print(f"\n{'='*70}")
    print(f"  PROCESSING: {INPUT_DIR}")
    print(f"{'='*70}")

    # === RGB (B04,B03,B02) -> Create a color GeoTIFF ===
    try:
        print("\n[RGB Creation] Scanning the folder for the B04,B03,B02 bands...")

        b2_list = glob.glob(os.path.join(INPUT_DIR, "**", "*B02*10m.jp2"), recursive=True)
        b3_list = glob.glob(os.path.join(INPUT_DIR, "**", "*B03*10m.jp2"), recursive=True)
        b4_list = glob.glob(os.path.join(INPUT_DIR, "**", "*B04*10m.jp2"), recursive=True)

        if b2_list and b3_list and b4_list:
            b2 = b2_list[0]
            b3 = b3_list[0]
            b4 = b4_list[0]

            base_name = os.path.basename(INPUT_DIR)
            output_rgb = os.path.join(INPUT_DIR, f"{base_name}.tif")
            tmp_rgb = os.path.join(INPUT_DIR, f"{base_name}_tmp.tif")

            print("[RGB Creation] Bands found:")
            print("  B02 (Blue): ", b2)
            print("  B03 (Green):", b3)
            print("  B04 (Red):  ", b4)



            with rasterio.open(b4) as src_ref, \
                 rasterio.open(b3) as src_g, \
                 rasterio.open(b2) as src_b:

                ref_profile = src_ref.profile.copy()
                ref_profile.update(
                    driver="GTiff",
                    count=3,
                    compress="LZW",
                    nodata=None,
                    dtype=rasterio.uint8
                )

                R = np.empty((src_ref.height, src_ref.width), dtype=src_ref.dtypes[0])
                G = np.empty_like(R, dtype=src_g.dtypes[0])
                B = np.empty_like(R, dtype=src_b.dtypes[0])

                R[:, :] = src_ref.read(1)

                reproject(
                    source=rasterio.band(src_g, 1),
                    destination=G,
                    src_transform   = src_g.transform,
                    src_crs         = src_g.crs,
                    dst_transform   = src_ref.transform,
                    dst_crs         = src_ref.crs,
                    resampling      = Resampling.bilinear
                )
                reproject(
                    source=rasterio.band(src_b, 1),
                    destination=B,
                    src_transform   = src_b.transform,
                    src_crs         = src_b.crs,
                    dst_transform   = src_ref.transform,
                    dst_crs         = src_ref.crs,
                    resampling      = Resampling.bilinear
                )

                def to_uint8(band):
                    b = band.astype("float32")
                    vmin = np.nanpercentile(b, 2)
                    vmax = np.nanpercentile(b, 98)
                    scaled = (b - vmin) / (vmax - vmin + 1e-6)
                    scaled = (scaled * 255.0).clip(0, 255).astype("uint8")
                    return scaled

                R8 = to_uint8(R)
                G8 = to_uint8(G)
                B8 = to_uint8(B)

                with rasterio.open(tmp_rgb, "w", **ref_profile) as dst:
                    dst.write(R8, 1)
                    dst.write(G8, 2)
                    dst.write(B8, 3)
                    dst.colorinterp = (ColorInterp.red, ColorInterp.green, ColorInterp.blue)

            translate_opts = gdal.TranslateOptions(creationOptions=["COMPRESS=LZW", "PHOTOMETRIC=RGB"])
            gdal.Translate(destName=output_rgb, srcDS=tmp_rgb, options=translate_opts)
            try:
                os.remove(tmp_rgb)
            except Exception:
                pass

            print("[RGB Creation] Color RGB GeoTIFF written ->", output_rgb)
        else:
            print("[RGB Creation] One of the required bands (B02,B03,B04) was not found.")
    except Exception as e:
        print("[RGB Creation] Error:", e)

    print(f"\n[DONE] {INPUT_DIR}")


# =====================================================================
# MAIN EXECUTION
# =====================================================================

if __name__ == "__main__":

    # --- STEP 1: Move the zips into numbered folders in date order ---
    created_folders = organize_sentinel_zips(ZIP_SOURCE_DIR, OUTPUT_BASE_DIR, START_NUMBER)

    if not created_folders:
        # If no zip was found, scan the existing numbered folders
        print("\n[INFO] No zip found, existing numbered folders will be scanned...")
        all_items = os.listdir(OUTPUT_BASE_DIR)
        created_folders = sorted([
            os.path.join(OUTPUT_BASE_DIR, d)
            for d in all_items
            if os.path.isdir(os.path.join(OUTPUT_BASE_DIR, d)) and d.isdigit()
        ], key=lambda x: int(os.path.basename(x)))

        if not created_folders:
            print("[ERROR] No numbered folders found either, stopping.")
        else:
            print(f"[INFO] {len(created_folders)} numbered folders found.")

    if created_folders:
        # --- STEP 2 & 3: Extract and process the zip in each folder ---
        for folder in created_folders:
            print(f"\n{'=' * 70}")
            print(f"  FOLDER: {folder}")
            print(f"{'=' * 70}")


            # Extract the zip (skips if there is none, but processing continues)

            extracted = extract_zips_in_folder(folder)
            if not extracted:
                print(f"  [INFO] Zip not found or could not be extracted, continuing with the existing files: {folder}")

            # Run all processes (NDWI, SHP, RGB, etc.)
            try:
                process_single_folder(folder)
            except Exception as e:
                print(f"  [ERROR] Error while processing {folder}: {e}")


                traceback.print_exc()
                continue

        print(f"\n{'=' * 70}")
        print(f"  ALL PROCESSES COMPLETED!")
        print(f"  Number of processed folders: {len(created_folders)}")
        print(f"{'=' * 70}")