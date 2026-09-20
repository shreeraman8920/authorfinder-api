@echo off
echo ============================================
echo   AuthorFinder - Build Standalone .exe
echo ============================================
echo.

echo [1/3] Installing build dependencies...
pip install pyinstaller openpyxl -q
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)

echo [2/3] Building .exe with PyInstaller...
pyinstaller build.spec --clean -q
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: PyInstaller build failed.
    pause
    exit /b 1
)

echo [3/3] Done!
echo.
echo Your .exe is at: dist\AuthorFinder.exe
echo.
pause
