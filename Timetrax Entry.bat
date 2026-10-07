@echo off
rem Double-click this file to open Timetrax Entry.
rem Finds Python on this computer, installs the two add-ons it needs the first
rem time, then opens the window without a console.
setlocal
cd /d "%~dp0"
title Timetrax Entry

rem Python 3.10 or newer: the py launcher first, then python on PATH, then the
rem usual install folders. The Microsoft Store placeholder fails the test run.
set "PY="
call :try py -3
if not defined PY call :try python
if not defined PY for /d %%D in ("%LocalAppData%\Programs\Python\Python3*" "%ProgramFiles%\Python3*" "C:\Python3*") do if not defined PY call :try "%%~D\python.exe"
if not defined PY goto nopython

%PY% -c "import pywinauto, pypdf" >nul 2>nul
if not errorlevel 1 goto launch
echo.
echo Timetrax Entry needs two add-ons for Python: pywinauto and pypdf.
echo This is needed once per computer and uses the internet.
echo.
choice /m "Install them now"
if errorlevel 2 exit /b
%PY% -m pip install --user pywinauto pypdf
%PY% -c "import pywinauto, pypdf" >nul 2>nul
if not errorlevel 1 goto launch
echo.
echo The add-ons did not install. Ask IT to run this on this computer:
echo     python -m pip install pywinauto pypdf
echo.
pause
exit /b

:launch
rem pythonw.exe sits next to python.exe and runs without a console window.
set "PYW="
%PY% -c "import sys, os; print(os.path.join(os.path.dirname(sys.executable), 'pythonw.exe'))" > "%TEMP%\timetrax_entry_pyw.txt" 2>nul
set /p PYW=<"%TEMP%\timetrax_entry_pyw.txt"
del "%TEMP%\timetrax_entry_pyw.txt" >nul 2>nul
if defined PYW if exist "%PYW%" (
    start "" "%PYW%" "%~dp0timetrax_entry.py"
    exit /b
)
start "" /min %PY% "%~dp0timetrax_entry.py"
exit /b

:nopython
echo.
echo Python is not installed on this computer, or Windows cannot find it.
echo.
echo Install Python 3 from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH" during setup, or ask IT to install it.
echo Then double-click Timetrax Entry again.
echo.
pause
exit /b

:try
%* -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=%*"
exit /b
