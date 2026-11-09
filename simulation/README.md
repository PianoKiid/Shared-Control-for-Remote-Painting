# Isaac Sim + Haply 원격 도장

RB10과 롤러를 Isaac Sim 5.1에서 움직이고, Haply 입력과 기존 LSTM을 사용해 공유제어를 비교하는 실행기입니다.

- **설치·실행·평가:** [USAGE_ko.md](USAGE_ko.md)
- **실행 명령:** [teleop.py](teleop.py)
- **설정:** [config/painting.json](config/painting.json)
- **알고리즘 수정:** [controller.py](../src/painting_teleop/controller.py)
- **포함 모델:** [모델 출처](models/provenance.json)
- **검증 기록:** [VALIDATION.md](VALIDATION.md)

장면은 프로젝트의 `issac sim_ws/all_models_with_testpiece_and_images/rb10_base_description/urdf/robot_paint.urdf`와 연결된 메시로 생성합니다. ROS2와 외부 USD 파일은 필요하지 않습니다. 결과는 `results/teleop/`, 임시 URDF는 `.cache/painting/`에 저장합니다.
