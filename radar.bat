@echo off
REM ============================================================
REM  8-eok radar only: real deals + court auction + onbid,
REM  then commit & push. (Full daily run: use the other .bat)
REM  Add --no-deals below to skip the slow real-deal scan.
REM
REM  NOTE: keep this file ASCII-only. cmd.exe reads a .bat with the
REM  console codepage, so "chcp 65001" + Korean text in the file
REM  makes the parser lose its place and run garbage fragments.
REM ============================================================
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

echo [%date% %time%] radar.py start
python radar.py
if errorlevel 1 (
  echo  !! radar.py failed
  pause
  exit /b 1
)

python -c "import json; json.load(open('docs/radar_data.json',encoding='utf-8'))"
if errorlevel 1 (
  echo  !! radar_data.json invalid - NOT committing
  pause
  exit /b 1
)

git add docs/radar_data.json
git diff --cached --quiet
if errorlevel 1 goto do_commit
echo  nothing changed - skipping commit
goto done

:do_commit
git commit -m "radar update"
git pull --rebase origin main
if errorlevel 1 (
  echo  !! git pull --rebase failed - fix conflicts then push by hand
  goto done
)
git push
if errorlevel 1 echo  !! push failed - data is saved, push later by hand

:done
echo [%date% %time%] finished
