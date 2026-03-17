#!/usr/bin/env python3
"""
Standalone image upscaler script.

Reads a configured input file (default `inputimage.txt`) and processes each line of pipe-separated image URLs:

- download each image (with retries)
- resize so the longest side is `TARGET_SIZE` (default 600px)
- save locally under `upscaled/line_<n>`
- optionally upload to a VPS API (configured via VPS_IP)
- optionally write resulting URLs back to a Google Sheet (if `GOOGLE_SHEET_ID`)

Usage:
    python upscaler.py

Configuration is handled via environment variables (use a `.env` file):
    VPS_IP            IP/hostname for the upload API
    GOOGLE_SHEET_ID   (optional) ID of the sheet to update
    WORKSHEET_NAME    (optional) worksheet to use, defaults to "Sheet1.cm"

"""
import os
import sys
import time
import json
import base64
import re
from io import BytesIO
import requests # type: ignore
from PIL import Image # type: ignore
from dotenv import load_dotenv # type: ignore

# lazy import gspread/google auth only if we use sheets
try:
    import gspread # type: ignore
    from google.oauth2.service_account import Credentials # type: ignore
    from google_auth_oauthlib.flow import InstalledAppFlow # type: ignore
    from google.oauth2.credentials import Credentials as UserCredentials # type: ignore
except ImportError:
    gspread = None

# load environment variables from .env, fall back to .env.example when the
# former doesn't exist so settings like TARGET_SIZE are visible without copying
# the file.
load_dotenv()
# second call will read .env.example but won't override any real settings
if not os.path.exists(os.path.join(os.path.dirname(__file__), ".env")):
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env.example"), override=False)

# Determine base directory of this script; helps when run from elsewhere.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Path to the file containing ASINs or URLs (one line per entry).
# Allows overriding by setting the INPUT_FILE environment variable.  If a
# relative path is provided, it is interpreted relative to the script folder.
INPUT_FILE = os.getenv("INPUT_FILE", "inputimage.txt")
if not os.path.isabs(INPUT_FILE):
    INPUT_FILE = os.path.join(BASE_DIR, INPUT_FILE)

# output directory; can be overridden with the OUT_DIR environment variable.
# Relative paths also resolve under the script folder so results always end up
# inside the image upscaler directory.
OUT_DIR = os.getenv("OUT_DIR", "upscalled")
if not os.path.isabs(OUT_DIR):
    OUT_DIR = os.path.join(BASE_DIR, OUT_DIR)

TIMEOUT = 20
RETRIES = 2
# Longest side target size (in pixels); override with env variable
TARGET_SIZE = int(os.getenv("TARGET_SIZE", "600"))  # px for longest side

# scraper api (optional) - if set, ASIN tokens will be replaced with product images
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY", "")
BASE_URL = "https://api.scraperapi.com"
ASIN_REGEX = re.compile(r"^[A-Z0-9]{10}$", re.I)

# sheet & vps config
SPREADSHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")
WORKSHEET_NAME = os.getenv("WORKSHEET_NAME", "Sheet1.cm")

# VPS CONFIG - Added defaults from common usage
VPS_IP = os.getenv("VPS_IP", "127.0.0.1")
VPS_PORT = os.getenv("VPS_PORT", "443")
VPS_SCHEME = os.getenv("VPS_SCHEME", "https")
VPS_VERIFY_SSL = os.getenv("VPS_VERIFY_SSL", "1") not in ("0","false","False")

# sheet scopes
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]

os.makedirs(OUT_DIR, exist_ok=True)


# ---------- helper functions ----------

def get_sheet():
    if not SPREADSHEET_ID:
        raise RuntimeError("GOOGLE_SHEET_ID is not configured")

    if gspread is None:
        raise RuntimeError("gspread/google-auth libraries are not installed")

    # prefer OAuth if a client file exists
    if os.path.exists("oauth_client.json"):
        creds = None
        if os.path.exists("token.json"):
            try:
                creds = UserCredentials.from_authorized_user_file("token.json", SCOPES)
            except Exception:
                creds = None

        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file("oauth_client.json", SCOPES)
            creds = flow.run_local_server(port=0)
            try:
                with open("token.json", "w") as tf:
                    tf.write(creds.to_json())
            except Exception:
                pass

        if gspread is not None:
             client = gspread.authorize(creds)
             ss = client.open_by_key(SPREADSHEET_ID)
             return ss.worksheet(WORKSHEET_NAME)

    # fallback to service account
    creds = Credentials.from_service_account_file(os.path.join(BASE_DIR, "credentials.json"), scopes=SCOPES)
    if gspread is not None:
        client = gspread.authorize(creds)
        ss = client.open_by_key(SPREADSHEET_ID)
        return ss.worksheet(WORKSHEET_NAME)
    raise RuntimeError("gspread is not initialized")


def download_image(url):
    for attempt in range(1, RETRIES + 1):
        try:
            resp = requests.get(url, timeout=TIMEOUT, stream=True)
            resp.raise_for_status()
            return resp.content
        except Exception:
            if attempt == RETRIES:
                raise
            time.sleep(1)
    raise RuntimeError("unreachable")


def upscale_image_bytes(img_bytes, target=TARGET_SIZE):
    with Image.open(BytesIO(img_bytes)) as im:
        im = im.convert("RGB")
        w, h = im.size
        if w >= h:
            new_w = target
            new_h = int(round((target / w) * h))
        else:
            new_h = target
            new_w = int(round((target / h) * w))
        if new_w == w and new_h == h:
            out = im.copy()
        else:
            out = im.resize((new_w, new_h), resample=Image.LANCZOS)
        buf = BytesIO()
        out.save(buf, format="JPEG", quality=92)
        buf.seek(0)
        return buf, (new_w, new_h)


def fetch_images_from_asin(asin, retries=3, delay=2):
    """Return one or more image URLs for the given ASIN (bottom section).

    Identical semantics to the earlier definition: ScraperAPI must be
    configured.  Removed any direct‑fetch or fallback rules to avoid
    confusion.
    """
    if not SCRAPER_API_KEY:
        raise RuntimeError("SCRAPER_API_KEY must be set to fetch ASIN images")


    params = {
        "api_key": SCRAPER_API_KEY,
        "url": f"https://www.amazon.com/dp/{asin}",
        "country_code": "us",
    }
    html = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(BASE_URL, params=params, timeout=25)
            if r.status_code == 200:
                html = r.text
                break
            else:
                print(f"⚠️ ASIN {asin}: HTTP {r.status_code} (try {attempt}/{retries})")
        except Exception as e:
            print(f"⚠️ ASIN {asin}: request failed ({e})")
        time.sleep(delay)
    
    if html is None:
        raise RuntimeError(f"failed to retrieve ASIN {asin}")

    # find large images
    images = []
    if html is not None:
        images = re.findall(r'"large":"(https:[^\"]+\.jpg)"', str(html))
    
    if not images:
        raise RuntimeError(f"no images found for {asin}")
    return images


def create_vps_folder(folder_name):
    """Ensure the named folder exists on the pictureDrive server.

    The API lives behind a configurable scheme/host/port.  We omit the port
    if it matches the default for the scheme (443 for https, 80 for http).
    """
    try:
        if (VPS_SCHEME == "https" and VPS_PORT in ("443", "")) or (
                VPS_SCHEME == "http" and VPS_PORT in ("80", "")):
            base = f"{VPS_SCHEME}://{VPS_IP}"
        else:
            base = f"{VPS_SCHEME}://{VPS_IP}:{VPS_PORT}"
        api_url = f"{base}/create-folder"
        print(f"  [DEBUG] creating VPS folder via {api_url}")
        resp = requests.post(api_url, json={"folderName": folder_name}, timeout=10,
                             verify=VPS_VERIFY_SSL)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            print(f"  [WARN] create-folder failed: {data}")
        return True
    except Exception as e:
        print(f"  [WARN] create-folder request failed: {e}")
        return False


def upload_to_vps_api(image_bytes_buf, folder_name, filename):
    """Upload upscaled image bytes to the VPS and return the public URL.

    No local file is written; the image is base64‑encoded in memory and sent
    directly to the `/upload` endpoint.  The connection parameters honour the
    same scheme/port/ssl configuration used by ``create_vps_folder``.
    """
    if not VPS_IP or VPS_IP == "127.0.0.1":
        return None
    try:
        create_vps_folder(folder_name)
        base64_encoded = base64.b64encode(image_bytes_buf.getvalue()).decode('utf-8')
        payload = {
            "folderName": folder_name,
            "fileName": filename,
            "imageBase64": base64_encoded
        }
        if (VPS_SCHEME == "https" and VPS_PORT in ("443", "")) or (
                VPS_SCHEME == "http" and VPS_PORT in ("80", "")):
            base = f"{VPS_SCHEME}://{VPS_IP}"
        else:
            base = f"{VPS_SCHEME}://{VPS_IP}:{VPS_PORT}"
        api_url = f"{base}/upload"
        print(f"  [DEBUG] uploading to VPS via {api_url}")
        headers = {'Content-Type': 'application/json'}
        response = requests.post(api_url, json=payload, headers=headers,
                                 verify=VPS_VERIFY_SSL)
        response.raise_for_status()
        data = response.json()
        if data.get('success'):
            relative_url = data.get('url')
            public_url = f"https://images.thedailytraveller.online{relative_url}"
            return public_url
        else:
            print(f"  [ERROR] VPS API returned failure: {data}")
            return None
    except Exception as e:
        print(f"  [ERROR] VPS Upload failed: {e}")
        return None


def process_line(line, line_idx, sheet=None):
    """Turn a line of input into a list of (source, url) entries.

    * `source` is the ASIN string if the token was an ASIN, otherwise None.
    * plain URLs are left unchanged.

    When generating output files the source value is used as the
    sub‑directory name (so every ASIN gets its own folder)."""
    tokens = [u.strip() for u in line.split("|") if u.strip()]
    url_entries = []  # list of (source, url)
    for token in tokens:
        if ASIN_REGEX.match(token):
            try:
                fetched = fetch_images_from_asin(token)
                for u in fetched:
                    url_entries.append((token, u))
            except Exception as e:
                print(f"  [WARN] failed to fetch ASIN {token}: {e}")
        else:
            url_entries.append((None, token))

    if not url_entries:
        return [], 0

    upscaled_urls_list: list[str] = []
    count = 0

    for i, (src, url) in enumerate(url_entries, start=1):
        # determine local and vps folder using the source token when available
        folder_label = src if src else f"line_{line_idx}"
        out_sub = os.path.join(OUT_DIR, folder_label)
        os.makedirs(out_sub, exist_ok=True)
        vps_folder_name = f"upscaled_{folder_label}"

        try:
            print(f"[INFO] {folder_label} - downloading image {i}: {url}")
            b = download_image(url)
            img_buf, size = upscale_image_bytes(b)
            filename = f"{i}_{TARGET_SIZE}.jpg"
            vps_url = upload_to_vps_api(img_buf, vps_folder_name, filename) if VPS_IP else None
            if vps_url:
                print(f"  [OK] Uploaded to VPS: {vps_url}")
                # Append the VPS URL to outputimage.txt
                with open(os.path.join(BASE_DIR, "outputimage.txt"), "a", encoding="utf-8") as outf:
                    outf.write(vps_url + "\n")
            upscaled_urls_list.append(vps_url or "")
            count += 1
        except Exception as e:
            print(f"  [ERROR] Failed image {i} ({url}): {e}")
            upscaled_urls_list.append("")
    
    # update sheet if requested
    if sheet and upscaled_urls_list:
        upscaled_str = "|".join([u for u in upscaled_urls_list if u])
        try:
            headers = sheet.row_values(5)
            col_idx = None
            for idx, h in enumerate(headers, 1):
                if h.strip() == "Upscaled Images":
                    col_idx = idx
                    break
            if col_idx is None:
                col_idx = len(headers) + 1
                headers.append("Upscaled Images")
                sheet.append_row(headers)
            row_num = 5 + line_idx
            sheet.update_cell(row_num, col_idx, upscaled_str)
            print(f"  [OK] Updated Sheet row {row_num} with upscaled image links")
        except Exception as e:
            print(f"  [WARN] Failed to update sheet: {e}")
    return upscaled_urls_list, count


# ---------- main ----------

def initialize_input():
    # run helper to refresh input file from sheet before doing anything else
    try:
        # Move import here to avoid circular dependency or missing module issues if not used
        import importlib.util
        spec = importlib.util.find_spec('sheet_to_input')
        if spec:
             import sheet_to_input # type: ignore
             sheet_to_input.main()
        else:
             print("[INFO] sheet_to_input module not found, skipping sheet refresh")
    except Exception as e:
        # if the helper fails, log but continue; the script may also read from an
        # existing inputimage.txt
        print(f"[WARN] sheet_to_input failed: {e}")


def main():
    initialize_input()
    # report configuration values for troubleshooting
    print(f"[INFO] INPUT_FILE={INPUT_FILE}")
    print(f"[INFO] OUT_DIR={OUT_DIR}")
    print(f"[INFO] TARGET_SIZE={TARGET_SIZE}")

    if not os.path.exists(INPUT_FILE):
        print(f"Input file not found: {INPUT_FILE}")
        sys.exit(1)
    
    sheet = None
    if SPREADSHEET_ID:
        print("[INFO] GOOGLE_SHEET_ID provided, attempting to connect...")
        try:
            sheet = get_sheet()
            print("[OK] Connected to sheet")
        except Exception as e:
            print(f"[ERROR] Failed to connect to sheet: {e}")
    else:
        print("[INFO] No GOOGLE_SHEET_ID; skipping sheet integration")
    
    total = 0
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            _, got = process_line(line, idx, sheet)
            total += got
    print(f"\nDone. Total images processed: {total}")
    print(f"Upscaled images saved in: {OUT_DIR}")


if __name__ == "__main__":
    main()
