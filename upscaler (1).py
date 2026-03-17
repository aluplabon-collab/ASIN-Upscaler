#!/usr/bin/env python3
"""
Image upscaler with Google Drive upload + Sheet integration.
Reads `inputimage.txt`, each line contains image URLs separated by '|'.
- Downloads each image
- Resizes so the longest side is 600px (preserving aspect ratio)
- Uploads to Google Drive folder
- Generates shareable public URLs
- Writes URLs back to Google Sheet in an "Upscaled Images" column

Usage:
  python upscaler.py

Config:
  - DRIVE_FOLDER_ID: Google Drive folder ID to upload to
  - SPREADSHEET_ID: Google Sheet ID to update with URLs
  - WORKSHEET_NAME: Worksheet name to update
"""
import os
import sys
import time
from io import BytesIO
import requests
from PIL import Image
from dotenv import load_dotenv

load_dotenv()

# Google APIs
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import gspread
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials as UserCredentials

INPUT_FILE = "inputimage.txt"
OUT_DIR = "upscaled"
TIMEOUT = 20
RETRIES = 2

# Drive & Sheet config
DRIVE_FOLDER_ID = "1GMlkMmaJ05vMgjRimrQrCg72bVkY1-ZV"
SPREADSHEET_ID = os.getenv("GOOGLE_SHEET_ID")
WORKSHEET_NAME = "Sheet1.cm"

# Scopes
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

os.makedirs(OUT_DIR, exist_ok=True)

# When a service account has no Drive storage quota, uploads will fail with a
# storageQuotaExceeded error. Use this flag to stop further Drive attempts
# once we detect that condition so the run is quieter and falls back to
# local paths.
DRIVE_UPLOAD_AVAILABLE = True


def get_drive_service():
    # Prefer OAuth user credentials if available
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
            # save token
            try:
                with open("token.json", "w") as tf:
                    tf.write(creds.to_json())
            except Exception:
                pass

        return build("drive", "v3", credentials=creds)

    # Fallback to service account
    creds = Credentials.from_service_account_file(
        "credentials.json", scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds)


def get_sheet():
    # Prefer OAuth if available (keeps Drive and Sheets under same account)
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

        client = gspread.authorize(creds)
        ss = client.open_by_key(SPREADSHEET_ID)
        return ss.worksheet(WORKSHEET_NAME)

    # Fallback to service account
    creds = Credentials.from_service_account_file(
        "credentials.json", scopes=SCOPES
    )
    client = gspread.authorize(creds)
    ss = client.open_by_key(SPREADSHEET_ID)
    return ss.worksheet(WORKSHEET_NAME)


def download_image(url):
    for attempt in range(1, RETRIES + 1):
        try:
            resp = requests.get(url, timeout=TIMEOUT, stream=True)
            resp.raise_for_status()
            return resp.content
        except Exception as e:
            if attempt == RETRIES:
                raise
            time.sleep(1)
    raise RuntimeError("unreachable")


def upscale_image_bytes(img_bytes, target=1500):
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


def upload_to_drive(service, file_bytes, filename):
    """Upload file to Google Drive and return shareable URL."""
    file_metadata = {
        "name": filename,
        "parents": [DRIVE_FOLDER_ID]
    }
    media = MediaIoBaseUpload(file_bytes, mimetype="image/jpeg", resumable=True)
    file_obj = service.files().create(body=file_metadata, media_body=media).execute()
    file_id = file_obj["id"]
    
    # Make publicly readable
    service.permissions().create(
        fileId=file_id,
        body={"role": "reader", "type": "anyone"}
    ).execute()
    
    url = f"https://drive.google.com/uc?id={file_id}&export=download"
    return url, file_id


def process_line(line, line_idx, sheet, drive_service=None):
    global DRIVE_UPLOAD_AVAILABLE
    urls = [u.strip() for u in line.split("|") if u.strip()]
    if not urls:
        return [], 0
    
    out_sub = os.path.join(OUT_DIR, f"line_{line_idx}")
    os.makedirs(out_sub, exist_ok=True)
    
    upscaled_urls = []
    count = 0
    
    for i, url in enumerate(urls, start=1):
        try:
            print(f"[INFO] Line {line_idx} - downloading image {i}: {url}")
            b = download_image(url)
            img_buf, size = upscale_image_bytes(b, target=1500)
            
            # Save locally
            out_path = os.path.join(out_sub, f"{i}_1500.jpg")
            with open(out_path, "wb") as f:
                f.write(img_buf.getvalue())
            print(f"  [OK] Saved locally: {out_path} ({size[0]}x{size[1]})")
            
            # Try uploading to Drive (if service provided), otherwise keep local path
            drive_url = ""
            if drive_service is not None and DRIVE_UPLOAD_AVAILABLE:
                try:
                    print(f"  [INFO] Uploading to Drive: {out_path}")
                    # Ensure buffer is at start
                    img_buf.seek(0)
                    filename = os.path.basename(out_path)
                    drive_url, file_id = upload_to_drive(drive_service, img_buf, filename)
                    print(f"  [OK] Uploaded to Drive: {drive_url}")
                except Exception as e:
                    # Detect Drive storage quota error for service accounts and
                    # flip the global flag to avoid repeated failed attempts.
                    msg = str(e)
                    print(f"  [WARN] Drive upload failed for {out_path}: {e}")
                    if "storageQuotaExceeded" in msg or "do not have storage quota" in msg:
                        DRIVE_UPLOAD_AVAILABLE = False
                        print("  [INFO] Disabling further Drive uploads for this run (service-account quota).")
                    drive_url = ""

            # Prefer Drive URL if available, otherwise local path
            upscaled_urls.append(drive_url if drive_url else out_path)
            count += 1
        except Exception as e:
            print(f"  [ERROR] Failed image {i} ({url}): {e}")
            upscaled_urls.append("")
    
    # Update sheet row with upscaled image local paths (pipe-separated)
    if upscaled_urls:
        upscaled_str = "|".join([u for u in upscaled_urls if u])
        try:
            # Find or create "Upscaled Images" column
            headers = sheet.row_values(5)
            col_idx = None
            for idx, h in enumerate(headers, 1):
                if h.strip() == "Upscaled Images":
                    col_idx = idx
                    break
            
            if col_idx is None:
                # Add new column
                col_idx = len(headers) + 1
                headers.append("Upscaled Images")
                sheet.append_row(headers)
            
            # Write upscaled paths to the sheet
            row_num = 5 + line_idx  # Assuming data starts at row 6
            sheet.update_cell(row_num, col_idx, upscaled_str)
            print(f"  [OK] Updated Sheet row {row_num} with upscaled image paths")
        except Exception as e:
            print(f"  [WARN] Failed to update sheet: {e}")
    
    return upscaled_urls, count


def main():
    if not os.path.exists(INPUT_FILE):
        print(f"Input file not found: {INPUT_FILE}")
        sys.exit(1)
    
    if not SPREADSHEET_ID:
        print("[ERROR] GOOGLE_SHEET_ID not set in .env")
        sys.exit(1)
    
    print("[INFO] Connecting to Google Sheets...")
    sheet = get_sheet()
    print("[OK] Connected to Sheets")

    # Try to create Drive service; if it fails, continue with local-only mode
    drive_service = None
    try:
        print("[INFO] Connecting to Google Drive...")
        drive_service = get_drive_service()
        print("[OK] Drive service ready")
    except Exception as e:
        print(f"[WARN] Could not initialize Drive service, continuing local-only: {e}")
    
    total = 0
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            urls, got = process_line(line, idx, sheet, drive_service=drive_service)
            total += got
    
    print(f"\nDone. Total images processed: {total}")
    print(f"Upscaled images saved in: {OUT_DIR}")


if __name__ == "__main__":
    main()
