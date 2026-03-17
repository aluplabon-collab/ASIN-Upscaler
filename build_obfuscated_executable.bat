@echo off
set "PYTHON_EXE=.venv\Scripts\python.exe"

echo ============================================================
echo  Installing all required dependencies including PyArmor...
echo ============================================================
echo.

echo [Step 1] Upgrading pip...
%PYTHON_EXE% -m pip install --upgrade pip --no-warn-script-location

echo.
echo [Step 2] Installing core packages (requests, Pillow)...
%PYTHON_EXE% -m pip install requests Pillow --no-warn-script-location

echo.
echo [Step 3] Installing rembg with ALL extras (cpu + cli)...
%PYTHON_EXE% -m pip install "rembg[cpu,cli]" --no-warn-script-location

echo.
echo [Step 4] Installing Google API libraries...
%PYTHON_EXE% -m pip install gspread google-auth google-auth-oauthlib python-dotenv --no-warn-script-location

echo.
echo [Step 5] Installing PyInstaller and PyArmor (obfuscation tools)...
%PYTHON_EXE% -m pip install pyinstaller pyarmor --no-warn-script-location

echo.
echo ============================================================
echo  All dependencies installed! Starting obfuscation...
echo ============================================================
echo.

if exist "obfuscated" rmdir /s /q "obfuscated"
mkdir "obfuscated"

echo [Step 6] Running PyArmor to obfuscate...
%PYTHON_EXE% -m pyarmor.cli gen -O "obfuscated" product_image_processor.py image_processor_core.py gsheet_handler.py
%PYTHON_EXE% -m pyarmor.cli gen -O "obfuscated/keygen" keygen.py
copy "license_utils.py" "obfuscated"
copy "license_utils.py" "obfuscated\keygen"

echo.
echo ============================================================
echo  Starting build with PyInstaller...
echo ============================================================
echo.

cd "obfuscated"

echo [Building Main Project...]
%PYTHON_EXE% -m PyInstaller ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --name "Image_Processor_Obfuscated" ^
    --icon "..\icon.ico" ^
    --add-data "..\icon.ico;." ^
    --collect-all tkinter ^
    --hidden-import license_utils ^
    --hidden-import image_processor_core ^
    --hidden-import onnxruntime ^
    --hidden-import onnxruntime.capi._pybind_state ^
    --hidden-import click ^
    --hidden-import filetype ^
    --hidden-import pymatting ^
    --hidden-import pooch ^
    --hidden-import watchdog ^
    --hidden-import scipy ^
    --hidden-import skimage ^
    --hidden-import gspread ^
    --hidden-import google.oauth2.service_account ^
    --hidden-import google_auth_oauthlib.flow ^
    --hidden-import google.oauth2.credentials ^
    --hidden-import gsheet_handler ^
    --collect-all rembg ^
    --collect-all onnxruntime ^
    --collect-all pycparser ^
    --copy-metadata pymatting ^
    --collect-data certifi ^
    product_image_processor.py

echo [Building Keygen...]
cd "keygen"
%PYTHON_EXE% -m PyInstaller ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --name "Image_Processor_Keygen" ^
    --icon "..\..\icon.ico" ^
    --collect-all tkinter ^
    --hidden-import license_utils ^
    keygen.py
cd ..

cd ..

echo.
echo ============================================================
echo  Build complete!
echo  Find the executables inside "obfuscated\dist" and "obfuscated\keygen\dist".
echo  Run "Image_Processor_Obfuscated.exe" and "Image_Processor_Keygen.exe" directly.
echo ============================================================
pause
