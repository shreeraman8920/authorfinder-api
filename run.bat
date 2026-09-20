@echo off
echo.
echo ==========================================
echo   AuthorFinder - Extract Author Info
echo ==========================================
echo.
set /p URL="Paste article URL: "
echo.
python -m authorfinder.cli "%URL%" --delay 1.5 --timeout 25
echo.
pause
