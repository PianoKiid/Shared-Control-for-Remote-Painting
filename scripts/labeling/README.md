# Sub12-14 WORK / MOVE / IDLE 라벨링

1. 프로젝트 최상위 폴더의 start_work_move_idle_labeler_12_14.bat를 더블클릭합니다.
2. 브라우저에서 각 실험의 구간을 선택하고 WORK, MOVE, IDLE 중 하나를 누릅니다.
3. 실험마다 저장을 누릅니다. 미라벨 구간은 UNLABELED로 남습니다.
4. 필요한 라벨링이 끝나면 '결과 계산 · 엑셀 복사본 업데이트'를 누릅니다.

중요 규칙
- 원본 MCAP와 원본 WIDE 엑셀은 수정하지 않습니다.
- 14-MP는 첫 번째 파일 뒤에 두 번째 파일을 이어서 보여줍니다.
- 파일 경계와 자동 감지된 통신 단절 경계에서는 거리/속도를 연결하지 않습니다.
- IDLE은 검토용 라벨 기록에는 남지만 모델용 NPZ와 작업/이동 지표에서는 제외됩니다.
- 작업/이동 평균 거리는 같은 상태의 각 구간별 거리의 산술평균입니다.
- 작업/이동 평균 속도는 같은 상태의 각 구간별 평균속도의 산술평균입니다.

주요 결과 위치
- 라벨/구간 기록: data\annotations\work_move_idle_12_14
- 지표: results\labeling\work_move_idle_12_14\metrics
- 모델용 데이터: data\processed\work_move_idle_v1
- WIDE 엑셀 복사본: results\spreadsheets\원격도장작업실험_0720_Wide Format_12-14추가.xlsx

- 화면용 중간 데이터: `data/interim/work_move_idle_12_14/`
- 서버 코드: `scripts/labeling/work_move_idle_labeler.py`
- 화면 코드: `scripts/labeling/ui/index.html`

프로젝트 최상위에서 `python scripts/labeling/work_move_idle_labeler.py serve`로 기존 준비 데이터를 열 수 있습니다.
