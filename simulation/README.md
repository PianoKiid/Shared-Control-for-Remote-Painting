# Isaac Sim

현재 보유한 로컬 자료는 [환경 구축 계획](../docs/isaac_sim/environment_setup_plan.html)입니다.
로봇·EOAT·베이스 모델과 장면 USD는 아직 이 작업 폴더에 없습니다.

멘티가 환경을 만들면 다음 위치에 저장합니다.

```text
simulation/
  assets/
    robot/
    base/
    eoat/
  scenes/
    painting_scene.usd
  scripts/
    joint_demo.py
  README.md
```

USD가 참조하는 메시·재질·텍스처를 함께 포함하고, 프로젝트 안에서는 상대경로를 사용합니다.
사용한 Isaac Sim 버전과 장면을 여는 방법을 이 README에 추가합니다.
Isaac Sim 설치 폴더와 캐시는 프로젝트에 포함하지 않습니다.
