@echo off
rem Change directory to the location of this bat file
cd /d "%~dp0"

echo ============================================================
echo  Installing Required Dependencies for Upscaler Project
echo ============================================================
echo.

echo [1/2] Upgrading pip to the latest version...
python -m pip install --upgrade pip
echo.

echo [2/2] Installing modules from requirements.txt...
pip install -r requirements.txt
echo.

echo ============================================================
echo  Installation Complete! You can now run the Python scripts.
echo ============================================================
pause
