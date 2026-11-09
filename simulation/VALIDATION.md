# 실행기 검증 기록 — 2026-11-09

## 수행 결과

Windows / Python 3.12에서 다음을 확인했다.

| 검증 | 결과 |
|---|---|
| 단위·회귀·로컬 통신 테스트 | **26개 통과** |
| NumPy LSTM과 원래 Torch 출력 | 연속 100프레임 fixture, 절대 허용오차 3×10⁻⁶·상대 허용오차 2×10⁻⁵ 이내 |
| URDF FK / IK / 힘 부호 / 생성본 경로 | 통과, 원본 자산 유지 |
| 해석 Jacobian과 FK 수치 미분 | 서로 다른 세 자세에서 일치 |
| 가상 Haply WebSocket 서버 → UDP | 위치·축 변환·0 N 송신·입력 끊김 확인 |
| 클러치·오래된 패킷·재연결 | 위치 기준 재설정, 이동 반복 방지 |
| 후퇴→중립→접촉 상실 | 후퇴 의도 유지, 자동 재접근 방지 |
| 물리/렌더 분리 및 Pause/Stop | 문서화된 시간 진행을 모사한 회귀 테스트 통과 |
| smoke: manual / probability / shared | 각각 14.1초·423프레임 정상 완료 |
| smoke: 6프레임 지연 / PAINTING 고정 | 각각 423프레임 정상 완료 |
| 저장 입력 재생 | 423프레임 정상 완료 |
| 비교 CSV 생성 | 세 조건의 지표·backend·종료 상태 포함 |
| Python 컴파일 / PowerShell 실행기 구문 | 통과 |

LSTM·공유제어·IK 계산을 120회 측정했다. 초기 자세에서 y축으로 매번 0.3 mm의 TCP 이동을 요청하고 힘은 10 N으로 제공했다. 중앙값 **10.30 ms**, 95백분위 **11.45 ms**, 최대 **13.42 ms**였다. 물리 엔진·렌더링·Haply 통신을 제외한 계산 경로의 시간이다.

리뷰에서 확인한 렌더링에 따른 추가 물리 진행, cylinder 접촉력 보고 설정, 중립 입력에서의 후퇴 의도 소실, native Stop/Pause 처리를 수정했다. 로컬 결과는 `.cache/teleop-final-validation/`에 보관하며 Git에는 실행 코드·테스트·검증 기록을 포함한다.

## 대상 Isaac PC에서 확인할 항목

현재 PC의 Python과 확인한 설치 경로에는 Isaac Sim 런타임이 없다. **PhysX 장면 실행과 실제 Haply 조작은 아직 수행하지 않았다.** 위 smoke 결과는 프로그램 연결 확인용이다.

1. `teleop.py isaac --input scripted --condition manual`로 초기 자세·메시·벽과 롤러 위치를 확인한다. TCP/FK 및 제어 구간의 물리 시간 불일치는 실행기가 오류로 보고한다.
2. 접근 후 `force_N`이 증가하고 후퇴하면 0으로 감소하는지 확인한다. 초기 간격은 약 35.78 mm이다. 접촉해도 힘이 계속 0이면 cylinder collider와 contact view를 확인한다.
3. 같은 입력을 `--headless`로 실행해 GUI 여부에 따른 물리 시간·접촉 추이를 비교한다. 제어 구간마다 120 Hz 스텝 네 번을 진행해야 한다.
4. Haply B 버튼·축 방향·스케일을 확인한다. 버튼 해제, 브리지 종료, 재연결, Pause 후 Play에서 명령 점프가 없는지 확인한다.
5. Esc, 패널 종료, native Stop, 창 닫기에서 summary와 종료 상태가 저장되는지 확인한다.
6. PAINTING 구간을 독립적으로 표시하여 세 조건과 지연·고정 상태 실험을 비교한다. 접촉 강성·관절 drive·스케일은 metadata로 보존한다.

재현 명령은 [USAGE_ko.md](USAGE_ko.md)에 있다. 테스트 환경에는 `simulation/requirements-haply.txt`를 설치한다.
