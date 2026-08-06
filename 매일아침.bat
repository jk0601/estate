@echo off
REM ============================================================
REM  Daily update: watch tracker + 8-eok radar, then commit & push.
REM  Just double-click this file once a morning. Takes 10-15 min.
REM
REM  NOTE: keep this file ASCII-only.
REM  cmd.exe reads a .bat with the console codepage; mixing
REM  "chcp 65001" with multi-byte (Korean) text makes it lose its
REM  place mid-file and run garbage fragments. Korean belongs in
REM  the Python output, not in this file.
REM
REM  collect.py (input-scheduled complex list) is NOT run here.
REM  It only changes month to month - run it manually now and then.
REM ============================================================
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
set "FAIL_WATCH="
set "FAIL_RADAR="

echo.
echo ============================================================
echo  [1/2] watch/scrape.py  - maemae/jeonse listings
echo ============================================================
python watch\scrape.py
if errorlevel 1 set "FAIL_WATCH=1"

echo.
echo ============================================================
echo  [2/2] radar.py  - real deals + court auction + onbid
echo ============================================================
python radar.py
if errorlevel 1 set "FAIL_RADAR=1"

echo.
echo ============================================================
echo  git commit and push
echo ============================================================
git add docs/watch_data.json docs/radar_data.json docs/data.json
git diff --cached --quiet
if errorlevel 1 goto do_commit
echo  nothing changed - skipping commit
goto done

:do_commit
git commit -m "daily update: watch + radar"
git push
if errorlevel 1 echo  !! push failed - data is saved, push later by hand

:done
echo.
if defined FAIL_WATCH echo  !! watch/scrape.py FAILED
if defined FAIL_RADAR echo  !! radar.py FAILED
if not defined FAIL_WATCH if not defined FAIL_RADAR echo  collection finished with no errors.
echo.
echo  Press any key to close.
pause >nul
