# Phase-learning model code

> 2026-10-16 폴더 정리: 공통 구현은 `src/phase_modeling/`, 현재 전환 분석 실행 파일은
> `scripts/analysis/analyze_lopo_transitions.py`에 있습니다.
> 아래 Training 및 Held-out causal evaluation의 `tools/train_*.py`, `tools/evaluate_phase_model.py` 명령은
> 이전 작업 기록입니다. 해당 실행 파일들은 현재 작업 폴더에 없어 그대로 실행할 수 없습니다.
> 데이터는 `data/processed/phase_model_inputs_v1/`, 저장된 LOPO 모델은
> `results/phase_learning/final_lopo/models/`에서 찾을 수 있습니다.

이 폴더는 `phase_model_inputs_v1`의 12차원 관측값으로 수동 phase 라벨을
학습하는 공통 구현이다. 라벨은 입력 feature에 포함되지 않으며 학습 target으로만
사용된다.

## Models

| 실행 파일 | 모델 | 현재 구현의 의미 |
|---|---|---|
| `train_causal_fsm.py` | Causal FSM | force magnitude, motion, approach direction, retract duration을 training data로 보정한 규칙 기반 baseline |
| `train_gmm_classifier.py` | GMM classifier | 각 phase에 대한 diagonal GMM, 현재 frame만으로 분류 |
| `train_gaussian_hmm.py` | Gaussian HMM | phase당 Gaussian 1개와 상태 전이확률 |
| `train_gmm_hmm.py` | GMM-HMM | phase당 여러 Gaussian mixture와 상태 전이확률 |
| `train_gmm_hsmm.py` | GMM-HSMM | GMM-HMM에 phase 지속시간 분포를 명시적으로 추가 |
| `train_calibrated_sticky_gmm_hmm.py` | Calibrated sticky GMM-HMM | 관측 우도 가중치와 자기상태 유지 강도를 training-only 교차검증으로 선택한 GMM-HMM |
| `train_random_forest.py` | Random Forest | 현재 frame의 12차원 feature를 사용하는 비선형 판별 baseline |
| `train_causal_lstm.py` | Causal LSTM | 과거 hidden state와 현재 frame만 사용하는 작은 단방향 시계열 판별모델 |

모든 확률모델은 수동 라벨을 사용하는 supervised 모델이다. HMM/HSMM의 평가는
미래 frame을 사용하는 Viterbi decoding이 아니라 한 frame씩 갱신하는 causal
forward filtering으로 수행한다.

## Training

프로젝트 루트에서 다음처럼 실행한다. 현재 실험 계획에 따라 네 trial을 넘긴다.

```powershell
python tools\train_gmm_classifier.py --train-trials 06_01 06_02 06_03 06_04
python tools\train_gaussian_hmm.py --train-trials 06_01 06_02 06_03 06_04
python tools\train_gmm_hmm.py --train-trials 06_01 06_02 06_03 06_04 --components 3
python tools\train_gmm_hsmm.py --train-trials 06_01 06_02 06_03 06_04 --components 3
python tools\train_causal_fsm.py --train-trials 06_01 06_02 06_03 06_04
python tools\train_calibrated_sticky_gmm_hmm.py --train-trials 06_01 06_02 06_03 06_04
python tools\train_random_forest.py --train-trials 06_01 06_02 06_03 06_04
python tools\train_causal_lstm.py --train-trials 06_01 06_02 06_03 06_04
```

`train_phase_model.py --model ...`로 같은 공통 코드를 직접 호출할 수도 있다.
모델은 압축 NPZ로 저장된다. 동일 경로에 수치 보관용
`*.training_report.json`과 사람이 확인하기 위한 `*.training_report.png`가 함께
생성된다. 이 diagnostic은 학습에 사용한 frame을 다시 예측한 값이므로 일반화
성능으로 보고하면 안 된다.

정규화 평균과 표준편차는 선택한 training trial로만 계산해 모델 안에 저장한다.
feature warm-up frame은 제외하며, MCAP 연속구간 경계마다 HMM/HSMM/FSM의 내부
상태를 reset한다. GMM component 수의 기본값은 phase당 3개이고 Gaussian HMM은
항상 phase당 1개다.

Calibrated sticky GMM-HMM은 네 training trial 중 하나씩을 검증용으로 빼는 4-fold
교차검증을 사용한다. 각 fold의 정규화와 모델 학습은 남은 세 trial로만 수행한다.
혼합성분 수, 관측 우도 가중치, 자기상태 유지 강도는 Macro F1과 phase 전환 event
F1의 평균으로 고른 뒤, 선택된 설정으로 네 trial 전체에서 모델을 처음부터 다시
학습한다. 최종 평가 trial은 이 선택 과정에 사용하지 않는다.

## Held-out causal evaluation

학습에 쓰지 않은 trial을 지정한다.

```powershell
python tools\evaluate_phase_model.py `
  --model results\phase_learning\models\gmm_hmm__06_01__06_02__06_03__06_04.npz `
  --test-trials 07_01 07_02 07_03 07_04
```

평가는 frame accuracy, macro F1, phase별 recall/F1, confusion
matrix, phase 전환 검출 오차, frame당 순차 추론시간을 기록한다. JSON과 함께 전체
요약 PNG 및 trial별 실제/예측 phase timeline PNG를 자동 생성한다. 추론시간에는 이미
만들어진 12차원 feature를 모델에 넣는 시간만 포함되고 raw pose/wrench에서 feature를
계산하는 시간은 포함하지 않는다.

## Saved model usage

```python
from pathlib import Path
from phase_modeling.model_io import load_model

model = load_model(Path("model.npz"))
model.reset()                 # 새 trial 또는 불연속 구간 시작
phase_id, probability = model.step(observation_12d)
```

`observation_12d`는 반드시 dataset README에 정의된 순서와 단위를 따라야 한다.
확률모델은 저장된 training-only scaler를 내부에서 자동 적용한다.
