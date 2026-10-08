import requests
import calendar
import os
import time

# --- 1. USER CREDENTIALS AND FILTERS ---
USERNAME = '' # Your Copernicus Open Access Hub username
PASSWORD = '' # Your Copernicus Open Access Hub password

OUTPUT_DIR = r'path\to\output'

TILE_ID = 'T38SKJ'
YEARS = range(2019, 2025) # Years to search for (inclusive)
TARGET_MONTHS = [4, 5, 7, 8, 10] # Months to search for (1=January, 12=December)

# We search only for Sentinel-2 Level-2A (atmospherically corrected) products
PRODUCT_TYPE = 'MSIL2A' # Product level searched in the file name (e.g. 'MSIL2A' = Level-2A, 'MSIL1C' = Level-1C)
MAX_CLOUD_COVER = 10 # Maximum cloud cover percentage allowed for the images (0-100)


# --- TOKEN MANAGEMENT ---
_token_cache = {'token': None, 'time': 0}
TOKEN_VALIDITY_SECONDS = 540  # 9 minutes (the token is valid for 10 min, safety margin)


def get_token(username, password):
    """Get a token; if the current token is still valid, return it."""
    now = time.time()
    if _token_cache['token'] and (now - _token_cache['time']) < TOKEN_VALIDITY_SECONDS:
        return _token_cache['token']

    print("Logging in and getting a token...")
    token_url = 'https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token'
    data = {'client_id': 'cdse-public', 'username': username, 'password': password, 'grant_type': 'password'}
    response = requests.post(token_url, data=data)
    response.raise_for_status()
    token = response.json()['access_token']

    _token_cache['token'] = token
    _token_cache['time'] = now
    return token


def search_and_download():

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    access_token = get_token(USERNAME, PASSWORD)
    headers = {"Authorization": f"Bearer {access_token}"}

    products_to_download = []

    # --- 2. LOOP OVER YEARS AND MONTHS ---
    for year in YEARS:
        for month in TARGET_MONTHS:
            last_day = calendar.monthrange(year, month)[1]
            start_date = f"{year}-{month:02d}-01T00:00:00.000Z"
            end_date = f"{year}-{month:02d}-{last_day}T23:59:59.999Z"

            print(f"Searching: Year {year}, Month {month}...")

            query = (
                f"contains(Name,'_{TILE_ID}_') and "
                f"contains(Name,'{PRODUCT_TYPE}') and "
                f"ContentDate/Start ge {start_date} and "
                f"ContentDate/Start le {end_date} and "
                f"Attributes/OData.CSC.DoubleAttribute/any(att:att/Name eq 'cloudCover' and att/OData.CSC.DoubleAttribute/Value le {MAX_CLOUD_COVER})"
            )

            # Get all results with pagination
            search_url = f"https://catalogue.dataspace.copernicus.eu/odata/v1/Products?$filter={query}&$top=1000"

            total = 0
            while search_url:
                response = requests.get(search_url, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    results = data.get('value', [])
                    for product in results:
                        products_to_download.append({'id': product['Id'], 'name': product['Name']})
                    total += len(results)

                    # Continue if there is a next page
                    search_url = data.get('@odata.nextLink', None)
                else:
                    print(f"  -> Search error: {response.status_code}")
                    break

            print(f"  -> {total} matching images found.")

    # --- 3. DOWNLOAD THE FOUND PRODUCTS ---
    print(f"\nA total of {len(products_to_download)} images will be downloaded.")

    for i, product in enumerate(products_to_download, 1):

        file_path = os.path.join(OUTPUT_DIR, f"{product['name']}.zip")

        if os.path.exists(file_path):
            print(f"[{i}/{len(products_to_download)}] {product['name']} already exists, skipping...")
            continue

        print(f"[{i}/{len(products_to_download)}] Downloading: {product['name']}")
        current_token = get_token(USERNAME, PASSWORD)
        headers = {"Authorization": f"Bearer {current_token}"}

        download_url = f"https://zipper.dataspace.copernicus.eu/odata/v1/Products({product['id']})/$value"

        # Download to a temporary file, then rename it to the final name when complete
        temp_file = file_path + ".tmp"

        try:
            with requests.get(download_url, headers=headers, stream=True) as r:
                if r.status_code == 200:
                    with open(temp_file, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            f.write(chunk)
                    # Download successful, rename the temporary file to the final name
                    os.rename(temp_file, file_path)
                    print(f"  -> Downloaded successfully.")
                else:
                    print(f"  -> Download failed! Error code: {r.status_code}")
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
        except Exception as e:
            print(f"  -> A connection error occurred: {e}")
            # Clean up the incomplete temporary file in case of an error
            if os.path.exists(temp_file):
                os.remove(temp_file)


# Run the code
search_and_download()