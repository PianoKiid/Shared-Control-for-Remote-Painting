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
# 0. 로봇 USD 경로
#    레포 안의 아래 파일을 그대로 쓴다. 레포를 어디에 받았든 자동으로 찾는다.
#    Shared-Control-for-Remote-Painting/issac sim_ws/all_models_with_testpiece_and_images/
#      rb10_base_description/sources/rb10.usd
# =============================================================================
import os

REPO_NAME = "Shared-Control-for-Remote-Painting"
ROBOT_USD_REL = os.path.join(REPO_NAME, "issac sim_ws",
                             "all_models_with_testpiece_and_images", "rb10_base_description",
                             "sources", "rb10.usd")


def _find_robot_usd():
    # (1) 이 스크립트를 sources 폴더에서 파일로 실행한 경우: 바로 옆 rb10.usd
    try:
        _cand = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rb10.usd")
        if os.path.isfile(_cand):
            return _cand
    except NameError:
        pass
    # (2) 그 외 (Script Editor 붙여넣기 등): 컴퓨터 안에서 레포 폴더를 찾아 그 안의 rb10.usd 사용
    #     홈 폴더를 먼저 보고 (빠름), 없으면 컴퓨터 전체를 본다 (외장 드라이브 포함, 조금 걸릴 수 있음)
    _home = os.path.expanduser("~")
    if os.name == "nt":                                    # Windows: C:\, D:\ ... 모든 드라이브
        _roots = [f"{c}:\\" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.exists(f"{c}:\\")]
    else:                                                  # Linux / Mac
        _roots = ["/"]
    _SKIP = {"proc", "sys", "dev", "run", "snap", "boot", "usr", "lib", "lib64", "bin", "sbin",
             "etc", "var", "tmp", "node_modules", "__pycache__", "Windows", "Program Files",
             "Program Files (x86)", "ProgramData", "$Recycle.Bin"}
    for _top in [_home] + _roots:
        for _dirpath, _dirnames, _ in os.walk(_top, onerror=lambda e: None):   # 권한 없는 폴더는 건너뜀
            if REPO_NAME in _dirnames:
                _cand = os.path.join(_dirpath, ROBOT_USD_REL)
                if os.path.isfile(_cand):
                    print(f"[OK] rb10.usd 찾음: {_cand}")
                    return _cand
            _dirnames[:] = [d for d in _dirnames if not d.startswith(".") and d not in _SKIP]
            if _dirpath[len(_top):].count(os.sep) >= 8:    # 너무 깊이는 안 들어감
                _dirnames[:] = []
    raise RuntimeError(f"컴퓨터에서 레포 안 rb10.usd 를 못 찾음: {ROBOT_USD_REL}")


ROBOT_USD = _find_robot_usd()

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
    raise RuntimeError(f"로봇 USD 파일이 없음: {ROBOT_USD}")


# (0) rb10.usd 안의 깨진 파일 경로를 레포 기준으로 자동 수정
#     rb10.usd 는 원래 바탕화면에서 "Shared-Control-for-Remote-Painting/..." 경로로 레포 파일을 불러오게 저장돼 있었다.
#     레포 안(sources)으로 옮기면 그 경로가 깨지므로, 레포 안에서 같은 파일을 찾아 상대경로로 바꿔 저장한다.
#     한 번 고치면 rb10.usd 파일 자체가 바뀌므로 다음부터는 아무것도 안 바꾼다.
def _fix_robot_usd_paths(usd_path):
    from pxr import Sdf, UsdUtils
    usd_dir = os.path.dirname(os.path.abspath(usd_path))
    root = usd_dir                                        # 레포 최상위 폴더 찾기
    while os.path.basename(root) != "Shared-Control-for-Remote-Painting" and root != os.path.dirname(root):
        root = os.path.dirname(root)
    if os.path.basename(root) != "Shared-Control-for-Remote-Painting":
        print("[WARN] rb10.usd is outside the repo folder - skip path fix")
        return
    layer = Sdf.Layer.FindOrOpen(usd_path)
    changed, missing = [], []

    def _fix(p):
        if not p or "://" in p:
            return p
        full = p if os.path.isabs(p) else os.path.normpath(os.path.join(usd_dir, p))
        if os.path.exists(full):
            return p                                      # 이미 정상
        parts = [s for s in p.replace("\\", "/").split("/") if s not in ("", ".")]
        for i in range(len(parts)):                       # 앞쪽 폴더를 하나씩 떼면서 레포 안에서 찾기
            cand = os.path.join(root, *parts[i:])
            if os.path.exists(cand):
                new = os.path.relpath(cand, usd_dir).replace(os.sep, "/")
                new = new if new.startswith(".") else "./" + new
                changed.append((p, new))
                return new
        missing.append(p)
        return p

    UsdUtils.ModifyAssetPaths(layer, _fix)
    for _old, _new in changed:
        print(f"[FIX] {_old}  ->  {_new}")
    for _m in missing:
        print(f"[WARN] path not found in repo: {_m}")
    if changed:
        layer.Save()
        print(f"[OK] rb10.usd paths fixed ({len(changed)}) and saved - commit rb10.usd and the folders above")


_fix_robot_usd_paths(ROBOT_USD)
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
        "로봇 모양을 못 불러옴 → rb10.usd 가 다른 파일을 상대경로로 불러오는 버전일 수 있음. "
        "원래 위치의 rb10.usd 를 열어 File → Save Flattened As 로 sources/rb10.usd 에 다시 저장")
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
# 4. 벽 (작업면) — 실험 데이터(13-VS, 13-03_0.mcap)로 만든 평면
#    실제로 벽을 누르던 순간(힘 > 10 N)의 롤러 중심 점 3개로 평면을 만듦
#      (접촉점 중 서로 가장 멀리 떨어진 세 점 = 삼각형 넓이가 가장 큰 세 점, 롤러 중심, mm)
#        t = 101.50 s  ( 769.9, -230.9, 299.9)  70 N
#        t = 313.96 s  ( 758.9,    4.4, 862.9)  11 N
#        t = 462.03 s  ( 756.0, -263.7, 912.3)  22 N
#    롤러 중심 평면 + 롤러 반지름(26 mm) = 벽 표면.  x축에서 약 1.3° 기울어 있음.
#    나머지 접촉점들은 이 평면에서 평균 0.6 mm 정도 벗어남.
#    (아래 값은 처음 켤 때 기본값. 재생 폴더를 Load 하면 그 폴더의 rb_ee_pose.csv + rb_ee_wrench.csv 로
#     같은 방법(세 점)으로 평면을 다시 만들어 벽을 옮김 — WALL_AUTO_PLANE)
#    벽 크기 = 롤러 중심이 지나간 범위 전체(맨 끝까지) + 여유 (위 WALL_MARGIN_TOP, 아래 WALL_MARGIN_BOTTOM, 좌우 WALL_MARGIN_SIDE)
#      → 롤러 중심이 가장 끝에 있어도 롤러 전체(길이 22 cm)가 벽 위에 옴
#    WALL_FROM_DATA = False 면 예전처럼 md 문서 값 (x = 0.80 수직 벽, 2.0 × 1.5 m)
# =============================================================================
WALL_FROM_DATA = True
WALL_THICK = 0.02
WALL_MARGIN_TOP = 0.30           # 위 여유 (m)  — 최소 0.12 (롤러 길이 절반 11 cm + 1 cm)
WALL_MARGIN_BOTTOM = 0.12        # 아래 여유 (m)
WALL_MARGIN_SIDE = 0.25          # 좌우 여유 (m)
if WALL_FROM_DATA:
    WALL_N = np.array([0.999729, -0.006674, 0.022304])   # 벽 표면 법선 (로봇 → 벽 방향)
    WALL_U = np.array([0.006676, 0.999978, 0.0])         # 벽 위 가로축 (≈ +y)
    WALL_V = np.array([-0.022304, 0.000149, 0.999751])   # 벽 위 세로축 (≈ +z)
    WALL_D = 0.80389                                     # 벽 표면: WALL_N · p = WALL_D
    PAINT_U = (-0.2588, 0.0095)                          # 롤러 중심이 지나간 범위 (가로, m)
    PAINT_V = (0.2703, 0.8977)                           # 롤러 중심이 지나간 범위 (세로, m)
else:
    WALL_N, WALL_U, WALL_V = np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0]), np.array([0.0, 0.0, 1.0])
    WALL_D = 0.80
    PAINT_U, PAINT_V = (-0.25, 0.25), (0.30, 0.70)       # md 작업영역 0.5 × 0.4 m
    WALL_MARGIN_TOP = WALL_MARGIN_BOTTOM = WALL_MARGIN_SIDE = 0.75
WALL_U_RANGE = (PAINT_U[0] - WALL_MARGIN_SIDE, PAINT_U[1] + WALL_MARGIN_SIDE)
WALL_V_RANGE = (PAINT_V[0] - WALL_MARGIN_BOTTOM, PAINT_V[1] + WALL_MARGIN_TOP)
WALL_FRONT_X = WALL_D            # (아래 계산은 전부 "법선 방향 거리" 로 함. 이름만 예전 그대로)


def add_plate(name, u_rng, v_rng, depth, thick, color, collide=True):
    """벽 평면 위 네모 판: 가로 u_rng, 세로 v_rng (m), 표면에서 법선 방향 depth 위치부터 thick 두께."""
    uc, vc = sum(u_rng) / 2, sum(v_rng) / 2
    w, h = u_rng[1] - u_rng[0], v_rng[1] - v_rng[0]
    ctr = WALL_N * (WALL_D + depth + thick / 2) + WALL_U * uc + WALL_V * vc
    M = np.eye(4)
    M[:3, 0], M[:3, 1], M[:3, 2], M[:3, 3] = WALL_N * thick, WALL_U * w, WALL_V * h, ctr
    cube = UsdGeom.Cube.Define(stage, f"{ENV}/{name}")
    cube.CreateSizeAttr(1.0)
    cube.CreateDisplayColorAttr([Gf.Vec3f(*color)])
    UsdGeom.Xformable(cube.GetPrim()).AddTransformOp().Set(Gf.Matrix4d(*M.T.flatten().tolist()))
    if collide:
        UsdPhysics.CollisionAPI.Apply(cube.GetPrim())
    return cube


# 벽 물리 충돌: 실제 롤러는 굴러가는데 시뮬레이션 롤러는 고정 원기둥이라, 벽과 물리 충돌하면
#   마찰 때문에 벽을 따라 매끄럽게 움직이지 않음. 벽 접촉·멈춤·힘은 코드가 위치로 직접 계산하므로
#   기본은 물리 충돌을 끔 (롤러가 벽을 지나가지 않는 건 코드의 벽 막기가 처리).
#   True 로 켜면 벽 마찰을 0 으로 둬서 붙잡히지 않게 함.
WALL_PHYSICS_COLLISION = False


def _build_wall():
    """지금 WALL_N/U/V/D, WALL_U_RANGE/V_RANGE 로 벽 판을 (다시) 만듦."""
    if stage.GetPrimAtPath(f"{ENV}/Wall").IsValid():
        stage.RemovePrim(f"{ENV}/Wall")
    w = add_plate("Wall", WALL_U_RANGE, WALL_V_RANGE, 0.0, WALL_THICK, (0.92, 0.92, 0.92),
                  collide=WALL_PHYSICS_COLLISION)
    if WALL_PHYSICS_COLLISION:
        from pxr import UsdShade
        mat = UsdShade.Material.Define(stage, f"{ENV}/WallNoFriction")
        pm = UsdPhysics.MaterialAPI.Apply(mat.GetPrim())
        pm.CreateStaticFrictionAttr(0.0)
        pm.CreateDynamicFrictionAttr(0.0)
        pm.CreateRestitutionAttr(0.0)
        UsdShade.MaterialBindingAPI.Apply(w.GetPrim()).Bind(
            mat, UsdShade.Tokens.weakerThanDescendants, "physics")
    return w


_wall = _build_wall()
print(f"[OK] 벽 물리 충돌: {'켜짐 (마찰 0)' if WALL_PHYSICS_COLLISION else '꺼짐 (접촉은 코드로 계산)'}")

print(f"[OK] 벽: {'실험 데이터(13-VS) 평면' if WALL_FROM_DATA else 'md 값'}  "
      f"법선 {np.round(WALL_N, 4).tolist()}, 크기 {WALL_U_RANGE[1] - WALL_U_RANGE[0]:.2f} × "
      f"{WALL_V_RANGE[1] - WALL_V_RANGE[0]:.2f} m")

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
STIFFNESS, DAMPING = 2500.0, 10.0    # DAMPING: 낮을수록 빨리 따라옴. 흔들리면 60~100 으로

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
# 10-1. 롤러 위치를 md 문서 값에 맞추기
#     rb10.usd(=URDF) 의 롤러는 TCP 에서 0.2442 m 앞에 붙어 있는데,
#     phase4_session4_environment.md 실측값은 0.2567 m (AFT200 0.0522 + 롤러 0.2045).
#     06_01 실험 데이터(벽 누를 때 TCP x = 0.508, 벽 0.80)도 md 값과 맞음.
#     → 롤러 부품(겉모양 + 충돌 모양)을 TCP -Y 방향으로 ROLLER_SHIFT_MD 만큼 앞으로 옮김.
#     rb10.usd 파일은 안 바뀜 (실행할 때만 옮김). 되돌리려면 0.0
# =============================================================================
ROLLER_SHIFT_MD = 0.0125         # m (= 0.2567 - 0.2442)
ROLLER_MIN_AHEAD = 0.12          # TCP 에서 이보다 앞에 있는 모양 부품 = 롤러 쪽 부품으로 보고 옮김

if ROLLER_SHIFT_MD != 0.0:
    _tc = Usd.TimeCode.Default()
    _all = list(Usd.PrimRange(stage.GetPseudoRoot(), Usd.TraverseInstanceProxies()))   # 인스턴스 안쪽까지
    _tcp_p = next((p for p in _all if p.GetName() == "tcp" and p.IsA(UsdGeom.Xformable)), None)
    if _tcp_p is None:
        print("[WARN] tcp 를 못 찾음 - 롤러 위치 보정 생략")
    else:
        _m_tcp = UsdGeom.Xformable(_tcp_p).ComputeLocalToWorldTransform(_tc)
        _m_tcp_inv = _m_tcp.GetInverse()
        _dir_w = _m_tcp.TransformDir(Gf.Vec3d(0.0, -1.0, 0.0)).GetNormalized()     # TCP -Y = 롤러 앞 방향
        _bc = UsdGeom.BBoxCache(_tc, ["default", "render", "proxy", "guide"])
        _targets = {}
        for _p in _all:
            if not _p.IsA(UsdGeom.Gprim) or str(_p.GetPath()).startswith(ENV):
                continue
            _r = _bc.ComputeWorldBound(_p).ComputeAlignedRange()
            if _r.IsEmpty():
                continue
            _ctr = _m_tcp_inv.Transform((_r.GetMin() + _r.GetMax()) / 2.0)
            if -_ctr[1] < ROLLER_MIN_AHEAD:                    # TCP 근처(힘센서, D405 등)는 그대로
                continue
            _a = _p
            while _a.IsInstanceProxy():                       # 인스턴스 안쪽은 못 고쳐서, 고칠 수 있는 바깥 부품으로
                _a = _a.GetParent()
            if _a.HasAPI(UsdPhysics.RigidBodyAPI) or _a.HasAPI(UsdPhysics.ArticulationRootAPI):
                print(f"[WARN] {_a.GetPath()} 는 로봇 링크라 못 옮김")
                continue
            _targets[str(_a.GetPath())] = _a
        # 부모-자식이 둘 다 있으면 부모만 옮김 (두 번 옮겨지지 않게)
        _keys = sorted(_targets, key=len)
        _final = [k for i, k in enumerate(_keys) if not any(k.startswith(o + "/") for o in _keys[:i])]
        _moved = []
        for _k in _final:
            _a = _targets[_k]
            _xf = UsdGeom.Xformable(_a)
            _m_par = _xf.ComputeParentToWorldTransform(_tc)     # 부모가 Xform 이 아니어도 정확
            _shift = _m_par.GetInverse().TransformDir(_dir_w) * ROLLER_SHIFT_MD   # 부모 좌표로 바꾼 이동량
            _old = _xf.GetOrderedXformOps()
            _op = _xf.AddTranslateOp(UsdGeom.XformOp.PrecisionDouble, "mdShift")
            _op.Set(Gf.Vec3d(_shift))
            _xf.SetXformOpOrder([_op] + list(_old), _xf.GetResetXformStack())
            _moved.append(_k)
        print(f"[OK] 롤러 쪽 부품 {len(_moved)}개를 {ROLLER_SHIFT_MD * 1000:.1f} mm 앞으로 (md 값):")
        for _k in _moved:
            _r = _bc.ComputeWorldBound(stage.GetPrimAtPath(_k)).ComputeAlignedRange()
            print(f"[DIAG]   {_k.split('/')[-1]}  (x 끝 {_r.GetMax()[0]:.3f})")
        if not _moved:
            print("[WARN] 옮길 롤러 부품을 못 찾음")

# =============================================================================
# 11. 기대값 (URDF 순기구학으로 미리 계산한 값, world 기준)
#     Play 후 tcp 를 클릭해서 Property 창의 위치와 비교해 보기
# =============================================================================
print("[INFO] WORK_POSE 에서 기대값: TCP ≈ (0.174, -0.154, 0.739), 도구 방향 ≈ +X(벽), "
      "롤러 중심 x ≈ 0.43 (벽 앞면 0.80 까지 약 0.37 m 떨어진 대기 자세)")

print("=" * 60)
print("실험실 환경 추가 완료")
print(f"  벽 표면 (법선 방향) = {WALL_D:.4f} m, 칠한 영역 {PAINT_U[1] - PAINT_U[0]:.2f} × {PAINT_V[1] - PAINT_V[0]:.2f} m")
print("  ▶ Play 를 누르면 로봇이 WORK_POSE 로 이동")
print("  ZED 시점 보기: 뷰포트 상단 카메라 메뉴 → Cameras → CameraLeft")
print("  저장: File → Save As")
print("=" * 60)


# =============================================================================
# 12. RB10 관절 조종 창 (원래 joint_teleop.py 내용 그대로)
#     환경 만들기와 동시에 조종 창이 뜬다. ▶ Play 를 눌러야 관절이 움직인다.
#
# 조작
#   마우스  : 창의 슬라이더 6개를 끌면 해당 관절이 그 각도로 움직임
#   키보드  : 1~6        관절 선택 (base, shoulder, elbow, wrist1, wrist2, wrist3)
#             ↑ / ↓      선택한 관절 +1° / -1°
#             Shift+↑↓   +5° / -5°
#             R          작업 자세(WORK_POSE)로 되돌리기
#             F          목표점 따라가기 켜기/끄기
#   목표점 따라가기 (Mouse target):
#             켜면 롤러 중심에 주황색 공(/World/TCP_Target)이 생긴다.
#             뷰포트에서 공을 클릭 → W(이동 도구) → 화살표를 마우스로 끌면
#             롤러가 공을 따라온다 (역기구학 IK 로 관절각 계산).
#             기본은 도구 방향 고정(벽을 향한 그대로). "Use target rotation" 을 켜면
#             E(회전 도구)로 공을 돌려서 도구 방향도 바꿀 수 있다.
#   벽 접촉  : 롤러(딱딱한 원통)는 벽 표면에서 멈춘다 (슬라이더·키보드·공·입력 재생 모두).
#             입력이 벽 안쪽으로 더 밀려고 한 만큼 힘이 생긴다 (가상 힘센서, ROLLER_MODEL = "rigid").
#             뒤로 빼거나 벽을 따라 좌우·위아래로는 움직일 수 있다.
#   힘 데이터: 조종 창에 Fz 표시, ▶ Play 동안 ~/isaac_force_logs/sim_ee_wrench_<시각>.csv 로 저장
#             (실제 /rb/ee_wrench 와 같은 열 이름·축: z = 도구 방향, 누르면 Fz 음수)
#   실험 재생: mcap_to_csv.py 로 뽑은 _csv 폴더 경로를 넣고 Load → ▶ Play → Replay.
#             rb_teleop_buttons.csv 의 buttons_b + rb_teleop_input_raw.csv 의 twist_linear_x,y,z
#             로 시뮬레이션 로봇을 조종 (입력 재생). b 가 True 인 동안만 움직임 (rb_joint_states.csv 안 씀)
#             시작 자세 = 처음 b 누른 순간의 rb_ee_pose, 벽 = 그 폴더의 세 점 평면 (파일 있을 때)
#             Exact 켜짐 = 각도를 바로 넣음 / 꺼짐 = 모터로 따라감
#
# 각도는 실제 RB10 펜던트 기준(도, °)으로 보여준다.
# base 관절은 위의 BASE_OFFSET_DEG 보정을 똑같이 더해서 시뮬레이션에 넣는다.
# (Isaac Sim 창 글꼴이 한글을 못 보여줘서 창·출력 글자는 영어로 둔다)
# =============================================================================
import builtins
import carb
import carb.input
import omni.appwindow
import omni.kit.app
import omni.ui as ui

# BASE_OFFSET_DEG 는 맨 위 값을 그대로 사용
STEP_DEG, BIG_STEP_DEG = 1.0, 5.0
LIMIT_DEG = 180.0                # URDF limit ±3.14 rad

JOINTS = ["base", "shoulder", "elbow", "wrist1", "wrist2", "wrist3"]
WORK_POSE_DEG = {                # 펜던트 값 (doc: phase4_session4_environment.md)
    "base": 0.03, "shoulder": -53.53, "elbow": 138.92,
    "wrist1": -93.35, "wrist2": 89.81, "wrist3": 0.0,
}

# 이전에 띄운 조종 창이 있으면 정리 (Run 을 여러 번 눌러도 창이 겹치지 않게)
_old = getattr(builtins, "_rb10_teleop", None)
if _old:
    try:
        _old["inp"].unsubscribe_to_keyboard_events(_old["kb"], _old["sub"])
    except Exception:
        pass
    try:
        _old["force_log_close"]()
    except Exception:
        pass
    for _k in ("update_sub", "replay_sub", "force_sub"):
        try:
            _old[_k].unsubscribe()
        except Exception:
            pass
    try:
        _old["window"].destroy()
    except Exception:
        pass
    builtins._rb10_teleop = None

# 관절 모터 찾기
stage = omni.usd.get_context().get_stage()
drives = {}
for p in stage.Traverse():
    if p.IsA(UsdPhysics.RevoluteJoint) and p.GetName() in JOINTS:
        drives[p.GetName()] = UsdPhysics.DriveAPI.Apply(p, "angular")   # 이미 있으면 그대로 사용

if len(drives) != 6:
    raise RuntimeError(f"Found {len(drives)} joints: {list(drives)}")
print(f"[OK] joints: {list(drives)}")


def _offset(name):
    return BASE_OFFSET_DEG if name == "base" else 0.0


def _current_pendant_deg(name):
    """지금 모터 목표값을 펜던트 각도로 (base 는 보정 빼기)."""
    v = drives[name].GetTargetPositionAttr().Get()
    return (float(v) if v is not None else 0.0) - _offset(name)


def _set_target(name, pendant_deg):
    """펜던트 각도 → 시뮬레이션 모터 목표값 (base 는 보정 더하기)."""
    pendant_deg = max(-LIMIT_DEG, min(LIMIT_DEG, pendant_deg))
    drives[name].GetTargetPositionAttr().Set(pendant_deg + _offset(name))


# 순기구학(FK) / 역기구학(IK) — robot_paint.urdf 수치, 펜던트 각도(도) 기준
#   world 기준 TCP 위치를 계산한다. (link0 +90° 와 base -90° 보정이 상쇄된 상태 = 보정 없는 URDF FK)
#   검증: WORK_POSE 에서 TCP = (0.174, -0.154, 0.739), 도구 방향 ≈ +X(벽).
#         벽 작업영역 전체(롤러가 벽에 닿는 거리, 50×40 cm)를 도구 방향 고정 상태로 도달 가능 (오차 < 0.01 mm)
def _rpy(r, p, y):
    cr, sr, cp, sp = math.cos(r), math.sin(r), math.cos(p), math.sin(p)
    cy, sy = math.cos(y), math.sin(y)
    return np.array([[cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
                     [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
                     [-sp, cp * sr, cp * cr]])


def _T(xyz=(0.0, 0.0, 0.0), rpy=(0.0, 0.0, 0.0)):
    M = np.eye(4)
    M[:3, :3] = _rpy(*rpy)
    M[:3, 3] = xyz
    return M


def _Rz(q):
    c, s = math.cos(q), math.sin(q)
    M = np.eye(4)
    M[:2, :2] = [[c, -s], [s, c]]
    return M


def _Ry(q):
    c, s = math.cos(q), math.sin(q)
    M = np.eye(4)
    M[0, 0], M[0, 2], M[2, 0], M[2, 2] = c, s, -s, c
    return M


_CHAIN = [  # URDF joint origin(부모 기준) + 회전축 : base, shoulder, elbow, wrist1, wrist2, wrist3
    ((0, 0, 0), _Rz), ((0, 0, 0.197), _Ry), ((0, -0.1875, 0.6127), _Ry),
    ((0, 0.1514, 0.57015), _Ry), ((0, -0.11715, 0), _Rz), ((0, 0, 0.11715), _Ry),
]
# link6 → ft_link → tcp (URDF fixed joint)
_TOOL = _T((0, 0.0147, 0), (-math.pi / 2, math.pi / 2, 0)) @ _T((0, 0, -0.13), (math.pi / 2, 0, -math.pi / 2))


def fk(q_deg):
    """펜던트 관절각(도) 6개 → TCP 4x4 행렬 (world)."""
    M = np.eye(4)
    for (xyz, rot), q in zip(_CHAIN, q_deg):
        M = M @ _T(xyz) @ rot(math.radians(q))
    return M @ _TOOL


def _rotvec(R):
    """회전행렬 → 회전벡터 (방향 오차 계산용)."""
    a = math.acos(max(-1.0, min(1.0, (np.trace(R) - 1.0) / 2.0)))
    if a < 1e-9:
        return np.zeros(3)
    if abs(math.pi - a) < 1e-6:
        return np.sqrt(np.maximum((np.diag(R) + 1.0) / 2.0, 0.0)) * a
    v = np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]])
    return v * a / (2.0 * math.sin(a))


_AXES = [2, 1, 1, 1, 2, 1]   # 관절 회전축 (0=x, 1=y, 2=z): base z, shoulder y, elbow y, wrist1 y, wrist2 z, wrist3 y


def _fk_jac(q_deg):
    """FK 한 번으로 TCP 행렬과 야코비안(관절축 기하로 직접 계산)을 같이 구함."""
    M = np.eye(4)
    axes, origins = [], []
    for (xyz, rot), q, a in zip(_CHAIN, q_deg, _AXES):
        M = M @ _T(xyz)
        axes.append(M[:3, a].copy())
        origins.append(M[:3, 3].copy())
        M = M @ rot(math.radians(q))
    M = M @ _TOOL
    J = np.zeros((6, 6))
    for i in range(6):
        J[:3, i] = np.cross(axes[i], M[:3, 3] - origins[i])
        J[3:, i] = axes[i]
    return M, J


def ik(q_seed_deg, p_target, R_target, iters=10, damping=0.05, tol=1e-4):
    """감쇠 최소제곱(DLS) IK: TCP 를 목표 위치·방향에 맞추는 관절각(도), 위치 오차(m).
    매 프레임 직전 자세에서 이어서 풀기 때문에 반복 10회, 0.1 mm 기준이면 충분 (한 프레임 약 2 ms)."""
    q = np.radians(np.asarray(q_seed_deg, float))
    W = np.diag([1.0, 1.0, 1.0, 0.3, 0.3, 0.3])
    for _ in range(iters):
        M, J = _fk_jac(np.degrees(q))
        e = np.concatenate([p_target - M[:3, 3], 0.3 * _rotvec(R_target @ M[:3, :3].T)])
        if np.linalg.norm(e) < tol:
            break
        J = W @ J
        step = J.T @ np.linalg.solve(J @ J.T + damping ** 2 * np.eye(6), e)
        n = np.linalg.norm(step)
        if n > 0.2:
            step *= 0.2 / n
        q = np.clip(q + step, -math.radians(LIMIT_DEG), math.radians(LIMIT_DEG))
    return np.degrees(q), float(np.linalg.norm(p_target - fk(np.degrees(q))[:3, 3]))


# 목표점 (주황색 공) — 마우스로 끌면 팔 끝이 따라온다
TARGET_PATH = "/World/TCP_Target"
TARGET_RADIUS = 0.035            # 롤러(반지름 2.6 cm)보다 커서 밖으로 보이게
# 공 = 롤러 중심. TCP 기준 롤러 중심 위치
#   앞쪽(TCP -Y) 거리는 phase4_session4_environment.md 값 0.2567 m (AFT200 0.0522 + 롤러 0.2045)
#   (robot_paint.urdf 로 계산하면 0.2442 m 라 1.25 cm 짧음 — 문서 실측값을 씀)
#   옆쪽 -0.018 m 는 URDF 값 그대로
ROLLER_IN_TCP = np.array([0.0, -0.2567, -0.018])
follow = {"on": False, "R_lock": None, "last": None}

# 벽 막기 — 롤러 중심이 WALL_STOP_X 를 넘으면 벽에 닿은 것으로 본다
#   (롤러를 반지름 ROLLER_RADIUS 인 공으로 보고 계산. 도구 방향 고정일 때는 실제 롤러와 같고,
#    "Use target rotation" 으로 크게 기울이면 롤러 끝이 먼저 닿을 수 있어 약간 오차가 생김)
ROLLER_RADIUS = 0.026            # 롤러 반지름 (m)
WALL_MARGIN = 0.0                # 0 = 벽 표면에서 접촉 시작
WALL_TOL = 0.0005                # 계산 오차 허용 0.5 mm

# 롤러 모델
#   "rigid" (기본): 보이는 딱딱한 원통 그대로. 벽 표면에서 멈추고 파고들지 않음.
#       힘 = ROLLER_K × (입력이 벽 안쪽으로 더 밀려고 한 양, 최대 INPUT_PUSH_MAX).  ← 햅틱의 god-object 방식
#   "soft": 스펀지처럼 눌림. 힘 = ROLLER_K × 눌린 깊이, FORCE_STOP 에서 멈춤 (최대 FORCE_STOP/ROLLER_K 파고듦)
#   ROLLER_K 10 N/mm (설계값): 벽·롤러 둘 다 딱딱한 면이라 힘을 몇 N 으로 낼지 정하는 값. 데이터로 맞춘 값 아님
#     (rigid 에서는 움직임·멈추는 위치에 영향 없음, 힘 크기만 바뀜)
#   FORCE_STOP 130 N: soft 에서만 씀 (06_01 실험에서 벽 누를 때 힘의 99% 가 127 N 이하)
ROLLER_MODEL = "rigid"
ROLLER_K = 10000.0               # N/m  (= 10 N/mm)
FORCE_STOP = 130.0               # N (soft 에서만)
# 접촉 보정 (CONTACT_OFFSET): 실제 롤러는 스펀지라 찌그러지고 팔도 살짝 휘어서, 실제로 벽을 누르던 순간에도
#   시뮬레이션의 딱딱한 롤러는 벽 몇 mm 앞에 있음 → 힘이 0. 그래서 "힘 계산용 벽면"을 그만큼 앞으로 당김.
#   (화면의 벽은 그대로. 롤러가 화면에서 몇 mm 파고들어 보이는 건 실제로 찌그러진 만큼)
CONTACT_OFFSET = 0.0             # m (벽을 실험 데이터 평면으로 만들었으므로 기본 0)


def _set_contact_offset(off):
    global CONTACT_OFFSET, WALL_CONTACT_X, WALL_STOP_X
    CONTACT_OFFSET = float(off)
    WALL_CONTACT_X = WALL_FRONT_X - ROLLER_RADIUS - WALL_MARGIN - CONTACT_OFFSET   # 롤러 중심이 여기 오면 접촉 시작
    WALL_STOP_X = WALL_CONTACT_X + (FORCE_STOP / ROLLER_K if ROLLER_MODEL == "soft" else 0.0)   # 여기서 멈춤


_set_contact_offset(CONTACT_OFFSET)
FORCE_LOG = True                 # ▶ Play 동안 힘 데이터를 CSV 로 저장
FORCE_LOG_DIR = "~/isaac_force_logs"
wall = {"q": None, "busy": False, "push": 0.0}   # push: rigid 에서 입력이 벽 안쪽으로 더 밀려고 한 양 (m)


ROLLER_PRIM_NAME = "roller_contact_collision"   # 이 이름이 들어간 롤러 충돌 모양을 읽어서 벽 접촉 계산에 씀


def _load_roller_points():
    """Isaac Sim 안의 롤러 충돌 모양을 TCP 기준 점들로 읽음 (원기둥이면 겉면 점, 메시면 꼭짓점).
    롤러가 기울면 끝부분이 먼저 벽에 닿는 것까지 정확히 계산하려고 씀. 못 찾으면 None (공 모양으로 계산)."""
    tc = Usd.TimeCode.Default()
    allp = list(Usd.PrimRange(stage.GetPseudoRoot(), Usd.TraverseInstanceProxies()))
    tcp_p = next((p for p in allp if p.GetName() == "tcp" and p.IsA(UsdGeom.Xformable)), None)
    rp = next((p for p in allp if ROLLER_PRIM_NAME in p.GetName() and p.IsA(UsdGeom.Gprim)), None)
    if tcp_p is None or rp is None:
        print("[WARN] roller collision shape not found - using sphere model")
        return None
    if rp.IsA(UsdGeom.Cylinder):
        cyl = UsdGeom.Cylinder(rp)
        r, h = float(cyl.GetRadiusAttr().Get()), float(cyl.GetHeightAttr().Get())
        ax = {"X": 0, "Y": 1, "Z": 2}[cyl.GetAxisAttr().Get() or "Z"]
        u, v = (ax + 1) % 3, (ax + 2) % 3
        loc = []
        for s_ in np.linspace(-h / 2, h / 2, 11):
            for a in np.linspace(0.0, 2 * math.pi, 72, endpoint=False):
                pt = [0.0, 0.0, 0.0]
                pt[ax], pt[u], pt[v] = s_, r * math.cos(a), r * math.sin(a)
                loc.append(pt)
    elif rp.IsA(UsdGeom.Mesh):
        loc = [list(p) for p in UsdGeom.Mesh(rp).GetPointsAttr().Get()]
        if len(loc) > 3000:
            loc = loc[:: len(loc) // 3000 + 1]
    else:
        rng = UsdGeom.Boundable(rp).ComputeLocalBound(tc, "default").GetRange()
        mn, mx = rng.GetMin(), rng.GetMax()
        loc = [[x, y, z] for x in (mn[0], mx[0]) for y in (mn[1], mx[1]) for z in (mn[2], mx[2])]
    m_rel = UsdGeom.Xformable(rp).ComputeLocalToWorldTransform(tc) * \
        UsdGeom.Xformable(tcp_p).ComputeLocalToWorldTransform(tc).GetInverse()
    pts = np.array([list(m_rel.Transform(Gf.Vec3d(*p))) for p in loc])
    print(f"[OK] roller shape for wall contact: {rp.GetName()} ({len(pts)} points, "
          f"center in TCP {np.round(pts.mean(0), 4).tolist()})")
    return pts


ROLLER_PTS = _load_roller_points()


def _roller_front(R, p):
    """TCP 회전 R, 위치 p → 롤러의 벽 쪽 맨 앞 (벽 법선 방향 거리) 와 그 점 (world).
    맨 앞 점이 벽 네모 밖이면 벽이 없는 것으로 보고 아주 먼 값을 돌려줌."""
    if ROLLER_PTS is None:
        c = p + R @ ROLLER_IN_TCP
        P = (c + WALL_N * ROLLER_RADIUS)[None, :]
    else:
        P = ROLLER_PTS @ R.T + p
    sN = P @ WALL_N
    i = int(np.argmax(sN))
    uu, vv = float(P[i] @ WALL_U), float(P[i] @ WALL_V)
    if not (WALL_U_RANGE[0] <= uu <= WALL_U_RANGE[1] and WALL_V_RANGE[0] <= vv <= WALL_V_RANGE[1]):
        return WALL_D - 1.0, P[i]                          # 벽 밖
    return float(sN[i]), P[i]


def _roller_x(q_deg):
    """관절각(도) → 벽 접촉 계산용 롤러 x (= 맨 앞 x - 반지름, 롤러 중심과 같은 기준)."""
    M = fk(q_deg)
    return _roller_front(M[:3, :3], M[:3, 3])[0] - ROLLER_RADIUS


def _allowed(q_new):
    """벽 밖이면 OK. 이미 닿아 있어도 벽에서 멀어지는 쪽이면 OK."""
    x_new = _roller_x(q_new)
    return x_new <= WALL_STOP_X + WALL_TOL or x_new <= _roller_x(wall["q"]) + 1e-6


def _wrench(q_deg):
    """관절각 → 가상 힘센서 값 (실제 /rb/ee_wrench 와 같은 축: z = 도구 방향, 누르면 Fz 음수).
    반환: 힘(N) xyz, 토크(Nm) xyz, 눌린 깊이(m), 벽까지 거리(m), TCP 위치"""
    M = fk(q_deg)
    R, p = M[:3, :3], M[:3, 3]
    front, cp = _roller_front(R, p)                         # 롤러 맨 앞 x, 접촉점
    surf = WALL_FRONT_X - WALL_MARGIN - CONTACT_OFFSET      # 힘 계산용 벽면
    press = max(0.0, front - surf)                          # 기록 자세 등이 벽 표면을 넘은 깊이
    if ROLLER_MODEL == "rigid":
        press = max(press, wall["push"])                    # + 입력이 더 밀려고 한 양
    gap = max(0.0, surf - front)
    Fw = -ROLLER_K * press * WALL_N                       # 벽이 롤러를 미는 힘 (world, 벽 법선 반대 방향)
    # 토크: 힘이 롤러 가운데 앞면에 걸린다고 봄 (롤러가 벽에 눌리면 접촉이 길이 방향으로 퍼지므로)
    ctr = p + R @ (ROLLER_PTS.mean(0) if ROLLER_PTS is not None else ROLLER_IN_TCP)
    cp = ctr + WALL_N * ROLLER_RADIUS
    Tw = np.cross(cp - p, Fw)                               # TCP 기준 토크 (world)
    S = np.column_stack([R[:, 0], R[:, 2], -R[:, 1]])       # 센서 축: x = TCP x, y = TCP z, z = TCP -y(도구 방향)
    return S.T @ Fw, S.T @ Tw, press, gap, p


def _show_wall(q, blocked=False):
    F, _T, press, gap, _p = _wrench(q)
    if press > 0.0:
        if ROLLER_MODEL == "rigid":
            txt = f"CONTACT  Fz {F[2]:6.1f} N  push {press * 1000:.1f} mm"
        else:
            txt = f"CONTACT  Fz {F[2]:6.1f} N  press {press * 1000:.1f} mm"
            if blocked or -F[2] >= FORCE_STOP - 0.5:
                txt += f"  STOP ({FORCE_STOP:.0f} N)"
    else:
        txt = f"wall gap: {gap * 1000:.1f} mm"
    wall_label.text = txt


def _on_slider(name, mdl):
    """슬라이더·키보드로 관절 하나가 바뀔 때: 벽을 뚫으면 원래 값으로 되돌림."""
    if wall["busy"]:
        return
    q_new = _q_now()
    if _allowed(q_new):
        _set_target(name, mdl.as_float)
        wall["q"] = q_new
        _show_wall(q_new)
    else:
        wall["busy"] = True
        mdl.set_value(wall["q"][JOINTS.index(name)])
        wall["busy"] = False
        _show_wall(wall["q"], blocked=True)


def _apply_pose(q_list):
    """관절 6개를 한 번에 바꿈 (버튼, R 키, 공 따라가기). 벽을 뚫으면 무시."""
    q_list = [float(v) for v in q_list]
    if not _allowed(q_list):
        _show_wall(wall["q"], blocked=True)
        return False
    wall["busy"] = True
    for n, v in zip(JOINTS, q_list):
        models[n].set_value(v)
    wall["busy"] = False
    for n in JOINTS:
        _set_target(n, models[n].as_float)
    wall["q"] = _q_now()
    _show_wall(wall["q"])
    return True


def _q_now():
    return [models[n].as_float for n in JOINTS]


def _target_to_tool():
    """공을 지금 롤러 중심 위치(방향은 TCP 방향)로 옮김."""
    M = fk(_q_now())
    p_ball = M[:3, 3] + M[:3, :3] @ ROLLER_IN_TCP
    if stage.GetPrimAtPath(TARGET_PATH):
        stage.RemovePrim(TARGET_PATH)
    s = UsdGeom.Sphere.Define(stage, TARGET_PATH)          # collision 없음 → 로봇과 안 부딪힘
    s.CreateRadiusAttr(TARGET_RADIUS)
    s.CreateDisplayColorAttr([Gf.Vec3f(1.0, 0.45, 0.0)])
    xf = UsdGeom.Xformable(s.GetPrim())
    xf.AddTranslateOp().Set(Gf.Vec3d(*[float(v) for v in p_ball]))
    print(f"[OK] target ball at roller center ({p_ball[0]:.3f}, {p_ball[1]:.3f}, {p_ball[2]:.3f})")
    q = Gf.Matrix3d(*M[:3, :3].T.flatten().tolist()).ExtractRotation().GetQuat()   # Gf 는 행=축 → 전치
    xf.AddOrientOp(UsdGeom.XformOp.PrecisionDouble).Set(q)
    follow["R_lock"] = M[:3, :3].copy()                    # 도구 방향 고정용
    follow["last"] = None


def _read_target():
    prim = stage.GetPrimAtPath(TARGET_PATH)
    if not prim or not prim.IsValid():
        return None, None
    m = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
    t = m.ExtractTranslation()
    r = m.ExtractRotationMatrix()
    R = np.array([[r[i][j] for j in range(3)] for i in range(3)]).T     # 행=축 → 열=축
    return np.array([t[0], t[1], t[2]], float), R


def _set_follow(on):
    follow["on"] = on
    if on:
        _target_to_tool()
        print("[OK] Mouse target ON - select /World/TCP_Target, press W, drag the arrows")
    if follow_model.as_bool != on:
        follow_model.set_value(on)


def _on_update(*args, **kwargs):
    """매 프레임: 공이 움직였으면 IK 로 관절각 계산 → 슬라이더(=모터 목표) 갱신."""
    if not follow["on"]:
        return
    p, R = _read_target()
    if p is None:
        return
    key = (tuple(np.round(p, 5)), tuple(np.round(R, 4).flatten()))
    if key == follow["last"]:
        return                                              # 공이 안 움직였으면 계산 안 함
    follow["last"] = key
    R_goal = R if rot_model.as_bool else follow["R_lock"]
    p_tcp = p - R_goal @ ROLLER_IN_TCP                     # 공(롤러 중심) → TCP 목표
    over = _roller_front(R_goal, p_tcp)[0] - ROLLER_RADIUS - WALL_STOP_X
    hit = over > 0.0
    if hit:                                                 # 공이 벽 안쪽이면 롤러는 멈춤 위치에서 멈춤
        p_tcp = p_tcp - WALL_N * over
    wall["push"] = over if hit else 0.0                     # rigid: 더 밀려고 한 양 → 힘
    q, perr = ik(_q_now(), p_tcp, R_goal)
    _apply_pose(q)
    if hit:
        _show_wall(wall["q"], blocked=True)
    reach_label.text = f"reach error: {perr * 1000:.1f} mm" + ("  (out of reach)" if perr > 0.005 else "")


# 실험 재생 (입력 파일)
import csv as _csv
import os as _os
import omni.timeline

REPLAY_CSV = ""                  # 기본 경로: _csv 폴더 (비워두면 창에서 입력)
REPLAY_SPEEDS = [0.5, 1.0, 2.0, 4.0]
# Input 모드: Haply 입력(teleop_input_raw) → delta(로봇 base 기준 속도 명령) → TCP 위치
#   raw → delta (실험 데이터 teleop_delta 와 97.7~99.9% 정확히 일치하는 규칙):
#     dx = clip( raw_y, ±INPUT_CLIP),  dy = clip(-raw_x, ±INPUT_CLIP),  dz = clip( raw_z, ±INPUT_CLIP)
#     회전 입력은 버림 (도구 자세 고정),  입력이 0 → 0이 아닌 값으로 바뀌는 첫 줄은 delta = 0
#   delta → 이동:  p ← p + INPUT_K · delta · dt   (dt = 다음 입력 줄까지 시간, 30 Hz zero-order hold)
#   INPUT_K = 4.35: 실험 데이터에서 실제 EE 속도 / delta (실험별 y, z 4.0~4.47). 정확한 값은 원격조종 코드에서 확인
#   INPUT_CLIP: 실험마다 다름 (06_01 은 1/15, 다른 실험은 클립 없음).
#     "auto" = 폴더에 rb_teleop_delta.csv 가 있으면 그걸 보고 정함, 없으면 1/15
INPUT_MAP = np.array([[0.0, 1.0, 0.0],
                      [-1.0, 0.0, 0.0],
                      [0.0, 0.0, 1.0]])
INPUT_K = 4.35
INPUT_CLIP = "auto"              # "auto" / 숫자 (예: 1/15) / None (안 자름)
INPUT_DT_MAX = 0.1               # 입력이 끊긴 구간(최대 9 s 등)은 0.1 s 까지만 적분
# 벽 안으로 민 양(롤러가 벽에 막힌 뒤에도 입력이 더 가려던 양)을 최대 얼마까지 쌓을지 (m)
#   한도가 없으면 오래 밀 때 수십 mm 가 쌓여서 힘이 수백~1000 N 이 되고, 당겨도 그만큼 벽에 붙어 있음.
#   20 mm (설계값): 힘 최대 = ROLLER_K × 20 mm = 200 N. 당길 때 2 cm 당기면 벽에서 떨어짐
#   0 으로 하면 벽이 살짝 기울어서 벽 따라 움직일 때 금방 떨어짐
INPUT_PUSH_MAX = 0.020
# 재생에 쓰는 파일: rb_teleop_buttons.csv (buttons_b) + rb_teleop_input_raw.csv (twist_linear_x,y,z) 만.
#   rb_joint_states.csv 는 안 씀. 처음 자세 한 번만 아래처럼 정하고, 그 뒤로는 입력만으로 움직임.
# 시작 자세: 폴더에 rb_ee_pose.csv 가 있으면 처음 b 를 누른 순간의 실제 TCP 위치·자세 (IK 로 관절각 계산)
#            없으면 INPUT_START_DEG (펜던트 각도, 도)
INPUT_START_DEG = [WORK_POSE_DEG[n] for n in JOINTS]
# 벽 평면 자동: True 면 Load 할 때 폴더에 rb_ee_pose.csv + rb_ee_wrench.csv 가 있으면 그 실험의 세 점 평면으로 벽을 다시 만듦
#   기본은 False: 노이즈가 가장 적은 13-VS 로 만든 평면 하나를 모든 실험에 씀
WALL_AUTO_PLANE = False
PLANE_FORCE_N = 10.0             # 이 힘(N) 넘게 누른 순간을 접촉점으로 씀
PLANE_FAR_M = 0.04               # 영점: 롤러가 벽에서 이만큼(m) 넘게 떨어진 순간의 힘 중앙값 = 0
replay = {"T": None, "Q": None, "t": 0.0, "playing": False, "speed": 1.0, "mode": "Input",
          "last_tl": None, "art": None, "art_idx": None, "busy": False,
          "inT": None, "inV": None, "inB": None,                       # 입력 재생 데이터
          "k": 0, "prev_b": False, "anchor": None, "R": None, "acc": None,
          "clip": 1.0 / 15.0, "prev_zero": True, "q0": None}
_timeline = omni.timeline.get_timeline_interface()
_ARTIC_PATH = next((p.GetPath().pathString for p in stage.Traverse()
                    if p.HasAPI(UsdPhysics.ArticulationRootAPI)), None)


def _read_inputs(folder):
    """rb_teleop_input_raw.csv + rb_teleop_buttons.csv → (시간, 입력 xyz, 버튼 b). 없으면 None."""
    pr = _os.path.join(folder, "rb_teleop_input_raw.csv")
    pb = _os.path.join(folder, "rb_teleop_buttons.csv")
    if not (_os.path.isfile(pr) and _os.path.isfile(pb)):
        return None
    tb, bb = [], []
    with open(pb, newline="", encoding="utf-8") as fo:
        for r in _csv.DictReader(fo):
            tb.append(float(r.get("t", r.get("time_s"))))
            bb.append(str(r.get("buttons_b", "")).strip().lower() == "true")
    T, V = [], []
    with open(pr, newline="", encoding="utf-8") as fo:
        rd = _csv.DictReader(fo)
        cols = rd.fieldnames or []
        keys = [f"twist_linear_{c}" for c in "xyz"] if "twist_linear_x" in cols else [f"lin_{c}" for c in "xyz"]
        for r in rd:
            try:
                V.append([float(r[k]) for k in keys])
                T.append(float(r.get("t", r.get("time_s"))))
            except (ValueError, TypeError, KeyError):
                continue
    if not T or not tb:
        return None
    tb = np.array(tb)
    idx = np.clip(np.searchsorted(tb, np.array(T), side="right") - 1, 0, len(bb) - 1)
    V = np.array(V)
    # 클립 값 정하기
    clip = INPUT_CLIP
    if clip == "auto":
        clip = 1.0 / 15.0
        pd = _os.path.join(folder, "rb_teleop_delta.csv")
        if _os.path.isfile(pd):
            with open(pd, newline="", encoding="utf-8") as fo:
                rd = _csv.DictReader(fo)
                kk = [f"twist_linear_{c}" for c in "xyz"] if "twist_linear_x" in (rd.fieldnames or []) \
                    else [f"lin_{c}" for c in "xyz"]
                dmax = max((max(abs(float(r[k])) for k in kk) for r in rd), default=0.0)
            rmax = float(np.abs(V @ INPUT_MAP.T).max()) if len(V) else 0.0
            clip = (1.0 / 15.0) if (dmax <= 1.0 / 15.0 + 1e-6 and rmax > 1.0 / 15.0 + 1e-3) else None
            print(f"[OK] input clip (auto from rb_teleop_delta.csv): "
                  f"{'1/15' if clip else 'none'}  (max |delta| {dmax:.4f}, max |raw| {rmax:.4f})")
        else:
            print("[INFO] no rb_teleop_delta.csv - input clip 1/15 (default)")
    replay["clip"] = clip
    return np.array(T), V, np.array(bb)[idx]                     # 각 입력 시각의 버튼 상태


def _find_csv_folder(path):
    """입력한 경로에서 CSV 가 든 폴더 찾기.
    _csv 폴더 / 그 안의 파일 / .mcap 파일 / .mcap 이 든 폴더 (예: 13-VS) 다 됨."""
    path = _os.path.expanduser(path.strip().strip('"').strip("'").rstrip("/"))
    names = ("rb_joint_states.csv", "rb_teleop_input_raw.csv")
    cands = []
    if path.endswith(".mcap"):
        cands.append(_os.path.splitext(path)[0] + "_csv")    # 06_01_0.mcap → 06_01_0_csv
        path = _os.path.dirname(path)
    if _os.path.isfile(path):
        path = _os.path.dirname(path)
    cands.append(path)
    if _os.path.isdir(path):                                  # 안에 있는 _csv 폴더
        cands += sorted(_os.path.join(path, d) for d in _os.listdir(path)
                        if d.endswith("_csv") and _os.path.isdir(_os.path.join(path, d)))
    for c in cands:
        if any(_os.path.isfile(_os.path.join(c, n)) for n in names):
            return c
    print(f"[ERROR] no csv in: {path}")
    if _os.path.isdir(path):
        print(f"        contents: {sorted(_os.listdir(path))[:15]}")
    else:
        print("        (this folder does not exist - check the path)")
    return path


def _read_csv_cols(path, cols):
    """CSV 에서 t 와 cols 열만 숫자로 읽기. 파일이 없거나 열이 없으면 None."""
    if not _os.path.isfile(path):
        return None
    T, X = [], []
    with open(path, newline="", encoding="utf-8") as fo:
        rd = _csv.DictReader(fo)
        if not set(cols) <= set(rd.fieldnames or []):
            return None
        for r in rd:
            try:
                X.append([float(r[c]) for c in cols])
                T.append(float(r.get("t", r.get("time_s"))))
            except (ValueError, TypeError):
                continue
    return (np.array(T), np.array(X)) if len(T) > 1 else None


def _quat_R(q):
    """쿼터니언 (x, y, z, w) 여러 개 → 회전행렬 (n, 3, 3)."""
    q = q / np.linalg.norm(q, axis=1, keepdims=True)
    x, y, z, w = q.T
    return np.stack([np.stack([1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)], -1),
                     np.stack([2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)], -1),
                     np.stack([2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)], -1)], 1)


def _read_ee_pose(folder):
    pc = [f"pose_position_{c}" for c in "xyz"] + [f"pose_orientation_{c}" for c in "xyzw"]
    d = _read_csv_cols(_os.path.join(folder, "rb_ee_pose.csv"), pc)
    if d is None:
        return None
    return d[0], d[1][:, :3], _quat_R(d[1][:, 3:])


def _start_pose(folder, inp):
    """시작 관절각: 처음 b 를 누른 순간의 rb_ee_pose 를 IK 로 풀기. 안 되면 INPUT_START_DEG."""
    ee = _read_ee_pose(folder)
    if ee is None or not inp[2].any():
        print("[INFO] no rb_ee_pose.csv - start from INPUT_START_DEG")
        return list(INPUT_START_DEG)
    t_on = float(inp[0][int(np.argmax(inp[2]))])
    i = int(np.clip(np.searchsorted(ee[0], t_on), 0, len(ee[0]) - 1))
    q, err = ik(INPUT_START_DEG, ee[1][i], ee[2][i], iters=300)
    if err > 0.002:
        print(f"[WARN] start pose IK error {err * 1000:.1f} mm - start from INPUT_START_DEG")
        return list(INPUT_START_DEG)
    print(f"[OK] start pose: rb_ee_pose at t = {t_on:.2f} s (first b press), IK error {err * 1000:.2f} mm")
    return [float(v) for v in q]


def _plane_3pt(folder):
    """세 점 평면: 그 실험에서 벽을 누르던 순간의 롤러 중심 점 중 삼각형 넓이가 가장 큰 세 점.
    1) 힘 영점 = 롤러가 벽에서 PLANE_FAR_M 넘게 떨어진 순간의 힘 중앙값
    2) 영점 맞춘 힘 > PLANE_FORCE_N 인 순간의 롤러 중심 (ee_pose + ROLLER_IN_TCP)
    3) 힘 센서가 튄 점 빼기: 전체 점으로 평면을 맞추고 3σ(1.4826·MAD) 밖 점 빼기 × 3번 (이 평면은 거르는 데만 씀)
    4) 남은 점에서 벽 위 좌표로 가장 바깥 점들 → 그중 삼각형 넓이가 가장 큰 세 점
    5) 세 점의 법선, 롤러 반지름만큼 벽 쪽으로 옮긴 것이 벽 표면.  안 되면 None."""
    ee = _read_ee_pose(folder)
    wr = _read_csv_cols(_os.path.join(folder, "rb_ee_wrench.csv"), ["wrench_force_z"])
    if ee is None or wr is None:
        print("[INFO] no rb_ee_pose.csv / rb_ee_wrench.csv - wall plane unchanged")
        return None
    tp, pos, Rm = ee
    ctr = pos + Rm @ ROLLER_IN_TCP
    f = np.interp(tp, wr[0], -wr[1][:, 0])                 # 누르면 + (Fz 는 누르면 -)
    far = ctr[:, 0] < np.percentile(ctr[:, 0], 99) - PLANE_FAR_M
    if far.sum() > 30:
        f = f - np.median(f[far])
    X = ctr[f > PLANE_FORCE_N]
    if len(X) < 50:
        print(f"[INFO] only {len(X)} contact points (> {PLANE_FORCE_N:.0f} N) - wall plane unchanged")
        return None
    keep = np.ones(len(X), bool)
    for _ in range(3):
        m = X[keep].mean(0)
        n = np.linalg.svd(X[keep] - m, full_matrices=False)[2][2]
        r = (X - m) @ n
        sd = 1.4826 * np.median(np.abs(r[keep] - np.median(r[keep])))
        keep = np.abs(r - np.median(r[keep])) < 3 * max(sd, 1e-4)
    X = X[keep]
    th = np.radians(np.arange(0, 360, 5))                  # 바깥 점 후보 (72 방향의 끝점)
    uv = X[:, 1:]
    cand = np.unique(np.argmax(uv @ np.stack([np.cos(th), np.sin(th)]), axis=0))
    best, area = None, -1.0
    for a in range(len(cand)):
        for b in range(a + 1, len(cand)):
            for c in range(b + 1, len(cand)):
                A, B, C = X[cand[a]], X[cand[b]], X[cand[c]]
                ar = np.linalg.norm(np.cross(B - A, C - A))
                if ar > area:
                    best, area = (cand[a], cand[b], cand[c]), ar
    A, B, C = X[list(best)]
    N = np.cross(B - A, C - A)
    N = N / np.linalg.norm(N)
    if N[0] < 0:
        N = -N
    res = (X - A) @ N
    ang = math.degrees(math.acos(min(1.0, abs(N[0]))))
    if res.std() > 0.005 or ang > 5.0:
        print(f"[WARN] contact points are not a plane (spread {res.std() * 1000:.1f} mm, tilt {ang:.1f} deg) "
              "- wall plane unchanged")
        return None
    U = np.cross([0.0, 0.0, 1.0], N)
    U = U / np.linalg.norm(U)
    V = np.cross(N, U)
    D = float(N @ A) + ROLLER_RADIUS
    pu, pv = X @ U, X @ V
    return dict(N=N, U=U, V=V, D=D, pts=(A, B, C), spread=float(res.std()),
                paint_u=(float(pu.min()), float(pu.max())),
                paint_v=(float(pv.min()), float(pv.max())))


def _wall_from_folder(folder):
    """그 실험의 세 점 평면으로 벽 옮기기."""
    global WALL_N, WALL_U, WALL_V, WALL_D, WALL_FRONT_X, PAINT_U, PAINT_V, WALL_U_RANGE, WALL_V_RANGE, _wall
    pl = _plane_3pt(folder)
    if pl is None:
        return
    WALL_N, WALL_U, WALL_V, WALL_D = pl["N"], pl["U"], pl["V"], pl["D"]
    WALL_FRONT_X = WALL_D
    PAINT_U, PAINT_V = pl["paint_u"], pl["paint_v"]
    WALL_U_RANGE = (PAINT_U[0] - WALL_MARGIN_SIDE, PAINT_U[1] + WALL_MARGIN_SIDE)
    WALL_V_RANGE = (PAINT_V[0] - WALL_MARGIN_BOTTOM, PAINT_V[1] + WALL_MARGIN_TOP)
    _wall = _build_wall()
    _set_contact_offset(CONTACT_OFFSET)
    print(f"[OK] wall plane from 3 contact points ({folder}):")
    for p in pl["pts"]:
        print(f"       roller center ({p[0] * 1000:7.1f}, {p[1] * 1000:7.1f}, {p[2] * 1000:7.1f}) mm")
    print(f"     N = {np.round(WALL_N, 6).tolist()},  N.p = {WALL_D:.5f} m,  "
          f"other contact points spread {pl['spread'] * 1000:.2f} mm")


def _replay_load(path):
    """재생 폴더 읽기: rb_teleop_buttons.csv + rb_teleop_input_raw.csv (필수),
    rb_ee_pose.csv (시작 자세), rb_ee_wrench.csv (벽 평면) 는 있으면 씀."""
    folder = _find_csv_folder(path)
    inp = _read_inputs(folder)
    if inp is None:
        replay_label.text = "no input csv found"
        print(f"[ERROR] need rb_teleop_buttons.csv + rb_teleop_input_raw.csv in {folder}")
        return
    if WALL_AUTO_PLANE:
        _wall_from_folder(folder)
    replay.update(T=inp[0], Q=None, t=float(inp[0][0]), playing=False,
                  inT=inp[0], inV=inp[1], inB=inp[2], q0=_start_pose(folder, inp))
    follow["on"] = False
    _replay_reset_at(replay["t"])
    _replay_show()
    print(f"[OK] replay loaded: {len(inp[0])} rows, {inp[0][-1] - inp[0][0]:.1f} s, "
          f"button b ON {inp[2].mean() * 100:.0f}%  ({folder})")


def _get_art():
    """Exact 모드용: 관절 각도를 바로 넣는 Isaac Sim articulation (Play 중에만 됨)."""
    if replay["art"] is not None:
        return replay["art"]
    if _ARTIC_PATH is None:
        return None
    try:
        try:
            from isaacsim.core.prims import SingleArticulation as _Art
        except ImportError:
            from omni.isaac.core.articulations import Articulation as _Art
        art = _Art(prim_path=_ARTIC_PATH)
        art.initialize()
        names = list(art.dof_names)
        replay["art_idx"] = np.array([names.index(n) for n in JOINTS])
        replay["art"] = art
        print(f"[OK] replay exact mode: {_ARTIC_PATH}")
        return art
    except Exception as e:
        print(f"[WARN] exact mode unavailable ({type(e).__name__}: {e}) -> motor mode")
        exact_model.set_value(False)
        return None


def _replay_apply(q_deg):
    """관절각을 로봇에 넣기: 모터 목표 + 슬라이더 표시 (+ Exact 면 각도를 바로 넣기)."""
    replay["busy"] = True
    wall["busy"] = True                                    # 재생 중에는 벽 막기 안 함
    for n, v in zip(JOINTS, q_deg):
        models[n].set_value(v)
        _set_target(n, v)
    wall["busy"] = False
    replay["busy"] = False
    wall["q"] = list(q_deg)
    if exact_model.as_bool and _timeline.is_playing():
        art = _get_art()
        if art is not None:
            rad = np.radians([v + _offset(n) for n, v in zip(JOINTS, q_deg)])
            try:
                art.set_joint_positions(rad, joint_indices=replay["art_idx"])
                art.set_joint_velocities(np.zeros(6), joint_indices=replay["art_idx"])
            except Exception as e:
                print(f"[WARN] set_joint_positions failed ({e}) -> motor mode")
                replay["art"] = None
                exact_model.set_value(False)


def _replay_reset_at(t):
    """시간 t 로 이동: 시작 자세에서 t 까지 입력을 빨리 돌려서 맞춤."""
    wall["push"] = 0.0
    _replay_apply(list(replay["q0"] or INPUT_START_DEG))
    replay.update(k=0, prev_b=False, anchor=None, R=None, acc=None, prev_zero=True)
    t0 = float(replay["inT"][0])
    for ti in np.arange(t0, t, 0.1):                       # 0.1 초 간격으로 빨리 돌리기
        _input_step(float(ti))
    _input_step(float(t))


def _input_step(t):
    """입력 재생: 시간 t 까지의 입력 줄을 처리하고, 버튼이 눌려 있으면 IK 로 로봇을 움직임."""
    T, V, Bs = replay["inT"], replay["inV"], replay["inB"]
    moved = False
    while replay["k"] < len(T) and T[replay["k"]] <= t:
        k = replay["k"]
        on = bool(Bs[k])
        if on and not replay["prev_b"]:                    # False → True: 지금 자리에서 새로 시작
            M = fk(_q_now())
            anchor, Rk = M[:3, 3].copy(), M[:3, :3].copy()
            replay.update(anchor=anchor, R=Rk, acc=np.zeros(3))
        d = INPUT_MAP @ V[k]                               # raw → delta (축 바꾸기)
        if replay["clip"]:
            d = np.clip(d, -replay["clip"], replay["clip"])
        is_zero = not np.any(V[k])
        if replay["prev_zero"] and not is_zero:            # 0 → 0이 아닌 첫 줄은 delta = 0
            d = np.zeros(3)
        replay["prev_zero"] = is_zero
        if on:
            dt = (T[k + 1] - T[k]) if k + 1 < len(T) else (T[k] - T[k - 1] if k > 0 else 1.0 / 30.0)
            replay["acc"] = replay["acc"] + INPUT_K * d * min(max(dt, 0.0), INPUT_DT_MAX)
            moved = True
        replay["prev_b"] = on
        replay["k"] = k + 1
    if not moved or replay["anchor"] is None:
        return
    R = replay["R"]
    p_tcp = replay["anchor"] + replay["acc"]
    roller_x = _roller_front(R, p_tcp)[0] - ROLLER_RADIUS
    hit = roller_x > WALL_STOP_X
    over = roller_x - WALL_STOP_X
    if hit:                                                # 벽 안쪽이면 벽에서 멈춤
        p_tcp = p_tcp - WALL_N * over
        if ROLLER_MODEL == "soft":
            replay["acc"] = replay["acc"] - WALL_N * over  # soft: 밀어 넣은 양은 버림
        elif over > INPUT_PUSH_MAX:                        # rigid: 민 양은 INPUT_PUSH_MAX 까지만 쌓고 나머지는 버림
            replay["acc"] = replay["acc"] - WALL_N * (over - INPUT_PUSH_MAX)
            over = INPUT_PUSH_MAX
    wall["push"] = over if hit else 0.0
    q, _ = ik(_q_now(), p_tcp, R)
    _replay_apply(list(q))
    _show_wall(wall["q"], blocked=hit)


def _replay_show():
    if replay["T"] is None:
        return
    t0, t1 = replay["T"][0], replay["T"][-1]
    replay["busy"] = True
    replay_slider_model.set_value(float((replay["t"] - t0) / max(t1 - t0, 1e-9)))
    replay["busy"] = False
    state_txt = "playing" if replay["playing"] else "paused"
    extra = ", b ON" if replay["prev_b"] else ", b off"
    replay_label.text = (f"{replay['t'] - t0:7.1f} / {t1 - t0:.1f} s  "
                         f"[{state_txt}, {replay['speed']}x{extra}]")


def _replay_toggle():
    if replay["T"] is None:
        replay_label.text = "load a csv first"
        return
    if replay["inT"] is None:
        replay_label.text = "no input files in this folder"
        return
    if replay["t"] >= replay["T"][-1]:
        replay["t"] = float(replay["T"][0])             # 끝까지 갔으면 처음부터
        _replay_reset_at(replay["t"])
    replay["playing"] = not replay["playing"]
    replay["last_tl"] = None
    follow["on"] = False
    if follow_model.as_bool:
        follow_model.set_value(False)
    if not _timeline.is_playing() and replay["playing"]:
        print("[INFO] press Play (timeline) - replay runs only while the simulation is playing")
    _replay_show()


def _replay_seek(frac):
    if replay["busy"] or replay["T"] is None:
        return
    t0, t1 = replay["T"][0], replay["T"][-1]
    replay["t"] = float(t0 + frac * (t1 - t0))
    _replay_reset_at(replay["t"])
    _replay_show()


def _replay_update(*args, **kwargs):
    """매 프레임: 시뮬레이션 시간이 흐른 만큼 재생 시간을 넘기고 그 시점 각도를 넣음."""
    if not _timeline.is_playing():
        replay["art"] = None                               # Stop 하면 articulation 다시 잡기
        replay["last_tl"] = None
        return
    if not replay["playing"] or replay["T"] is None:
        return
    cur = _timeline.get_current_time()
    last = replay["last_tl"]
    replay["last_tl"] = cur
    if last is None:
        return
    dt = cur - last
    if dt <= 0.0 or dt > 1.0:
        return
    replay["t"] = min(replay["t"] + dt * replay["speed"], float(replay["T"][-1]))
    _input_step(replay["t"])
    if replay["t"] >= replay["T"][-1]:
        replay["playing"] = False
        print("[OK] replay finished")
    _replay_show()


# 조종 창 (슬라이더 6개 + 버튼)
state = {"sel": "base"}
models, labels = {}, {}

window = ui.Window("RB10 Joint Teleop", width=460, height=600)
with window.frame:
    with ui.VStack(spacing=6):
        ui.Label("Mouse: drag sliders  |  Keys: 1-6 select, Up/Down +-1 deg, "
                 "Shift +-5 deg, R = WORK_POSE  |  Press Play to move",
                 word_wrap=True, height=36)
        for i, n in enumerate(JOINTS):
            with ui.HStack(height=26):
                labels[n] = ui.Label(f"  {i + 1} {n}", width=110)
                m = ui.SimpleFloatModel(_current_pendant_deg(n))
                ui.FloatSlider(model=m, min=-LIMIT_DEG, max=LIMIT_DEG, step=0.1)
                m.add_value_changed_fn(lambda mdl, name=n: _on_slider(name, mdl))
                models[n] = m
        with ui.HStack(height=30, spacing=6):
            ui.Button("Reset to WORK_POSE",
                      clicked_fn=lambda: _apply_pose([WORK_POSE_DEG[n] for n in JOINTS]))
            ui.Button("All zero",
                      clicked_fn=lambda: _apply_pose([0.0] * 6))
        ui.Separator(height=6)
        with ui.HStack(height=24, spacing=6):
            follow_model = ui.SimpleBoolModel(False)
            ui.CheckBox(model=follow_model, width=20)
            ui.Label("Mouse target (F): drag orange ball with W tool", width=0)
        with ui.HStack(height=24, spacing=6):
            rot_model = ui.SimpleBoolModel(False)
            ui.CheckBox(model=rot_model, width=20)
            ui.Label("Use target rotation (E tool). Off = keep tool facing wall", width=0)
        with ui.HStack(height=28, spacing=6):
            ui.Button("Target to tool", clicked_fn=lambda: _target_to_tool())
            reach_label = ui.Label("reach error: -")
        wall_label = ui.Label("wall gap: -", height=24)
        ui.Separator(height=6)
        ui.Label("Replay experiment (_csv folder from mcap_to_csv.py)", height=20)
        with ui.HStack(height=24, spacing=4):
            replay_path_model = ui.SimpleStringModel(REPLAY_CSV)
            ui.StringField(model=replay_path_model)
            ui.Button("Load", width=60, clicked_fn=lambda: _replay_load(replay_path_model.as_string))
        with ui.HStack(height=28, spacing=6):
            ui.Button("Replay / Pause", clicked_fn=lambda: _replay_toggle())
            speed_combo = ui.ComboBox(1, *[f"{v}x" for v in REPLAY_SPEEDS], width=70)
            speed_combo.model.get_item_value_model().add_value_changed_fn(
                lambda m: replay.update(speed=REPLAY_SPEEDS[m.as_int]) or _replay_show())
            exact_model = ui.SimpleBoolModel(True)
            ui.CheckBox(model=exact_model, width=20)
            ui.Label("Exact", width=40)
        replay_slider_model = ui.SimpleFloatModel(0.0)
        ui.FloatSlider(model=replay_slider_model, min=0.0, max=1.0, height=22)
        replay_slider_model.add_value_changed_fn(lambda m: _replay_seek(m.as_float))
        replay_label = ui.Label("no file loaded", height=20)
follow_model.add_value_changed_fn(lambda m: _set_follow(m.as_bool) if m.as_bool != follow["on"] else None)


def _select(name):
    state["sel"] = name
    for i, n in enumerate(JOINTS):
        labels[n].text = f"{'>' if n == name else ' '} {i + 1} {n}"


_select("base")
wall["q"] = _q_now()
_show_wall(wall["q"])

# 키보드
_KEY_TO_JOINT = {
    carb.input.KeyboardInput.KEY_1: "base",
    carb.input.KeyboardInput.KEY_2: "shoulder",
    carb.input.KeyboardInput.KEY_3: "elbow",
    carb.input.KeyboardInput.KEY_4: "wrist1",
    carb.input.KeyboardInput.KEY_5: "wrist2",
    carb.input.KeyboardInput.KEY_6: "wrist3",
}


def _on_key(event, *args, **kwargs):
    if event.type not in (carb.input.KeyboardEventType.KEY_PRESS,
                          carb.input.KeyboardEventType.KEY_REPEAT):
        return True
    key = event.input
    if key in _KEY_TO_JOINT:
        _select(_KEY_TO_JOINT[key])
    elif key in (carb.input.KeyboardInput.UP, carb.input.KeyboardInput.DOWN):
        shift = bool(event.modifiers & carb.input.KEYBOARD_MODIFIER_FLAG_SHIFT)
        step = BIG_STEP_DEG if shift else STEP_DEG
        if key == carb.input.KeyboardInput.DOWN:
            step = -step
        m = models[state["sel"]]
        m.set_value(m.as_float + step)            # 슬라이더도 같이 움직이고, 모터 목표도 바뀜
    elif key == carb.input.KeyboardInput.R:
        _apply_pose([WORK_POSE_DEG[n] for n in JOINTS])
        if follow["on"]:
            _target_to_tool()                     # 공도 팔 끝으로 같이 이동
    elif key == carb.input.KeyboardInput.F:
        _set_follow(not follow["on"])
    return True                                   # 다른 창(뷰포트 등)도 키를 계속 받게


_inp = carb.input.acquire_input_interface()
_kb = omni.appwindow.get_default_app_window().get_keyboard()
_sub = _inp.subscribe_to_keyboard_events(_kb, _on_key)

# 매 프레임 호출 (목표점 따라가기)
_update_sub = omni.kit.app.get_app().get_update_event_stream().create_subscription_to_pop(
    _on_update, name="rb10_teleop_ik")

# 힘 데이터 CSV 저장 (▶ Play 동안, 매 프레임)
import datetime as _dt
_flog = {"f": None, "w": None, "path": None}


def _force_log_close():
    if _flog["f"] is not None:
        _flog["f"].close()
        print(f"[OK] force log saved: {_flog['path']}")
    _flog.update(f=None, w=None, path=None)


def _force_update(*args, **kwargs):
    """매 프레임: 힘 표시 + (Play 중이면) CSV 한 줄 저장."""
    if wall["q"] is None:
        return
    if not _timeline.is_playing():
        _force_log_close()
        return
    F, T, press, gap, p = _wrench(wall["q"])
    if not FORCE_LOG:
        return
    if _flog["f"] is None:
        d = _os.path.expanduser(FORCE_LOG_DIR)
        _os.makedirs(d, exist_ok=True)
        _flog["path"] = _os.path.join(d, "sim_ee_wrench_" + _dt.datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv")
        _flog["f"] = open(_flog["path"], "w", newline="", encoding="utf-8")
        _flog["w"] = _csv.writer(_flog["f"])
        _flog["w"].writerow(["sim_time", "replay_t", "mode", "buttons_b", "header_frame_id",
                             "wrench_force_x", "wrench_force_y", "wrench_force_z",
                             "wrench_torque_x", "wrench_torque_y", "wrench_torque_z",
                             "press_mm", "wall_gap_mm", "tcp_x", "tcp_y", "tcp_z"])
        print(f"[OK] force log started: {_flog['path']}")
    mode = replay["mode"] if replay["playing"] else "manual"
    b = int(bool(replay["prev_b"])) if replay["playing"] and replay["mode"] == "Input" else ""
    _flog["w"].writerow([f"{_timeline.get_current_time():.4f}", f"{replay['t']:.4f}" if replay["playing"] else "",
                         mode, b, "tcp",
                         *[f"{v:.3f}" for v in F], *[f"{v:.4f}" for v in T],
                         f"{press * 1000:.2f}", f"{gap * 1000:.2f}", *[f"{v:.5f}" for v in p]])


_force_sub = omni.kit.app.get_app().get_update_event_stream().create_subscription_to_pop(
    _force_update, name="rb10_teleop_force")

# 창·키보드·프레임 연결이 사라지지 않게 보관 (다음 Run 때 위에서 정리)
_replay_sub = omni.kit.app.get_app().get_update_event_stream().create_subscription_to_pop(
    _replay_update, name="rb10_teleop_replay")

builtins._rb10_teleop = {"window": window, "inp": _inp, "kb": _kb, "sub": _sub,
                         "update_sub": _update_sub, "replay_sub": _replay_sub, "force_sub": _force_sub,
                         "force_log_close": _force_log_close}
if REPLAY_CSV:
    _replay_load(REPLAY_CSV)
print("[OK] RB10 Joint Teleop window ready - press Play, then drag sliders, use keys, "
      "or turn on Mouse target (F)")
