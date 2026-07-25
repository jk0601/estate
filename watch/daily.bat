@echo off
REM 힐스테이트 메디알레 전세 동향 매일 수집 + GitHub 반영
REM Windows 작업 스케줄러에 이 파일을 매일 1회 등록하세요.
chcp 65001 >nul
cd /d "%~dp0.."
echo [%date% %time%] 전세 동향 수집 시작
python watch\scrape.py
if errorlevel 1 (
  echo 수집 실패 - 종료
  exit /b 1
)
git add docs/watch_data.json
git commit -m "전세 동향 갱신"
git push
echo [%date% %time%] 완료
