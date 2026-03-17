#!/usr/bin/env python3
"""Dump column B from row 6 down into inputimage.txt.

This helper is standalone so the main upscaler script can remain unchanged.
It uses the same Google Sheets credentials mechanism as the upscaler.

Usage:
    python sheet_to_input.py

The output file is created in the same directory as the script.  Any
existing content is overwritten.
"""
import os
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials

# determine base directory and load .env from there; also try parent dir
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# load primary .env
load_dotenv(os.path.join(BASE_DIR, ".env"))
# if still missing, check parent folder
if not os.getenv("GOOGLE_SHEET_ID"):
    load_dotenv(os.path.join(BASE_DIR, "..", ".env"))
# if still missing, try the example file(s)
if not os.getenv("GOOGLE_SHEET_ID"):
    load_dotenv(os.path.join(BASE_DIR, ".env.example"))
if not os.getenv("GOOGLE_SHEET_ID"):
    load_dotenv(os.path.join(BASE_DIR, "..", ".env.example"))

# fetch configuration; allow environment variables to override
SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "").strip()
if not SHEET_ID:
    raise RuntimeError("GOOGLE_SHEET_ID not set; please configure .env or set env var")
WORKSHEET_NAME = os.getenv("WORKSHEET_NAME", "Sheet1.cm").strip()

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

def get_sheet():
    if not SHEET_ID:
        raise RuntimeError("GOOGLE_SHEET_ID is not configured")
    creds = Credentials.from_service_account_file(
        os.path.join(BASE_DIR, "credentials.json"),
        scopes=SCOPES,
    )
    client = gspread.authorize(creds)
    ss = client.open_by_key(SHEET_ID)
    return ss.worksheet(WORKSHEET_NAME)


def main():
    sheet = get_sheet()
    # pull column B starting from row 6 until the first empty cell
    values = sheet.col_values(2)[5:]
    out_file = os.path.join(BASE_DIR, "inputimage.txt")
    # clear the file up front
    open(out_file, "w", encoding="utf-8").close()
    if not values:
        print(f"No ASINs found in sheet; {out_file} has been emptied")
        return
    with open(out_file, "w", encoding="utf-8") as f:
        for v in values:
            v = v.strip()
            if v:
                f.write(v + "\n")
    print(f"Wrote {len(values)} rows from sheet to {out_file}")


if __name__ == "__main__":
    main()
