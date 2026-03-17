@echo off
echo ====================================
echo  Rebuilding Obfuscated Executables...
echo ====================================
call build_obfuscated_executable.bat

echo.
echo ====================================
echo  Starting Git Push...
echo ====================================
set /p commit_msg="Enter commit message (default: Update): "
if "%commit_msg%"=="" set commit_msg=Update

echo.
echo [1/3] Staging changes...
git add .

echo [2/3] Committing changes...
git commit -m "%commit_msg%"

echo [3/3] Pushing to main...
git push origin main

echo.
echo ====================================
echo  Build and Git Push Complete!
echo ====================================
pause
