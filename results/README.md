# 연구 결과

| 위치 | 내용 |
|---|---|
| `phase_learning/final_lopo/models/` | LOPO fold별 모델 |
| `phase_learning/final_lopo/results/strict_original/` | strict 기준 평가 결과 |
| `phase_learning/final_lopo/results/buffered_1s/` | 1초 buffer 기준 평가 결과 |
| `phase_learning/final_lopo/results/tolerant_3s/` | ±3초 tolerance 기준 결과와 관련 보고서 |
| `phase_learning/final_lopo/held_out_07_report/` | held-out 07의 표·재생 화면·보고서 |
| `phase_learning/final_lopo/replay_data/` | 재생용 데이터 |
| `phase_learning/transition_aware_analysis/` | shared-control 전환 관점의 분석 |
| `phase_learning/paper_3s_results/` | 논문용 그림과 표 |
| `labeling/work_move_idle_12_14/` | 라벨링 진행 정보, 내보내기 기록과 계산 지표 |
| `spreadsheets/` | 참여자 12–14를 반영한 WIDE·인터뷰 최종 엑셀 |

실험별 내부 구조는 유지했습니다. 수동 라벨과 라벨링 화면용 데이터만 각각
`data/annotations/`, `data/interim/`으로 분리했습니다.

평가 기준이 다른 결과를 섞어 비교하지 않습니다. 기존 결과는 유지하고 새로운 실행은
별도 실험 이름으로 저장하는 것을 권장합니다.
