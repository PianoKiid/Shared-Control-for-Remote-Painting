# 데이터

| 위치 | 내용 |
|---|---|
| `raw/6/` … `raw/11/` | 이전 `Data/6/` … `Data/11/`의 MCAP와 metadata.yaml |
| `processed/phase_model_inputs_v1/` | phase learning의 12차원 입력과 라벨 snapshot |
| `processed/work_move_idle_v1/` | WORK/MOVE/IDLE 작업에서 내보낸 모델용 NPZ |
| `annotations/phase_v2/` | 수동 phase 라벨, 구간, 수정 이력, 이전 자동 라벨 |
| `annotations/work_move_idle_12_14/` | 참여자 12–14의 수동 WORK/MOVE/IDLE 라벨 |
| `interim/work_move_idle_12_14/` | 라벨링 화면용 JSON·NPZ |
| `interviews/cleaned/` | 정리한 인터뷰 텍스트 |
| `interviews/backups/before_sub12-14/` | 참여자 12–14 반영 전 인터뷰 정리본 |
| `spreadsheets/source_snapshots/` | 엑셀 가공 전 원본 사본 |

두 라벨 체계는 다릅니다. `phase_v2`는 FREE_MOTION / APPROACH / PAINTING / RETRACT,
`work_move_idle_12_14`는 WORK / MOVE / IDLE입니다.

원본 데이터와 수동 라벨은 덮어쓰지 않습니다. 가공된 파일은 `processed/` 또는 `interim/`에 저장합니다.
참여자·trial 번호와 각 실험 폴더 내부 파일명은 기존 값을 유지했습니다.

참여자 12–14의 MCAP 원본은 이 폴더에 복사하지 않았습니다. 라벨링 도구에서 기존 외부 실험 폴더를 읽습니다.
