# Image Upscaler

This is a standalone version of the image upscaling system originally found in the
`Product scraper` folder. It can be used independently to download, resize, upload
and optionally record the results in a Google Sheet.

## Features

- Read image URLs or Amazon ASINs from a configurable input file (default
  `inputimage.txt`).  Each line may contain pipe-separated values; ASINs
  (10‑character alphanumeric) will trigger a ScraperAPI lookup to acquire the
  product's large image URLs.  When ASINs are used, the output directory will
  contain a subfolder named after that ASIN, and all processed images for that
  product will be stored there (rather than the generic `line_<n>` folder).
- Download each image with retries.
- Resize so the longest side is configurable (default 600 px via `TARGET_SIZE`).
- Save the processed image locally in an `upscalled/` subfolder (configurable via `OUT_DIR`).
- Upload the output to a custom Node.js VPS API (port 5000 by default).
  The server exposes three endpoints:

      * **POST /create-folder** – ensure a folder (prefixed with `az_`) exists.
        Body `{ "folderName": "xyz" }` returns `{success,folder,path}`.
      * **POST /upload** – send `{folderName,fileName,imageBase64}`; returns
        `{success,folder,file,url,filePath}`.  The `url` field is a relative
        path you can GET directly (e.g. `http://host:5000/drive/az_xyz/photo.jpg`).
      * **GET /drive/<folder>/<file>** – retrieve stored files.

    The script now calls `/create-folder` automatically before uploading each
    image.
- Optionally update a Google Sheet with the public links (set `GOOGLE_SHEET_ID`).

## Getting started

1. Copy this directory and its contents or symlink it into your project.
2. Create an `.env` file (or copy `.env.example`) and set the following values;
   the script will also automatically read from `.env.example` if `.env` is
   missing so you can try out default settings without manual copying.
   ```env
   VPS_IP=209.74.86.194       # required for upload, leave blank to skip (user-provided)
   GOOGLE_SHEET_ID=...        # optional, omit to disable sheet updates
   WORKSHEET_NAME=Sheet1.cm   # optional, defaults to Sheet1.cm
   ```

   You may also override `INPUT_FILE` and `OUT_DIR` here; paths are resolved
   relative to the `image upscaler` folder so the script works even if you
   invoke it from another directory.
3. Install dependencies:
   ```bash
   python -m pip install -r requirements.txt
   ```
4. Populate `inputimage.txt` with one or more image URLs per line separated by `|`.
5. Run the script:
   ```bash
   python upscaler.py
   ```

## Notes

- The script will create the configured output directory (default `upscalled/`) and mirror
the row index inside that folder.
- VPS uploads are skipped when `VPS_IP` is unset or equal to `127.0.0.1`.
- Google Sheets integration requires either service account credentials (`credentials.json`)
  or OAuth client (`oauth_client.json` + interactive token exchange).

## License

Feel free to adapt or reuse the code in this directory for your own projects.