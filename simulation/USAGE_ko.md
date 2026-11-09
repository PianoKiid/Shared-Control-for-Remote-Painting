# Isaac Sim + Haply 가상 원격 도장 사용법

## 1. 실행 구조

Haply 입력 브리지 → 같은 PC의 UDP → Isaac Sim → causal feature·LSTM → 공유제어 → TCP 역기구학 → RB10 관절 drive의 순서로 동작한다.

물리 계산은 **120 Hz**, 공유제어와 기록은 **30 Hz**이다. 매 제어 시점에 직전 네 물리 스텝의 롤러–벽 접촉력을 평균하고, 실제 관절 위치에서 계산한 TCP 위치와 함께 LSTM에 전달한다. 해당 행의 제어 출력은 다음 구간에 적용된다.

## 2. 준비

- Isaac Sim **5.1** standalone 환경과 해당 `python.bat` 또는 `python.sh`.
- Haply Inverse3, VerseGrip, Haply Inverse Service **3.x**. 기본 주소는 `ws://localhost:10001`.
- 입력 브리지용 일반 Python 3.11 이상.
- 저장소에 포함된 URDF·메시·`simulation/models/phase_lstm.npz`.

프로젝트 최상위에서 실행한다.

```powershell
python -m venv .venv-teleop
.\.venv-teleop\Scripts\python.exe -m pip install -r simulation/requirements-haply.txt
.\.venv-teleop\Scripts\python.exe simulation/teleop.py preflight
```

`assets_and_model: OK`와 초기 롤러 간격 약 **35.78 mm**를 확인한다. 일반 Python에서 `isaacsim_available: false`이면 Isaac 전용 Python으로 아래 장면 실행 명령을 실행한다. Isaac 환경에는 추가 PyTorch 설치가 필요 없다. 모델은 NumPy로 추론한다.

## 3. 실시간 조종

Haply Hub에서 Inverse3와 VerseGrip을 준비한 뒤 터미널 두 개를 연다. 두 프로그램은 같은 PC에서 실행한다.

**터미널 A — Haply 입력**

```powershell
.\.venv-teleop\Scripts\python.exe simulation/teleop.py bridge
```

**터미널 B — Isaac Sim**

아래 설치 경로를 실제 Isaac Sim 위치로 바꾼다.

```powershell
& 'C:\isaac-sim\python.bat' simulation/teleop.py isaac --input haply --condition shared
```

PowerShell 실행기를 사용해도 된다.

```powershell
.\simulation\start_teleop.ps1 -IsaacPython 'C:\isaac-sim\python.bat' -Condition shared
```

Linux에서는 동일한 인자를 `python.sh`에 전달한다.

```bash
/path/to/isaac-sim/python.sh simulation/teleop.py isaac --input haply --condition shared
```

| 조작 | 동작 |
|---|---|
| 무선 VerseGrip의 **B 버튼을 누른 채 이동** | 클러치 활성화, TCP 병진 이동 |
| 유선 VerseGrip의 버튼 | 동일한 클러치 동작 |
| Isaac 창에서 **Space를 누른 채 Haply 이동** | 키보드 클러치, VerseGrip 없이 입력 확인 가능 |
| B / Space 해제 | 현재 측정 자세에서 유지 |
| 1 또는 FREE 버튼 | 평가용 작업 라벨 FREE |
| 2 또는 APPROACH 버튼 | 평가용 작업 라벨 APPROACH |
| 3 또는 PAINTING 버튼 | 평가용 작업 라벨 PAINTING |
| 4 또는 RETRACT 버튼 | 평가용 작업 라벨 RETRACT |
| Esc / End trial / Isaac의 Stop | 실험 종료와 결과 저장 |

`Painting Teleoperation` 패널에 접촉력·간격·위임 계수·PAINTING 확률이 표시된다. 작업 라벨은 평가용이고, 제어기의 상태 판단은 LSTM이 담당한다. 키보드 포커스가 맞지 않으면 화면 버튼을 사용한다. 다음 실험은 명령을 다시 실행하여 같은 초기 자세에서 시작한다.

제공한 실물 `rb10_teleop.py`에서 **30 Hz, B 버튼 클러치, `[dy, -dx, dz]` base 축 변환, 병진 스케일 9, 클러치 시작 시 위치 기준 재설정**을 반영했다. 회전은 초기 TCP 방향으로 고정한다. 여기서는 Inverse Service의 cursor 위치 차이에 스케일을 적용하며, 실물 코드의 외부 `PybindTeleopAgent`와 0.08초 궤적 생성기는 사용하지 않는다.

Haply에는 위치 스트리밍을 위한 **0 N** 명령을 보낸다. 이번 버전은 입력 기능을 제공하며 Haply 힘 반력 출력은 포함하지 않는다. 물리 RB10에는 연결하지 않는다.

입력이 **0.15초** 이상 끊기면 자세를 유지한다. 재연결·클러치 재시작 시 새 위치를 기준으로 잡고, 초기 **0.5초**는 feature 준비 구간으로 둔다. 힘·추종 오차 상한이나 역기구학 실패가 발생하면 실험을 종료하고 사유를 저장한다.

## 4. 조건별 평가

| `--condition` | 법선 방향 제어 |
|---|---|
| `manual` | 사용자 입력 전달. 공통 속도·작업 범위·중단 조건 적용. |
| `probability` | 실제 접촉 중 LSTM PAINTING 확률과 불확실성으로 힘 보조 비중 결정. |
| `shared` | probability 보조에 최근 접촉 맥락, 제한된 접촉 복귀, 후퇴 의도 유지를 추가. |

```powershell
& 'C:\isaac-sim\python.bat' simulation/teleop.py isaac --condition manual
& 'C:\isaac-sim\python.bat' simulation/teleop.py isaac --condition probability
& 'C:\isaac-sim\python.bat' simulation/teleop.py isaac --condition shared
```

같은 벽·초기 자세·목표 힘 아래에서 접촉 유지와 짧은 후퇴 후 재접촉을 수행한다. PAINTING 구간의 시작·종료를 패널에 표시한다. 상태 추정이 틀린 프레임도 이 평가 구간에 포함된다. 표시하지 않은 시간은 UNMARKED로 남고 도장 성능 분모에서 빠진다.

## 5. 입력 재생과 상태 오류 주입

장치 없이 14.1초의 접근–도장–후퇴–재접근 입력을 Isaac에서 실행한다. 평가 라벨도 이 시간표에서 제공한다.

```powershell
& 'C:\isaac-sim\python.bat' simulation/teleop.py isaac --input scripted --condition shared --headless
```

실시간 실험에서 기록한 사용자 입력을 다른 조건으로 재생한다. `TRIAL`은 실제 폴더명으로 바꾼다.

```powershell
& 'C:\isaac-sim\python.bat' simulation/teleop.py isaac --input replay --replay 'results/teleop/TRIAL/samples.csv' --condition manual
& 'C:\isaac-sim\python.bat' simulation/teleop.py isaac --input replay --replay 'results/teleop/TRIAL/samples.csv' --condition shared
```

재생은 저장된 **사용자 속도 입력·클러치·독립 작업 라벨**을 사용한다. 힘·로봇 위치·LSTM 확률은 각 조건에서 다시 계산한다. 제어 개입에 따른 로봇 운동 차이를 비교할 수 있으며, 사용자가 그 변화에 반응하는 과정은 실시간 실험에서 평가한다.

```powershell
# 제어기에 전달할 LSTM 출력을 6프레임(시뮬레이션 시간 0.2초) 지연
& 'C:\isaac-sim\python.bat' simulation/teleop.py isaac --input scripted --condition shared --phase-delay-frames 6

# 제어기에 전달할 상태를 PAINTING으로 고정
& 'C:\isaac-sim\python.bat' simulation/teleop.py isaac --input scripted --condition shared --force-phase PAINTING
```

원래 확률은 `p_*`, 실제 사용한 확률은 `used_p_*`로 저장된다. `--force-phase`가 있으면 지연된 확률보다 우선한다. 같은 오류 조건을 probability와 shared에 적용하여 힘 유지·후퇴 방해·접촉 복귀를 비교한다.

## 6. 저장 파일과 해석

기본 경로는 `results/teleop/<UTC시각>_<backend>_<condition>/`이다. `--output`으로 상위 폴더를 바꿀 수 있다.

| 파일 | 내용 |
|---|---|
| `metadata.json` | 조건, 입력 출처, 오류 주입, 전체 설정, 모델·코드 해시, 힘의 출처와 좌표계 |
| `samples.csv` | 측정·입력·확률·명령·위임 계수·제어 모드·독립 작업 라벨·중단 사유 |
| `summary.json` | 완료/중단 상태와 요약 지표 |

Isaac의 `force_N`은 직전 네 물리 스텝의 평균 힘, `force_peak_N`은 최대 힘이다. 같은 행의 명령은 다음 구간에 적용된다. `input_raw_*`는 축 변환·스케일 적용 후 속도 제한 전 입력, `human_*`는 제한 후 입력, `requested_*`는 공유제어 출력, `command_*`는 작업 범위·중단 처리까지 반영한 TCP 목표 속도다. 실제 운동은 위치와 관절 기록으로 확인한다.

- **힘 RMSE / 평균 / 목표 ±2 N 비율:** 독립 PAINTING 구간의 접촉력 유지.
- **1 N 미만 비율 / 상실 횟수:** 같은 구간의 저접촉. 구간 시작부터 저접촉이면 하나의 사건으로 센다.
- **평균 복귀 시간 / 복귀 사건 수:** 같은 PAINTING 구간에서 다시 1 N에 도달한 사건. 미복귀 수는 상실 횟수와 복귀 횟수의 차이로 확인한다.
- **양의 간격 평균:** 도장 중 벽에서 떨어진 거리.
- **접촉 경로 길이:** 연속된 두 PAINTING 샘플이 모두 1 N 이상일 때의 접선 이동 길이. 반복 경로도 누적되므로 도장 면적과 구분한다.
- **후퇴 방해량:** RETRACT 중 사용자 후퇴 속도를 줄인 명령 차이의 시간 적분, 단위 mm.
- **비활성 비율 / 중단 사유 / 최대 추종 오차:** 입력 해제, feature 준비, 중단 및 추종 상태.

```powershell
python simulation/teleop.py compare 'results/teleop/TRIAL_MANUAL' 'results/teleop/TRIAL_PROBABILITY' 'results/teleop/TRIAL_SHARED' --out results/teleop/comparison.csv
```

비교 표에는 backend와 종료 상태도 포함된다. 정상 완료와 조기 중단을 확인하여 같은 작업 구간끼리 비교한다. 이번 장면은 접촉과 운동을 평가하며 도막 두께·도료 분포는 계산하지 않는다.

## 7. 알고리즘을 수정할 때

`src/painting_teleop/controller.py`의 `Controller.step()`과 `simulation/config/painting.json`을 수정한다. 입력은 `Observation`, 출력 `Decision.command`는 법선 속도다. **+X가 벽 안쪽**, 양의 간격이 벽 바깥쪽이다. 접선 y·z 입력은 사람이 담당한다.

현재 접촉 중 힘 보조 속도와 기본 혼합은 다음과 같다.

\[
v_a=k_F(F_d-F),\qquad v_n=(1-\alpha)v_h+\alpha v_a.
\]

기본 목표 힘은 10 N이다. 위임 계수 목표는 PAINTING 확률과 정규화된 엔트로피로 계산하며 0.1초 시상수로 갱신한다. `painting_authority`는 최대 위임 비중이다. JSON 값은 실행을 시작하기 위한 설정이며 실물 롤러의 식별 결과는 아니다.

`shared`에서는 다음을 추가했다.

1. 접촉 중 PAINTING이 확인되면 짧은 시간 그 맥락을 유지한다.
2. 최근 접촉이 있었고 의도적인 후퇴 이탈이 아니며 벽이 가까우면 제한된 전진 보조로 복귀한다. 다시 전진을 요청하면 오래된 RETRACT 추정 아래에서도 복귀를 허용한다. 시간·간격·추가 보조 이동량을 제한한다.
3. 후퇴가 입력되면 그 의도를 중립 입력에서도 유지한다. 최종 속도가 사용자 후퇴를 방해하지 않게 제한하며, 다음 전진 입력에서 해제한다.

| 파일 | 수정 대상 |
|---|---|
| `controller.py` | 위임·접촉 유지·복귀·후퇴 처리 |
| `features.py`, `lstm.py` | causal 전처리와 모델 추론 |
| `input.py`, `haply_bridge.py` | 클러치·축 변환·통신 |
| `geometry.py` | FK/IK·거리·힘 좌표 변환 |
| `isaac_scene.py` | 물리 장면·관절 drive·화면 |
| `runtime.py`, `session.py` | 실행·재생·기록 |
| `metrics.py` | 평가 지표 |

설정 파일을 복사해 `--config`로 지정하면 실험 조건을 보존할 수 있다. 제공 체크포인트의 feature 주기에 맞춰 제어 주기는 30 Hz로 고정한다.

## 8. 좌표·모델·물리 조건

원본 URDF의 `support_to_rb10`에 있는 Z축 90도 회전은 `.cache/painting/robot_paint.urdf` 생성본에서만 0으로 바꾼다. world와 link0가 일치하며 임의의 base 관절 보정은 더하지 않는다. 초기화 때 USD TCP와 FK가 3 mm 이내로 일치하는지도 확인한다.

벽 앞면은 x=0.48 m이다. 롤러의 길이·반지름·방향으로 간격을 구한다. 벽과 롤러는 물리 collider이며 기본 접촉 강성 6000 N/m, 감쇠 20 N·s/m와 관절 drive 이득은 JSON에서 바꿀 수 있다. 실험 중에는 joint drive로 움직이며 직접 관절 위치 지정은 초기화에만 사용한다.

법선 힘은 PhysX 로봇 반력의 -X 성분이다. LSTM에는 반력 부호를 반전하여 FT 좌표로 회전한 값을 전달한다. 초기 도장 자세에서 누르는 힘은 기존 기록처럼 FT 음의 Z 값이다. 여기서는 롤러–벽의 법선 접촉 성분을 사용하므로, 실물 FT의 중력·마찰·다른 접촉 성분에 따른 입력 차이는 독립 라벨과 `p_*`를 함께 보며 확인한다.

포함 모델은 기존 LOPO `held_out_09` 체크포인트이고 재학습하지 않았다. 학습 trial과 SHA-256은 `models/provenance.json`에 있다. Torch와 NumPy의 연속 100프레임 추론 일치를 테스트한다.

## 9. 장치 없이 확인

```powershell
python simulation/teleop.py smoke --condition manual
python simulation/teleop.py smoke --condition probability
python simulation/teleop.py smoke --condition shared
python -m unittest discover -s tests -v
```

`smoke`는 같은 LSTM·제어·기록에 간단한 스프링 벽과 속도 응답을 붙인 실행 점검이다. 결과 backend가 `smoke`로 표시되고 Isaac 물리 실행은 `isaac`로 표시된다. WebSocket 통합 테스트에는 `requirements-haply.txt`가 필요하다. 수행한 검증과 대상 PC에서 확인할 항목은 [VALIDATION.md](VALIDATION.md)에 있다.

## 10. 문제 확인

- **Isaac 모듈 없음:** 설치 폴더의 `python.bat` / `python.sh`로 실행한다.
- **Haply 입력 없음:** Hub의 ready 상태와 B 버튼을 확인한다. 여러 장치가 있으면 bridge에 `--device-id ID --grip-id ID`를 지정한다.
- **Service 형식 차이:** 기본은 설치된 3.3 예제의 `set_cursor_force.values` 형식이다. `vector`를 쓰는 버전은 `bridge --force-key vector`로 지정한다. 10000번 legacy 3.0과 10001번 3.x 포트를 구분한다.
- **메시 없음:** `issac sim_ws` 전체가 있는지 확인한다. LFS 객체가 필요하면 `git lfs pull`을 실행한다.
- **초기 자세/좌표 검사 실패:** 콘솔의 import 경로와 TCP 검사 메시지를 확인한다. 다른 URDF나 Isaac 버전에서는 root와 articulation 구성을 확인한다.
- **힘/추종 상한 종료:** summary의 status와 마지막 CSV의 힘·오차를 확인한다. 공유제어 이득, 관절 drive, 접촉 강성은 별도 설정이다.

API 기준: [Isaac 5.1 URDF](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/importer_exporter/import_urdf.html), [Isaac 5.1 contact API](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/py/source/extensions/isaacsim.core.prims/docs/index.html), [PhysX compliant contact](https://docs.omniverse.nvidia.com/kit/docs/omni_physics/latest/dev_guide/rigid_bodies_articulations/rigid_bodies.html), [Haply Inverse Service 3.3](https://docs.haply.co/inverseSDK/3.3.x/service/).
