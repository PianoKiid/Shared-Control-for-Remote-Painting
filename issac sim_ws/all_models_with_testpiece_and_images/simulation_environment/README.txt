상용로봇 뿜칠/용접 + 새 시험체

commercial_spray_weld_testpiece.png: 기존 로컬 Isaac scene.usda의 실제 로봇/시험체 메시와 저장된 월드 변환을 읽어 별도 렌더러로 그린 이미지입니다. 라이브 Isaac 화면 캡처가 아닙니다. 원본 재질 대신 식별용 색상을 사용했습니다. 로컬 적용 설정은 변경하지 않았습니다.

testpiece/source/Steel Structure.usdc: 새 시험체 원본, 바이트 변경 없음.
testpiece/source/Steel_Structure_portable.usdc: 원본의 Windows 역슬래시 텍스처 경로만 /로 바꾼 호환본. 형상 유지. 배치용 USDA는 이 호환본을 참조합니다.
testpiece/source/textures/: 원본 HDR 자산.
testpiece/h_steel_placed.usda: 기존 시뮬레이션 위치 및 충돌 설정 포함. 메시와 텍스처 상대경로를 유지하여 함께 이동하세요.

기존 로봇 URDF·메시·미리보기는 전체 ZIP에 그대로 포함합니다. 이 추가 묶음은 로컬 제어기/ROS 실행 전체를 복제한 패키지는 아닙니다.
