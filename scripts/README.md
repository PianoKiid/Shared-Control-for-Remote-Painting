# 실행 도구

프로젝트 최상위에서 아래 경로로 실행합니다.

| 위치 | 역할 |
|---|---|
| `labeling/work_move_idle_labeler.py` | 참여자 12–14 라벨링 서버, 전처리와 결과 내보내기 |
| `labeling/ui/index.html` | 라벨링 화면 |
| `analysis/analyze_lopo_transitions.py` | 저장된 Causal LSTM을 이용한 전환 분석 |
| `spreadsheets/` | WIDE·인터뷰 엑셀 검사, 갱신, 비교 |
| `reporting/` | LOPO 그림·표·Word 문서와 PDF 생성 |
| `documents/extract_outline.py` | 검토 문서의 텍스트 추출 |
| `project_paths.mjs` | 엑셀 도구에서 사용하는 프로젝트 경로 계산 |

`reporting/build_lopo_08_01_timeline.py`는 그림만 읽는 도구가 아닙니다.
일부 모델을 학습하고 예측 결과를 다시 작성하므로 필요할 때 실행합니다.

Word/PDF 생성용 PowerShell·VBS 도구는 Windows와 Microsoft Word를 사용합니다.
문서 추출·인터뷰 검사 도구 일부는 기존 외부 입력 파일을 참조하므로, 다른 PC에서는 입력 경로를 맞춰야 합니다.
