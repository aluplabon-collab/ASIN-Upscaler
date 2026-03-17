import requests
import json
import time

API_KEY = "ca4ee8579ab0b0373df8997a4de8b146" # Assuming test API key is fine to capture response, or we'll prompt the user for their API Key
PRODUCT_ID = "363812242"
URL = f"https://www.walmart.com/ip/{PRODUCT_ID}"

def test_scraper(render_val, premium_val):
    print(f"\n--- Testing render={render_val}, premium={premium_val} ---")
    params = {
        'api_key': API_KEY,
        'url': URL,
        'country_code': 'us'
    }
    if render_val: params['render'] = render_val
    if premium_val: params['premium'] = premium_val

    try:
        resp = requests.get('https://api.scraperapi.com', params=params, timeout=60)
        print(f"Status Code: {resp.status_code}")
        if resp.status_code == 200:
            print("SUCCESS! Length:", len(resp.text))
            # Just rough check if we got content
            if "walmart" in resp.text.lower():
                print("Content seems valid.")
            return True
        else:
            print(f"Failed. Snippet: {resp.text[:200]}")
    except Exception as e:
        print(f"Request Error: {e}")
    return False

if __name__ == "__main__":
    test_scraper('true', None)
    test_scraper('true', 'true')
    test_scraper(None, 'true')
    test_scraper(None, None)
