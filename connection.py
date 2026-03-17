import os
import gspread
from google.oauth2.service_account import Credentials

# Set the base directory to the same directory as this script
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDS_FILE = os.path.join(BASE_DIR, "image upscaler v2", "credentials.json")

# Using the Sheet ID from the upscaler.py file for testing
SHEET_ID = "1_9cfiZT92a-1Whj3v5H71v-yKxjwyqx0Rqc5TGpiEw0"

def test_connection():
    print("=== Google Sheets Connection Test ===")
    print(f"Looking for credentials at: {CREDS_FILE}")
    
    if not os.path.exists(CREDS_FILE):
        print("ERROR: credentials.json not found!")
        return

    try:
        # Load credentials
        creds = Credentials.from_service_account_file(
            CREDS_FILE,
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        print("Loaded credentials successfully")

        # Authorize client
        client = gspread.authorize(creds)
        print("Authorized gspread client")

        # Open sheet
        print(f"Attempting to open spreadsheet with ID: {SHEET_ID}")
        ss = client.open_by_key(SHEET_ID)
        print(f"Connected successfully to Spreadsheet: '{ss.title}'")

        # Access first worksheet
        ws = ss.worksheet("Sheet3")
        print(f"Accessed Worksheet: '{ws.title}'")

        print("Writing to A1...")
        ws.update_acell("A1", "connected")
        print("Successfully wrote 'connected' to cell A1")

        print("\nSUCCESS: Connection is working perfectly!")

    except Exception as e:
        print(f"\nERROR: Connection failed!")
        print(f"Details: {str(e)}")

if __name__ == "__main__":
    test_connection()
