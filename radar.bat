@echo off
REM 8억 레이더: 실거래 + 법원경매 + 온비드 공매 수집 후 GitHub 반영
REM 하루 1회 더블클릭하거나, Windows 작업 스케줄러에 등록하세요.
chcp 65001 >nul
cd /d "%~dp0"
echo [%date% %time%] 8억 레이더 수집 시작

REM 경매/공매만 빠르게 돌리려면 아래 줄에 --no-deals 를 붙이세요.
python radar.py
if errorlevel 1 (
  echo 수집 실패 - 종료
  pause
  exit /b 1
)

git add docs/radar_data.json
git commit -m "8억 레이더 갱신"
git push
echo [%date% %time%] 완료
