---
description: rebuild obfuscated executables for the Upscaler Project
---

# Rebuild Obfuscated Executables (Upscaler Project)

Run after every code change to `product_image_processor.py`, `image_processor_core.py`, `gsheet_handler.py`, or `keygen.py`.

// turbo
1. Run the build script:
```
cmd.exe /c "d:\Others\Work\Prace BD\Development\Upscaler Project\build_obfuscated_executable.bat"
```
   - Wait for exit code 0 and the final "Build complete!" message.

// turbo
2. Run the AmazonScraper build script (if scraper files were also changed):
```
cmd.exe /c "d:\Others\Work\Prace BD\Development\AmazonScraper - Copy\build_obfuscated.bat"
```
   - Wait for "=== Build complete ===" message.

3. Confirm output files exist:
   - `d:\Others\Work\Prace BD\Development\Upscaler Project\obfuscated\dist\Image_Processor_Obfuscated.exe`
   - `d:\Others\Work\Prace BD\Development\Upscaler Project\obfuscated\keygen\dist\Image_Processor_Keygen.exe`
   - `d:\Others\Work\Prace BD\Development\AmazonScraper - Copy\obfuscated\AmazonScraper.exe` (if scraper rebuilt)
