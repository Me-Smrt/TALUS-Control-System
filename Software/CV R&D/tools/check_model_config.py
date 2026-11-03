from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from inmoov_cv.kinematics import ArmChain

cfg = json.loads((ROOT / "config" / "inmoov_kinematics.json").read_text())

print(f"model_scale = {cfg['source']['model_scale']}")
for side in ("left", "right"):
    chain = ArmChain(cfg["arms"][side])
    print(
        f"{side:5s}: shoulder->elbow={chain.rest_shoulder_to_elbow_m*1000:.1f} mm, "
        f"elbow->wrist={chain.rest_elbow_to_wrist_m*1000:.1f} mm"
    )
    for joint in cfg["arms"][side]["joints"]:
        print(
            f"  {joint['name']:20s} "
            f"{math.degrees(joint['lower']):7.1f} .. {math.degrees(joint['upper']):7.1f} deg "
            f"vmax={math.degrees(joint.get('velocity_limit_rad_s',0.0)):5.1f} deg/s"
        )
    for label in ("wrist_rotation_z", "wrist_bend_x"):
        j = cfg["arms"][side][label]
        print(
            f"  {j['joint_name']:20s} "
            f"{math.degrees(j['lower']):7.1f} .. {math.degrees(j['upper']):7.1f} deg "
            f"vmax={math.degrees(j.get('velocity_limit_rad_s',0.0)):5.1f} deg/s"
        )
print("torso:")
for name, j in cfg["torso"].items():
    print(f"  {name:6s}: {math.degrees(j['lower']):6.1f} .. {math.degrees(j['upper']):6.1f} deg")
