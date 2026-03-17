# Note: rembg, gspread, and google libraries are now lazy-loaded inside functions.


# ---------------------------------------------------------------------------
# VPS Upload helpers (mirrors image upscaler v2)
# ---------------------------------------------------------------------------

def _vps_create_folder(vps_base_url, folder_name):
    """Ensure the named folder exists on the VPS pictureDrive server."""
    api_url = vps_base_url.rstrip('/') + '/create-folder'
    for attempt in range(3):
        try:
            resp = requests.post(api_url, json={'folderName': folder_name}, timeout=10, verify=False)
            resp.raise_for_status()
            data = resp.json()
            if not data.get('success'):
                print(f"  [WARN] VPS create-folder returned: {data}")
            return True
        except Exception as e:
            print(f"  [WARN] VPS create-folder failed on attempt {attempt+1}: {e}")
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                return False


def _vps_upload_image(vps_base_url, image_bytes_buf, folder_name, filename):
    """Base64-encode and POST an image to the VPS. Returns the public URL or empty string."""
    if not vps_base_url:
        return ''
    
    _vps_create_folder(vps_base_url, folder_name)
    b64 = base64.b64encode(image_bytes_buf.getvalue()).decode('utf-8')
    payload = {
        'folderName': folder_name,
        'fileName': filename,
        'imageBase64': b64,
    }
    api_url = vps_base_url.rstrip('/') + '/upload'
    
    for attempt in range(4):
        try:
            print(f"  [DEBUG] Uploading to VPS: {api_url} (Attempt {attempt+1})")
            resp = requests.post(api_url, json=payload,
                                 headers={'Content-Type': 'application/json'}, timeout=60, verify=False)
            resp.raise_for_status()
            data = resp.json()
            if data.get('success'):
                relative = data.get('url', '')
                public_url = vps_base_url.rstrip('/') + relative
                print(f"  [OK] VPS upload succeeded: {public_url}")
                return public_url
            else:
                print(f"  [ERROR] VPS upload API returned failure: {data}")
                return ''
        except Exception as e:
            print(f"  [WARN] VPS upload failed on attempt {attempt+1}: {e}")
            if attempt < 3:
                time.sleep(2 ** attempt)
            else:
                print(f"  [ERROR] VPS upload definitively failed after 4 attempts.")
                return ''


# ---------------------------------------------------------------------------
# Google Sheets helper
# ---------------------------------------------------------------------------

def _get_sheet(sheet_id, worksheet_name):
    """Return a gspread Worksheet. Supports OAuth and Service Account auth."""
    try:
        import gspread # type: ignore
        from google.oauth2.service_account import Credentials # type: ignore
        from google_auth_oauthlib.flow import InstalledAppFlow # type: ignore
        from google.oauth2.credentials import Credentials as UserCredentials # type: ignore
    except ImportError:
        raise RuntimeError('gspread / google-auth libraries are not installed. Run: pip install gspread google-auth-oauthlib')

    if not sheet_id:
        raise RuntimeError('Google Sheet ID is not configured')

    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

    import sys
    if getattr(sys, 'frozen', False):
        BASE_DIR = os.path.dirname(sys.executable)
    else:
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))

    oauth_file = os.path.join(BASE_DIR, 'oauth_client.json')
    token_file = os.path.join(BASE_DIR, 'token.json')
    creds_file = os.path.join(BASE_DIR, 'credentials.json')

    if os.path.exists(oauth_file):
        creds = None
        if os.path.exists(token_file):
            try:
                creds = UserCredentials.from_authorized_user_file(token_file, SCOPES)
            except Exception:
                creds = None
        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file(oauth_file, SCOPES)
            creds = flow.run_local_server(port=0)
            try:
                with open(token_file, 'w') as tf:
                    tf.write(creds.to_json())
            except Exception:
                pass
        client = gspread.authorize(creds)
        ss = client.open_by_key(sheet_id)
        try:
            return ss.worksheet(worksheet_name)
        except gspread.WorksheetNotFound:
            print(f"  [WARN] Worksheet '{worksheet_name}' not found. Falling back to the first available sheet.")
            return ss.get_worksheet(0)
    
    # Fallback to Service Account
    try:
        import gspread # type: ignore
        from google.oauth2.service_account import Credentials as ServiceAccountCredentials # type: ignore
        creds = ServiceAccountCredentials.from_service_account_file(creds_file, scopes=SCOPES)
        client = gspread.authorize(creds)
        ss = client.open_by_key(sheet_id)
        try:
            return ss.worksheet(worksheet_name)
        except gspread.WorksheetNotFound:
            print(f"  [WARN] Worksheet '{worksheet_name}' not found. Falling back to the first available sheet.")
            return ss.get_worksheet(0)
    except Exception as e:
        raise RuntimeError(f"Failed to connect to Google Sheet: {e}")

import os, sys, time, re, base64
import typing
from typing import List, Optional
from io import BytesIO
import requests # type: ignore
from PIL import Image, ImageDraw # type: ignore
import urllib3 # type: ignore
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class ImageProcessorCore:
    def _strip_amazon_image_size(self, url):
        """Remove Amazon size/crop suffixes to get the full-resolution image URL.
        e.g. https://m.media-amazon.com/images/I/71abc._AC_SX38_.jpg
          -> https://m.media-amazon.com/images/I/71abc.jpg
        """
        # Strip everything between the last dot-prefixed size tag and the extension
        # Common patterns: ._AC_SX38_., ._AC_SL1500_., ._SY300_SX300_QL70_ML2_.
        return re.sub(r'\._[A-Z0-9_,]+_\.', '.', url)

    def _parse_amazon_images_from_html(self, html: str) -> list[str]:
        """Extract hi-res Amazon image URLs from rendered HTML.
        Tries JSON data blocks first, then falls back to regex CDN scan.
        Returns a deduplicated list of full-resolution image URLs.
        """
        import json as _json
        import ast as _ast
        image_urls: list[str] = []

        # Strategy A: 'colorImages' data block (most reliable)
        # We look for the raw string inside the curly braces of initial: [...]
        for pattern in [
            r'["\']colorImages["\']\s*:\s*\{\s*["\']initial["\']\s*:\s*(\[.*?\])\s*\}\s*,\s*["\']colorToAsin["\']',
            r'data\[["\']colorImages["\']\]\s*=\s*\{["\']initial["\']\s*:\s*(\[.*?\])\s*}\s*;',
            r'["\']colorImages["\']\s*:\s*\{\s*["\']initial["\']\s*:\s*(\[.+?\])\s*\}',
            r'["\']colorImages["\']\s*:\s*\{\s*["\']initial["\']\s*:\s*(\[.*?\])\s*\}'
        ]:
            match = re.search(pattern, html, re.DOTALL)
            if match:
                captured = match.group(1)
                items = None
                try:
                    # Attempt 1: Standard JSON
                    items = _json.loads(captured)
                except Exception:
                    try:
                        # Attempt 2: AST literal_eval (handles single quotes and other JS-isms)
                        # We sanitize potentially dangerous JS bits if needed, but usually Amazon 
                        # just uses standard list/dict structure here.
                        items = _ast.literal_eval(captured)
                    except Exception as e:
                        print(f"  [WARN] Both JSON and AST parse failed for colorImages: {e}")
                
                if items and isinstance(items, list):
                    for item in items:
                        if not isinstance(item, dict): continue
                        # Avoid video variants
                        variant = item.get('variant', '')
                        if variant and ('VID' in variant.upper() or 'MAIN_VIDEO' in variant.upper()):
                            continue
                            
                        url = item.get('hiRes') or item.get('large') or ''
                        if not url and isinstance(item.get('main'), dict):
                            # Usually main: {"url": [w, h], ...}
                            url = next(iter(item['main'].keys()), '')
                        
                        if url:
                            hi_res = self._strip_amazon_image_size(url)
                            if hi_res not in image_urls and not hi_res.lower().endswith(('.mp4', '.webm')):
                                image_urls.append(hi_res)
                    
                    if image_urls:
                        print(f"  [PARSE] Extracted {len(image_urls)} image(s) from colorImages block.")
                        return image_urls[:5] # type: ignore

        # Strategy B: Regex scan for all Amazon CDN image URLs
        # Restrict scan to potential image containers
        containers = re.findall(r'<div[^>]*id="?(?:main-image-container|imageBlock|altImages|ivMain|main-image-canvas)"?[^>]*>.*?</div>', html, re.DOTALL | re.IGNORECASE)
        html_to_scan = "\n".join(containers) if containers else html

        found = re.findall(
            r'https://m\.media-amazon\.com/images/I/[A-Za-z0-9%+\-_.]+\.(?:jpg|jpeg|png|webp)',
            html_to_scan,
            re.IGNORECASE
        )
        for raw in dict.fromkeys(found):
            hi_res = self._strip_amazon_image_size(raw)
            # Filter out UI elements
            if any(x in hi_res.lower() for x in ['play', 'video', 'transparent', 'pixel', 'sprite', 'play-icon-overlay']):
                continue
            if hi_res not in image_urls:
                image_urls.append(hi_res)

        if image_urls:
            print(f"  [PARSE] Regex scan found {len(image_urls)} image(s). (Fallback)")
            return image_urls[:5] # type: ignore

        return image_urls

    def fetch_amazon_images(self, asin: str, api_key: Optional[str] = None) -> List[str]:
        # type: (str, str) -> list[str]
        if not api_key:
            raise Exception(
                "A ScraperAPI key is required to fetch Amazon images.\n"
                "Please enter your ScraperAPI key in the 'ScraperAPI Key' field."
            )

        url = f"https://www.amazon.com/dp/{asin}?th=1"
        print(f"[FETCH] Fetching via ScraperAPI (render=true): {url}")
        params = {
            'api_key': api_key,
            'url': url,
            'render': 'true',
            'country_code': 'us',
        }
        resp = None
        for attempt in range(3):
            try:
                resp = requests.get('https://api.scraperapi.com', params=params, timeout=60)
                if resp.status_code == 200:
                    break
                print(f"[WARN] ScraperAPI returned HTTP {resp.status_code}. Attempt {attempt+1}/3")
            except Exception as e:
                print(f"[WARN] ScraperAPI request failed: {e}. Attempt {attempt+1}/3")
            time.sleep(2 ** attempt)
            
        if resp is None:
            raise Exception("ScraperAPI failed after 3 attempts (Connection Error). Check your API key or account credits.")
        assert resp is not None
        if resp.status_code != 200:
            raise Exception(f"ScraperAPI failed after 3 attempts (Last status: {resp.status_code}). Check your API key or account credits.")
        
        html = resp.text
        if "captcha" in html.lower()[:3000] or "robot check" in html.lower()[:3000]:
            raise Exception(
                "ScraperAPI returned a CAPTCHA page. "
                "Try enabling the 'ultra_premium' option on your ScraperAPI plan, "
                "or retry after a short delay."
            )
        print(f"[FETCH] ScraperAPI response received ({len(html):,} bytes).")
        image_urls = self._parse_amazon_images_from_html(html)
        if not image_urls:
            raise Exception(
                "ScraperAPI fetched the page but no product images were found. "
                "The ASIN may be invalid, or Amazon changed its page structure."
            )
        return image_urls

    def fetch_walmart_images(self, item_id: str, api_key: Optional[str] = None) -> List[str]:
        # type: (str, str) -> list[str]
        if not api_key:
            raise Exception(
                "A ScraperAPI key is required to fetch Walmart images.\n"
                "Please enter your ScraperAPI key in the 'ScraperAPI Key' field."
            )

        url = f"https://www.walmart.com/ip/{item_id}"
        print(f"[FETCH] Fetching via ScraperAPI: {url}")
        params = {
            'api_key': api_key,
            'url': url,
            'country_code': 'us',
        }
        resp = None
        for attempt in range(3):
            try:
                resp = requests.get('https://api.scraperapi.com', params=params, timeout=60)
                if resp.status_code == 200:
                    break
                print(f"[WARN] ScraperAPI returned HTTP {resp.status_code}. Attempt {attempt+1}/3")
            except Exception as e:
                print(f"[WARN] ScraperAPI request failed: {e}. Attempt {attempt+1}/3")
            time.sleep(2 ** attempt)
            
        if resp is None:
            raise Exception("ScraperAPI failed after 3 attempts (Connection Error). Check your API key or account credits.")
        assert resp is not None
        if resp.status_code != 200:
            raise Exception(f"ScraperAPI failed after 3 attempts (Last status: {resp.status_code}). Check your API key or account credits.")
            
        html = resp.text
        if "captcha" in html.lower()[:3000] or "robot check" in html.lower()[:3000]:
            raise Exception(
                "ScraperAPI returned a CAPTCHA page for Walmart. "
                "Try enabling the 'ultra_premium' option on your ScraperAPI plan, "
                "or retry after a short delay."
            )
        print(f"[FETCH] ScraperAPI response received ({len(html):,} bytes).")

        image_urls = []

        # Strategy A: Parse Walmart __NEXT_DATA__ JSON state (Highly accurate)
        import json as _json
        match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if match:
            try:
                data = _json.loads(match.group(1))
                # We'll try multiple common paths for image data in Walmart's Next.js state
                initial_data = data.get('props', {}).get('pageProps', {}).get('initialData', {}).get('data', {})
                product_data = initial_data.get('product', {})
                
                # 1. Primary allImages path
                all_images = product_data.get('imageInfo', {}).get('allImages', [])
                if not all_images:
                    # 2. Try variant mapping if primary is empty
                    variants = product_data.get('variantsMap', {})
                    for v_key in variants:
                        v_imgs = variants[v_key].get('imageInfo', {}).get('allImages', [])
                        if v_imgs:
                            all_images = v_imgs
                            break
                            
                if not all_images:
                    # 3. Try imageMap
                    img_map = product_data.get('imageMap', {})
                    if img_map:
                        all_images = [{"url": v.get('url')} for v in img_map.values() if v.get('url')]

                for img_obj in all_images:
                    url = img_obj.get('url') if isinstance(img_obj, dict) else img_obj
                    if url:
                        hi_res = url.split('?')[0]
                        if hi_res not in image_urls:
                            image_urls.append(hi_res)
                            
                if image_urls:
                    image_urls = image_urls[:5] # type: ignore
                    print(f"  [PARSE] Found {len(image_urls)} Walmart image(s) from JSON paths.")
                    return image_urls
            except Exception as e:
                print(f"  [WARN] Walmart JSON parse attempt failed: {e}")

        # Strategy B: Fallback Regex for Walmart image CDN URLs
        # We broaden the scan to the whole HTML if the testid-container is missing or changed
        container_match = re.search(r'(<div[^>]*data-testid="item-page"[^>]*>.*?</form>|<div[^>]*data-testid="media-gallery"[^>]*>.*?</div>)', html, re.DOTALL | re.IGNORECASE)
        html_to_scan = container_match.group(0) if container_match else html

        # Broaden patterns: include webp, case-insensitive, and diverse subdomains if they appear
        patterns = [
            r'https://i5\.walmartimages\.com/asr/[^\s"\'<>]+\.(?:jpg|jpeg|png|webp)',
            r'https://i5\.walmartimages\.com/seo/[^\s"\'<>]+\.(?:jpg|jpeg|png|webp)',
            r'https://i5\.walmartimages\.com/[^\s"\'<>]+\.(?:jpg|jpeg|png|webp)',
        ]
        local_urls = []
        for pattern in patterns:
            found = re.findall(pattern, html_to_scan, re.IGNORECASE)
            for raw in found:
                # Strip query params and normalize
                hi_res = raw.split('?')[0]
                if hi_res not in local_urls:
                    local_urls.append(hi_res)

        if local_urls:
            image_urls.extend(local_urls[:5]) # type: ignore
            print(f"  [PARSE] Regex scan found {len(image_urls)} Walmart image(s). (Fallback)")
            return image_urls

        raise Exception(
            "ScraperAPI fetched the Walmart page but no product images were found. "
            "The item ID may be invalid, Walmart changed its page structure, or ScraperAPI returned an incomplete page."
        )

    # --- Processing Methods ---
    def add_watermark(self, image_pil, watermark_path, is_template=False, product_scale=0.70):
        try:
            watermark = Image.open(watermark_path).convert("RGBA")
            image_width, image_height = image_pil.size
            if image_width < 1 or image_height < 1:
                return image_pil
            
            # Ensure base image is RGBA
            base_image = image_pil.convert("RGBA")

            if is_template:
                # --- Full Image Frame Mode ---
                # The correct compositing for a "frame" template is:
                #   1. Place the product on a white canvas (slightly inset)
                #   2. Overlay the frame ON TOP — frame's transparent center lets product show,
                #      opaque border/decorations overlay the product edges (like a picture frame)

                # 1. White canvas base
                result = Image.new("RGBA", base_image.size, (255, 255, 255, 255))

                # 2. Paste the product scaled to user-configured % centered on the white canvas
                scale_factor = max(0.30, min(0.95, product_scale / 100.0))
                new_w = int(image_width * scale_factor)
                new_h = int(image_height * scale_factor)
                scaled_base = base_image.resize((new_w, new_h), Image.LANCZOS)
                product_x = (image_width - new_w) // 2
                product_y = (image_height - new_h) // 2
                # Force fully opaque paste so product always shows
                if scaled_base.mode == "RGBA":
                    # fill any transparent pixels with white before pasting
                    white_fill = Image.new("RGBA", scaled_base.size, (255, 255, 255, 255))
                    white_fill.paste(scaled_base, mask=scaled_base.split()[3])
                    scaled_base = white_fill
                result.paste(scaled_base, (product_x, product_y))

                # 3. Scale frame to full output size
                frame = watermark.resize((image_width, image_height), Image.LANCZOS)

                # 4. Check if the frame has any transparent pixels in the center
                #    If yes → paste frame on top (transparent center lets product show)
                #    If no (opaque-center frame) → frame is already the background so return as-is
                frame_alpha = frame.split()[3]
                # Sample center pixel alpha
                cx, cy = image_width // 2, image_height // 2
                center_alpha = frame_alpha.getpixel((cx, cy))

                if center_alpha < 30:
                    # Frame has transparent center → paste frame on product (ideal case, like shoe example)
                    result.paste(frame, (0, 0), mask=frame)
                else:
                    # Frame center is opaque — create frame as background, place product on top
                    bg = Image.new("RGBA", base_image.size, (255, 255, 255, 255))
                    bg.paste(frame, (0, 0), mask=frame)
                    bg.paste(scaled_base, (product_x, product_y))
                    result = bg

                # 5. Flatten to RGB
                final_white_bg = Image.new("RGB", result.size, (255, 255, 255))
                final_white_bg.paste(result, mask=result.split()[3])
                return final_white_bg

            else:
                # --- Center Logo / Small Watermark Mode ---
                transparent = Image.new('RGBA', base_image.size, (255, 255, 255, 0))
                transparent.paste(base_image, (0, 0))

                wm_target_w = int(image_width * 0.20)
                wm_target_h = int((wm_target_w / watermark.size[0]) * watermark.size[1])
                position = (
                    (image_width - wm_target_w) // 2,
                    (image_height - wm_target_h) // 2
                )
                wm_resized = watermark.resize((wm_target_w, wm_target_h), Image.LANCZOS)
                transparent.paste(wm_resized, position, mask=wm_resized)

                final_white_bg = Image.new("RGB", transparent.size, (255, 255, 255))
                final_white_bg.paste(transparent, mask=transparent.split()[3])
                return final_white_bg

        except Exception as e:
            print(f"[WARN] Failed to add watermark: {e}")
            return image_pil

    def process_and_save_image(self, url, idx, is_first, out_folder, target_width, target_height, do_white_bg, watermark_path, is_template, vps_base_url='', vps_folder_name='', save_locally=True, product_scale=70, lock_aspect_ratio=True):
        """Download, process, and optionally upload one image.
        Returns the final public URL (VPS) or local file path, or empty string on failure.
        """
        try:
            print(f"  [INFO] Downloading Image {idx}: {url}")
            resp = None
            for attempt in range(3):
                try:
                    resp = requests.get(url, stream=True, timeout=15)
                    resp.raise_for_status()
                    break
                except Exception as e:
                    print(f"  [WARN] Download failed on attempt {attempt+1}: {e}")
                    time.sleep(2 ** attempt)
            
            if resp is None:
                raise Exception(f"Failed to download image from {url} after 3 attempts (Connection Error).")
            assert resp is not None
            if resp.status_code != 200:
                raise Exception(f"Failed to download image from {url} after 3 attempts (Status: {resp.status_code}).")
                
            img = Image.open(BytesIO(resp.content))
            img = img.convert("RGBA")

            # 1. Background removal to white (if first image and AI is enabled)
            if is_first and do_white_bg:
                print(f"  [PROC] Performing AI background removal...")
                try:
                    import importlib.util
                    if importlib.util.find_spec('rembg') is not None:
                        from rembg import remove # type: ignore
                        img_bytes = BytesIO()
                        img.save(img_bytes, format='PNG')
                        output_bytes = remove(img_bytes.getvalue())
                        img_bg_removed = Image.open(BytesIO(output_bytes)).convert("RGBA")
                        
                        # Fix: check if rembg removed too much (e.g. subject is completely gone)
                        alpha_channel = img_bg_removed.split()[3]
                        if alpha_channel.getextrema()[1] < 10:
                            print("  [WARN] AI background removal resulted in an empty image. Proceeding with original image.")
                        else:
                            # Create a white canvas and paste the extracted subject onto it
                            white_canvas = Image.new("RGBA", img_bg_removed.size, (255, 255, 255, 255))
                            white_canvas.paste(img_bg_removed, (0, 0), img_bg_removed)
                            img = white_canvas
                    else:
                        print(f"  [WARN] 'rembg' is not installed. AI background removal skipped.")
                except Exception as bg_e:
                    print(f"  [WARN] AI background removal failed: {bg_e}. Proceeding with original image.")

            # Ensure we convert back to RGB for size manipulation & saving as JPEG
            img = img.convert("RGB")

            # 2. Resize to target dimensions
            w, h = img.size
            if target_width > 0 and target_height > 0:
                if lock_aspect_ratio:
                    # Fit within the target box while maintaining aspect ratio
                    scale = min(target_width / w, target_height / h)
                    new_w = int(round(w * scale))
                    new_h = int(round(h * scale))
                else:
                    # Stretch exactly to target
                    new_w, new_h = target_width, target_height
            elif target_width > 0:
                # Only width specified — scale height proportionally
                new_w = target_width
                new_h = int(round((target_width / w) * h))
            elif target_height > 0:
                # Only height specified — scale width proportionally
                new_h = target_height
                new_w = int(round((target_height / h) * w))
            else:
                # Neither set — keep original size
                new_w, new_h = w, h
                
            img = img.resize((new_w, new_h), Image.LANCZOS)

            # 3. Add Watermark (only to the first image)
            if is_first and watermark_path and os.path.exists(watermark_path):
                img = self.add_watermark(img, watermark_path, is_template, product_scale=product_scale)

            # 4. Upload to VPS (if configured)
            vps_url = ''
            if vps_base_url:
                img_buf = BytesIO()
                img.save(img_buf, format='JPEG', quality=95)
                filename = f"image_{idx}.jpg"
                vps_url = _vps_upload_image(vps_base_url, img_buf, vps_folder_name, filename)
                
                if vps_url:
                    # Mirror upscaler.py logic: always append to outputimage.txt
                    import sys
                    if getattr(sys, 'frozen', False):
                        base_dir = os.path.dirname(sys.executable)
                    else:
                        base_dir = os.path.dirname(os.path.abspath(__file__))
                        
                    with open(os.path.join(base_dir, "outputimage.txt"), "a", encoding="utf-8") as outf:
                        outf.write(vps_url + "\n")
                    
                    # If we succeeded in uploading, only save locally if specifically requested
                    if save_locally and out_folder:
                        out_path = os.path.join(out_folder, f"image_{idx}.jpg")
                        img.save(out_path, format="JPEG", quality=95)
                        print(f"  [OK] Saved locally -> {out_path} ({img.size[0]}x{img.size[1]})")
                    return vps_url
                else:
                    print(f"  [WARN] VPS upload failed for Image {idx}. Falling back to local/temp file.")

            # 5. Save locally (Fallback or if VPS not used/failed)
            # Even if save_locally was False, if VPS failed we MUST try to save locally to provide a link/proof
            if not out_folder:
                # If no out_folder provided (Cloud Mode), we use a temp one for this failsafe
                out_folder = os.path.join(os.getcwd(), "failed_vps_uploads")
                os.makedirs(out_folder, exist_ok=True)

            out_path = os.path.join(out_folder, f"image_{idx}.jpg")
            img.save(out_path, format="JPEG", quality=95)
            print(f"  [OK] Saved -> {out_path} ({img.size[0]}x{img.size[1]})")
            return out_path

        except Exception as e:
            print(f"  [ERROR] Image {idx} failed: {e}")
            return ''

    def process_single_product(self, product_id, platform, out_base, api_key, target_width, target_height, do_white_bg, watermark_path, is_template, vps_base_url='', sheet=None, sheet_row_idx=0, product_scale=70, lock_aspect_ratio=True):
        print(f"\n==============================================")
        print(f"[START] Processing {platform} Product ID: {product_id}")

        try:
            image_urls: list[str] = []
            if platform == "Amazon":
                image_urls = self.fetch_amazon_images(product_id, api_key=api_key)
            else:
                image_urls = self.fetch_walmart_images(product_id, api_key=api_key)

            print(f"[FETCH] Found {len(image_urls)} images for {product_id}.")
            
            # STRICT LIMIT: 5 images max
            if len(image_urls) > 5:
                print(f"  [INFO] Limiting from {len(image_urls)} to top 5 images.")
                image_urls = image_urls[:5] # type: ignore

            # If user provided a sheet AND a VPS, we can skip local saving to save space
            save_locally = not (sheet is not None and vps_base_url)
            
            out_folder = ""
            if save_locally:
                out_folder = os.path.join(out_base, f"{platform}_{product_id}")
                os.makedirs(out_folder, exist_ok=True)
                print(f"[INFO] Saving {product_id} results to: {out_folder}")
            else:
                print(f"[INFO] Cloud Mode: Images for {product_id} will be directly uploaded to VPS (Local saving bypassed).")

            vps_folder_name = f"{platform.lower()}_{product_id}"
            result_urls = []

            for idx, url in enumerate(image_urls, start=1):
                # Check for stop signal
                if hasattr(self, 'stop_event') and self.stop_event.is_set(): # type: ignore
                    print(f"[INFO] Process for {product_id} was stopped by user.")
                    break

                # Check for pause signal and wait if necessary
                while hasattr(self, 'pause_event') and self.pause_event.is_set() and not self.stop_event.is_set(): # type: ignore
                    time.sleep(0.5)

                if hasattr(self, 'stop_event') and self.stop_event.is_set(): # type: ignore
                    print(f"[INFO] Process for {product_id} was stopped by user during pause.")
                    break

                is_first = (idx == 1)
                final_url = self.process_and_save_image(
                    url, idx, is_first, out_folder,
                    target_width, target_height, do_white_bg,
                    watermark_path, is_template,
                        vps_base_url=vps_base_url,
                        vps_folder_name=vps_folder_name,
                        save_locally=save_locally,
                        product_scale=product_scale,
                        lock_aspect_ratio=lock_aspect_ratio
                    )
                # Slot persistence: Add placeholder if failed so others don't shift
                result_urls.append(final_url if final_url else "")

            # Write results to Google Sheet if configured
            # Filter out empty results to see if we have anything to write
            valid_any = any(u for u in result_urls)
            if sheet is not None and valid_any:
                try:
                    # Strip trailing empty slots for a cleaner string
                    while result_urls and not result_urls[-1]:
                        result_urls.pop()
                    url_str = '|'.join(result_urls)
                    # We look for "Item photo URL" in the header row (row 5)
                    header_row = 5
                    headers = sheet.row_values(header_row)
                    col_idx = None
                    for col_i, h in enumerate(headers, 1):
                        if h.strip().lower() == 'item photo url':
                            col_idx = col_i
                            break
                    
                    if col_idx is None:
                        col_idx = len(headers) + 1
                        sheet.update_cell(header_row, col_idx, 'Item photo URL')
                        print(f"  [INFO] Created 'Item photo URL' column at col {col_idx}")
                    
                    row_num = header_row + sheet_row_idx
                    sheet.update_cell(row_num, col_idx, url_str)
                    print(f"  [OK] Updated Sheet row {row_num} col {col_idx} with {len(result_urls)} VPS URL(s)")
                except Exception as se:
                    print(f"  [WARN] Failed to update Google Sheet: {se}")

        except Exception as e:
            print(f"[FATAL] {product_id} - {str(e)}")

    # --- Runner ---
