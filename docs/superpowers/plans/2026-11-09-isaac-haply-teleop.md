# Isaac Sim + Haply Shared Control Implementation Plan

> For agentic workers: use executing-plans inline, test-driven-development and a fresh final review. User authorized implementation, decisions, commit and push.

**Goal:** Run the supplied RB10/roller in Isaac Sim using live Haply input, the existing LSTM, replaceable shared control, and reproducible evaluation logs.

**Architecture:** An input-only Haply Inverse Service bridge sends validated position/clutch packets over localhost UDP. A standalone Isaac Sim 5.1 runner imports the existing URDF, uses physical roller/wall contact forces, solves TCP IK and calls a simulator-independent controller at 30 Hz. NumPy LSTM inference and causal feature extraction retain the trained contract. Each trial records inputs, measured and commanded motion, inference, controller mode, independent task markers and condition metadata.

**Tech Stack:** Python 3.11+, NumPy, websockets for the external Haply bridge, Isaac Sim 5.1/PhysX/USD; unittest. Selected 80 KB checkpoint included, no retraining.

**Spec:** User request in this chat (2026-11-09) and immediately preceding proposed contact-maintenance/recovery + directional withdrawal law. Current robot assets are in `issac sim_ws/all_models_with_testpiece_and_images/rb10_base_description`.

## Global constraints and rulings

- Preserve existing raw data, research drafts, recording-conditioned simulation and legacy ROS scene scripts.
- Current checkout has untracked research artifacts. Work in place on `codex/isaac-haply-shared-control`, stage only this task's files; existing permission to decide/execute supersedes optional worktree/plan confirmation.
- Physical robot drivers are not part of this simulator. Haply receives only zero-force streaming commands. Release clutch, invalid/stale data, tracking failure or emergency stop prevents new motion commands.
- Default normal is base +X; URDF support-to-link0 rotation is normalized only in a generated import copy. Scene and classifier base frames are explicit. Actual wall force is rotated to the trained FT convention separately.
- Control 30 Hz, physics 120 Hz. Force collection averages all physics substeps. Wall is collidable, not a VisualCuboid-only display.
- Three trial conditions: manual, probability (contact-only baseline), shared (contact recovery and directional release). One condition per trial. Future algorithm edits live in `src/painting_teleop/controller.py`.
- Performance denominator comes from operator/script task markers, never inferred LSTM classes. Include low force, force RMSE/range, release interference, reacquisition, coverage proxy, stops and tracking errors. Markers missing means no painting performance claim.
- Isaac runtime is not currently installed in the detected paths. Validate pure core, socket integration, checkpoint equivalence, CLI and generated assets locally; document hardware/PhysX checks requiring the target workstation.

## Review focus

1. Repeated, delayed, malformed or reconnecting input must not repeat movement or jump on clutch re-engagement.
2. Contact loss during withdrawal must not initiate automatic pursuit; inward resumption must permit bounded recovery despite stale RETRACT prediction.
3. Frame/sign/quaternion/URDF root conventions must agree between IK, physical contact and LSTM features.
4. Model/artifact dependencies must work in a fresh clone without `.analysis_deps` or untracked result folders.
5. Logs must use real measured forces and independent task labels; elapsed simulation/wall times and aborts remain visible.

## Tasks

- [x] 1. Core and inference: failing behavior tests first; implement controller dataclasses/step, portable causal preprocessing, NumPy checkpoint inference, URDF FK/IK and configuration. Verify withdrawal, recovery bounds, disable, finite values, FK/IK and parity with existing model.
- [x] 2. Input and sessions: test packet validation, clutch edge, freshness/reconnect and metric denominators; implement Haply parser/bridge, UDP receiver, trial logging and metrics/replay utilities.
- [x] 3. Isaac runner: create imported physical scene, drive joint targets from IK, collect roller-wall forces at physics rate, update core at 30 Hz, add operator controls/task markers and display; add scripted/recorded-input modes for repeatable evaluation and a no-Isaac core smoke runner.
- [x] 4. Documentation and release: Korean setup/run/edit/evaluate Markdown, configs and selected model provenance, root README link; run full relevant tests, offline end-to-end smoke and source/API review; commit explicit files and push main as requested, verify remote SHA.

## Progress ledger

- Baseline: no tracked test suite or runnable teleoperation package. Existing Isaac script requires an external Linux USD and ROS2 workspace; it uses a visual wall. Haply Inverse Service is installed locally with 3.x WebSocket port 10001.
- Git metadata is read-only under default permissions; requested branch creation through the authorized escalation path. Initial remote read failed due network resolution; retry remote synchronization with the authorized network path before push.
- Implemented and verified 26 tests, including localhost WebSocket-to-UDP, checkpoint parity, controller withdrawal/recovery, FK/IK/Jacobian and pause/stop timing contracts. All six end-to-end smoke/replay/fault runs completed 423 samples; comparison CSV generated.
- Fresh review findings fixed: separate physics steps from rendering, disable unsupported custom cylinder contact geometry, retain withdrawal intent through neutral input, finalize native Stop and render paused UI without advancing physics. No deferred review findings.
- Timing inspection found expensive repeated XML transforms/numerical Jacobians. Cached URDF transforms and analytical Jacobian preserve FK derivatives and reduced the measured 95th percentile core+IK time to 11.45 ms (120 incremental target requests; excludes PhysX/rendering).
- Ruling: retain the supplied script's axis mapping, scale and clutch conventions; use direct Inverse Service cursor input because its external PybindTeleopAgent is absent. Physical response will require target-system calibration. No physical RB10 driver is invoked.
- Ruling: keep input-only Haply zero-force streaming and a portable NumPy model; hardware force-feedback is outside this integration. User can revise the controller independently.
- Ruling: local Isaac runtime is absent. PhysX and actual device acceptance steps are documented in simulation/VALIDATION.md; local verification covers the executable core and protocol, not completed hardware validation.
- Release completed on 2026-11-09: user explicitly requested main instead of a feature branch. Fast-forwarded main from 39c3b349665be4d4e1abad4393d9774a8f2a2304 to implementation commit 053d4f78690fc6eaa690263950a3ebbff0e08d59, pushed origin/main and verified the matching remote SHA. No remote feature branch was created. Unrelated untracked research remains untouched.
