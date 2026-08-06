@echo off
REM ============================================================
REM  Watch tracker only: daily maemae/jeonse listings for the
REM  complexes in watch/scrape.py, then commit & push.
REM  (Full daily run: use the morning .bat in the repo root.)
REM
REM  NOTE: keep this file ASCII-only. cmd.exe reads a .bat with the
REM  console codepage, so "chcp 65001" + Korean text in the file
REM  makes the parser lose its place and run garbage fragments.
REM ============================================================
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0.."

echo [%date% %time%] watch/scrape.py start
python watch\scrape.py
if errorlevel 1 (
  echo  !! scrape.py failed
  pause
  exit /b 1
)

git add docs/watch_data.json
git diff --cached --quiet
if errorlevel 1 goto do_commit
echo  nothing changed - skipping commit
goto done

:do_commit
git commit -m "watch update"
git push
if errorlevel 1 echo  !! push failed - data is saved, push later by hand

:done
echo [%date% %time%] finished
