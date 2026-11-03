from __future__ import annotations

"""Static sanity check for the cleaned current Blender/CV contract.

This deliberately checks only files that ship in the project. It does not depend
on an old generated reference report or a particular .blend file.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
kin = json.loads((ROOT / "config" / "inmoov_kinematics.json").read_text(encoding="utf-8"))
default = json.loads((ROOT / "config" / "default.json").read_text(encoding="utf-8"))

for side in ("left", "right"):
    arm = kin["arms"][side]
    assert len(arm["joints"]) == 4, f"{side}: expected four arm IK joints"

    wrist = arm["wrist_rotation_z"]
    assert wrist["lower"] < 0.0 < wrist["upper"], wrist
    assert wrist["joint_name"] == f"{side}_wrist_z"

builder_path = ROOT / "builder" / "build_inmoov_complete.py"
bridge_path = ROOT / "blender" / "inmoov_blender_bridge.py"
assert builder_path.is_file(), builder_path
assert bridge_path.is_file(), bridge_path

builder = builder_path.read_text(encoding="utf-8")
assert 'VISUALIZATION_ARM_BINDING_MODE = "SOURCE_FK"' in builder
assert 'if VISUALIZATION_ARM_BINDING_MODE == "LEGACY_PROXY_IK"' in builder

bridge = bridge_path.read_text(encoding="utf-8")
assert "_apply_wrists_source_fk" in bridge
assert 'frame.get("simulation") or frame.get("robot", {})' in bridge

model_cfg = default["mediapipe"]
assert model_cfg["model_path"].endswith("holistic_landmarker.task")
assert str(model_cfg.get("model_url", "")).startswith("https://")

sim = default["simulation_motion"]
assert sim["enabled"] is True
assert float(sim["default_max_velocity_rad_s"]) > 0
assert float(sim["default_max_acceleration_rad_s2"]) > 0

print("BLENDER/CV CONTRACT STATIC CHECK OK")
print("  canonical builder: builder/build_inmoov_complete.py")
print("  canonical bridge: blender/inmoov_blender_bridge.py")
print("  upper-body visualization binding: SOURCE_FK")
print("  wrist axial rotation: bidirectional in current config")
print("  MediaPipe model: downloaded on demand")
print("  simulation motion profile: enabled and separate from raw robot IK")
