# Shared Control for Remote Painting

원격 도장 작업의 상태 인식과 shared control 연구를 위한 작업 폴더입니다.
현재는 실험 데이터, 수동 라벨, phase learning 코드와 결과, 연구 문서, Isaac Sim 환경 구축 계획을 보관합니다.

## 폴더 안내

| 폴더 | 넣는 내용 |
|---|---|
| [data/](data/README.md) | 실험 원본, 전처리 데이터, 수동 라벨, 인터뷰와 엑셀 원본 사본 |
| [src/](src/phase_modeling/README.md) | 여러 실행 도구에서 함께 사용하는 상태 인식 모델 코드 |
| [scripts/](scripts/README.md) | 라벨링, 분석, 엑셀 처리, 보고서 생성 도구 |
| [results/](results/README.md) | 학습·평가 결과, 저장된 모델, 최종 엑셀과 분석 보고서 |
| [docs/](docs/README.md) | 연구 방향, 논문 초안, 문헌 정리, 검토 의견, 개발 계획 |
| [simulation/](simulation/README.md) | 앞으로 구축할 Isaac Sim 장면·모델·실행 코드 |

```text
data/
  raw/                      # 참여자 6–11의 기존 MCAP 원본
  processed/                # 모델 입력용으로 가공한 데이터
  annotations/              # 사람이 부여한 라벨과 수정 이력
  interim/                  # 라벨링 화면용 중간 데이터
  interviews/               # 인터뷰 정리본과 이전 버전
  spreadsheets/             # 엑셀 처리에 사용한 원본 사본
src/
  phase_modeling/           # FSM, GMM/HMM 계열, Random Forest, Causal LSTM
scripts/
  analysis/                 # 상태 전환 분석
  labeling/                 # WORK/MOVE/IDLE 라벨링 서버와 화면
  spreadsheets/             # 엑셀 검사·갱신
  reporting/                # 그림·표·Word·PDF 생성
  documents/                # 문서 텍스트 추출
results/
  phase_learning/           # 기존 LOPO 실험 묶음
  labeling/                 # 라벨링 진행 정보와 계산 지표
  spreadsheets/             # 최종 엑셀
docs/
  research/                 # 연구 방향과 인수인계 기록
  manuscripts/              # 논문 초안과 개요
  literature/               # 관련 연구와 문헌 발췌
  reviews/                  # 문서 검토 의견
  isaac_sim/                # 환경 구축 계획
  project/                  # 폴더 이동 안내
simulation/
  README.md                 # Isaac Sim 파일 배치 규칙
```

## 자주 찾는 자료

- **현재 연구 방향:** [shared control 인수인계 v2](docs/research/shared_control_handoff_v2.md)
- **Isaac Sim 환경 구축 계획:** [HTML 문서](docs/isaac_sim/environment_setup_plan.html) — 내려받아 브라우저로 열 수 있습니다.
- **논문 초안:** [phase recognition 문서](docs/manuscripts/phase_recognition/)
- **수동 phase 라벨:** [data/annotations/phase_v2/](data/annotations/phase_v2/)
- **참여자 12–14의 WORK/MOVE/IDLE 라벨:** [data/annotations/work_move_idle_12_14/](data/annotations/work_move_idle_12_14/)
- **LOPO 결과와 모델:** [results/phase_learning/final_lopo/](results/phase_learning/final_lopo/)
- **상태 전환 분석:** [분석 보고서](results/phase_learning/transition_aware_analysis/TRANSITION_AWARE_ANALYSIS.md)
- **최종 엑셀:** [results/spreadsheets/](results/spreadsheets/)
- **기존 파일의 새 위치:** [폴더 이동 안내](docs/project/FOLDER_MAP.md)

관련 연구 정리는 [Related works.docx](docs/literature/Related%20works.docx)에 있습니다.

## 라벨링 실행

프로젝트 최상위의 **`start_work_move_idle_labeler_12_14.bat`**를 더블클릭합니다.
실행 버튼 이름은 이전과 같습니다. 자세한 사용법은 [라벨링 안내](scripts/labeling/README.md)에 있습니다.

이미 준비된 데이터를 이용해 화면만 열려면 프로젝트 최상위에서 실행합니다.

```powershell
python scripts/labeling/work_move_idle_labeler.py serve
```

현재 실행 버튼은 이 PC의 Codex Python 경로를 사용합니다. 원본 참여자 12–14 MCAP와 원본 WIDE 엑셀은
프로젝트 밖의 기존 실험 폴더를 참조합니다. 다른 PC에서 실행할 때는
`scripts/labeling/work_move_idle_labeler.py`의 외부 입력 경로와 실행 환경을 맞춰야 합니다.

## 실행 환경과 Git 관리

- `.analysis_deps/`는 현재 분석 코드가 사용하는 Python 라이브러리입니다. 로컬에 유지하고 Git에서는 제외합니다.
- `scripts/node_modules`는 현재 PC의 공용 Node 라이브러리 폴더를 가리키는 연결입니다. Git에서는 제외합니다.
- 원본·전처리·중간 데이터, 인터뷰 원본 사본, 모델 가중치와 캐시는 `.gitignore`로 제외합니다.
- 수동 라벨, 코드, 문서, 지표와 최종 결과물은 따로 추적할 수 있게 구성했습니다.
- 모델 학습용 공통 구현과 저장된 모델은 있지만, 과거 문서에 나오는 `train_*.py` 실행 파일은 현재 폴더에 없습니다. [모델 코드 안내](src/phase_modeling/README.md)를 참고하세요.
- 이전 분석 기록의 JSON·CSV·NPZ와 연구 문서에는 생성 당시 경로가 남아 있을 수 있습니다. 원본 기록은 보존하고, 현재 실행에 사용하는 코드와 라벨링 경로 정보는 새 위치로 갱신했습니다.

## 새 파일을 저장할 때

1. 측정 원본은 `data/raw/`, 모델 입력은 `data/processed/`, 수동 라벨은 `data/annotations/`에 둡니다.
2. 공통 알고리즘은 `src/`, 직접 실행하는 작업은 `scripts/`의 해당 기능 폴더에 둡니다.
3. 실험 결과는 `results/<연구 단계>/<실험 이름>/`에 코드·조건·결과가 연결되도록 묶습니다.
4. 논문과 연구 계획은 `docs/`에, 시뮬레이션 프로젝트는 `simulation/`에 둡니다.
5. 다시 만들 수 있는 미리보기와 임시 이미지는 `.cache/`에 둡니다.
