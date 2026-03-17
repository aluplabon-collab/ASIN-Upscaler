import requests
import json
import os

from dotenv import load_dotenv

# Try to get the real API key from the local environment
load_dotenv(os.path.join(os.path.dirname(__file__), "image upscaler v2", ".env"))
API_KEY = os.environ.get("SCRAPER_API_KEY", "b423be93bd855633bdfc59cfadeec090") # fallback to the one in background.js if found, else just prompting

PRODUCT_ID = "363812242"
URL = f"https://api.scraperapi.com/structured/walmart/product?api_key={API_KEY}&PRODUCT_ID={PRODUCT_ID}&premium=true"

print(f"Testing URL: {URL.replace(API_KEY, 'SECRET')}")
try:
    resp = requests.get(URL, timeout=60)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        with open("structured_walmart_response.json", "w") as f:
            json.dump(data, f, indent=2)
        print("Success! Saved response to structured_walmart_response.json")
        print("Keys:", list(data.keys()))
        
        # Look for images
        images = []
        if 'images' in data:
            images = data['images']
            print(f"Found {len(images)} images in 'images' key: {images[:2]}")
        else:
            print("No 'images' key found.")
    else:
        print("Failed:", resp.text[:200])
except Exception as e:
    print("Error:", e)
