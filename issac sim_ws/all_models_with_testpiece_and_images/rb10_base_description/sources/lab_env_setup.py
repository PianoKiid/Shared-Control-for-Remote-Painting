"""
RB10 실험실 환경 추가 스크립트
기준: phase4_session4_environment.md (2026-05-12 측정값)

URDF(robot_paint.urdf)를 불러와 저장한 USD에는 이미
  로봇팔 + 힘센서 + 롤러 + D405 + 테이블 + 철판
이 들어 있다. 이 스크립트는 나머지
  바닥, 벽, 작업영역 테이프, ZED 거치대(ㄴ자 프레임, 볼헤드, 볼트), ZED 카메라
를 추가하고, 로봇 관절 목표값을 실제 작업 자세(WORK_POSE)로 맞춘다.

좌표계: world = 실제 RB10 base = (0, 0, 0), 단위 m, Z가 위.
URDF 안의 support_world 가 이 world 와 같다.

"""
import math
import numpy as np
import omni.usd
from pxr import Usd, UsdGeom, UsdPhysics, Gf

# =============================================================================
# 0. 여기만 바꾸기: 저장한 로봇 USD 경로
# =============================================================================
ROBOT_USD = "/home/jungho/Desktop/rb10.....usd"   # 롤러 EOAT + 힘센서 + D405 달린 새 로봇 USD

# 로봇 받침대가 +90도 돌아가 있는 만큼 base 관절을 반대로 돌려서 상쇄 (도구가 벽 +X 를 향하게)
# 원래 동작(보정 없음)으로 되돌리려면 0.0
BASE_OFFSET_DEG = -90.0

ENV = "/World/LabEnv"          # 추가 물체들을 모아둘 위치

# =============================================================================
# 1. USD 열기
# =============================================================================
import os

PHYSICS_VARIANT = "physx"      # rb10.usd 의 Physics variant 중 사용할 것 (physx / physics / mujoco / none)

ctx = omni.usd.get_context()

# (1) rb10.usd 를 매번 새로 연다 (이전 실행의 찌꺼기 제거)
if not os.path.isfile(ROBOT_USD):
    raise RuntimeError(f"로봇 USD 파일이 없음: {ROBOT_USD}  → 터미널에서 ls ~/Desktop 으로 확인")
ctx.open_stage(ROBOT_USD)
stage = ctx.get_stage()
print(f"[OK] rb10.usd 새로 열기: {stage.GetRootLayer().identifier}")

# (2) 로봇 본체 = default prim (/rb10_base_description)
ROBOT_ROOT = stage.GetDefaultPrim()
if not ROBOT_ROOT or not ROBOT_ROOT.IsValid():
    raise RuntimeError("rb10.usd 에 default prim 이 없음")
print(f"[OK] 로봇 본체: {ROBOT_ROOT.GetPath()}")

# (3) 관절(물리)이 불러와지도록 Physics variant 선택
_vsets = ROBOT_ROOT.GetVariantSets()
if _vsets.HasVariantSet("Physics"):
    _vs = _vsets.GetVariantSet("Physics")
    if not _vs.GetVariantSelection():
        _vs.SetVariantSelection(PHYSICS_VARIANT)
    print(f"[OK] Physics variant = {_vs.GetVariantSelection()} (선택지: {_vs.GetVariantNames()})")

# (4) 로봇이 제대로 들어왔는지 확인: 모양(link0) + 관절 6개
_n_link0 = sum(1 for p in stage.Traverse() if p.GetName() == "link0")
_n_rev = sum(1 for p in stage.Traverse() if p.IsA(UsdPhysics.RevoluteJoint))
print(f"[DIAG] link0 {_n_link0}개, 회전 관절 {_n_rev}개  ← 1개, 6개면 정상")
if _n_link0 == 0:
    raise RuntimeError(
        "로봇 모양을 못 불러옴 → rb10.usd 옆에 Shared-Control-for-Remote-Painting 폴더가 있는지 확인 "
        "(rb10.usd 가 그 폴더 안의 파일들을 불러옴)")
if _n_rev == 0:
    raise RuntimeError("로봇 관절을 못 불러옴 → 위 Physics variant 줄 확인 (PHYSICS_VARIANT 를 'physics' 로 바꿔보기)")

# 반복 실행해도 겹치지 않게 기존 환경 지우기
if stage.GetPrimAtPath(ENV):
    stage.RemovePrim(ENV)
UsdGeom.Xform.Define(stage, "/World")
UsdGeom.Xform.Define(stage, ENV)


# =============================================================================
# 2. 도형 만드는 함수들
# =============================================================================
def _place(prim, center, scale=None):
    xf = UsdGeom.Xformable(prim)
    xf.AddTranslateOp().Set(Gf.Vec3d(*center))
    if scale is not None:
        xf.AddScaleOp().Set(Gf.Vec3f(*scale))


def add_box(name, center, size, color, collide=True):
    """center: 중심 좌표 [x,y,z], size: 크기 [x,y,z] (m)"""
    cube = UsdGeom.Cube.Define(stage, f"{ENV}/{name}")
    cube.CreateSizeAttr(1.0)                       # 1m 정육면체를 size 만큼 늘림
    cube.CreateDisplayColorAttr([Gf.Vec3f(*color)])
    _place(cube.GetPrim(), center, size)
    if collide:
        UsdPhysics.CollisionAPI.Apply(cube.GetPrim())
    return cube


def add_sphere(name, center, radius, color):
    s = UsdGeom.Sphere.Define(stage, f"{ENV}/{name}")
    s.CreateRadiusAttr(radius)
    s.CreateDisplayColorAttr([Gf.Vec3f(*color)])
    _place(s.GetPrim(), center)
    UsdPhysics.CollisionAPI.Apply(s.GetPrim())
    return s


def add_cylinder(name, center, radius, height, color, axis="Z"):
    c = UsdGeom.Cylinder.Define(stage, f"{ENV}/{name}")
    c.CreateRadiusAttr(radius)
    c.CreateHeightAttr(height)
    c.CreateAxisAttr(axis)
    c.CreateDisplayColorAttr([Gf.Vec3f(*color)])
    _place(c.GetPrim(), center)
    UsdPhysics.CollisionAPI.Apply(c.GetPrim())
    return c


# =============================================================================
# 3. 바닥 (테이블 다리 끝, z = -0.823)
# =============================================================================
add_box("Floor", [0.0, 0.0, -0.828], [6.0, 6.0, 0.01], (0.35, 0.35, 0.35))

# =============================================================================
# 4. 벽 (작업면)
#    중심 [0.81, 0, 0.5], 크기 [0.02, 2.0, 1.5] → 앞면 x = +0.80
# =============================================================================
WALL_CENTER = [0.81, 0.0, 0.5]
WALL_SIZE = [0.02, 2.0, 1.5]
WALL_FRONT_X = WALL_CENTER[0] - WALL_SIZE[0] / 2      # 0.80
add_box("Wall", WALL_CENTER, WALL_SIZE, (0.92, 0.92, 0.92))

# =============================================================================
# 5. 작업영역 노란 테이프
#    중심 [0.80, 0, 0.5], 폭 0.5 (y) × 높이 0.4 (z), 테이프 폭 0.02
#    벽 앞 1mm 에 띄워서 겹쳐 깜빡이는 현상 방지
# =============================================================================
AREA_W, AREA_H, AREA_ZC = 0.5, 0.4, 0.5
TAPE_W, TAPE_X = 0.02, WALL_FRONT_X - 0.001
YELLOW = (1.0, 0.85, 0.0)
z_top, z_bot = AREA_ZC + AREA_H / 2, AREA_ZC - AREA_H / 2
y_out = AREA_W / 2

add_box("Tape_Top",    [TAPE_X, 0.0, z_top - TAPE_W / 2], [0.001, AREA_W, TAPE_W], YELLOW, collide=False)
add_box("Tape_Bottom", [TAPE_X, 0.0, z_bot + TAPE_W / 2], [0.001, AREA_W, TAPE_W], YELLOW, collide=False)
add_box("Tape_Left",   [TAPE_X, -y_out + TAPE_W / 2, AREA_ZC], [0.001, TAPE_W, AREA_H], YELLOW, collide=False)
add_box("Tape_Right",  [TAPE_X,  y_out - TAPE_W / 2, AREA_ZC], [0.001, TAPE_W, AREA_H], YELLOW, collide=False)

# =============================================================================
# 6. ZED 거치대 (ㄴ자 알루미늄 프레임 + 볼헤드 + 볼트)
# =============================================================================
ALU = (0.6, 0.6, 0.65)
add_box("Mount_Seg1_Horizontal", [-0.35, 0.2, 0.015], [0.30, 0.05, 0.05], ALU)
add_box("Mount_Seg2_Vertical",   [-0.50, 0.2, 0.465], [0.05, 0.05, 0.85], ALU)
add_sphere("Mount_Ballhead", [-0.50, 0.2, 0.92], 0.025, (0.08, 0.08, 0.08))
add_cylinder("Mount_Bolt",   [-0.50, 0.2, 0.95], 0.004, 0.01, (0.55, 0.55, 0.60))

# =============================================================================
# 7. ZED 카메라 (문서의 optical static TF 사용)
#    translation [-0.471575, 0.256286, 1.008593]
#    rotation xyzw [-0.536213, 0.626502, -0.429749, 0.367815]
#    ROS optical frame(+Z 앞, +Y 아래) → USD camera(-Z 앞, +Y 위) 는 로컬 X축 180도 차이
# =============================================================================
#    구조 (공식 ZED_2i.usdc 와 같은 이름):
#      {ENV}/ZED                         본체 — md 중심 [-0.5, 0.2, 1.0], 카메라 방향대로 기울어짐
#        /base_link/ZED_2i/CameraLeft    좌 카메라 — md optical TF 위치·방향 그대로
#        /base_link/ZED_2i/CameraRight   우 카메라 — 좌에서 baseline 만큼 오른쪽
#        /base_link/ZED_2i/Body_Visual   검은 상자 (보기용)
from scipy.spatial.transform import Rotation as _R

ZED_CENTER = np.array([-0.5, 0.2, 1.0])                          # md: ZED collision/root 중심
ZED_OPTICAL_T = np.array([-0.471575, 0.256286, 1.008593])        # md: 좌 카메라 optical 위치
ZED_OPTICAL_Q_XYZW = [-0.536213, 0.626502, -0.429749, 0.367815]  # md: 좌 카메라 optical 방향

# 가정값 (md 에 없음)
ZED_BASELINE = 0.12                       # 좌우 렌즈 간격 120 mm (ZED 2i 제조사 스펙)
ZED_BODY_SIZE = (0.03, 0.175, 0.03)       # 본체 크기 (깊이, 폭, 높이) — 대략값
ZED_FX_PX = 530.0                         # HD720 초점거리(px) 근사값 — 실제 calibration 값으로 교체 권장

# 본체 방향 = optical 방향에서 축 이름만 바꾼 것
#   body +X(앞) = optical +Z,  body +Y(왼쪽) = optical -X,  body +Z(위) = optical -Y
_R_opt = _R.from_quat(ZED_OPTICAL_Q_XYZW).as_matrix()
_R_body = _R_opt @ np.array([[0.0, -1.0, 0.0], [0.0, 0.0, -1.0], [1.0, 0.0, 0.0]])

ZED_ROOT = f"{ENV}/ZED"
_zed_root = UsdGeom.Xform.Define(stage, ZED_ROOT)
_zm = Gf.Matrix4d(1.0)
_zm.SetRotateOnly(Gf.Matrix3d(*_R_body.T.flatten().tolist()))   # Gf 는 행=축 관례 → 전치
_zm.SetTranslateOnly(Gf.Vec3d(*ZED_CENTER.tolist()))
UsdGeom.Xformable(_zed_root.GetPrim()).AddTransformOp().Set(_zm)
UsdGeom.Xform.Define(stage, ZED_ROOT + "/base_link")
_ZED_INNER = ZED_ROOT + "/base_link/ZED_2i"
UsdGeom.Xform.Define(stage, _ZED_INNER)

# 좌·우 카메라 위치 — md optical TF 를 본체 기준으로 바꿈
#   USD 카메라는 -Z 를 보고 +Y 가 위 → ROS optical 에서 local X축 180도
_R_cam_local = _R_body.T @ _R_opt @ np.diag([1.0, -1.0, -1.0])
_p_left = _R_body.T @ (ZED_OPTICAL_T - ZED_CENTER)               # 약 (0.015, +0.06, 0.015)
_p_right = _p_left + np.array([0.0, -ZED_BASELINE, 0.0])         # 오른쪽 = 본체 -Y

# 겉모양 (보기용, collision 없음) — 실물처럼 양 끝이 둥근 막대 + 앞면 렌즈 2개
#   앞에서 보면 "직사각형 + 양쪽 반원" 모양. 렌즈가 앞면에 오도록 본체를 렌즈 뒤에 둔다.
_BODY_D, _BODY_W, _BODY_H = ZED_BODY_SIZE                        # 깊이, 전체 폭, 높이
_body_c = np.array([_p_left[0] - _BODY_D / 2.0, 0.0, _p_left[2]])  # 두 렌즈 가운데, 렌즈 뒤
_BLACK = Gf.Vec3f(0.05, 0.05, 0.05)

_zmid = UsdGeom.Cube.Define(stage, _ZED_INNER + "/Body_Visual")          # 가운데 직육면체
_zmid.CreateSizeAttr(1.0)
_zmid.CreateDisplayColorAttr([_BLACK])
_zmid_xf = UsdGeom.Xformable(_zmid.GetPrim())
_zmid_xf.AddTranslateOp().Set(Gf.Vec3d(*_body_c.tolist()))
_zmid_xf.AddScaleOp().Set(Gf.Vec3f(_BODY_D, _BODY_W - _BODY_H, _BODY_H))

for _side, _sy in [("L", +1.0), ("R", -1.0)]:                           # 양 끝 둥근 부분
    _end = UsdGeom.Cylinder.Define(stage, _ZED_INNER + f"/Body_End_{_side}")
    _end.CreateAxisAttr("X")                                            # 깊이 방향으로 뻗은 원기둥
    _end.CreateRadiusAttr(_BODY_H / 2.0)
    _end.CreateHeightAttr(_BODY_D)
    _end.CreateDisplayColorAttr([_BLACK])
    UsdGeom.Xformable(_end.GetPrim()).AddTranslateOp().Set(Gf.Vec3d(
        float(_body_c[0]), float(_sy * (_BODY_W - _BODY_H) / 2.0), float(_body_c[2])))

for _side, _lp in [("L", _p_left), ("R", _p_right)]:                    # 렌즈 = 은색 테두리 + 어두운 유리
    for _part, _r, _h, _dx, _col in [
        ("Ring",  0.0125, 0.004, 0.002, (0.70, 0.72, 0.75)),           # 은색 테두리 (앞으로 2 mm)
        ("Glass", 0.0090, 0.004, 0.004, (0.10, 0.14, 0.22)),           # 어두운 유리 (앞으로 4 mm)
    ]:
        _lens = UsdGeom.Cylinder.Define(stage, _ZED_INNER + f"/Lens_{_side}_{_part}")
        _lens.CreateAxisAttr("X")
        _lens.CreateRadiusAttr(_r)
        _lens.CreateHeightAttr(_h)
        _lens.CreateDisplayColorAttr([Gf.Vec3f(*_col)])
        UsdGeom.Xformable(_lens.GetPrim()).AddTranslateOp().Set(Gf.Vec3d(
            float(_lp[0] + _dx), float(_lp[1]), float(_lp[2])))
_H_AP = 20.955                                                   # mm (USD 기본값)
_FOCAL = _H_AP * ZED_FX_PX / 1280.0                              # fx(px) → focal(mm)
_V_AP = _H_AP * 720.0 / 1280.0                                   # 16:9

ZED_LEFT_CAM = _ZED_INNER + "/CameraLeft"
ZED_RIGHT_CAM = _ZED_INNER + "/CameraRight"
for _cpath, _cp in [(ZED_LEFT_CAM, _p_left), (ZED_RIGHT_CAM, _p_right)]:
    _c = UsdGeom.Camera.Define(stage, _cpath)
    _c.CreateClippingRangeAttr(Gf.Vec2f(0.05, 20.0))
    _c.CreateHorizontalApertureAttr(_H_AP)
    _c.CreateVerticalApertureAttr(_V_AP)
    _c.CreateFocalLengthAttr(_FOCAL)
    _cm = Gf.Matrix4d(1.0)
    _cm.SetRotateOnly(Gf.Matrix3d(*_R_cam_local.T.flatten().tolist()))
    _cm.SetTranslateOnly(Gf.Vec3d(*[float(v) for v in _cp]))
    UsdGeom.Xformable(_c.GetPrim()).AddTransformOp().Set(_cm)

print(f"[OK] ZED 2i (md 기반) 생성: {ZED_ROOT} — 좌/우 카메라, baseline={ZED_BASELINE} m, fx≈{ZED_FX_PX} px")

# =============================================================================
# 8. 물리 장면이 없으면 추가 (▶ Play 때 중력·관절이 작동하려면 필요)
# =============================================================================
if not any(p.IsA(UsdPhysics.Scene) for p in stage.Traverse()):
    scene = UsdPhysics.Scene.Define(stage, "/physicsScene")
    scene.CreateGravityDirectionAttr(Gf.Vec3f(0.0, 0.0, -1.0))
    scene.CreateGravityMagnitudeAttr(9.81)
    print("[OK] physicsScene 추가")

# =============================================================================
# 9. 로봇 작업 자세 (실제 RB10 펜던트 값, rad)
#    ▶ Play 를 누르면 관절 모터가 이 각도로 움직인다
# =============================================================================
WORK_POSE = {
    "base":      0.0005,   # +0.03 deg
    "shoulder": -0.9343,   # -53.53 deg
    "elbow":     2.4246,   # +138.92 deg
    "wrist1":   -1.6293,   # -93.35 deg
    "wrist2":    1.5675,   # +89.81 deg
    "wrist3":    0.0000,
}
STIFFNESS, DAMPING = 2500.0, 300.0

found = []
for p in stage.Traverse():
    if p.IsA(UsdPhysics.RevoluteJoint) and p.GetName() in WORK_POSE:
        drive = UsdPhysics.DriveAPI.Apply(p, "angular")
        drive.CreateTypeAttr("force")
        target_deg = math.degrees(WORK_POSE[p.GetName()])          # USD 각도 단위는 degree
        if p.GetName() == "base":
            target_deg += BASE_OFFSET_DEG                            # 받침대 +90도 상쇄
            print(f"[OK] base 목표 = 펜던트 {math.degrees(WORK_POSE['base']):.2f}° "
                  f"+ 보정 {BASE_OFFSET_DEG:.0f}° = {target_deg:.2f}°")
        drive.CreateTargetPositionAttr(target_deg)
        drive.CreateStiffnessAttr(STIFFNESS)
        drive.CreateDampingAttr(DAMPING)
        drive.CreateMaxForceAttr(1e6)
        found.append(p.GetName())

if len(found) == 6:
    print(f"[OK] 관절 6개 목표 자세 설정: {found}")
else:
    print(f"[WARN] 관절 {len(found)}개만 찾음: {found} — USD 안 관절 이름 확인 필요")

# =============================================================================
# 10. 진단: 로봇 link0 위치가 world 원점에 있는지
#     (0,0,0) 이 아니면 로봇 루트에 추가 이동이 걸린 것 → 환경 물체와 어긋남
# =============================================================================
for p in stage.Traverse():
    if p.GetName() == "link0" and p.IsA(UsdGeom.Xformable):
        m = UsdGeom.Xformable(p).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        t = m.ExtractTranslation()
        print(f"[DIAG] link0 world 위치 = ({t[0]:.4f}, {t[1]:.4f}, {t[2]:.4f})  ← (0,0,0) 이면 정상")
        # link0 의 x축이 world 에서 어느 방향인지 (Gf 행렬은 0번째 행 = x축 방향)
        x_axis = m.ExtractRotationMatrix().GetRow(0)
        yaw_deg = math.degrees(math.atan2(x_axis[1], x_axis[0]))
        net_deg = yaw_deg + BASE_OFFSET_DEG                          # 받침대 회전 + base 보정
        print(f"[DIAG] link0 z축 회전 = {yaw_deg:.1f}°, base 보정 = {BASE_OFFSET_DEG:.0f}°, "
              f"합계 = {net_deg:.1f}°")
        if abs(net_deg) < 1.0:
            print("[OK] 합계 0° → WORK_POSE 에서 도구가 벽(+X)을 향함")
        else:
            print(f"[WARN] 합계가 0° 가 아님 → BASE_OFFSET_DEG 를 {-yaw_deg:.0f} 으로 바꾸면 벽을 향함")
        break

# =============================================================================
# 11. 기대값 (URDF 순기구학으로 미리 계산한 값, world 기준)
#     Play 후 tcp 를 클릭해서 Property 창의 위치와 비교해 보기
# =============================================================================
print("[INFO] WORK_POSE 에서 기대값: TCP ≈ (0.174, -0.154, 0.739), 도구 방향 ≈ +X(벽), "
      "롤러 중심 x ≈ 0.43 (벽 앞면 0.80 까지 약 0.37 m 떨어진 대기 자세)")

# =============================================================================
# 12. [추가] D405 손목 카메라 (센서)
#     로봇 USD 의 D405 는 "모양"뿐이라 영상이 안 나온다. URDF 의 d405 depth optical
#     frame 과 같은 위치·방향(tcp 기준)에 USD 카메라를 하나 둔다.
#     tcp 기준 위치 (0.00905, -0.0764, 0.04375), 정면 = tcp -Y (롤러 쪽), 화면 위 = tcp +Z
# =============================================================================
D405_POS_IN_TCP = (0.00905, -0.07640, 0.04375)
# Gf 행렬은 "행 = 축" 관례. USD 카메라: x=화면 오른쪽, y=화면 위, -z=정면
_D405_ROT_IN_TCP = Gf.Matrix3d(
    -1.0, 0.0, 0.0,    # 카메라 x축 = tcp -X
     0.0, 0.0, 1.0,    # 카메라 y축 = tcp +Z
     0.0, 1.0, 0.0,    # 카메라 z축 = tcp +Y  → 정면(-z) = tcp -Y
)

D405_CAMERA_PRIM_PATH = None
_tcp_prim = next((p for p in stage.Traverse()
                  if p.GetName() == "tcp" and p.IsA(UsdGeom.Xformable)), None)
if _tcp_prim is None:
    print("[WARN] tcp prim 없음 — D405 카메라 생략")
else:
    D405_CAMERA_PRIM_PATH = _tcp_prim.GetPath().pathString + "/d405_depth_camera"
    if stage.GetPrimAtPath(D405_CAMERA_PRIM_PATH):
        stage.RemovePrim(D405_CAMERA_PRIM_PATH)                  # 반복 실행 대비
    _d405_cam = UsdGeom.Camera.Define(stage, D405_CAMERA_PRIM_PATH)
    _d405_cam.CreateClippingRangeAttr(Gf.Vec2f(0.04, 1.50))      # D405 는 근거리용
    _d405_cam.CreateFocalLengthAttr(2.0)                         # 원본 isaac_sim_rb10.py 값
    _d405_cam.CreateHorizontalApertureAttr(3.8)
    _d405_cam.CreateVerticalApertureAttr(2.85)
    _d405_m = Gf.Matrix4d(1.0)
    _d405_m.SetRotateOnly(_D405_ROT_IN_TCP)
    _d405_m.SetTranslateOnly(Gf.Vec3d(*D405_POS_IN_TCP))
    UsdGeom.Xformable(_d405_cam.GetPrim()).AddTransformOp().Set(_d405_m)
    print(f"[OK] D405 카메라(센서) 추가: {D405_CAMERA_PRIM_PATH}")

# =============================================================================
# 13. [추가] ROS2 연결 (원본 isaac_sim_rb10.py 와 같은 토픽 이름)
#     보냄: /joint_states, /clock, /tf(ZED), ZED 컬러·깊이, D405 깊이
#     받음: /isaac_joint_command  (관절 각도 명령, rad)
#     ▶ Play 중에만 토픽이 나간다.
# =============================================================================
import time as _time
import omni.kit.app
import omni.graph.core as og
import usdrt.Sdf
from pxr import Sdf

try:
    from isaacsim.core.utils.extensions import enable_extension
except ImportError:
    from omni.isaac.core.utils.extensions import enable_extension

try:
    enable_extension("isaacsim.ros2.bridge")
    _bridge_name = "isaacsim.ros2.bridge"
except Exception:
    enable_extension("omni.isaac.ros2_bridge")
    _bridge_name = "omni.isaac.ros2_bridge"
_manager = omni.kit.app.get_app().get_extension_manager()
for _i in range(50):
    if _manager.get_enabled_extension_id(_bridge_name):
        print(f"[OK] ROS2 bridge enabled: {_manager.get_enabled_extension_id(_bridge_name)}")
        break
    _time.sleep(0.1)
else:
    raise RuntimeError(f"ROS2 bridge '{_bridge_name}' 켜기 실패")


def _node_type(name_50, name_45):
    """Isaac Sim 버전에 따라 노드 이름이 달라서, 있는 쪽을 고른다."""
    try:
        if og.get_node_type(name_50) is not None:
            return name_50
    except Exception:
        pass
    return name_45


NT_TICK = "omni.graph.action.OnPlaybackTick"
NT_SIM_TIME = _node_type("isaacsim.core.nodes.IsaacReadSimulationTime",
                         "omni.isaac.core_nodes.IsaacReadSimulationTime")
NT_PUB_TF = _node_type("isaacsim.ros2.bridge.ROS2PublishTransformTree",
                       "omni.isaac.ros2_bridge.ROS2PublishTransformTree")
NT_PUB_JS = _node_type("isaacsim.ros2.bridge.ROS2PublishJointState",
                       "omni.isaac.ros2_bridge.ROS2PublishJointState")
NT_SUB_JS = _node_type("isaacsim.ros2.bridge.ROS2SubscribeJointState",
                       "omni.isaac.ros2_bridge.ROS2SubscribeJointState")
NT_ARTIC_CTRL = _node_type("isaacsim.core.nodes.IsaacArticulationController",
                           "omni.isaac.core_nodes.IsaacArticulationController")
NT_PUB_CLOCK = _node_type("isaacsim.ros2.bridge.ROS2PublishClock",
                          "omni.isaac.ros2_bridge.ROS2PublishClock")
NT_CREATE_RP = _node_type("isaacsim.core.nodes.IsaacCreateRenderProduct",
                          "omni.isaac.core_nodes.IsaacCreateRenderProduct")
NT_CAMERA_HELPER = _node_type("isaacsim.ros2.bridge.ROS2CameraHelper",
                              "omni.isaac.ros2_bridge.ROS2CameraHelper")
NT_CAMERA_INFO_HELPER = _node_type("isaacsim.ros2.bridge.ROS2CameraInfoHelper",
                                   "omni.isaac.ros2_bridge.ROS2CameraInfoHelper")
keys = og.Controller.Keys

# 로봇 articulation 경로 (관절 명령을 받을 대상)
ARTICULATION_PATH = next((p.GetPath().pathString for p in stage.Traverse()
                          if p.HasAPI(UsdPhysics.ArticulationRootAPI)), None)
if ARTICULATION_PATH is None:
    raise RuntimeError("로봇 ArticulationRoot 를 못 찾음 — 로봇 USD 를 열었는지 확인")
print(f"[OK] ArticulationRoot: {ARTICULATION_PATH}")

ZED_RES_W, ZED_RES_H, ZED_FRAME_SKIP = 1280, 720, 1     # 60 Hz / 2 = 30 Hz
ZED_LEFT_FRAME_ID = "zed_left_camera_frame_optical"
ZED_RIGHT_FRAME_ID = "zed_right_camera_frame_optical"
ZED_RGB_TOPIC = "/zed/zed_node/rgb/color/rect/image"
ZED_RGB_INFO_TOPIC = "/zed/zed_node/rgb/color/rect/camera_info"
ZED_DEPTH_TOPIC = "/zed/zed_node/depth/depth_registered"
ZED_DEPTH_INFO_TOPIC = "/zed/zed_node/depth/camera_info"
D405_RES_W, D405_RES_H, D405_FRAME_SKIP = 640, 480, 1
D405_DEPTH_TOPIC = "/d405/d405/depth/image_rect_raw"
D405_DEPTH_INFO_TOPIC = "/d405/d405/depth/camera_info"
D405_OPTICAL_FRAME_ID = "d405_color_optical_frame"

# 반복 실행 대비: 이전 그래프 지우기
_GRAPHS = ["/World/TFGraph", "/World/JointGraph", "/World/ClockGraph",
           "/World/ZedROS2Graph", "/World/D405ROS2Graph"]
for _g in _GRAPHS:
    if stage.GetPrimAtPath(_g):
        stage.RemovePrim(_g)


def _set_camera_target(node_path, camera_path):
    """render product 노드가 어떤 카메라를 찍을지 연결 (SET_VALUES 로는 안 돼서 따로)."""
    _np = stage.GetPrimAtPath(node_path)
    _rel = _np.GetRelationship("inputs:cameraPrim") or \
        _np.CreateRelationship("inputs:cameraPrim", custom=False)
    _rel.SetTargets([Sdf.Path(camera_path)])


# (a) ZED 카메라 위치 → /tf  (로봇 TF 는 바깥 robot_state_publisher 가 URDF 로 계산)
og.Controller.edit(
    {"graph_path": "/World/TFGraph", "evaluator_name": "execution"},
    {
        keys.CREATE_NODES: [("Tick", NT_TICK), ("SimTime", NT_SIM_TIME), ("PubTF", NT_PUB_TF)],
        keys.CONNECT: [
            ("Tick.outputs:tick", "PubTF.inputs:execIn"),
            ("SimTime.outputs:simulationTime", "PubTF.inputs:timeStamp"),
        ],
        keys.SET_VALUES: [
            ("PubTF.inputs:parentPrim", [Sdf.Path("/World")]),
            ("PubTF.inputs:targetPrims", [Sdf.Path(ZED_ROOT)]),   # 본체 + 좌우 카메라 자동 포함
            ("PubTF.inputs:topicName", "/tf"),
        ],
    },
)

# (b) 관절 각도 보내기 + 관절 명령 받기
og.Controller.edit(
    {"graph_path": "/World/JointGraph", "evaluator_name": "execution"},
    {
        keys.CREATE_NODES: [
            ("Tick", NT_TICK), ("SimTime", NT_SIM_TIME),
            ("PubJS", NT_PUB_JS), ("SubJC", NT_SUB_JS), ("WriteJC", NT_ARTIC_CTRL),
        ],
        keys.CONNECT: [
            ("Tick.outputs:tick", "PubJS.inputs:execIn"),
            ("Tick.outputs:tick", "SubJC.inputs:execIn"),
            ("Tick.outputs:tick", "WriteJC.inputs:execIn"),
            ("SimTime.outputs:simulationTime", "PubJS.inputs:timeStamp"),
            ("SubJC.outputs:jointNames", "WriteJC.inputs:jointNames"),
            ("SubJC.outputs:positionCommand", "WriteJC.inputs:positionCommand"),
            ("SubJC.outputs:velocityCommand", "WriteJC.inputs:velocityCommand"),
            ("SubJC.outputs:effortCommand", "WriteJC.inputs:effortCommand"),
        ],
        keys.SET_VALUES: [
            ("WriteJC.inputs:robotPath", ARTICULATION_PATH),
            ("PubJS.inputs:topicName", "/joint_states"),
            ("SubJC.inputs:topicName", "/isaac_joint_command"),
            ("PubJS.inputs:targetPrim", [usdrt.Sdf.Path(ARTICULATION_PATH)]),
        ],
    },
)

# (c) 시뮬레이션 시간 → /clock
og.Controller.edit(
    {"graph_path": "/World/ClockGraph", "evaluator_name": "execution"},
    {
        keys.CREATE_NODES: [("Tick", NT_TICK), ("SimTime", NT_SIM_TIME), ("PubClock", NT_PUB_CLOCK)],
        keys.CONNECT: [
            ("Tick.outputs:tick", "PubClock.inputs:execIn"),
            ("SimTime.outputs:simulationTime", "PubClock.inputs:timeStamp"),
        ],
        keys.SET_VALUES: [("PubClock.inputs:topicName", "/clock")],
    },
)

# (d) ZED 컬러·깊이 영상 + camera_info
og.Controller.edit(
    {"graph_path": "/World/ZedROS2Graph", "evaluator_name": "execution"},
    {
        keys.CREATE_NODES: [
            ("OnTick", NT_TICK), ("ZedRP", NT_CREATE_RP), ("ZedRightRP", NT_CREATE_RP),
            ("RGBHelper", NT_CAMERA_HELPER), ("DepthHelper", NT_CAMERA_HELPER),
            ("CamInfoRGB", NT_CAMERA_INFO_HELPER), ("CamInfoDepth", NT_CAMERA_INFO_HELPER),
        ],
        keys.CONNECT: [
            ("OnTick.outputs:tick", "ZedRP.inputs:execIn"),
            ("OnTick.outputs:tick", "ZedRightRP.inputs:execIn"),
            # 우 카메라는 camera_info 의 stereo 값(좌우 간격)용
            ("ZedRightRP.outputs:renderProductPath", "CamInfoRGB.inputs:renderProductPathRight"),
            ("ZedRightRP.outputs:renderProductPath", "CamInfoDepth.inputs:renderProductPathRight"),
            ("ZedRP.outputs:execOut", "RGBHelper.inputs:execIn"),
            ("ZedRP.outputs:execOut", "DepthHelper.inputs:execIn"),
            ("ZedRP.outputs:execOut", "CamInfoRGB.inputs:execIn"),
            ("ZedRP.outputs:execOut", "CamInfoDepth.inputs:execIn"),
            ("ZedRP.outputs:renderProductPath", "RGBHelper.inputs:renderProductPath"),
            ("ZedRP.outputs:renderProductPath", "DepthHelper.inputs:renderProductPath"),
            ("ZedRP.outputs:renderProductPath", "CamInfoRGB.inputs:renderProductPath"),
            ("ZedRP.outputs:renderProductPath", "CamInfoDepth.inputs:renderProductPath"),
        ],
        keys.SET_VALUES: [
            ("ZedRP.inputs:width", ZED_RES_W), ("ZedRP.inputs:height", ZED_RES_H),
            ("ZedRightRP.inputs:width", ZED_RES_W), ("ZedRightRP.inputs:height", ZED_RES_H),
            ("CamInfoRGB.inputs:topicNameRight", ZED_RGB_INFO_TOPIC + "_right"),
            ("CamInfoRGB.inputs:frameIdRight", ZED_RIGHT_FRAME_ID),
            ("CamInfoDepth.inputs:topicNameRight", ZED_DEPTH_INFO_TOPIC + "_right"),
            ("CamInfoDepth.inputs:frameIdRight", ZED_RIGHT_FRAME_ID),
            ("RGBHelper.inputs:type", "rgb"),
            ("RGBHelper.inputs:topicName", ZED_RGB_TOPIC),
            ("RGBHelper.inputs:frameId", ZED_LEFT_FRAME_ID),
            ("RGBHelper.inputs:frameSkipCount", ZED_FRAME_SKIP),
            ("DepthHelper.inputs:type", "depth"),
            ("DepthHelper.inputs:topicName", ZED_DEPTH_TOPIC),
            ("DepthHelper.inputs:frameId", ZED_LEFT_FRAME_ID),
            ("DepthHelper.inputs:frameSkipCount", ZED_FRAME_SKIP),
            ("CamInfoRGB.inputs:topicName", ZED_RGB_INFO_TOPIC),
            ("CamInfoRGB.inputs:frameId", ZED_LEFT_FRAME_ID),
            ("CamInfoRGB.inputs:frameSkipCount", ZED_FRAME_SKIP),
            ("CamInfoDepth.inputs:topicName", ZED_DEPTH_INFO_TOPIC),
            ("CamInfoDepth.inputs:frameId", ZED_LEFT_FRAME_ID),
            ("CamInfoDepth.inputs:frameSkipCount", ZED_FRAME_SKIP),
        ],
    },
)
_set_camera_target("/World/ZedROS2Graph/ZedRP", ZED_LEFT_CAM)
_set_camera_target("/World/ZedROS2Graph/ZedRightRP", ZED_RIGHT_CAM)
print("[OK] ROS2: /tf, /joint_states, /isaac_joint_command, /clock, ZED 컬러·깊이")

# (e) D405 깊이 영상 + camera_info
if D405_CAMERA_PRIM_PATH:
    og.Controller.edit(
        {"graph_path": "/World/D405ROS2Graph", "evaluator_name": "execution"},
        {
            keys.CREATE_NODES: [
                ("OnTick", NT_TICK), ("D405RP", NT_CREATE_RP),
                ("DepthHelper", NT_CAMERA_HELPER), ("CamInfoDepth", NT_CAMERA_INFO_HELPER),
            ],
            keys.CONNECT: [
                ("OnTick.outputs:tick", "D405RP.inputs:execIn"),
                ("D405RP.outputs:execOut", "DepthHelper.inputs:execIn"),
                ("D405RP.outputs:execOut", "CamInfoDepth.inputs:execIn"),
                ("D405RP.outputs:renderProductPath", "DepthHelper.inputs:renderProductPath"),
                ("D405RP.outputs:renderProductPath", "CamInfoDepth.inputs:renderProductPath"),
            ],
            keys.SET_VALUES: [
                ("D405RP.inputs:width", D405_RES_W), ("D405RP.inputs:height", D405_RES_H),
                ("DepthHelper.inputs:type", "depth"),
                ("DepthHelper.inputs:topicName", D405_DEPTH_TOPIC),
                ("DepthHelper.inputs:frameId", D405_OPTICAL_FRAME_ID),
                ("DepthHelper.inputs:frameSkipCount", D405_FRAME_SKIP),
                ("CamInfoDepth.inputs:topicName", D405_DEPTH_INFO_TOPIC),
                ("CamInfoDepth.inputs:frameId", D405_OPTICAL_FRAME_ID),
                ("CamInfoDepth.inputs:frameSkipCount", D405_FRAME_SKIP),
            ],
        },
    )
    _set_camera_target("/World/D405ROS2Graph/D405RP", D405_CAMERA_PRIM_PATH)
    print(f"[OK] ROS2: D405 깊이 {D405_DEPTH_TOPIC}")

if BASE_OFFSET_DEG != 0.0:
    print(f"[WARN] base 보정 {BASE_OFFSET_DEG:.0f}° 사용 중 → /joint_states 의 base 값에도 이 보정이 섞여 나가고, "
          f"/isaac_joint_command 로 보낼 base 값에도 같은 보정을 더해야 함")

# =============================================================================
# 14. [추가] 정답값 파일 (ground_truth.json) — 원본과 같은 항목
#     시뮬레이션 속 벽·작업영역·카메라·로봇 받침대의 정확한 위치를 world 기준으로 저장
# =============================================================================
import json as _json

GT_PATH = os.path.expanduser("~/ground_truth.json")


def _world_pose_dict(prim_path, usd_camera_to_optical=False):
    """prim 의 world 위치·방향. 카메라면 USD 카메라 → ROS optical (local X축 180도)."""
    _p = stage.GetPrimAtPath(prim_path)
    if not _p or not _p.IsValid() or not _p.IsA(UsdGeom.Xformable):
        return None
    _m = UsdGeom.Xformable(_p).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
    _t = _m.ExtractTranslation()
    _q = _m.ExtractRotation().GetQuat()
    if usd_camera_to_optical:
        _q = _q * Gf.Quatd(0.0, 1.0, 0.0, 0.0)
    if _q.GetReal() < 0:                       # q 와 -q 는 같은 회전 → w ≥ 0 으로 통일
        _q = Gf.Quatd(-_q.GetReal(), -_q.GetImaginary())
    _i = _q.GetImaginary()
    return {"translation": [float(_t[0]), float(_t[1]), float(_t[2])],
            "rotation_xyzw": [float(_i[0]), float(_i[1]), float(_i[2]), float(_q.GetReal())]}


_link0_path = next((p.GetPath().pathString for p in stage.Traverse() if p.GetName() == "link0"), None)
_gt = {
    "schema_version": 1,
    "units": "meters / quaternion(xyzw)",
    "physics_dt_hz": 60,
    "wall": {
        "world_pose": {"translation": WALL_CENTER, "rotation_xyzw": [0.0, 0.0, 0.0, 1.0]},
        "size_xyz": WALL_SIZE,
        "front_surface_x": WALL_FRONT_X,
        "front_surface_normal": [-1.0, 0.0, 0.0],
    },
    "work_area": {
        "size_wh": [AREA_W, AREA_H],
        "tape_width": TAPE_W,
        "corners": [
            {"id": "tl", "world": [WALL_FRONT_X, -y_out, z_top]},
            {"id": "tr", "world": [WALL_FRONT_X,  y_out, z_top]},
            {"id": "bl", "world": [WALL_FRONT_X, -y_out, z_bot]},
            {"id": "br", "world": [WALL_FRONT_X,  y_out, z_bot]},
        ],
    },
    "camera_optical_world_pose": _world_pose_dict(ZED_LEFT_CAM, usd_camera_to_optical=True),
    "camera_right_optical_world_pose": _world_pose_dict(ZED_RIGHT_CAM, usd_camera_to_optical=True),
    "robot_base_world_pose": _world_pose_dict(_link0_path) if _link0_path else None,
    "base_joint_offset_deg": BASE_OFFSET_DEG,
    "topics": {
        "rgb": ZED_RGB_TOPIC, "rgb_camera_info": ZED_RGB_INFO_TOPIC,
        "depth": ZED_DEPTH_TOPIC, "depth_camera_info": ZED_DEPTH_INFO_TOPIC,
        "d405_depth": D405_DEPTH_TOPIC, "d405_depth_camera_info": D405_DEPTH_INFO_TOPIC,
    },
    "frames": {"left_camera_optical": ZED_LEFT_FRAME_ID, "right_camera_optical": ZED_RIGHT_FRAME_ID,
               "d405_optical": D405_OPTICAL_FRAME_ID},
}
try:
    with open(GT_PATH, "w") as _f:
        _json.dump(_gt, _f, indent=2)
    print(f"[OK] ground_truth.json 저장: {GT_PATH}")
except Exception as _e:
    print(f"[ERROR] ground_truth.json 저장 실패: {_e}")

# =============================================================================
# 15. 뷰포트의 카메라 아이콘 숨기기 (= 메뉴의 Show By Type → Cameras 끄기)
#     카메라 센서 3개(ZED 좌·우, D405) 자리에 Isaac Sim 이 그리는 회색 영화카메라 아이콘만 숨긴다.
#     카메라 센서·ROS2 영상에는 영향 없음.
#     Kit 버전에 따라 쓰는 설정이 달라서 두 가지를 모두 끈다:
#       /app/viewport/show/camera                 (새 뷰포트)
#       /persistent/app/viewport/displayOptions   (이전 뷰포트, 카메라 = 1<<5 비트)
#     다시 보이게 하려면: 뷰포트 눈 아이콘 → Show By Type → Cameras 체크
# =============================================================================
import carb.settings

HIDE_CAMERA_ICONS = True
if HIDE_CAMERA_ICONS:
    _settings = carb.settings.get_settings()
    try:
        _settings.set_bool("/app/viewport/show/camera", False)
        _opts = _settings.get("/persistent/app/viewport/displayOptions")
        if isinstance(_opts, int):
            _settings.set_int("/persistent/app/viewport/displayOptions", _opts & ~(1 << 5))
        print("[OK] 뷰포트 카메라 아이콘 숨김 (카메라 센서는 그대로)")
    except Exception as _e:
        print(f"[WARN] 카메라 아이콘 숨기기 실패: {_e} → 뷰포트 눈 아이콘 → Show By Type → Cameras 해제")

print("=" * 60)
print("실험실 환경 추가 완료")
print(f"  벽 앞면 x = {WALL_FRONT_X:.3f} m, 작업영역 {AREA_W} × {AREA_H} m @ z={AREA_ZC}")
print("  ▶ Play 를 누르면 로봇이 WORK_POSE 로 이동")
print("  ZED 시점 보기: 뷰포트 상단 카메라 메뉴 → Cameras → CameraLeft")
print("  저장: File → Save As")
print("=" * 60)
