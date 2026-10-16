# Remote Painting Shared Control — Research and Implementation Handoff v2

> 폴더 위치는 2026-10-16에 정리했습니다. 아래 연구 내용은 기존 기록이며, 현재 파일 위치는 [폴더 이동 안내](../project/FOLDER_MAP.md)를 참고하세요. 이전 인수인계는 [v1 보관본](archive/shared_control_handoff_v1.md)에 있습니다.

> Updated: 2026-09-11  
> Purpose: 로봇이 연결된 컴퓨터의 에이전트가 현재 연구 방향, 이미 확인된 결과, 미결정 사항을 혼동 없이 이어서 검토·구현하도록 한다.  
> Authority: 이 문서는 `REMOTE_PAINTING_SHARED_CONTROL_HANDOFF.md`의 shared-control 방향을 갱신한다. 두 문서가 충돌하면 이 v2를 우선한다.

---

## 0. 가장 먼저 읽을 결론

1. 연구의 출발점은 원격 도장 작업자 인터뷰에서 확인된 두 요구이다.
   - Painting 중 벽과의 접촉을 안정적으로 유지하고 싶다.
   - 도료를 묻히거나 펴 바르는 상황에 따라 접촉 수준을 `LIGHT/STRONG`으로 조절하고 싶다.
2. 작업자는 Haply Inverse3의 A 또는 B 버튼을 **누른 채** 로봇을 움직인다. 버튼을 놓으면 teleoperation 자체가 멈춘다.
3. A/B는 모든 phase에서 teleoperation clutch이며, `PAINTING`에서만 접촉 mode 선택 기능이 추가된다.
   - `PAINTING + A`: LIGHT
   - `PAINTING + B`: STRONG
4. 따라서 버튼 release를 contact-assistance override로 사용할 수 없다. 작업자가 벽에서 후퇴할 때도 A 또는 B를 누른 채 움직여야 한다.
5. 현재 Causal LSTM의 phase argmax를 그대로 assistance ON/OFF에 연결할 경우, 전환 지연과 예측 흔들림이 제어 충돌로 전달될 수 있는 phase-gate exposure가 offline replay에서 확인되었다.
6. 특히 `PAINTING → RETRACT` 전환과 Painting 종료 후 assistance 해제가 취약하다.
7. 그러나 해결책을 단순한 rule-based filter나 미래 예측형 LSTM으로 확정하지 않았다.
8. 현재 연구의 중심 문제는 다음과 같다.

> **How can phase-aware contact assistance remain effective during painting while preventing phase-transition errors from interfering with the operator?**

9. 다음 단계에서는 동일한 problem formulation에 대한 두 solution family를 검토한다.
   - prediction-side anticipation: 전환 timing 오차 자체를 감소
   - control-side transition-robust authority handover: timing 오차가 작업자를 방해하는 결과를 감소
10. 현재 우선순위는 새 모델부터 만드는 것이 아니라, 제어 요구사항·실패 시나리오·평가지표를 먼저 고정하고 baseline system에서 실제 문제가 재현되는지 확인하는 것이다.

---

## 1. 연구 배경과 목표

### 1.1 작업자 요구

선행 원격 도장 실험의 인터뷰에서 다음 문제가 확인되었다.

- 원격 영상만으로 롤러가 벽에 얼마나 접촉했는지 판단하기 어렵다.
- 원격 컨트롤러의 작은 움직임만으로 벽과 롤러 사이의 거리를 정밀하게 유지하기 어렵다.
- 작업자는 항상 동일한 접촉을 원하는 것이 아니다.
  - 도료를 충분히 묻히거나 짜낼 때에는 강한 접촉이 필요할 수 있다.
  - 묻은 도료를 고르게 펴 바를 때에는 약한 접촉이 필요할 수 있다.

따라서 shared control의 기본 목적은 다음 두 가지이다.

1. **Contact maintenance:** Painting 중 롤러가 벽에서 떨어지거나 과도하게 눌리지 않도록 접촉을 보조한다.
2. **Human-adjustable contact:** 작업자가 LIGHT와 STRONG 접촉 수준을 직접 선택한다.

정확한 하나의 힘 값을 완벽하게 추종하는 force-control 알고리즘 자체가 연구의 유일한 목적은 아니다. 접촉 안정성, 도장 결과, 작업자의 통제감이 함께 개선되어야 한다.

### 1.2 현재 권장 시스템 명칭

**Transition-robust, phase-aware, human-adjustable contact shared control for remote painting**

`transition-robust`는 최종 알고리즘의 이름이 아니라 현재 problem formulation을 나타내는 표현이다. 구체적인 supervisor 또는 authority-handover 방법은 아직 미결정이다.

---

## 2. A/B 버튼의 정확한 의미

| Recognized phase | Button | Intended behavior |
|---|---|---|
| Any phase | None | Teleoperation inactive; robot does not follow the Haply motion |
| `FREE_MOTION` | A or B | Direct human teleoperation |
| `APPROACH` | A or B | Direct human teleoperation; no confirmed force-maintenance mode yet |
| `PAINTING` | A | Tangential human motion + LIGHT normal contact assistance |
| `PAINTING` | B | Tangential human motion + STRONG normal contact assistance |
| `RETRACT` | A or B | Direct human teleoperation; normal authority should be returned to the human |

중요:

- A/B는 `assistance ON/OFF button`이 아니다.
- A/B는 teleoperation을 가능하게 하는 clutch이다.
- A/B의 차이는 `PAINTING`일 때 LIGHT/STRONG setpoint 선택으로 사용한다.
- 작업자가 후퇴하려면 버튼을 계속 눌러야 하므로 `button release → assistance OFF`를 transition 문제의 해결책으로 제안하면 안 된다.
- A와 B를 동시에 누른 경우의 동작은 아직 확정되지 않았다. 구현 전 결정해야 한다.

---

## 3. 현재 phase learning

### 3.1 Phase labels

| ID | Phase | Operational meaning |
|---:|---|---|
| 0 | `FREE_MOTION` | 벽과 접촉하지 않는 일반 자유 이동 |
| 1 | `APPROACH` | 비접촉 상태에서 도구가 벽 방향으로 접근하는 구간 |
| 2 | `PAINTING` | 도구가 벽에 접촉하여 도장하는 구간 |
| 3 | `RETRACT` | 접촉 종료 후 도구가 벽에서 떨어지는 후퇴 구간 |

`LIGHT/STRONG`은 phase label이 아니다. `PAINTING` 안에서 작업자가 선택하는 shared-control submode이다.

### 3.2 Dataset and model

- Participants: 6 (`06`–`11`)
- Trials: 22
- Valid continuous sequences: 61
- Valid duration: approximately 115 min
- Input: 12-D causal observation
  - TCP force `Fx, Fy, Fz`
  - trial-start-relative TCP position `dx, dy, dz`
  - causal velocity `vx, vy, vz`
  - causal acceleration `ax, ay, az`
- Selected model: small unidirectional Causal LSTM
- Online inference: current and past observations only

현재 저장된 모델은 다음 LOPO validation fold이다.

```text
results/phase_learning/final_lopo/models/causal_lstm_all_folds/
  held_out_06/causal_lstm.npz
  held_out_07/causal_lstm.npz
  held_out_08/causal_lstm.npz
  held_out_09/causal_lstm.npz
  held_out_10/causal_lstm.npz
  held_out_11/causal_lstm.npz
```

이 모델들은 deployment model이 아니다. 실제 신규 참여자 실험 전 전체 training data로 deployment model을 다시 학습하고 별도 저장해야 한다.

### 3.3 기존 5-seed strict LOPO 결과

- Accuracy: 79.58%
- Balanced accuracy: 57.55%
- Macro F1: 0.587
- FREE F1: 0.693
- APPROACH F1: 0.490
- PAINTING F1: 0.865
- RETRACT F1: 0.300
- Matched-transition absolute delay: mean 480 ms
- False transitions: mean 281.8 per fold

`±3 s tolerant F1`은 phase-learning 비교에는 사용할 수 있지만 실시간 shared control timing의 충분한 근거가 아니다. 수백 ms의 지연도 제어에서는 중요할 수 있다.

---

## 4. 새로 수행한 transition-aware LOPO replay 분석

### 4.1 분석 범위와 주의사항

- 22 trials, 61 sequences, 115.3 min
- LOPO fold마다 저장된 Causal LSTM checkpoint 1개를 사용
- five-seed 전체에 대한 framewise prediction file은 저장되어 있지 않아, 아래 결과는 five-seed 반복 결과가 아니다.
- `stable detection`은 분석을 위해 예측이 150 ms 이상 유지되는 경우로 정의했다.
- 150 ms는 proposed supervisor의 dwell-time parameter가 아니다.
- 실제 A/B 신호와 shared controller 출력이 없는 offline causal replay이다.
- 따라서 아래 `phase gate` 오류는 실제 로봇 assistance나 human–robot conflict를 직접 측정한 결과가 아니다.

### 4.2 Phase duration and detectability

| Phase | Episodes | Median duration | Under 1 s | Stable 150-ms detection |
|---|---:|---:|---:|---:|
| `FREE_MOTION` | 350 | 3.022 s | 16.0% | 78.0% |
| `APPROACH` | 154 | 1.299 s | 40.3% | 61.0% |
| `PAINTING` | 318 | 9.125 s | 8.8% | 96.9% |
| `RETRACT` | 141 | 1.027 s | 48.2% | 50.4% |

0.5 s 미만의 짧은 transition phase에서는 검출률이 매우 낮았다.

| Phase | Episodes under 0.5 s | Any detection | Stable 150-ms detection |
|---|---:|---:|---:|
| `APPROACH` | 28 | 10.7% | 3.6% |
| `RETRACT` | 27 | 44.4% | 11.1% |

따라서 긴 dwell-time filter는 짧은 phase를 완전히 제거할 수 있다. 임의의 smoothing을 바로 추가하면 안 된다.

### 4.3 Canonical transition behavior

| True transition | Correct at boundary | Stable detection within target phase | Median stable delay among detected events |
|---|---:|---:|---:|
| `FREE → APPROACH` | 4.7% | 61.4% | 0.302 s |
| `APPROACH → PAINTING` | 53.2% | 94.2% | 0.000 s |
| `PAINTING → RETRACT` | 1.7% | 45.8% | 0.393 s |
| `RETRACT → FREE` | 27.6% | 80.0% | 0.186 s |

Painting assistance의 진입보다 해제가 더 취약했다.

- 전체 Painting episode의 stable activation delay median: 0.041 s
- Painting 종료 후 predicted Painting이 남은 시간 median: 0.665 s
- `PAINTING → RETRACT`에서 Painting prediction linger median: 0.514 s
- `PAINTING → FREE`에서 Painting prediction linger median: 0.766 s

### 4.4 Direct argmax gate의 문제

`predicted phase = PAINTING`일 때 phase gate를 연다고 가정한 결과:

- True phase transitions: 7.83/min
- Predicted phase switches: 18.24/min = true count의 2.33배
- True Painting-gate toggles: 5.34/min
- Predicted Painting-gate toggles: 12.72/min = true count의 2.38배
- True Painting 중 gate closed: 8.7%
- Non-Painting 중 gate open: 29.9%
- True Retract 중 predicted Painting: 49.0%

실제 force assistance에는 A/B 조건도 필요하므로 이 수치를 실제 assistance duration으로 해석하면 안 된다. 다만 A/B를 누른 채 작업하는 현재 interaction에서는 phase gate 오류가 실제 제어로 전달될 가능성이 있다.

### 4.5 Label-chain issue

현재 318개 Painting episode 중:

- 명시적 Approach가 바로 앞에 있는 episode: 139개 = 43.7%
- 명시적 Retract가 바로 뒤에 있는 episode: 120개 = 37.7%
- `FREE → PAINTING`: 162 transitions
- `PAINTING → FREE`: 188 transitions

따라서 현재 라벨은 항상 다음 chain을 따르지 않는다.

$$
\mathrm{FREE}
\rightarrow
\mathrm{APPROACH}
\rightarrow
\mathrm{PAINTING}
\rightarrow
\mathrm{RETRACT}
\rightarrow
\mathrm{FREE}
$$

이는 반드시 라벨 오류라는 뜻은 아니다. 실제 Approach/Retract가 너무 짧거나 수동 labeling에서 별도 phase로 지정되지 않았을 수 있다. 그러나 Approach/Retract를 shared-control timing의 핵심으로 사용할 경우, 이 phase들이 항상 존재하지 않는 문제를 먼저 다뤄야 한다.

### 4.6 Participant variation

- Approach stable detection: participant별 9.7%–100%
- Retract stable detection: participant별 13.6%–100%
- Non-Painting gate-open exposure: participant별 13.8%–42.9%

따라서 모든 사람에게 동일한 고정 delay가 발생하는 문제가 아니다. 동작 특성에 따른 participant-independent generalization 문제도 함께 존재한다. 하나의 고정 threshold/dwell time으로 해결된다고 가정하면 안 된다.

---

## 5. Current problem formulation

### 5.1 Core problem

Phase recognition의 목적은 단순히 네 클래스를 높은 F1으로 분류하는 것이 아니라, 적절한 시점에 shared control을 제공하는 것이다. 그러나 짧은 전환에서는 실제 작업 상태와 phase-based assistance 사이에 temporal mismatch가 발생한다.

> **In phase-aware shared control, short and rapid task transitions can create a temporal mismatch between the operator's current motion intention and the assistance selected from causal phase estimates. This mismatch can produce premature, delayed, or unstable assistance during contact-rich remote painting.**

대표적인 failure mode는 다음과 같다.

1. **Premature engagement:** Approach 중 Painting이 너무 일찍 예측되어 contact force controller가 조기에 개입한다.
2. **Delayed engagement:** Painting이 시작됐지만 assistance가 늦게 활성화되어 접촉이 불안정하다.
3. **Unstable engagement:** Painting 중 phase prediction이 흔들리며 assistance가 반복적으로 ON/OFF된다.
4. **Delayed disengagement:** 작업자가 벽에서 후퇴하려 하지만 Painting prediction과 contact-maintenance가 남아 작업자의 법선 입력을 방해한다.

### 5.2 Research objective

$$
\boxed{
\text{Maintain useful contact assistance during Painting}
\quad\text{while minimizing transition-induced inappropriate assistance.}
}
$$

개념적인 성능 목적은 다음처럼 표현할 수 있다.

$$
J
=
J_{contact}
+\lambda_{pre}J_{premature}
+\lambda_{post}J_{delayed\ release}
+\lambda_{conflict}J_{human-robot\ conflict}
+\lambda_{switch}J_{mode\ switching}.
$$

아직 각 항의 정의와 가중치는 확정하지 않았다. 실제 pilot과 사용자 영향에 근거해 정의해야 하며, 임의로 숫자를 정하면 안 된다.

---

## 6. Baseline shared-control formulation

벽 방향 단위벡터를 $\mathbf n_c$로 두고, 벽 방향을 양수로 정의한다.

$$
\mathbf P_T=\mathbf I-\mathbf n_c\mathbf n_c^\top,
\qquad
v_{h,n}=\mathbf n_c^\top\mathbf v_h.
$$

- $\mathbf P_T\mathbf v_h$: 작업자가 담당하는 벽 접선 방향 이동
- $v_{h,n}$: 작업자의 벽 법선 방향 명령
- $v_F$: contact-force error로부터 생성되는 로봇 법선 보정 명령

A/B에 따라 목표 접촉 수준을 설정한다.

$$
F_d=
\begin{cases}
F_{light}, & A\text{ held during Painting},\\
F_{strong}, & B\text{ held during Painting}.
\end{cases}
$$

예시 PI force regulator는 다음과 같다.

$$
e_F=F_d-F_n,
\qquad
\dot z=e_F,
$$

$$
v_F=
\operatorname{sat}
\left(
K_p e_F+K_i z,
-v_{n,max},
v_{n,max}
\right).
$$

기존 baseline 합성식은 다음이다.

$$
\boxed{
\mathbf v_{cmd}
=
\mathbf P_T\mathbf v_h
+
\mathbf n_c
\left[
(1-\alpha) v_{h,n}
+
\alpha v_F
\right]
}
$$

Direct phase-gating baseline에서는:

$$
\alpha_{phase}=
\begin{cases}
1, & \hat q_t=\mathrm{PAINTING}\text{ and A or B is held},\\
0, & \text{otherwise}.
\end{cases}
$$

`PAINTING`에서 $\alpha=1$이면:

$$
v_{cmd,n}=v_F,
$$

즉 작업자의 법선 입력이 완전히 제거된다. 이 구조가 transition error에 취약한 핵심 이유이다.

### 6.1 대표적인 control conflict

작업자가 A/B를 계속 누른 채 벽에서 후퇴한다고 하자.

$$
v_{h,n}<0.
$$

그러나 LSTM이 계속 `PAINTING`으로 예측하고, force controller가 감소한 접촉력을 회복하려 하면:

$$
v_F>0.
$$

따라서:

$$
v_{h,n}<0<v_F
$$

가 되어 인간과 로봇의 법선 방향 명령이 충돌한다. 작업자는 후퇴를 위해 버튼을 계속 눌러야 하므로 button release로 이 문제를 해결할 수 없다.

---

## 7. Solution family A — Prediction-side anticipation

### 7.1 Concept

현재 phase만 추정하는 대신 가까운 미래의 contact onset/offset event를 예측한다.

$$
P(\text{contact onset within }\tau\mid o_{1:t}),
$$

$$
P(\text{contact offset within }\tau\mid o_{1:t}).
$$

이는 LSTM, multi-task sequence model 또는 별도의 causal event predictor로 구현할 수 있다.

### 7.2 이 방향이 problem을 해결하는 논리

$$
\text{Reactive phase recognition}
\rightarrow
\text{late transition detection}
\rightarrow
\text{assistance mismatch}
$$

에서 첫 번째 원인인 transition detection delay를 직접 줄인다.

### 7.3 아직 확인해야 할 것

- 전환 전에 onset/offset을 예측할 수 있는 관측 신호가 실제로 존재하는가?
- Approach/Retract가 0.5 s 미만일 때도 useful prediction horizon이 존재하는가?
- 단순히 현재 label을 시간만큼 앞당겨 학습한 결과가 진짜 anticipation인가, 아니면 class prior를 학습한 것인가?
- phase accuracy가 아니라 assistance timing과 실제 작업 성능이 개선되는가?
- participant-independent LOPO에서 일반화되는가?

현재 분석에서 기존 LSTM의 Approach/Retract probability는 전환 전에 뚜렷하게 상승하지 않았다. 그러나 현재 모델은 미래 예측을 학습하지 않았으므로 미래 예측 가능성이 없다고 단정할 수는 없다. **이 방향은 후보이지 확정 solution이 아니다.**

---

## 8. Solution family B — Control-side transition-robust authority handover

### 8.1 Concept

Phase prediction이 지연되거나 틀리더라도 그 오류가 큰 물리적 간섭으로 이어지지 않도록 shared-control policy를 설계한다.

$$
p_t=f(o_{1:t}),
$$

$$
\alpha_{eff}
=
\pi
\left(
p_t,
b_t,
v_{h,n},
v_F,
F_n,
\text{transition history}
\right),
$$

$$
\mathbf v_{cmd}
=
\mathbf P_T\mathbf v_h
+
\mathbf n_c
\left[
(1-\alpha_{eff})v_{h,n}
+
\alpha_{eff}v_F
\right].
$$

여기서 $b_t$는 A/B 버튼 상태이다. $\pi$의 구체적인 형태는 아직 확정하지 않았다.

### 8.2 필요한 동작 특성

아래 항목은 구현 방식이 아니라 system requirement 후보이다.

1. **Human withdrawal must not be trapped by stale Painting recognition.**
2. **Premature Painting recognition must not produce unsafe inward force before contact is established.**
3. **One- or two-frame prediction flicker must not produce large command discontinuities.**
4. **The force-controller integrator must not retain unsafe state during disengagement.**
5. **LIGHT/STRONG 선택과 human tangential motion must remain under operator control.**

벽 방향을 양수로 정의했을 때, 명확한 인간 후퇴 입력에 대해 검토할 수 있는 제어 보장 후보는 다음과 같다.

$$
v_{h,n}< -\delta
\quad\Longrightarrow\quad
v_{cmd,n}\leq 0
\quad\text{within }T_{handover}.
$$

이 식은 최종 controller가 아니다. “작업자가 명확하게 후퇴하려 할 때 로봇이 계속 벽 방향으로 밀어서는 안 된다”는 requirement를 수식화한 것이다.

### 8.3 Rule-based filter와의 구분

다음처럼 사용하면 안 된다.

```text
LSTM predicts Approach
+ robot velocity is wallward
+ robot is near wall
=> confirm Approach
```

위 위치·속도·힘은 이미 LSTM 입력에 들어 있으므로 독립적인 확인 정보가 아니다. 같은 정보를 외부에서 다시 thresholding하면 redundant filtering과 추가 delay가 생길 수 있다.

반면 다음은 역할이 다르다.

- Phase model: 작업 context를 추정
- Human command $v_{h,n}$: 작업자가 현재 내리는 직접적인 motion command
- Force/contact measurement: 실제 물리 상태와 안전 한계 확인
- Shared controller: 서로 충돌하는 인간/로봇 명령 사이에서 authority를 배분

따라서 control-side solution을 개발한다면 “phase를 rule로 다시 분류”하는 것이 아니라, **phase error가 존재할 때에도 만족해야 하는 제어 성질**에서 정책을 도출해야 한다.

### 8.4 아직 결정하지 않은 방법

아래 항목은 모두 후보이며 확정 설계가 아니다.

- asymmetric engagement/disengagement
- conflict-aware authority reduction
- constrained control allocation
- optimization- or cost-based arbitration
- limited pre-contact normal assistance
- causal hysteresis or dwell logic
- integrator reset/bleed-off and bumpless transfer

각 기능은 관찰된 failure mode와 요구사항에 의해 정당화되어야 한다. 단순히 구현하기 쉽다는 이유로 추가하면 안 된다.

---

## 9. Approach와 Retract의 역할에 대한 미결정 사항

현재 세 가지 해석 가능성이 있다.

### Option 1: Explicit phase states

Approach와 Retract를 모든 Painting 전후에 일관되게 존재하는 상태로 정의한다. 이 경우 labeling 기준을 재검토하고 누락된 짧은 구간을 어떻게 처리할지 결정해야 한다.

### Option 2: Optional transition states

Approach와 Retract는 충분히 관측 가능한 경우에만 나타나는 phase이다. 이 경우 shared controller는 이 phase가 누락되어도 안전하게 작동해야 한다.

### Option 3: Transition events rather than sustained states

Approach/Retract 분류보다 `contact onset is imminent`과 `contact offset is imminent`을 직접 예측한다.

아직 어느 해석을 사용할지 확정하지 않았다. 이 결정 없이 supervisor부터 구현하면 연구 논리가 불명확해질 수 있다.

---

## 10. 현재 권장 연구 순서

### Step 1. Control requirements 확정

최소한 다음 요구사항의 operational definition을 만든다.

- $R_1$: Painting 중 contact-maintenance benefit
- $R_2$: premature engagement 제한
- $R_3$: delayed disengagement의 최대 허용 시간 또는 충돌 크기 제한
- $R_4$: 작업자의 outward command에 대한 authority handover
- $R_5$: phase flicker에 대한 command continuity

### Step 2. Logging-only real-time integration

먼저 로봇을 phase model로 제어하지 않고 다음 신호를 동시에 기록한다.

- timestamp
- 12-D phase-model input
- four-class phase probability
- argmax phase
- A/B/none button state
- master/Haply command $\mathbf v_h$
- wall-normal command $v_{h,n}$
- measured normal force $F_n$
- hypothetical baseline $\alpha_{phase}$
- hypothetical force correction $v_F$
- phase model inference latency

목적은 실제 operator input과 phase prediction의 시간 관계를 확인하는 것이다.

### Step 3. Direct-gating baseline

안전한 범위에서 다음 baseline을 구현한다.

$$
\hat q_t=\arg\max_q p_t(q)
\quad\rightarrow\quad
\alpha_{phase}\in\{0,1\}.
$$

이 baseline은 proposed method가 아니라 transition problem을 재현하고 비교하기 위한 조건이다.

### Step 4. Failure-focused pilot

다음 시나리오를 반복한다.

1. Free → fast Approach → Painting
2. Painting → fast Retract
3. Painting 중 LIGHT ↔ STRONG 변경
4. Painting 중 짧은 force/contact disturbance
5. A/B를 누른 채 빠른 stroke 반복

측정:

- premature gate-open time
- Painting activation delay
- Painting disengagement delay
- human–robot normal command conflict duration
- conflict magnitude or time integral
- normal-force overshoot
- contact-loss ratio
- gate/controller toggle count
- operator-rated interference and perceived control

### Step 5. Solution comparison

최소 비교 구조:

1. Direct argmax phase gating
2. Conventional causal temporal filtering/hysteresis baseline
3. Proposed transition-robust authority policy
4. Oracle labels as a system upper bound

Prediction-side anticipation을 개발하는 경우 다음 조건을 추가한다.

5. Future onset/offset prediction + the same control policy

이렇게 해야 성능 개선이 prediction 때문인지 arbitration 때문인지 구분할 수 있다.

---

## 11. Evaluation priorities

### 11.1 Phase/timing metrics

- exact boundary accuracy
- onset and offset delay distributions
- stable target detection within the true phase
- premature detection
- predicted switch frequency
- participant-level variation

### 11.2 Control-consequence metrics

- Painting contact-loss ratio
- normal-force variability
- time within LIGHT/STRONG target ranges
- impact/force overshoot
- human–robot command-conflict duration and integral
- assistance release time after operator withdrawal begins
- robot motion smoothness

### 11.3 Task and human metrics

- paint coverage and uniformity
- completion time
- NASA-TLX
- perceived control
- perceived interference/frustration
- confidence in LIGHT/STRONG distinction

최종 성능 판단은 phase F1만으로 하면 안 된다. Phase model이 다소 틀리더라도 작업자 방해가 작고 contact benefit이 크다면 shared-control system으로는 더 우수할 수 있다.

---

## 12. Robot-side implementation cautions

1. 현재 LOPO fold model을 deployment model로 오해하지 않는다.
2. 학습 때 사용한 feature 순서, 단위, coordinate frame, causal filtering, reset 조건을 그대로 재현한다.
3. 새 trial, 통신 gap 또는 reset 이후 LSTM hidden state와 preprocessing state를 초기화한다.
4. wall-normal sign convention을 force error 및 velocity command 전체에서 하나로 통일한다.
5. force-controller saturation, anti-windup, integrator reset, force hard limit를 반드시 둔다.
6. phase output이 사라지거나 inference가 늦어질 때 safe fallback을 정의한다.
7. phase probability를 곧바로 authority ratio로 해석하지 않는다.
   - $p(\mathrm{Painting})=0.7$은 “force control을 70% 섞어라”라는 물리적 의미가 아니다.
8. 아직 확정되지 않은 supervisor를 임의 threshold로 구현해 최종 방식처럼 굳히지 않는다.
9. 첫 통합은 logging-only로 시작하고, 이후 low-force/low-speed pilot로 진행한다.

---

## 13. Robot-side agent가 바로 할 일

### Immediate task A — Interface verification

- A/B/none 상태가 어떤 ROS topic/message로 들어오는지 확인
- A/B를 누르지 않았을 때 robot command가 어떻게 처리되는지 확인
- A와 B를 누른 상태에서 같은 Haply motion이 동일한 teleoperation command를 생성하는지 확인
- Painting 밖에서 A/B의 차이를 무시할 수 있는지 확인

### Immediate task B — Coordinate and contact verification

- 벽 방향 단위벡터 $\mathbf n_c$ 정의
- positive normal direction을 wallward로 통일
- measured force $F_n$의 부호와 zeroing 확인
- $v_{h,n}=\mathbf n_c^\top\mathbf v_h$ 계산 검증

### Immediate task C — Logging-only phase integration

- LOPO model loader와 preprocessing pipeline 실행 확인
- raw phase probability와 argmax를 robot command에 적용하지 않고 기록
- A/B state, $v_{h,n}$, $F_n$과 timestamp alignment 확인
- `Painting → withdrawal` 구간의 phase lag과 human command를 plot/replay

### Immediate task D — Baseline controller safety review

- force regulator가 no-contact 상태에서 목표 힘을 만들기 위해 벽 방향으로 과도하게 이동하지 않는지 확인
- $v_{n,max}$, force limit, workspace limit, emergency stop 확인
- integrator reset/anti-windup 동작 확인
- $\alpha=1$일 때 human normal command가 완전히 제거된다는 점을 명시적으로 검증

구체적인 proposed supervisor 구현은 Immediate task A–D의 결과와 함께 결정한다.

---

## 14. Relevant workspace files

```text
REMOTE_PAINTING_SHARED_CONTROL_HANDOFF_v2.md

Data/processed/phase_model_inputs_v1/
  trials/*.npz
  sequence_manifest.csv
  trial_summary.csv

tools/phase_modeling/
  data.py
  discriminative.py
  model_io.py

results/phase_learning/final_lopo/
  models/causal_lstm_all_folds/
  results/strict_original/lopo_five_seed_summary.csv
  results/tolerant_3s/

results/phase_learning/transition_aware_analysis/
  TRANSITION_AWARE_ANALYSIS.md
  transition_aware_summary.json
  transition_events.csv
  phase_episodes.csv
  sequence_control_summary.csv
  participant_control_summary.csv

tools/analyze_lopo_transitions.py
```

---

## 15. Current decisions versus open questions

### Confirmed

- Remote painting is the target task.
- Human controls tangential painting motion.
- Robot is intended to assist wall-normal contact during Painting.
- A/B must be held for teleoperation.
- A selects LIGHT and B selects STRONG during Painting.
- LIGHT/STRONG are not new phase labels.
- Current Causal LSTM is causal but transition performance, especially disengagement, is insufficient for unquestioned direct gating.
- Direct argmax gating is a baseline, not yet the final shared-control policy.

### Open

- Exact LIGHT/STRONG force setpoints or acceptable ranges
- Whether force control should regulate an exact setpoint or a contact band
- Whether Approach/Retract remain explicit classes, optional classes, or are replaced/supplemented by onset/offset event prediction
- Whether the main proposed solution is prediction-side, control-side, or combined
- Exact definition of human withdrawal/conflict
- Authority-handover policy $\pi$
- Contact-established logic and safe approach behavior
- Engagement/disengagement ramp times
- A+B simultaneous-button behavior
- Final experimental conditions and participant count

---

## 16. One-paragraph handoff summary

The project develops human-adjustable contact shared control for remote painting. The operator must hold Haply button A or B throughout teleoperation; during Painting, A selects LIGHT and B selects STRONG contact assistance. A causal LSTM recognizes Free, Approach, Painting, and Retract, but offline LOPO replay shows that short Approach/Retract phases are often missed, Painting disengagement is delayed, and raw argmax gating switches too frequently. Because the button must remain held during withdrawal, button release cannot solve stale Painting assistance. The central research problem is therefore to retain useful contact assistance while preventing phase-transition errors from producing premature, delayed, unstable, or conflicting wall-normal control. Future-transition prediction and transition-robust authority handover are alternative solution families, not yet fixed designs. The robot-side implementation should begin with coordinate verification and logging-only integration, reproduce the failure cases, and then select a supervisor/control policy based on explicit control requirements and measured consequences.
