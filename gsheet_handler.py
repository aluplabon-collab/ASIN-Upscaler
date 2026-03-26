import gspread
from google.oauth2 import service_account
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
import os
import sys
import time
from typing import Any, Dict, List, cast

class GSheetHandler:
    def __init__(self, json_keyfile_path, token_name="token.json"):
        self.scope = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive',
            'https://www.googleapis.com/auth/userinfo.email',
            'openid'
        ]
        
        # Cache key: (sheet_id, sheet_name) -> worksheet object
        self._sheet_cache = {}
        # Cache key: (sheet_id, sheet_name) -> headers list
        self._headers_cache = {}
        
        # Determine if it's a Service Account or User Credentials based on file content or just try both
        # For simplicity, if json file has "type": "service_account", use SA.
        # Otherwise, assume it's "installed" (Client ID) for User Auth.
        
        is_service_account = False
        try:
            with open(json_keyfile_path, 'r') as f:
                content = f.read()
                if '"type": "service_account"' in content:
                    is_service_account = True
        except:
            pass # Invalid path or file, will fail later anyway

        if is_service_account:
            try:
                self.creds = service_account.Credentials.from_service_account_file(json_keyfile_path, scopes=self.scope)
            except Exception as e:
                raise Exception(f"Service Account Auth Failed: {e}")
        else:
            # User Credentials Flow
            self.creds = None
            import license_utils
            base_dir = license_utils.get_app_data_path()
                
            token_dir = os.path.join(base_dir, 'tokens')
            
            if not os.path.exists(token_dir):
                os.makedirs(token_dir)
                
            token_path = os.path.join(token_dir, token_name) if token_name else None
            
            # Load existing token if valid
            if token_path and os.path.exists(token_path):
                try:
                    self.creds = Credentials.from_authorized_user_file(token_path, self.scope)
                except:
                    self.creds = None

            # Refresh or Login
            if not self.creds or not self.creds.valid:
                if self.creds and self.creds.expired and self.creds.refresh_token:
                    try:
                        self.creds.refresh(Request())
                    except:
                        self.creds = None
                
                if not self.creds:
                    if not os.path.exists(json_keyfile_path):
                         raise Exception("Credentials JSON file not found.")
                         
                    try:
                        flow = InstalledAppFlow.from_client_secrets_file(json_keyfile_path, self.scope)
                        self.creds = flow.run_local_server(port=0)
                    except Exception as e:
                         raise Exception(f"User Auth Failed: {e}")
                    
                    if not token_name:
                        import requests
                        try:
                            resp = requests.get('https://www.googleapis.com/oauth2/v2/userinfo', headers={'Authorization': f'Bearer {self.creds.token}'})
                            email = resp.json().get('email', 'unknown_user')
                        except Exception:
                            email = "unknown_user"
                        token_name = f"{email}.json"
                        token_path = os.path.join(token_dir, token_name)
                    
                    # Save token
                    if token_path:
                        with open(token_path, 'w') as token:
                            token.write(self.creds.to_json())

            self.token_name = token_name

        self.client = gspread.authorize(self.creds)

    @staticmethod
    def retry_with_backoff(func):
        def wrapper(*args, **kwargs):
            max_retries = 5
            base_delay = 2 # seconds
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except gspread.exceptions.APIError as e:
                    # Check if it's a 429 error (Quota exceeded)
                    # APIError args usually tuple: (response, error_dict)
                    # response.status_code should be 429
                    code = 0
                    try:
                        code = e.response.status_code
                    except:
                        pass
                        
                    if code == 429 or "429" in str(e):
                        delay = base_delay * (2 ** attempt)
                        print(f"Rate limited (429). Retrying in {delay}s...")
                        time.sleep(delay)
                    else:
                        raise e # Not a rate limit error
                except Exception as e:
                    # Generic retry for connection issues?
                    # For now, just re-raise unless we are sure it's transient
                    raise e
            raise Exception("Max retries exceeded for Google Sheet API.")
        return wrapper

    @retry_with_backoff
    def get_sheet(self, sheet_id, sheet_name):
        """Opens a sheet by ID and Name, with caching."""
        cache_key = (sheet_id, sheet_name)
        if cache_key in self._sheet_cache:
            return self._sheet_cache[cache_key]
            
        try:
            spreadsheet = self.client.open_by_key(sheet_id)
            try:
                sheet = spreadsheet.worksheet(sheet_name)
            except gspread.WorksheetNotFound:
                # If not found, imply it might be the first one or create it? 
                # For now, let's just fail or try default
                sheet = spreadsheet.sheet1
            
            self._sheet_cache[cache_key] = sheet
            return sheet
        except Exception as e:
            raise Exception(f"Failed to open sheet: {e}")

    @retry_with_backoff
    def read_asins(self, sheet_id, sheet_name, col_index=1):
        """Reads ASINs from a specific column (default column A/1)."""
        sheet = self.get_sheet(sheet_id, sheet_name)
        # Assuming ASINs are in the first column, skipping header if exists
        vals = sheet.col_values(col_index)
        
        # Simple heuristic: if first row looks like a header, skip it
        if vals and vals[0] and ("asin" in str(vals[0]).lower() or "id" in str(vals[0]).lower()):
            vals = vals[1:]
            
        return [str(v).strip() for v in vals if v and str(v).strip()]

    @retry_with_backoff
    def init_headers(self, sheet_id, sheet_name):
        """Ensures headers exist."""
        sheet = self.get_sheet(sheet_id, sheet_name)
        # Import here to avoid circular dependency at top level if any
        try:
            from amazon_scraper import AmazonScraper # type: ignore
            target_headers = AmazonScraper.CSV_HEADERS
        except ImportError:
            # Fallback headers if amazon_scraper is missing
            target_headers = ["ASIN", "Title", "Price", "Description", "Item photo URL", "Item URL"]
        
        # Check if first row is empty or doesn't match
        # We can try to use cache if we have it, but init_headers usually implies we want to be sure
        first_row = sheet.row_values(1)
        
        if not first_row:
            sheet.insert_row(target_headers, 1)
            self._headers_cache[(sheet_id, sheet_name)] = target_headers
        else:
            self._headers_cache[(sheet_id, sheet_name)] = first_row

    @retry_with_backoff
    def ensure_row(self, sheet_id, sheet_name, asin):
        """Finds row for ASIN or creates a new one. Returns row index. Support duplicates if existing rows are filled."""
        sheet = self.get_sheet(sheet_id, sheet_name)
        
        # Get headers to find "Custom label (SKU)" column
        cache_key = (sheet_id, sheet_name)
        if cache_key in self._headers_cache:
            headers = self._headers_cache[cache_key]
        else:
            headers = sheet.row_values(1)
            if not headers:
                 self.init_headers(sheet_id, sheet_name)
                 headers = sheet.row_values(1)
            self._headers_cache[cache_key] = headers

        # Find column index for "Custom label (SKU)"
        col_idx = 1 # Default to A
        try:
             col_idx = headers.index("Custom label (SKU)") + 1
        except ValueError:
             col_idx = 2 
        
        # Get all ASINs in that column
        col_vals = sheet.col_values(col_idx)
        
        # Find all indices where ASIN matches
        # enumerate starts at 1 if we want 1-based index? No, enumerate is 0-based.
        matching_rows = [i + 1 for i, x in enumerate(col_vals) if x == asin]
        
        target_row_idx = -1
        
        if matching_rows:
            # Check if any of these rows are "empty" (pending scrape)
            # We check a key column like "Title" (assuming it's a separate column)
            title_col_idx = -1
            try:
                title_col_idx = headers.index("Title") + 1
            except ValueError:
                pass
            
            if title_col_idx != -1:
                # We need to check the Title value for each matching row.
                # Optimized: Fetch specific cells? Or just batch get?
                # Batch get is better but complex to implement with gspread cleanly here without excessive API.
                # Simple loop: check last one first?
                # If we are processing a list, duplicates usually come sequentially.
                # If we have 2 existing filled rows, and we want a 3rd.
                # We check row X. Title filled? Yes.
                # We check row Y. Title filled? Yes.
                # No empty found -> Append new.
                
                # Check backwards?
                for r_idx in reversed(matching_rows):
                    title_val = sheet.cell(r_idx, title_col_idx).value
                    if not title_val:
                        target_row_idx = r_idx
                        break
            else:
                # No Title column? Just take the last one?
                # If we can't verify "filled", we might overwrite.
                # Safe fallback: If found, assume we want to update it?
                # But requirement says "don't ignore duplicate".
                # If we can't check emptiness, we must assume filled and append?
                target_row_idx = -1 # Force append

        if target_row_idx != -1:
            return target_row_idx
        else:
            # Append new row
            row_data = [''] * len(headers)
            if "Custom label (SKU)" in headers:
                row_data[headers.index("Custom label (SKU)")] = asin
            if "C:ASIN" in headers:
                 row_data[headers.index("C:ASIN")] = asin
                 
            sheet.append_row(row_data)
            # Return new row index
            # Since we cached col_vals length could be stale if concurrent?
            # But single worker usually.
            # Best to trust len(col_vals) + 1 if we assume we are at end?
            # Actually col_vals from earlier + 1 is safe enough.
            return len(col_vals) + 1

    @retry_with_backoff
    def update_row_data(self, sheet_id: str, sheet_name: str, row_idx: int, asin: str, data: Dict[str, Any]):
        """Updates a specific row with data."""
        sheet = self.get_sheet(sheet_id, sheet_name)
        cache_key = (sheet_id, sheet_name)
        
        # Get headers
        raw_headers = []
        if cache_key in self._headers_cache:
            raw_headers = self._headers_cache[cache_key]
        else:
            raw_headers = sheet.row_values(1)
            self._headers_cache[cache_key] = raw_headers
        
        headers: List[str] = cast(List[str], raw_headers)

        # Prepare row data dictionary
        row_dict: Dict[str, Any] = {}
         # Map Scraper Data
        row_dict['Custom label (SKU)'] = asin
        row_dict['C:ASIN'] = asin
        row_dict['Title'] = data.get('Title', '')
        row_dict['Price'] = data.get('Price', '')
        row_dict['Description'] = data.get('Description', '')
        row_dict['Item photo URL'] = data.get('Item photo URL', '')
        row_dict['Item URL'] = data.get('Item URL', '')
        
        for k, v in data.items():
            if k in headers:
                row_dict[k] = v

        # Construct values list
        row_values = []
        for h in headers:
             row_values.append(row_dict.get(h, ''))

        # Update the row
        sheet.update(range_name=f"A{row_idx}", values=[row_values])

