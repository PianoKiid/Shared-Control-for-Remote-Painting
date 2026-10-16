# 폴더 이동 안내

2026-10-16에 기존 파일을 역할별로 정리했습니다. 실험 번호와 데이터 내용은 유지했습니다.

| 이전 위치 | 현재 위치 |
|---|---|
| `Data/6/` … `Data/11/` | `data/raw/6/` … `data/raw/11/` |
| `Data/processed/` | `data/processed/` |
| `results/phase_labeling_all_v2/` | `data/annotations/phase_v2/` |
| `results/work_move_idle_labeling_12_14/labels/` | `data/annotations/work_move_idle_12_14/` |
| `results/work_move_idle_labeling_12_14/trial_data/` | `data/interim/work_move_idle_12_14/` |
| 해당 라벨링 폴더의 나머지 파일 | `results/labeling/work_move_idle_12_14/` |
| `tools/phase_modeling/` | `src/phase_modeling/` |
| `tools/analyze_lopo_transitions.py` | `scripts/analysis/analyze_lopo_transitions.py` |
| `tools/work_move_idle_labeler.py` | `scripts/labeling/work_move_idle_labeler.py` |
| `manual_labeling_12_14/index.html` | `scripts/labeling/ui/index.html` |
| `tools/*wide_format*.mjs` | `scripts/spreadsheets/` |
| `spreadsheet_update_work/*.mjs` | `scripts/spreadsheets/` |
| `spreadsheet_update_work/*.xlsx` | `data/spreadsheets/source_snapshots/` |
| `interview_cleaning_update/` 정리본 | `data/interviews/cleaned/` |
| 인터뷰의 이전 버전 폴더 | `data/interviews/backups/before_sub12-14/` |
| `outputs/01a0e602-…/*.xlsx` | `results/spreadsheets/` |
| `outputs/notion_transfer/plan.html` | `docs/isaac_sim/environment_setup_plan.html` |
| 최상위 phase recognition Word·PDF | `docs/manuscripts/phase_recognition/` |
| `results/paper_outline_phase_learning/`의 Word | `docs/manuscripts/phase_recognition/` |
| `results/phase_learning/paper_outline_html/`의 HTML | `docs/manuscripts/phase_recognition/` |
| 최상위 인수인계 v2 | `docs/research/shared_control_handoff_v2.md` |
| 최상위 이전 인수인계 | `docs/research/archive/shared_control_handoff_v1.md` |
| 최상위 `Related works.docx` | `docs/literature/Related works.docx` |
| `document_review/`의 검토 텍스트·의견 | `docs/reviews/visual_interfaces/` |
| `document_review/extract_outline.py` | `scripts/documents/extract_outline.py` |
| `document_review/compare_qualitative_counts.mjs` | `scripts/spreadsheets/compare_qualitative_counts.mjs` |
| `tmp/*.py`, `tmp/*.ps1`, `tmp/*.vbs` | `scripts/reporting/` |
| `tmp/pdfs/`의 문헌 텍스트 | `docs/literature/extracted_text/` |
| `tmp/held_out_07_apa_render/`의 PDF | `results/phase_learning/final_lopo/held_out_07_report/` |
| `tmp/lopo_doc_render/`의 PDF | `results/phase_learning/final_lopo/results/tolerant_3s/` |

## 경로를 찾을 때

현재 코드가 참조하는 경로와 라벨링 manifest·내보내기 정보는 수정했습니다.
과거 JSON·CSV·NPZ와 연구 기록의 경로는 생성 당시 출처를 나타내므로 일괄 변경하지 않았습니다.

기존 `node_modules` 연결 3개는 `scripts/node_modules` 하나로 통합했습니다.
연결 대상인 외부 공용 라이브러리는 변경하지 않았습니다.

## 정리 후 확인

- 경로·안내 문서를 수정한 파일과 열려 있는 문서를 제외한 기존 파일 858개의 SHA-256이 이동 전과 일치했습니다.
- 이후 사용자가 저장하고 닫은 `Related works.docx`도 이동했으며, 저장된 최신 파일의 이동 전후 SHA-256이 일치했습니다.
- 라벨링 화면과 데이터 응답 처리에서 기존 12개 trial의 경로를 읽었습니다.
- phase 데이터 22개 trial을 찾고, 그중 `06_01`의 3개 연속 구간을 읽었습니다.
- 저장된 Causal LSTM을 불러와 8개 frame에서 유효한 확률 출력을 확인했습니다.
- Python 14개, JavaScript 8개, PowerShell 2개 파일의 문법과 안내 문서의 로컬 링크를 확인했습니다.
- 엑셀 도구의 Node 라이브러리 연결과 입력·출력 폴더 경로를 확인했습니다.

실험 데이터를 다시 가공하거나 학습·결과 내보내기를 실행하지 않았습니다.
브라우저와 서버 간 실제 통신은 실행 환경의 로컬 소켓 제한으로 확인하지 못했으며,
화면·데이터 응답 처리는 서버 내부에서 직접 호출해 확인했습니다.
