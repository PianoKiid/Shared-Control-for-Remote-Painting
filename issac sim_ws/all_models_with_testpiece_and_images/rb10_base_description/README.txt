rb10_base_description

RB10-1300E-U + 고정식 받침 테이블(600×800×813 mm) + 마운팅 철판(200×200×10 mm). 기존 Isaac 장면의 실측 치수 기반 box 형상이며 이동대차/바퀴 CAD는 아닙니다. robot은 EOAT 없는 본체, robot_spray/weld/paint는 공정별 장착본입니다.

사용법
- ZIP 전체를 풀고 urdf/<model>.urdf를 Isaac Sim URDF Importer에서 선택합니다. meshes 폴더를 유지하세요.
- ROS 2: 패키지 폴더를 워크스페이스 src에 넣고 colcon build 후 install/setup.bash를 source합니다. urdf/<model>.ros.urdf는 package:// 경로를 사용합니다.
- <model>.urdf는 상대 메시 경로, <model>.ros.urdf는 ROS 패키지 경로인 동일 모델입니다.
- 모델 치수/관절/질량/관성은 저장소 원본 또는 기존 자산 생성기의 값을 유지합니다. 실측 보정 완료를 뜻하지 않습니다.
- EOAT TCP는 설계 기준이며 실측 보정되지 않았습니다.
- 모델 전달용입니다. 제어기, MoveIt SRDF, 센서 실행, ROS bridge, 힘 제어, 공정 출력 설정은 포함하지 않습니다.
- Isaac import 후 고정부 고정, 관절 drive, 충돌 분해와 센서 설정을 별도로 확인하세요. fixed joint 병합은 필요한 TCP/센서 프레임 보존 여부를 확인하고 선택하세요.
- 검증 범위: XML, 단일 루트/연결성, 메시 참조/해시, ZIP 무결성. 수신 환경 ROS/Isaac 실행 검증은 미실시.
- manifest.json에 메시 출처/해시가 있습니다. 원본 자산의 배포 권한을 새로 부여하는 패키지가 아닙니다.

https://docs.isaacsim.omniverse.nvidia.com/6.0.0/importer_exporter/ext_isaacsim_asset_importer_urdf.html

받침대 좌표/물리 조건
- support_world는 실제 RB10 마운팅 면 중심입니다. 바닥은 z=-0.823 m입니다. 바닥을 z=0에 배치하려면 모델 전체를 +0.823 m 올리세요.
- support_world → link0에 Z +90도 보정을 포함했습니다. 기존 Isaac 장면과 동일하며 외부에서 중복 회전하지 마세요.
- 받침대/철판은 고정식 시각·충돌 형상입니다. 미측정 질량/관성을 임의로 넣지 않았습니다. Isaac에서는 고정 베이스로 가져오고 고정 링크의 물리 처리를 확인하세요. 이동대차 동역학 모델이 아닙니다.
- sources에 치수 원문과 기존 장면 파일을 동봉했습니다.
