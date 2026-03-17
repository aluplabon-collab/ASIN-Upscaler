from PIL import Image
import os
import sys

# Base directory for the script
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# default to looking for a logo.png in the same directory if the specific brain path doesn't exist
png_path = os.path.join(BASE_DIR, "logo.png")
ico_path = os.path.join(BASE_DIR, "icon.ico")

if not os.path.exists(png_path):
    print(f"Warning: {png_path} not found. Searching for any PNG in the current directory...")
    # Try to find any PNG file in the same folder as a fallback
    png_files = [f for f in os.listdir(BASE_DIR) if f.lower().endswith(".png")]
    if png_files:
        png_path = os.path.join(BASE_DIR, png_files[0])
        print(f"Using found PNG: {png_path}")
    else:
        print("Error: No PNG file for conversion found in the script's directory.")
        sys.exit(1)

try:
    img = Image.open(png_path)
    # Ensure it's square if possible, or just save as ICO
    img.save(ico_path, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])
    print(f"Successfully converted and saved to {ico_path}")
except Exception as e:
    print(f"Error converting image: {e}")
