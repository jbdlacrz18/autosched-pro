@echo off
echo Installing required Python packages (Flask, Pandas, Openpyxl, Xlsxwriter)...
py -m pip install flask pandas openpyxl xlsxwriter || python3 -m pip install flask pandas openpyxl xlsxwriter || python -m pip install flask pandas openpyxl xlsxwriter

echo.
echo Starting AutoSched Pro...
py app.py || python3 app.py || python app.py
pause
