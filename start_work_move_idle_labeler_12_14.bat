@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PYTHON_EXE=C:\Users\USER\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%PYTHON_EXE%" (
  echo Python 실행 파일을 찾지 못했습니다.
  echo %PYTHON_EXE%
  pause
  exit /b 1
)
echo Sub12-14 MCAP 데이터를 준비하고 라벨링 화면을 엽니다.
echo 처음 실행은 MCAP 가공 때문에 시간이 걸릴 수 있습니다.
"%PYTHON_EXE%" "%~dp0scripts\labeling\work_move_idle_labeler.py" prepare-serve
if errorlevel 1 (
  echo.
  echo 실행 중 오류가 발생했습니다.
  pause
)
endlocal
