# Remote Painting Shared Control — 연구 및 구현 인수인계

> **중요 — 2026-09-11 업데이트:** shared-control timing, A/B 버튼 의미, transition-aware problem formulation은 `REMOTE_PAINTING_SHARED_CONTROL_HANDOFF_v2.md`에서 갱신되었다. 두 문서가 충돌하면 v2를 우선한다. 이 기존 문서의 `argmax phase 직접 사용 / 별도 supervisor 없음`은 이제 final decision이 아니라 baseline으로 취급한다.

> 작성일: 2026-09-07  
> 목적: 로봇이 연결된 다른 컴퓨터에서 새로운 에이전트 또는 개발자가 이 문서만 먼저 읽고, 현재 연구 방향을 유지한 채 shared-control 구현을 이어갈 수 있게 한다.  
> 상태 표기: **[확정]** 연구자가 결정한 사항 / **[제안]** 현재 권장 설계 / **[미결정]** 실기 구현 전에 확정해야 할 사항

---

## 0. 새 에이전트가 가장 먼저 알아야 할 결론

1. 이 연구의 중심은 새로운 일반-purpose shared-control 알고리즘을 발명하는 것이 아니다.
2. 출발점은 원격 도장 작업자 인터뷰에서 나온 두 요구이다.
   - 벽과의 접촉을 계속 유지하고 싶다.
   - 도료를 짜내거나 펴 바르는 상황에 따라 접촉 강도를 바꾸고 싶다.
3. 이를 위해 인간과 로봇의 역할을 방향별로 나눈다.
   - 인간: 벽면 접선 방향의 이동 경로와 목표 접촉 강도 선택
   - 로봇: 힘 피드백을 이용해 벽면 법선 방향 pose/velocity를 미세 조정하고, 선택된 접촉 상태를 안정적으로 유지
4. **[확정] Haply Inverse3의 A 버튼을 누른 채 PAINTING 하면 LIGHT, B 버튼을 누른 채 PAINTING 하면 STRONG이다.**
5. `LIGHT`와 `STRONG`은 새 phase label이 아니다. 기존 `PAINTING` phase 안에서 작업자가 선택하는 **shared-control submode**이다.
6. phase recognition은 연구의 최종 novelty라기보다 shared control을 적절한 작업 구간에서 작동시키기 위한 enabling component이다.
7. 현재 저장된 Causal LSTM 모델들은 `held_out_06`부터 `held_out_11`까지의 **LOPO 검증용 fold 모델**이다. 전체 데이터로 다시 학습한 배포용 최종 모델로 간주하면 안 된다.
8. phase model의 최고확률 class(`argmax`)를 그대로 제어에 사용한다. phase probability 자체를 authority ratio로 사용하거나 별도의 confidence supervisor를 기본 설계에 추가하지 않는다.
9. phase가 결정하는 목표 authority는 0 또는 1이지만, 실제 authority $\alpha$는 명령 불연속을 막기 위해 짧은 ramp로 전환한다.
10. force setpoint/허용범위, 제어 gain, 안전 한계, A/B를 모두 누르거나 아무것도 누르지 않은 경우의 최종 동작은 아직 확정되지 않았다.

---

## 1. 연구 방향

### 1.1 문제의 출발점

첫 번째 원격 도장 연구의 작업자 인터뷰에서 다음 문제가 확인되었다.

- 영상만으로는 롤러 또는 도장 도구가 벽에 얼마나 닿아 있는지 판단하기 어렵다.
- 원격 컨트롤러의 작은 움직임으로 벽과 도구 사이의 거리를 정밀하게 계속 조절하기 어렵다.
- 그러나 작업자는 접촉을 단순히 항상 같은 값으로 유지하기만 원하는 것이 아니다.
  - 도료를 충분히 짜내거나 묻힐 때에는 더 강한 접촉이 필요할 수 있다.
  - 이미 묻은 도료를 고르게 펴 바를 때에는 더 약한 접촉이 필요할 수 있다.

따라서 이 연구가 해결하려는 것은 다음 두 요구의 동시 달성이다.

1. **Contact maintenance:** 작업 중 롤러가 벽에서 떨어지거나 과도하게 눌리지 않도록 안정적인 접촉 상태를 유지한다.
2. **Contact adjustability:** 접촉 상태를 작업자의 의도에 따라 `LIGHT/STRONG` 두 단계로 바꿀 수 있게 한다.

본 연구의 목표는 하나의 힘 값을 완벽하게 추종하는 정밀 force-control 알고리즘 자체가 아니다. 롤러의 `LIGHT/STRONG` 눌림 변위 차이가 5 mm 미만일 수 있으므로, 순수한 절대 pose offset만으로 두 상태를 만드는 대신 실제 힘 피드백을 사용해 법선 pose를 정밀하게 보정한다. 평가의 핵심은 정확한 setpoint 추종만이 아니라 다음 세 가지이다.

- 도장 중 접촉이 끊어지지 않는가
- `LIGHT/STRONG` 상태가 실제 힘과 도장 결과에서 명확히 구분되는가
- 작업자가 접선 경로에 대한 통제권을 유지하는가

### 1.2 제안 시스템의 한 문장 정의

**Phase-aware, operator-selectable contact-force shared control for remote painting**

즉, 원격 도장 phase를 인식하고, 작업자는 접선 이동을 직접 수행하면서 A/B 버튼으로 목표 접촉 수준을 선택하며, 로봇은 힘 피드백을 이용해 법선 방향 pose/velocity를 미세 조정하여 그 접촉 상태를 유지한다.

### 1.3 연구 contribution의 권장 정리

논문에서는 다음 세 항목을 중심 contribution으로 제시하는 것이 적절하다.

1. **Requirement-driven formulation**  
   원격 도장 작업자 인터뷰에서 접촉 유지와 접촉 강도 조절 요구를 도출하고 이를 shared-control 설계 요구사항으로 변환했다.

2. **Human-adjustable contact shared control**  
   인간에게 접선 경로와 접촉 강도의 선택권을 남기고, 로봇이 법선 방향 접촉력을 보조하는 두 단계 `LIGHT/STRONG` shared control을 구현했다.

3. **Empirical validation in remote painting**  
   제안 시스템이 직접 원격조작보다 접촉 유지, 힘 조절, 도장 품질, 작업부담 또는 주관적 통제감을 개선하는지 실제 도장 작업으로 검증한다.

건설 분야의 sanding, wiping, cleaning, sealing 같은 다른 surface-contact 작업으로의 확장은 **discussion/future work**로 두는 편이 안전하다. 다른 작업에서 직접 검증하지 않았다면 핵심 contribution으로 강하게 주장하지 않는다. 또한 “원격 도장에서 최초”라는 표현은 체계적인 문헌 검토로 확인하기 전에는 “underexplored” 또는 “among the first” 수준으로 표현한다.

---

## 2. 현재 폴더의 phase labeling 정리

### 2.1 라벨 체계

코드에 정의된 phase 순서는 다음과 같다.

| ID | 이름 | 현재 자료에 근거한 operational meaning |
|---:|---|---|
| 0 | `FREE_MOTION` | 벽과 접촉하지 않으며 approach 또는 retract로 지정되지 않은 일반 자유 이동 |
| 1 | `APPROACH` | 비접촉 상태에서 도구가 벽/접촉 방향으로 접근하는 구간 |
| 2 | `PAINTING` | 도구가 벽에 접촉하여 실제 도장 동작을 수행하는 구간 |
| 3 | `RETRACT` | 접촉이 끝난 직후 도구가 벽에서 떨어지는 짧은 후퇴 구간 |

Phase 이름의 코드상 원본은 `tools/phase_modeling/data.py`의 `PHASE_NAMES`이다.

주의할 점:

- 각 trial은 반드시 `FREE → APPROACH → PAINTING → RETRACT`를 매번 완전하게 반복하지 않는다. 수동 편집 결과에 따라 일부 짧은 approach/retract가 없을 수 있다.
- 위 의미는 현재 저장된 라벨, 자동 초안 설정, FSM baseline의 작동 방식을 종합한 operational interpretation이다.
- `LIGHT`와 `STRONG`은 이 네 클래스에 추가하지 않는다. 둘은 shared controller의 submode이며 phase-learning target이 아니다.

### 2.2 라벨 생성 및 수동 편집 상태

현재 라벨 source of truth는 다음 위치이다.

- `results/phase_labeling_all_v2/<trial>/manual_phase_labels.npz`
- 각 연속구간: `results/phase_labeling_all_v2/<trial>/segment_XXX/phase_labels.csv`
- 구간 요약: `results/phase_labeling_all_v2/<trial>/segment_XXX/phase_intervals.csv`
- 전체 요약: `results/phase_labeling_all_v2/labeling_summary.json`

저장된 요약에 따르면:

- 모든 최종 라벨은 `label_source = manual`이다.
- 수동 편집 이력이 있으며 `MANUALLY_EDITED` 플래그가 기록되어 있다.
- 자동 라벨 초안에 사용된 대표 설정은 다음과 같다.
  - 접촉 방향 처리: `sign_invariant_abs_fz`
  - 접촉 판단: `sign_coherent_abs_smoothed_fz_after_despike`
  - contact-on threshold: 6.0 N
  - contact-off threshold: 4.0 N
  - movement speed threshold: 0.02 m/s
  - release lookback: 0.75 s
  - maximum retract: 1.0 s

이 threshold들은 최종 수동 라벨을 만들기 위한 자동 초안 설정이다. 실기 shared-control 안전 threshold나 목표 접촉력으로 그대로 재사용하면 안 된다.

### 2.3 모델 입력 데이터셋

배포 재현성을 고려해 정리된 입력 데이터는 `Data/processed/phase_model_inputs_v1/`에 있다.

| 항목 | 값 |
|---|---:|
| 참여자 | 6명 (`06`–`11`) |
| trials | 22 |
| continuous sequences | 61 |
| samples | 208,430 |
| 총 길이 | 6,947.45 s = 115.79 min |
| feature dimension | 12 |
| resampling | 없음; 원래 timestamp와 frame 순서 유지 |
| manual labels | 전체 sample에 대해 확인됨 |
| valid feature samples | 207,488 |

12차원 feature의 순서와 단위는 고정되어 있다.

1. TCP signed force: `Fx, Fy, Fz` [N]
2. 전체 trial의 첫 pose에 대한 base-frame 상대 위치: `dx, dy, dz` [m]
3. base-frame causal velocity: `vx, vy, vz` [m/s]
4. base-frame causal acceleration: `ax, ay, az` [m/s²]

라벨은 feature에 들어가지 않고 학습 target으로만 사용한다. 온라인 구현은 이 순서, frame, 단위를 정확히 재현해야 한다.

### 2.4 Causal preprocessing

`Data/processed/phase_model_inputs_v1/processing_config.json`의 설정은 다음과 같다.

- force source: first-frame-zeroed signed wrench
- force hard limit: 150 N; 비정상 sample은 직전 정상값 사용
- one-sided Hampel history: 7 samples, 약 0.21 s
- Hampel threshold: 4.5 robust sigma, 최소 10 N floor
- force EMA time constant: 0.12 s
- velocity EMA time constant: 0.10 s
- acceleration EMA time constant: 0.15 s
- reset 후 warm-up: 0.50 s
- timestamp gap reset: 0.20 s
- centered/noncausal smoothing은 모델 입력에 사용하지 않음

모든 필터는 현재와 과거 sample만 사용한다. 새로운 trial, 통신 단절, 0.20 s보다 큰 timestamp gap에서는 전처리 상태와 모델 hidden state를 reset해야 한다. warm-up 0.50 s 동안은 모델 출력을 정상 관측으로 간주하지 말고 알려진 안전 상태를 유지한다.

### 2.5 클래스 불균형

| Phase | Samples | 비율 | Duration [s] | Intervals | 평균 구간 [s] |
|---|---:|---:|---:|---:|---:|
| `FREE_MOTION` | 61,608 | 29.56% | 2,053.61 | 353 | 5.82 |
| `APPROACH` | 10,429 | 5.00% | 347.63 | 154 | 2.26 |
| `PAINTING` | 130,652 | 62.68% | 4,354.95 | 318 | 13.69 |
| `RETRACT` | 5,741 | 2.75% | 191.26 | 141 | 1.36 |

`PAINTING`이 대부분이고 `APPROACH/RETRACT`가 적다. 따라서 accuracy만으로 모델을 판단하면 안 되며 phase별 F1, macro F1, transition event 성능을 함께 봐야 한다.

### 2.6 Phase-learning 결과와 해석

현재 비교된 모델에는 Causal FSM, GMM, Gaussian HMM, GMM-HMM, GMM-HSMM 계열, Random Forest, Causal LSTM이 포함된다. 최종적으로 Causal LSTM이 가장 유력하다.

5-seed participant-independent LOPO strict 평가(`lopo_five_seed_summary.csv`)의 Causal LSTM 평균은 다음과 같다.

- frame accuracy: 79.58%
- balanced accuracy: 57.55%
- macro F1: 0.587
- `FREE_MOTION` F1: 0.693
- `APPROACH` F1: 0.490
- `PAINTING` F1: 0.865
- `RETRACT` F1: 0.300
- false transitions: fold당 평균 281.8
- matched transition absolute delay: 평균 480.45 ms

별도의 tolerance 분석은 다음 결과를 기록한다.

- ±1 s 허용 평가: tolerant accuracy 85.93%, transition F1 0.327
- ±3 s 허용 평가: tolerant accuracy 90.54%, tolerant macro F1 0.812, `PAINTING` F1 0.970

해석 시 주의:

- ±1 s와 ±3 s 결과는 경계 주변의 시간 오차를 허용한 분석이며 strict online 성능이 아니다.
- `PAINTING` 인식은 상대적으로 강하지만 phase 전환과 `RETRACT` 인식은 약하다.
- false transition이 적지 않다는 점은 실기 평가와 결과 해석에서 반드시 보고해야 한다.
- 그러나 기본 shared-control 설계에서는 별도의 probability threshold, confidence arbitration 또는 dwell-time supervisor를 추가하지 않는다. 모델의 최고확률 class를 현재 phase로 사용하고, phase에 따라 목표 authority $\alpha_d\in\{0,1\}$를 정한다.
- 순간적인 phase 변화가 곧바로 로봇 명령의 큰 불연속으로 이어지지 않도록 실제 $\alpha$만 짧은 ramp/low-pass transition으로 변화시킨다. 이는 phase 판단을 다시 수행하는 confidence logic이 아니라 제어 명령의 bumpless transfer이다.

### 2.7 저장 모델에 대한 중요 경고

현재 다음 파일들이 있다.

```text
results/phase_learning/final_lopo/models/causal_lstm_all_folds/
  held_out_06/causal_lstm.npz
  held_out_07/causal_lstm.npz
  held_out_08/causal_lstm.npz
  held_out_09/causal_lstm.npz
  held_out_10/causal_lstm.npz
  held_out_11/causal_lstm.npz
```

이 파일은 각각 특정 참여자를 제외하고 학습한 LOPO 검증용 모델이다. 신규 실험 참여자에 배포할 최종 모델은 가능한 한 22개 trial 전체를 사용해 동일한 preprocessing과 hyperparameter로 다시 학습하고, 별도의 이름(예: `causal_lstm_all_participants_deployment.npz`)으로 export해야 한다.

또한 `tools/phase_modeling/README.md`는 `tools/train_causal_lstm.py`, `tools/evaluate_phase_model.py` 등의 실행 파일을 언급하지만, 현재 workspace의 `tools/` 최상위에는 이 실행 파일들이 보이지 않고 package 코드만 있다. 다른 컴퓨터로 옮기기 전에 학습/평가 entry script의 원본 위치를 찾거나 복원해야 한다.

저장 모델의 기본 inference interface는 다음과 같다.

```python
from pathlib import Path
from phase_modeling.model_io import load_model

model = load_model(Path("causal_lstm_all_participants_deployment.npz"))
model.reset()
phase_id, phase_probability = model.step(observation_12d)
```

현재 loader 구현은 NumPy 외에 PyTorch와 scikit-learn을 import한다. 로봇 컴퓨터에 동일한 Python 환경을 구성하거나 inference-only loader로 의존성을 줄여야 한다.

---

## 3. Shared-control 설계

### 3.1 역할 배분

벽 쪽을 향하는 단위 접촉 방향을 $\mathbf n_c \in \mathbb R^3$로 둔다. 벽의 바깥쪽 surface normal을 알고 있다면 $\mathbf n_c$는 그 반대 방향이다.

법선 및 접선 투영행렬은 다음과 같다.

$$
\mathbf P_N = \mathbf n_c\mathbf n_c^\top,
\qquad
\mathbf P_T = \mathbf I-\mathbf P_N.
$$

Haply 입력을 slave/base frame으로 변환한 인간의 선속도 명령을 $\mathbf v_h$라 하면,

$$
\mathbf v_{h,T}=\mathbf P_T\mathbf v_h,
\qquad
v_{h,n}=\mathbf n_c^\top\mathbf v_h.
$$

- $\mathbf v_{h,T}$: 인간이 그대로 담당하는 벽면 접선 이동
- $v_{h,n}$: 인간이 입력한 벽면 법선 이동
- $v_F$: 로봇 force regulator가 계산한 법선 속도

일반적인 합성식은 다음과 같다.

$$
\boxed{
\mathbf v_{cmd}
=
\mathbf v_{h,T}
+
\mathbf n_c
\left[(1-\alpha)v_{h,n}+\alpha v_F\right]
}
$$

여기서 $\alpha\in[0,1]$는 법선 방향 권한 비율이다.

- $\alpha=0$: 인간의 법선 입력을 그대로 사용하는 direct teleoperation
- $\alpha=1$: 로봇이 법선 방향 force regulation을 담당
- 전환 중 $0<\alpha<1$: jerk를 줄이기 위한 짧은 bumpless ramp

본 연구의 핵심 구현에서는 모델이 출력한 최고확률 phase를 그대로 사용한다.

$$
\hat q_t=\arg\max_q p(q\mid \mathbf x_{1:t}).
$$

목표 authority는 다음처럼 이산적으로 정한다.

$$
\alpha_d=
\begin{cases}
1, & \hat q_t=\mathrm{PAINTING}\ \land\ (A\oplus B),\\
0, & \text{otherwise}.
\end{cases}
$$

여기서 $A\oplus B$는 A와 B 중 정확히 하나만 눌린 상태를 뜻한다. phase probability 자체를 $\alpha$로 사용하지 않는다. 예를 들어 $p_{painting}=0.7$을 $\alpha=0.7$로 사용하면 작업자 법선 입력의 30%와 force regulator의 70%가 동시에 들어가며, 이는 '70% 확신'이 아니라 두 제어 명령의 물리적 혼합이다. `LIGHT/STRONG`의 변위 차이가 작을 때 이러한 혼합은 접촉 상태를 흐릴 수 있다.

단, $\alpha_d$를 순간적으로 적용하면 command jump가 발생할 수 있으므로 실제 $\alpha$에는 다음과 같은 1차 전환을 둔다.

$$
\tau_\alpha\dot\alpha+\alpha=\alpha_d.
$$

권장 초기 방향은 진입을 비교적 부드럽게, 이탈을 더 빠르게 만드는 것이다.

$$
\tau_{on}>\tau_{off}.
$$

초기 pilot 후보는 $\tau_{on}=0.2\text{--}0.4$ s, $\tau_{off}=0.05\text{--}0.15$ s이며 실제 로봇에서 조정해야 한다. 이때 중간의 $0<\alpha<1$은 phase confidence를 표현하는 값이 아니라 0/1 권한 전환 중 발생하는 짧은 transient이다.

### 3.2 Haply Inverse3 버튼 mapping

#### 확정된 동작

| Recognized phase | Haply input | Controller submode | 의미 |
|---|---|---|---|
| `PAINTING` | A 버튼을 누른 채 이동 | `PAINT_LIGHT` | 낮은 접촉 수준을 안정적으로 유지 |
| `PAINTING` | B 버튼을 누른 채 이동 | `PAINT_STRONG` | 높은 접촉 수준을 안정적으로 유지 |

다음 관계를 만족해야 한다.

$$
0 < F_L < F_H < F_{safe},
$$

여기서 $F_L$은 LIGHT의 nominal force, $F_H$는 STRONG의 nominal force, $F_{safe}$는 독립적인 안전 한계이다. 이 값들은 연구의 최종 성능목표 그 자체라기보다 두 접촉 상태를 재현하기 위한 제어 기준이다.

정확한 한 점 추종보다 접촉 범위로 평가할 경우에는 다음처럼 정의할 수 있다.

$$
\mathcal F_L=[F_L-\Delta F_L,F_L+\Delta F_L],
\qquad
\mathcal F_H=[F_H-\Delta F_H,F_H+\Delta F_H].
$$

두 상태가 명확히 구분되려면 적어도 다음을 만족하도록 nominal force와 허용범위를 정한다.

$$
F_L+\Delta F_L<F_H-\Delta F_H.
$$

이 값들은 임의로 정하지 말고 실제 롤러의 눌림 변위-힘 관계를 측정한 뒤 결정한다. 특히 눌림 변위 차이가 5 mm 미만이므로 도료 유무, 접근/이탈 방향에 따른 히스테리시스, 센서 noise까지 확인해야 한다.

버튼에 따른 요청 force는 개념적으로 다음과 같다.

$$
F_{req}=
\begin{cases}
F_L, & \hat q_t=\mathrm{PAINTING} \land A \land \neg B,\\
F_H, & \hat q_t=\mathrm{PAINTING} \land B \land \neg A,\\
\text{none}, & \text{otherwise}.
\end{cases}
$$

#### 아직 확정해야 할 버튼 edge case

- **[미결정] 아무 버튼도 누르지 않은 PAINTING:** force assist OFF로 할지, 마지막 mode를 유지할지
- **[미결정] A와 B를 동시에 누른 경우:** 요청 무효, LIGHT 우선, 또는 즉시 assist OFF 중 선택
- **[미결정] A/B가 teleoperation clutch 역할도 동시에 하는지:** Haply SDK와 기존 조작 mapping 확인 필요

안전 측면의 현재 권장 provisional policy는 다음과 같다.

- A만 눌림: LIGHT
- B만 눌림: STRONG
- 둘 다 눌리거나 둘 다 안 눌림: force assist OFF, $\alpha\rightarrow0$
- 이전 STRONG 명령을 button ambiguity에서 암묵적으로 유지하지 않음

이 provisional policy는 실제 사용자 조작감 pilot 후 연구자가 최종 승인해야 한다.

### 3.3 Force measurement 및 법선 pose 미세보정

$\mathbf n_c$가 도구에서 벽 쪽을 향하고, 센서가 도구에 가해지는 반력을 측정한다고 할 때 compressive normal force를 다음처럼 정의할 수 있다.

$$
F_n = \max\left(0,-\mathbf n_c^\top\mathbf f_{TCP}\right).
$$

실제 부호는 센서 frame과 wrench convention을 확인한 뒤 고정해야 한다. 부호가 틀리면 positive feedback이 되므로 실기 전에 저속 접촉으로 반드시 검증한다.

목표값은 버튼 전환 때 step으로 바꾸지 않고 rate limit를 둔다.

$$
F_d[k]=F_d[k-1]
+\operatorname{clip}
\left(
F_{req}-F_d[k-1],
-r_{down}\Delta t,
r_{up}\Delta t
\right).
$$

순수 pose 방식처럼 `LIGHT는 벽 쪽으로 2 mm`, `STRONG은 5 mm`를 고정적으로 명령하지 않는다. 벽 위치 오차, 롤러 압축, 도료 상태, 기구 변형이 5 mm 미만의 mode 차이를 쉽게 상쇄할 수 있기 때문이다. 대신 측정 힘의 오차를 법선 방향의 작은 속도 명령으로 변환하고, 이를 누적해 로봇의 normal pose reference를 계속 수정한다.

가장 단순한 시작점은 P형 admittance-type force-to-velocity regulator이다.

$$
e_F = F_d-F_n,
$$

$$
v_F=\operatorname{sat}
\left(K_p e_F,
-v_{n,max},
v_{n,max}
\right).
$$

- $e_F>0$: 현재 접촉이 목표보다 약하므로 벽 쪽으로 미세 전진
- $e_F<0$: 현재 접촉이 목표보다 강하므로 벽에서 미세 후퇴
- $e_F\approx0$: 현재 법선 pose를 거의 유지

로봇이 Cartesian velocity 명령을 받으면 $v_F$를 직접 법선 속도로 사용한다. pose 명령을 받는 경우에는 다음처럼 적분해 다음 목표 위치를 만든다.

$$
x_{n,d}[k+1]=x_{n,d}[k]+v_F[k]\Delta t,
$$

또는 3차원 위치로

$$
\mathbf p_d[k+1]
=\mathbf p_d[k]+\mathbf n_c v_F[k]\Delta t.
$$

따라서 이 설계는 `admittance control`과 `pose 조절` 중 하나를 택하는 구조가 아니다. 외부 힘 오차를 admittance 방식으로 속도에 변환하고, 로봇의 내부 position/velocity servo가 이를 실행하는 구조이다.

P 제어에서 작은 정상상태 오차가 문제가 될 때에만 적분항을 추가한다.

$$
\dot z=e_F,
\qquad
v_F=\operatorname{sat}
\left(K_pe_F+K_iz,-v_{n,max},v_{n,max}\right).
$$

처음부터 큰 적분항을 사용하면 롤러가 과도하게 눌리거나 contact 전 windup이 발생할 수 있으므로, 초기 prototype은 P 제어로 시작하고 필요성이 확인된 뒤 작은 $K_i$와 anti-windup을 추가한다.

따라서 force assist가 완전히 활성화된 PAINTING 동안은

$$
\boxed{
\mathbf v_{cmd}=\mathbf P_T\mathbf v_h+\mathbf n_c v_F
}
$$

가 된다. Force controller가 꺼져 있으면 $\alpha=0$이므로

$$
\mathbf v_{cmd}=\mathbf v_h
$$

가 된다.

필수 세부사항:

- force assist가 꺼지거나 phase가 reset되면 integrator를 reset하거나 안전하게 bleed-off한다.
- saturation 중 anti-windup을 적용한다.
- 작은 deadband 또는 허용범위는 force noise로 인한 진동을 줄이는 용도이며, `LIGHT/STRONG` 분리가 흐려질 정도로 넓게 설정하지 않는다.
- $F_d$와 $\alpha$ 모두 ramp를 사용해 mode change의 jerk를 줄인다.
- $v_{n,max}$, total Cartesian speed, acceleration, jerk, $F_{safe}$를 독립적으로 제한한다.
- 벽을 향한 motion과 벽에서 떨어지는 motion의 speed limit를 다르게 둘 수 있다.

### 3.4 Phase-to-control mapping

Phase recognition의 기능은 **접촉 보조를 언제 적용할지 결정하는 것**이다. A/B 버튼은 **어느 접촉 수준을 적용할지 결정**한다. 두 역할을 겹치지 않게 유지한다.

```text
12-D causal features ─> Causal LSTM ─> argmax phase ─> alpha_d = 0 or 1
Haply A/B buttons ────────────────────────────────> LIGHT/STRONG target
alpha_d ─> short authority ramp ─> alpha
```

각 phase의 제어상 의미는 다음과 같다.

- `FREE_MOTION`: force assist OFF, 작업자가 모든 병진 방향을 조작한다.
- `APPROACH`: force assist OFF 상태를 유지한다. 아직 PAINTING이 아니므로 작업자가 벽 방향 접근을 수행한다. 이 phase는 PAINTING 활성화 이전 경계를 제공한다.
- `PAINTING + valid A/B`: 목표 authority를 1로 설정한다. 작업자는 접선 방향, 로봇은 법선 방향을 담당한다.
- `RETRACT`: 목표 authority를 0으로 설정한다. 로봇의 접촉 유지가 작업자의 이탈을 방해하지 않도록 법선 권한을 작업자에게 돌려준다. 이 phase는 PAINTING 해제 경계를 제공한다.

APPROACH와 RETRACT가 서로 다른 controller를 가져야 하는 것은 아니다. 둘 다 실제 출력은 direct teleoperation일 수 있지만, 각각 PAINTING의 시작 전과 종료 후를 구분한다. 4-class learning의 목적은 네 개 controller를 만드는 것이 아니라 PAINTING interval의 시간적 맥락과 경계를 인식하는 데 있다.

APPROACH/RETRACT가 짧게 인식되어도 별도의 dwell 조건을 요구하지 않는다.

$$
\mathrm{FREE}\rightarrow\mathrm{APPROACH}\rightarrow\mathrm{PAINTING}
$$

에서 PAINTING이 출력되는 순간 $\alpha_d=1$이 되고, 실제 $\alpha$가 $\tau_{on}$에 따라 올라간다. 반대로

$$
\mathrm{PAINTING}\rightarrow\mathrm{RETRACT}\rightarrow\mathrm{FREE}
$$

에서는 RETRACT가 출력되는 순간 $\alpha_d=0$이 되고 이후 FREE에서도 0이 유지되므로 RETRACT가 길게 지속될 필요가 없다. 한두 frame의 순간적인 오분류는 $\alpha$ ramp 때문에 곧바로 완전한 authority switch로 이어지지 않는다.

모델 probability는 반드시 기록하지만 기본 제어에는 직접 사용하지 않는다. 향후 별도 연구질문이 생기면 probability-based blending을 비교조건으로 추가할 수 있으나, 현재 baseline에 포함하지 않는다.

다음 항목은 phase confidence를 대체하는 판단기가 아니라 모든 force controller에 필요한 독립적 물리 안전 제한이다.

- contact 전 force integrator 동결 또는 reset
- 최대 법선 속도와 최대 힘 제한
- stale sensor/communication 시 안전 정지 또는 direct teleoperation 복귀
- emergency stop

### 3.5 전체 상태표

| Phase/control state | Normal-axis authority | Tangential authority | Force target |
|---|---|---|---|
| warm-up / stale / fault | 안전 상태 | 안전 상태 | 없음 |
| `FREE_MOTION` | human | human | 없음 |
| `APPROACH` | human | human | 없음 |
| `PAINTING` + valid A | robot normal-position correction from force feedback | human | $F_L$ |
| `PAINTING` + valid B | robot normal-position correction from force feedback | human | $F_H$ |
| `PAINTING` + invalid/no request | human, provisional | human | 없음 |
| `RETRACT` | human | human | 없음; integrator reset |

첫 prototype에서는 `APPROACH`에 별도의 자동 감속 controller를 추가하지 않는다. `APPROACH`는 PAINTING 이전의 assist-OFF 경계, `RETRACT`는 PAINTING 이후의 assist-OFF 경계로 사용한다. 이후 pilot에서 접근 충격이 실제 문제로 확인될 때에만 normal speed cap을 추가한다.

### 3.6 전체 신호 흐름

```text
Haply Inverse3 pose/velocity ─> frame mapping & scaling ─> human command v_h
Haply A/B buttons ───────────────────────────────────────> force-level selector

Robot pose/wrench ─> causal feature pipeline ─> phase model ─> argmax phase
Robot wrench + wall normal ───────────────────────────────> measured force F_n

v_h ─> tangent/normal decomposition ─┐
F_req, F_n ─> force regulator ─> v_F ├─> authority blend ─> safety limits ─> robot v_cmd
phase + A/B ─> alpha_d ─> alpha ramp ┘

All raw and derived signals ─> synchronized logger
```

Haply-to-robot mapping 자체도 명시해야 한다.

$$
\mathbf v_h=s_v\mathbf R_{BH}\mathbf v_{Haply},
$$

여기서 $s_v$는 motion scale, $\mathbf R_{BH}$는 Haply frame에서 robot base frame으로의 회전이다. 현재 연구는 우선 3-DOF 선속도와 고정/별도 관리되는 tool orientation을 가정한다. 자세 제어가 필요하면 별도 설계가 필요하다.

---

## 4. 구현 계획

### Stage 0 — 로봇 컴퓨터 환경 확인

1. robot 종류, control API/ROS topic, Cartesian velocity 명령 주기 확인
2. F/T sensor topic, 단위, frame, sign convention 확인
3. Haply Inverse3 SDK에서 A/B의 실제 button index와 press/hold event 확인
4. wall plane 및 normal을 어떻게 calibration할지 결정
5. robot computer의 Python, NumPy, PyTorch, scikit-learn 버전 확인
6. 현재 프로젝트의 누락된 training/evaluation entry script 위치 확인

### Stage 1 — Logging-only 통합

로봇에 힘 명령을 보내지 않고 다음을 동기화해 기록한다.

- Haply pose/velocity
- A/B raw state 및 debounced state
- robot TCP pose/velocity
- raw/filtered wrench
- 12-D phase feature
- raw phase ID와 4-class probability
- `argmax` phase와 $\alpha_d$

이 단계에서 frame, timestamp, force sign, button mapping을 검증한다.

### Stage 2 — Phase 없이 force regulator 단독 검증

1. 고정된 벽면에서 롤러를 0.5 mm 또는 1 mm 간격으로 천천히 눌러 눌림 변위-힘 관계를 측정
2. 가능하면 도료가 없는 상태와 묻은 상태, 접근과 이탈을 각각 측정해 히스테리시스 확인
3. 측정 결과로 $F_L$, $F_H$, 허용범위 및 $F_{safe}$ 후보 결정
4. 저속/낮은 force limit와 실험자 수동 enable로 LIGHT부터 검증
5. 안정성이 확인되면 STRONG 검증
6. step 대신 target ramp를 적용해 overshoot 측정
7. 접촉 loss, peak force, mode separation, steady-state error, oscillation 확인

Phase model과 force controller를 처음부터 동시에 켜지 않는다. 각 모듈의 실패 원인을 분리해야 한다.

### Stage 3 — A/B mode switching 검증

1. `A hold → LIGHT`
2. `B hold → STRONG`
3. `A → B`, `B → A` 전환
4. button release
5. both/none edge case
6. setpoint separation과 transient peak 확인

### Stage 4 — 방향 분리 shared control

접선 방향은 인간 입력, 법선 방향은 force regulator를 사용한다. 다음을 확인한다.

- 접선 이동 중 force가 유지되는가
- 인간의 접선 방향과 로봇의 법선 보정이 서로 간섭하지 않는가
- 벽면 좌표계 오차가 lateral drift 또는 force oscillation을 만들지 않는가
- saturation 후 정상적으로 회복하는가

### Stage 5 — Phase gating 결합

1. recorded replay에서 `argmax phase → $\alpha_d$` mapping과 $\alpha$ ramp를 먼저 검증
2. 실기에서는 low-force/LIGHT mode부터 시작
3. false engage, missed engage, engage delay, false disengage 기록
4. raw phase, 4-class probability, $\alpha_d$, 실제 $\alpha$를 모두 기록
5. $\tau_{on}$과 $\tau_{off}$가 접촉 안정성과 이탈 반응에 미치는 영향 확인
6. warm-up, timestamp gap, sensor dropout 시 독립 안전동작 확인

### Stage 6 — Pilot 및 본 실험

Pilot에서 먼저 force setpoint와 gain을 고정한 뒤 본 실험에 들어간다. 본 실험 도중 participant별로 gain이나 setpoint를 임의 조정하면 조건 비교가 어려워진다. 개인화가 연구 질문이라면 별도 calibration protocol로 명시해야 한다.

---

## 5. 권장 평가 설계

### 5.1 조건

가능하면 다음 세 조건을 비교한다.

| 조건 | 목적 |
|---|---|
| C1. Direct teleoperation | 전체 shared-control 효과의 baseline |
| C2. Fixed-force shared control | 접촉 유지 보조 자체의 효과 측정 |
| C3. A/B adjustable shared control | 작업자 조절 가능성의 추가 효과 측정 |

실험 규모상 두 조건만 가능하면 C1과 C3를 우선 비교할 수 있다. 다만 이 경우 접촉 유지 보조와 A/B adjustability의 효과를 분리해 주장하기 어렵다.

### 5.2 과업 설계

A/B 두 수준을 실제로 사용할 이유가 생기도록 한 trial 안에 서로 다른 요구를 넣는다.

- STRONG이 적합한 구간: 도료를 눌러 충분히 배출/전달하는 구간
- LIGHT가 적합한 구간: 이미 묻은 도료를 얇고 고르게 펴는 구간

두 mode를 만들었지만 과업이 하나의 힘 수준만 요구하면 “human-adjustable contact” contribution을 검증할 수 없다.

### 5.3 객관적 지표

- contact maintenance ratio
- contact-loss 횟수와 총 duration
- mode별 target-force RMSE/MAE
- LIGHT와 STRONG의 실제 force separation
- peak force와 safety-limit 접근 횟수
- force overshoot 및 settling time
- operator normal-axis input 또는 correction effort
- completion time
- trajectory/path deviation
- paint coverage, 균일도, 미도장/과도장 면적
- 가능하면 도막 두께 또는 대체 가능한 이미지 기반 품질 지표
- live phase gate의 false engage, missed engage, transition delay

### 5.4 주관적 지표

- 접촉을 유지하기 쉬웠는가
- 원하는 순간에 접촉 강도를 바꿀 수 있었는가
- LIGHT/STRONG의 차이가 명확했는가
- 시스템이 의도와 다르게 밀거나 놓는다고 느꼈는가
- 통제감/sense of agency
- confidence/trust
- NASA-TLX 또는 유사 작업부담
- 조건 선호도와 이유

### 5.5 핵심 hypothesis 예시

- H1: Adjustable shared control은 direct teleoperation보다 contact maintenance ratio를 높이고 contact loss를 줄인다.
- H2: Adjustable shared control은 direct teleoperation보다 normal-force 변동과 peak force를 줄인다.
- H3: 작업자는 A/B를 이용해 LIGHT와 STRONG에서 통계적으로 구분되는 접촉력을 만들 수 있다.
- H4: Adjustable shared control은 접촉 제어 용이성과 주관적 통제감을 높인다.
- H5: 이러한 개선은 tangential path control이나 completion time을 과도하게 악화시키지 않는다.

---

## 6. 반드시 기록할 신호

가능하면 하나의 공통 monotonic timestamp로 다음을 모두 기록한다.

- participant, condition, trial, task segment
- Haply pose, velocity, A raw, B raw
- mapped $\mathbf v_h$, $\mathbf v_{h,T}$, $v_{h,n}$
- robot TCP pose, commanded velocity, measured velocity
- raw wrench, filtered wrench, $F_n$
- $F_L$, $F_H$, $F_{req}$, ramped $F_d$, $e_F$, integrator $z$, $v_F$
- raw phase ID, phase probabilities, $\alpha_d$
- 실제 $\alpha$, assist enable, LIGHT/STRONG mode
- every saturation/safety/fault flag
- communication delay, stale-data flag, control-loop period
- emergency stop 및 operator override event

분석 시 raw model error, phase-to-control mapping, authority transition, force-controller error를 분리하려면 raw와 derived 신호를 모두 남겨야 한다.

---

## 7. 실기 전 미결정 사항 체크리스트

### Hardware/API

- [ ] 로봇 모델과 Cartesian velocity/force-control interface
- [ ] 제어 주기와 end-to-end latency
- [ ] F/T 센서 위치, frame, bias/tare 절차, force sign
- [ ] Haply A/B button index 및 clutch와의 관계
- [ ] emergency stop, deadman switch, robot protective stop 연동

### Geometry

- [ ] 벽 plane과 $\mathbf n_c$ calibration 방법
- [ ] tool orientation 유지 방법
- [ ] master-to-slave frame rotation $\mathbf R_{BH}$
- [ ] motion scale $s_v$

### Force control

- [ ] $F_L$ [N]
- [ ] $F_H$ [N]
- [ ] $F_{safe}$ [N]
- [ ] $K_p$, $K_i$, deadband, anti-windup
- [ ] $v_{n,max}$, total velocity/acceleration/jerk limits
- [ ] setpoint ramp rates $r_{up}$, $r_{down}$
- [ ] contact 전 integrator 동결/reset 조건

### Phase gating/UI

- [ ] `argmax phase → $\alpha_d$` mapping 구현
- [ ] $\tau_{on}$, $\tau_{off}$ 또는 동등한 authority ramp rate
- [ ] A/B none 및 both 정책 최종 승인
- [ ] operator에게 LIGHT/STRONG/assist-active 상태를 보여줄 시각·청각·촉각 피드백
- [ ] phase model 미동작 시 fallback

### Model deployment

- [ ] 22 trials 전체로 deployment model 재학습/export
- [ ] 누락된 train/evaluate entry script 복원
- [ ] robot computer에서 12-D preprocessing bit-for-bit 또는 tolerance 내 재현
- [ ] sequence reset과 0.5 s warm-up 구현
- [ ] recorded replay 결과가 기존 evaluation과 일치하는지 확인

---

## 8. 다른 컴퓨터로 옮길 항목

최소 복사 대상:

```text
REMOTE_PAINTING_SHARED_CONTROL_HANDOFF.md
tools/phase_modeling/
Data/processed/phase_model_inputs_v1/        # 재학습/검증/replay 시
results/phase_labeling_all_v2/               # manual labels가 필요할 때
results/phase_learning/final_lopo/            # 평가 결과와 LOPO 모델
Phase_Recognition_for_Shared_Control_updated.pdf
```

다음은 source of truth가 아니므로 일반적으로 복사할 필요가 없다.

- `.analysis_deps/`: 이 컴퓨터에서 분석을 위해 설치한 로컬 Python dependency 모음
- `.tmp_doc_review/`, `.tmp_doc_review.zip`, `tmp/`: 임시 작업물

환경 폴더를 복사하기보다 로봇 컴퓨터에서 필요한 dependency를 새로 설치하고 버전을 기록한다.

---

## 9. 주요 reference files

- 데이터 설명: `Data/processed/phase_model_inputs_v1/README.md`
- 전처리 설정: `Data/processed/phase_model_inputs_v1/processing_config.json`
- 전체 데이터 요약: `Data/processed/phase_model_inputs_v1/dataset_summary.json`
- phase 분포: `Data/processed/phase_model_inputs_v1/phase_summary.csv`
- 최종 수동 라벨 요약: `results/phase_labeling_all_v2/labeling_summary.json`
- phase 이름 및 데이터 loader: `tools/phase_modeling/data.py`
- 모델 사용법: `tools/phase_modeling/README.md`
- 공통 model loader: `tools/phase_modeling/model_io.py`
- Causal LSTM 구현: `tools/phase_modeling/discriminative.py`
- strict LOPO: `results/phase_learning/final_lopo/results/strict_original/lopo_five_seed_summary.csv`
- ±1 s 분석: `results/phase_learning/final_lopo/results/buffered_1s/buffered_evaluation_metrics.json`
- ±3 s 분석: `results/phase_learning/final_lopo/results/tolerant_3s/phase_metrics_3s.json`
- phase 결과 보고서: `Phase_Recognition_for_Shared_Control_updated.pdf`

---

## 10. 다음 에이전트에 대한 작업 지시

1. 이 문서의 **[확정]**, **[제안]**, **[미결정]**을 구분한다.
2. `LIGHT/STRONG`을 phase classifier의 새 label로 만들지 않는다.
3. LOPO fold 모델 하나를 임의로 deployment final model이라 부르지 않는다.
4. centered smoothing, future frame, Viterbi decoding처럼 온라인에서 사용할 수 없는 정보를 phase pipeline에 추가하지 않는다.
5. 모델의 `argmax phase`로 목표 authority $\alpha_d\in\{0,1\}$를 정하고, 실제 $\alpha$에는 짧은 bumpless ramp만 적용한다. phase probability를 $\alpha$로 직접 사용하거나 별도의 confidence supervisor를 기본 설계에 추가하지 않는다.
6. force sign, wall normal, safety limit 검증 전에는 STRONG mode를 실기에서 활성화하지 않는다.
7. shared-control 알고리즘 자체의 보편적 novelty를 과장하지 않는다. 연구의 중심은 원격 도장 요구에서 출발한 시스템 설계와 실증이다.
8. 구현 전 이 문서의 체크리스트에서 robot-specific 미결정 값을 연구자와 확정한다.
9. 가장 먼저 만들 코드는 logging-only 통합본이며, 그 다음 force controller, 마지막으로 phase gating과 authority ramp를 결합한다.

이 문서 이후의 코드 변경, 확정된 parameter, pilot 결과는 날짜와 함께 이 파일에 계속 추가한다.
