# InMoov Complete Engineering Reference Builder v4.0 — Source-FK Visualization Binding
# Run with Blender 4.5+/5.x: blender --background --factory-startup --python build_inmoov_reference.py
#
# Output: InMoov_Complete_Rigged_MM.blend
# Scene convention: 1 Blender Unit = 1 millimeter.
#
# v3.3 changes (all confined to leg/hip/toe placement; upper-body URDF import
# and the armature-building code are untouched):
#   1. Hip spacing is no longer a single width-based guess clamped to an
#      arbitrarily tight 170-195 mm. It is measured after initial placement
#      and widened until a real minimum thigh clearance is achieved (see
#      LEG_HIP_MIN_THIGH_CLEARANCE_MM), clamped to a wider 220-280 mm range.
#      v3.2 measured a real 56.82 mm thigh overlap and only logged it as a
#      warning; v3.3 corrects for it and re-measures.
#   2. Hip X/Y position now comes from the actual low-stomach mounting band
#      (lowest slice of the torso shell) instead of the whole torso bbox
#      center -- see torso_mount_reference().
#   3. The final toe yaw was 180 degrees, which pointed the visible toe mesh
#      opposite to its own control bone and the foot's own -Y "forward"
#      convention. It is now 0 (see FINAL_TOE_YAW_CORRECTION_DEG).
#   4. The hardware-reference import no longer silently caps at 16 parts.
#
# v3.4 changes:
#   5. normalize_foot() no longer assumes the raw foot mesh's Y axis already
#      points straight forward. It measures the actual toe<->heel heading
#      from the shape and rotates the foot about the ankle's vertical axis
#      to square it with -Y (see FOOT_YAW comment in normalize_foot()).
#      This was reported as "feet still rotated incorrectly" after v3.3.
#
# v3.5 changes:
#   6. Added alignment.side_consistency_check to the JSON report: the final
#      world-X center of each of the 8 leg objects (R/L x thigh/calf/foot/toe),
#      so a "legs on the wrong side" report can be checked directly against
#      the JSON instead of eyeballing a render (very easy to mirror-confuse)
#      or hand-parsing the .blend. No placement logic changed in v3.5.
#
# v3.6 changes:
#   7. normalize_toe() gets the same yaw-correction treatment v3.4 gave
#      normalize_foot(): it now measures the toe cap's own actual tip<->rear
#      heading and rotates it to square with world Y, instead of trusting
#      the raw mesh's axes to already be square. Reported as "toes still
#      rotated" after v3.4 (which only fixed the *foot's* yaw -- the toe
#      cap is a separate mesh with its own independent native orientation).
#   8. side_consistency_check now also reports RIGHT_ARM/RIGHT_HAND/
#      LEFT_ARM/LEFT_HAND world-X centers from the URDF's own forward
#      kinematics (untouched by any leg code) and a leg_matches_urdf_right_arm
#      flag, so a "wrong side" report can be checked against an independent
#      ground truth instead of a guess.
#
# v3.7 changes:
#   9. Fixed calf/foot/toe chirality: confirmed against real InMoov reference
#      photos that the community "right"-named calf/foot/toe STLs actually
#      model left-handed geometry. Both legs were self-consistently placed
#      (v3.5's side_consistency_check was correct) but built from the wrong-
#      handed shape on both sides -- the "big toes point outward on both
#      feet, shins bow away from each other" symptom, not a simple L/R swap.
#      The raw import is now mirrored through its own native X axis before
#      any other processing; nothing downstream needed to change. Thigh is
#      untouched (no evidence it's affected).
#  10. Added import_official_knee_ankle_hardware(): downloads and imports the
#      official inmoov.fr Legs-Knee and Legs-Ankle STL sets (a different,
#      authoritative source from the community SolidWorks reverse-engineering
#      used for the main leg shells) into their own unplaced reference
#      collection, same "no mate data available" treatment as the existing
#      hip/knee/tibia reference parts.
#
# v3.8 changes:
#  11. Manual calibration workflow. The toe cap's rest orientation and the
#      hip-hardware install positions have proven to be a bad fit for more
#      procedural guessing (the v3.6 toe yaw fix did not resolve the
#      reported "toes still malrotated" -- this shape is short/wide enough
#      that a tip<->rear band heading estimate is unreliable, and the real
#      fix may not even be a pure yaw). Rather than keep iterating blind,
#      this adds:
#        - REF::R_HIP/L_HIP/R_KNEE/L_KNEE/R_ANKLE/L_ANKLE empties (hidden
#          collection "93_CALIBRATION_REFERENCE_POINTS"), real objects at
#          this build's actual joint points to measure from by hand.
#        - MANUAL_CALIBRATION_OVERRIDES: a dict of exact, human-verified
#          position+rotation offsets from a reference point, applied by
#          apply_calibration_overrides() as the absolute last step in
#          main() -- after every procedural placement/correction, so a
#          calibrated part is never re-adjusted by a heuristic.
#        - An embedded "CALIBRATION_HELPER" Blender text block containing
#          print_calibration_offset(obj, reference_point_name), runnable
#          directly from the Scripting tab, which prints a ready-to-paste
#          override entry after a part has been manually positioned.
#      This applies to any named object -- the toe cap, the thigh objects
#      themselves (for the hip-mounting-position complaint), or the new
#      official knee/ankle hardware pieces once placed by hand.
#
# v3.9 changes:
#  12. MANUAL_CALIBRATION_OVERRIDES populated with the user's manually-
#      verified leg placement (all 8 leg objects: thigh/calf/foot/toe x
#      R/L), extracted from a matrix_world dump of the calibrated .blend
#      and cross-checked against this file's own reference-point math
#      (every Y/Z component matched to within 0.0001 mm before being
#      accepted). Torso/URDF-body repositioning is NOT yet included here --
#      that data came back looking physically implausible (every body mesh
#      collapsed to nearly one point) and needs to be re-captured before
#      it can be trusted; see the conversation for what to check next.
#
# Sources:
#   Sentience Robotics inmoov_urdf / inmoov_ros_sim (URDF + InMoov-derived meshes)
#   wei1224hf/inmoov-solidworks (community reverse-engineered servo/CAD reference)
#   Original InMoov design by Gael Langevin: https://inmoov.fr/
#
# InMoov-derived geometry is CC BY-NC; see source repositories for exact licensing.

from __future__ import annotations

import bpy
import math
import os
import re
import ssl
import sys
import importlib.util
import json
import time
import shutil
import zipfile
import traceback
import subprocess
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
from mathutils import Matrix, Vector

# ------------------------------- CONSTANTS ----------------------------------
def resolve_builder_root() -> Path:
    """Return a writable project directory in Blender GUI or CLI runs.

    Blender 5.x can report a Text Editor script path relative to the current .blend
    in odd forms such as::

        C:\\project\\TALUS.blend\\build_inmoov_reference.py.001

    ``TALUS.blend`` is a file, not a directory, so that path can never exist.  For
    reliability we treat the saved ``bpy.data.filepath`` as authoritative whenever a
    .blend is open and use *its parent directory*.  Text-block and ``__file__`` paths
    are only accepted when they resolve to an existing regular file.
    """
    env_root = os.environ.get("INMOOV_BUILDER_ROOT", "").strip()
    if env_root:
        root = Path(env_root).expanduser().resolve()
        # If someone points the override at a .blend file, use its folder.
        if root.suffix.lower() == ".blend":
            root = root.parent
        return root

    # A saved .blend has the most dependable location in Blender 5.x.
    # IMPORTANT: use Path(bpy.data.filepath).parent directly; bpy.path.abspath("//")
    # may be interpreted unexpectedly for Text Editor scripts in some Blender builds.
    try:
        blend_path_text = str(getattr(bpy.data, "filepath", "") or "").strip()
        if blend_path_text:
            blend_path = Path(blend_path_text).expanduser().resolve()
            if blend_path.suffix.lower() == ".blend":
                return blend_path.parent
            # Defensive fallback in case Blender ever exposes a nonstandard filename.
            if blend_path.is_file():
                return blend_path.parent
    except Exception:
        pass

    # If no .blend has been saved yet, accept a Text Editor path only if it points
    # to a real file on disk.  This rejects synthetic paths containing a .blend
    # component as a directory.
    try:
        space = getattr(bpy.context, "space_data", None)
        text_block = getattr(space, "text", None)
        filepath = getattr(text_block, "filepath", "") if text_block else ""
        if filepath:
            candidate = Path(bpy.path.abspath(filepath)).expanduser().resolve()
            if candidate.is_file():
                return candidate.parent
    except Exception:
        pass

    # Context can change while operators run, so inspect all loaded text blocks too.
    try:
        for text_block in bpy.data.texts:
            filepath = getattr(text_block, "filepath", "")
            if not filepath:
                continue
            candidate = Path(bpy.path.abspath(filepath)).expanduser().resolve()
            if candidate.is_file() and candidate.name.lower().startswith("build_inmoov_reference"):
                return candidate.parent
    except Exception:
        pass

    # Normal command-line/background Blender invocation.  Again, accept only a real
    # script file and never a synthetic drive-root or .blend-as-directory path.
    try:
        candidate = Path(__file__).expanduser().resolve()
        drive_root = Path(candidate.anchor) if candidate.anchor else None
        if candidate.is_file() and (drive_root is None or candidate.parent != drive_root):
            return candidate.parent
    except Exception:
        pass

    # Final fallback is a conventional user-writable location.
    return (Path.home() / "Documents" / "InMoov_Engineering_Reference_Builder").resolve()


ROOT = resolve_builder_root()
SCRIPT_PATH = ROOT / "build_inmoov_reference.py"
CACHE = ROOT / "_inmoov_cache"
DOWNLOADS = CACHE / "downloads"
SOURCES = CACHE / "sources"
OUTPUT_BLEND = ROOT / "InMoov_Complete_Rigged_MM.blend"
REPORT_JSON = ROOT / "InMoov_Complete_Rigged_MM.json"

DOWNLOAD_TIMEOUT = 120
USER_AGENT = "Mozilla/5.0 InMoovEngineeringReferenceBuilder/3.9"

REPOSITORIES = [
    {
        "name": "sentience_current",
        "owner": "Sentience-Robotics",
        "repo": "inmoov_urdf",
        "branches": ["main", "master"],
        "role": "preferred_current_urdf_and_meshes",
    },
    {
        "name": "sentience_archived",
        "owner": "Sentience-Robotics",
        "repo": "inmoov_ros_sim",
        "branches": ["master", "main"],
        "role": "fallback_complete_urdf_and_stl",
    },
    {
        "name": "alan_ros",
        "owner": "alansrobotlab",
        "repo": "inmoov_ros",
        "branches": ["master", "main"],
        "role": "fallback_articulated_urdf",
    },
    {
        "name": "community_solidworks",
        "owner": "wei1224hf",
        "repo": "inmoov-solidworks",
        "branches": ["main", "master"],
        "role": "community_hardware_reference",
    },
]

# Filenames known to have had problems in an older archived simulator snapshot.
# v3.2 leg orientation policy — preserve native community CAD axes exactly.
# Direct inspection of the uploaded source shows:
#   大腿右.stl : ~163 x 209 x 465 mm -> source Z is already vertical
#   右小腿.stl : ~125 x 159 x 355 mm -> source Z is already vertical
#   右脚.stl   : ~110 x 224 x 119 mm -> source Y is length, Z is vertical
# Therefore no PCA, no axis remapping and no 90-degree facing correction is used.
LEG_ORIENTATION_Z_DEG = {
    "thigh": 0.0,
    "calf": 0.0,
    "foot": 0.0,
}

LEG_SIDE_CLEARANCE_MM = 12.0
# Hip spacing.
#
# v3.2 picked the hip-pivot spacing from the thigh's total lateral WIDTH
# (native_thigh_width + a clearance), clamped to 170-195 mm. That is only
# correct if the thigh's top pivot sits at the shell's lateral midpoint. It
# doesn't: normalize_long_segment() centers the pivot on the *top mounting
# face* of the thigh, which this CAD source places well toward one side of
# the shell, not its center. So half of "total width" understates how far
# the shell actually reaches back across the midline, and v3.2 measured a
# real 56.82 mm AABB overlap (see README_FIRST.md / InMoov_Complete_Rigged_MM.json
# -> alignment.thigh_aabb_gap_mm) instead of the small clearance it intended.
#
# v3.3 no longer trusts a single width-based guess. It places both thighs,
# *measures* the resulting AABB gap, and pushes the hips further apart by
# exactly the measured shortfall until a real minimum clearance is met (see
# LEG_HIP_MIN_THIGH_CLEARANCE_MM below and the placement code in
# import_and_fit_standing_legs). The constants below now bound that search
# instead of being dead code: they were already sized for the true inward
# reach of this shell (hence "FALLBACK_MIN" 220 mm, not 170 mm) but v3.2
# never actually applied them.
LEG_HIP_SPACING_FALLBACK_MIN_MM = 220.0
LEG_HIP_SPACING_MAX_MM = 280.0

# Minimum clear (non-overlapping) gap the corrective step in
# import_and_fit_standing_legs must achieve between the two thigh AABBs.
LEG_HIP_MIN_THIGH_CLEARANCE_MM = 8.0

# How far above the true bottom of the torso shell the hip pivot sits. Small
# and purely cosmetic (recesses the pivot slightly into the torso instead of
# right on its outer surface); the actual mounting-position fix is in how
# hip_y/hip_x are now sourced (see torso_mount_reference()).
HIP_MOUNT_Z_CLEARANCE_MM = 12.0

# Separate toe cap is present in the community CAD source and in the official
# non-motorized leg design. Place its rear edge slightly inside the foot shell.
LEG_TOE_OVERLAP_MM = 10.0

# v3.3 FIX: this was 180.0 in v3.1/v3.2. That flips the toe cap end-for-end
# *after* import_and_fit_standing_legs has already placed it with its native
# -Y axis (rear flat/attachment face at Y=0, tapered tip at negative local Y)
# pointing the same "toward the toes" direction as everything else in this
# file — the foot mesh itself, and the CTRL_LEG.<side>.FOOT/TOE bones built
# later in build_armature_from_links, both explicitly use -Y as "forward"
# (see the "Foot bone intentionally points toward native toe direction (-Y)"
# comment there). The 180-degree flip made the visible toe mesh point the
# opposite way from its own control bone and from the foot: it buried the
# tapered tip against/inside the foot and swung the wide rear face out to
# become the visible "tip," which is the "toe pieces aren't properly aligned"
# symptom. normalize_toe() already gets the orientation right on its own, so
# the extra yaw here should be 0. Kept as a named constant (rather than
# deleted outright) in case a future community mesh genuinely needs a flip —
# if a toe cap ever again looks reversed after re-downloading the source
# repo, this is the one number to try 180 on.
FINAL_TOE_YAW_CORRECTION_DEG = 0.0

# After any final toe yaw, mate its rear face into the foot front by this much.
# This correction happens after floor/rig placement, so it cannot move the body.
FINAL_TOE_MATING_OVERLAP_MM = 3.0

# ---------------------------------------------------------------------------
# v3.8: MANUAL CALIBRATION OVERRIDES
# ---------------------------------------------------------------------------
# For parts this script has no real mate/assembly data for (the toe cap's
# exact rest orientation, hip/knee/ankle hardware, the pelvis parts, etc.),
# continuing to guess procedural corrections has diminishing returns -- a
# human looking at the actual mesh next to a reference photo can nail these
# in minutes. This section lets that one-time manual result get baked back
# into the script so every future run reproduces it automatically, instead
# of staying an unplaced shelf or an approximate heuristic forever.
#
# HOW TO CALIBRATE A PART:
#   1. Run the script and open the resulting .blend.
#   2. Find "REF::R_HIP", "REF::L_KNEE", etc. under the hidden
#      "93_CALIBRATION_REFERENCE_POINTS" collection (unhide it) -- these are
#      real Empty objects sitting exactly at this run's hip/knee/ankle
#      points, so you have a concrete point to measure from.
#   3. Manually move/rotate the part you want to fix into the correct place.
#   4. Open the Scripting tab, find the embedded "CALIBRATION_HELPER" text
#      block, select your part in the viewport, and run:
#          print_calibration_offset(bpy.context.object, "R_ANKLE")
#      (using whichever REF point is the closest sensible parent -- R_ANKLE
#      for a right toe, R_HIP for right hip hardware, etc.) It prints a
#      ready-to-paste entry.
#   5. Paste that entry into MANUAL_CALIBRATION_OVERRIDES below and re-run.
#      apply_calibration_overrides() applies it as the absolute final
#      transform for that object, after every other placement/correction
#      step in this file -- so it wins regardless of what the procedural
#      guess would otherwise have done.
#
# Format: {object_name: {"reference_point": one of "R_HIP"/"L_HIP"/"R_KNEE"/
# "L_KNEE"/"R_ANKLE"/"L_ANKLE", "position_offset_mm": (x,y,z),
# "rotation_euler_deg": (x,y,z)}}. Rotation is applied X then Y then Z, as
# an absolute world rotation (every reference point's own orientation is
# identity, since all leg placement in this file is translation-only).
MANUAL_CALIBRATION_OVERRIDES: dict[str, dict] = {
    # Verified against a matrix_world dump of the manually-positioned .blend;
    # every entry's Y/Z matched this file's own procedural reference-point
    # math to within 0.0001 mm before being accepted here.
    "LEG_REF::R::THIGH": {
        "reference_point": "R_HIP",
        "position_offset_mm": (27.3177, 0.0, 0.0),
        "rotation_euler_deg": (0.0, 0.0, 0.0),
    },
    "LEG_REF::R::CALF": {
        "reference_point": "R_KNEE",
        "position_offset_mm": (27.3177, 0.0, 0.0),
        "rotation_euler_deg": (0.0, 0.0, 0.0),
    },
    "LEG_REF::R::FOOT": {
        "reference_point": "R_ANKLE",
        "position_offset_mm": (15.1388, 0.0, 0.0),
        "rotation_euler_deg": (0.0, 0.0, 0.0),
    },
    "LEG_REF::R::TOE": {
        "reference_point": "R_ANKLE",
        "position_offset_mm": (54.1807, -232.149, -118.5388),
        "rotation_euler_deg": (0.0, 0.0, -163.1246),
    },
    "LEG_REF::L::THIGH": {
        "reference_point": "L_HIP",
        "position_offset_mm": (-16.7663, 0.0, 0.0),
        "rotation_euler_deg": (0.0, 0.0, 0.0),
    },
    "LEG_REF::L::CALF": {
        "reference_point": "L_KNEE",
        "position_offset_mm": (-16.7663, 0.0, 0.0),
        "rotation_euler_deg": (0.0, 0.0, 0.0),
    },
    "LEG_REF::L::FOOT": {
        "reference_point": "L_ANKLE",
        "position_offset_mm": (-4.5875, 0.0, 0.0),
        "rotation_euler_deg": (0.0, 0.0, 0.0),
    },
    "LEG_REF::L::TOE": {
        "reference_point": "L_ANKLE",
        "position_offset_mm": (-42.6805, -227.1479, -118.5388),
        "rotation_euler_deg": (0.1611, 0.978, 162.7115),
    },
}

# v4.0 visualization policy: geometry stays bound to the actual URDF source
# joint hierarchy. Proxy IK targets are still created as optional manual/reference
# controls, but they DO NOT own arm/hand/finger geometry. This keeps Blender a
# faithful renderer of externally solved joint angles instead of a second IK solver.
VISUALIZATION_ARM_BINDING_MODE = "SOURCE_FK"

KNOWN_SUSPECT_MESHES = {
    "Texture.261.stl", "Texture.262.stl", "Texture.265.stl", "Texture.266.stl"
}

# Keywords used only for organization in Blender; they do not alter geometry.
REGION_RULES = [
    ("LEFT_HAND", ["left_hand", "lhand", "leftfinger", "left_finger", "leftthumb", "left_thumb"]),
    ("RIGHT_HAND", ["right_hand", "rhand", "rightfinger", "right_finger", "rightthumb", "right_thumb"]),
    ("LEFT_ARM", ["left_arm", "leftshoulder", "left_shoulder", "leftbicep", "left_bicep", "leftelbow", "left_elbow", "leftforearm", "left_forearm", "leftwrist", "left_wrist"]),
    ("RIGHT_ARM", ["right_arm", "rightshoulder", "right_shoulder", "rightbicep", "right_bicep", "rightelbow", "right_elbow", "rightforearm", "right_forearm", "rightwrist", "right_wrist"]),
    ("HEAD_NECK", ["head", "neck", "jaw", "mouth", "eye", "eyebrow", "skull"]),
    ("TORSO", ["torso", "chest", "stomach", "waist", "spine", "body", "omoplate", "scapula"]),
    ("LEFT_LEG", ["left_leg", "leftthigh", "left_thigh", "leftknee", "left_knee", "leftshin", "left_shin", "leftankle", "left_ankle", "leftfoot", "left_foot"]),
    ("RIGHT_LEG", ["right_leg", "rightthigh", "right_thigh", "rightknee", "right_knee", "rightshin", "right_shin", "rightankle", "right_ankle", "rightfoot", "right_foot"]),
]

REPORT = {
    "builder_version": "4.0",
    "created_unix": time.time(),
    "units": "millimeters",
    "blender_unit_definition": "1 Blender Unit = 1 mm",
    "downloads": [],
    "urdf": None,
    "root_link": None,
    "links": 0,
    "joints": 0,
    "visuals_imported": 0,
    "visuals_failed": [],
    "hardware_reference_imported": [],
    "official_knee_ankle_hardware_imported": [],
    "warnings": [],
    "stand_removed": [],
    "leg_source_root": None,
    "leg_source_files": {},
    "leg_dimensions_mm": {},
    "armature": {},
    "source_manifest": [
        {
            "name": "Sentience Robotics current InMoov URDF",
            "url": "https://github.com/Sentience-Robotics/inmoov_urdf",
            "purpose": "canonical upper-body Xacro/URDF and 290 DAE visuals"
        },
        {
            "name": "Sentience Robotics archived InMoov ROS simulator",
            "url": "https://github.com/Sentience-Robotics/inmoov_ros_sim",
            "purpose": "fallback/reference only"
        },
        {
            "name": "Alan's InMoov ROS",
            "url": "https://github.com/alansrobotlab/inmoov_ros",
            "purpose": "fallback/reference only"
        },
        {
            "name": "wei1224hf InMoov SolidWorks reverse engineering",
            "url": "https://github.com/wei1224hf/inmoov-solidworks",
            "purpose": "standing-leg and servo/motor reference geometry"
        }
    ],
    "output": {
        "blend": "InMoov_Complete_Rigged_MM.blend",
        "json": "InMoov_Complete_Rigged_MM.json",
        "blender_backup_versions": 0
    }
}


def log(msg: str) -> None:
    print(f"[InMoovBuilder] {msg}", flush=True)


def ensure_dirs() -> None:
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    SOURCES.mkdir(parents=True, exist_ok=True)


def download(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 1024:
        log(f"Using cached download: {dest.name}")
        return
    log(f"Downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    context = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT, context=context) as response, open(dest, "wb") as out:
        shutil.copyfileobj(response, out)
    log(f"Downloaded {dest.name}: {dest.stat().st_size / 1024 / 1024:.1f} MiB")


def extract_zip(zip_path: Path, dest_dir: Path) -> Path:
    marker = dest_dir / ".extracted_ok"
    if marker.exists():
        children = [p for p in dest_dir.iterdir() if p.name != marker.name]
        return children[0] if len(children) == 1 and children[0].is_dir() else dest_dir
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        # Avoid zip-slip.
        root_resolved = dest_dir.resolve()
        for info in zf.infolist():
            target = (dest_dir / info.filename).resolve()
            if root_resolved not in target.parents and target != root_resolved:
                raise RuntimeError(f"Unsafe archive path: {info.filename}")
        zf.extractall(dest_dir)
    marker.write_text("ok", encoding="utf-8")
    children = [p for p in dest_dir.iterdir() if p.name != marker.name]
    return children[0] if len(children) == 1 and children[0].is_dir() else dest_dir


def acquire_repo(spec: dict) -> Path | None:
    for branch in spec["branches"]:
        archive = DOWNLOADS / f'{spec["name"]}-{branch}.zip'
        url = f'https://codeload.github.com/{spec["owner"]}/{spec["repo"]}/zip/refs/heads/{branch}'
        try:
            download(url, archive)
            extracted = extract_zip(archive, SOURCES / f'{spec["name"]}-{branch}')
            REPORT["downloads"].append({"name": spec["name"], "branch": branch, "url": url, "path": str(extracted)})
            return extracted
        except Exception as exc:
            log(f"Could not acquire {spec['owner']}/{spec['repo']}:{branch}: {exc}")
            if archive.exists() and archive.stat().st_size < 1024:
                archive.unlink(missing_ok=True)
    REPORT["warnings"].append(f"Repository unavailable: {spec['owner']}/{spec['repo']}")
    return None


def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for datablocks in (bpy.data.meshes, bpy.data.curves, bpy.data.materials, bpy.data.cameras, bpy.data.lights):
        # Do not aggressively remove while iterating; stale blocks are harmless.
        pass


def setup_si_units_for_build() -> None:
    """Assemble the canonical ROS model in native SI units first.

    URDF uses metres.  The maintained InMoov model's DAE meshes are intended for
    that same ROS/SI coordinate system.  Building in metres avoids the unit
    mismatch that affected v1.0-v1.4.
    """
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.length_unit = "METERS"
    scene.unit_settings.scale_length = 1.0
    scene["INMOOV_BUILD_UNITS"] = "native SI metres during assembly"


def finalize_mm_units() -> None:
    """After a validated SI assembly has been baked x1000, expose true mm units."""
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.length_unit = "MILLIMETERS"
    scene.unit_settings.scale_length = 0.001
    scene["INMOOV_UNIT_CONVENTION"] = "1 Blender Unit = 1 millimeter"
    scene["INMOOV_VISUALIZATION_BINDING_MODE"] = VISUALIZATION_ARM_BINDING_MODE
    scene["INMOOV_MEASUREMENT_USE"] = "Engineering-reference mesh assembly; verify community hardware reference before fit-critical design"



def configure_viewports() -> None:
    """Set a depth-buffer-friendly clipping range for a ~2 m millimetre scene.

    1 BU = 1 mm, so:
      Clip Start = 1 mm
      Clip End   = 10,000 mm (10 m)

    This is ample for the robot while giving much better Z-buffer precision
    than the older 0.1 mm -> 100 m range.
    """
    try:
        for window in bpy.context.window_manager.windows:
            screen = window.screen
            if not screen:
                continue
            for area in screen.areas:
                if area.type != "VIEW_3D":
                    continue
                for space in area.spaces:
                    if space.type == "VIEW_3D":
                        space.clip_start = 1.0
                        space.clip_end = 10000.0
    except Exception as exc:
        REPORT["warnings"].append(
            f"Could not configure 3D viewport clipping: {exc!r}"
        )



def get_or_create_collection(name: str, parent: bpy.types.Collection | None = None) -> bpy.types.Collection:
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
    if parent is None:
        if col.name not in bpy.context.scene.collection.children:
            try:
                bpy.context.scene.collection.children.link(col)
            except RuntimeError:
                pass
    else:
        if col.name not in parent.children:
            try:
                parent.children.link(col)
            except RuntimeError:
                pass
    return col


def unlink_from_all_collections(obj: bpy.types.Object) -> None:
    for col in list(obj.users_collection):
        col.objects.unlink(obj)


def move_object_to_collection(obj: bpy.types.Object, col: bpy.types.Collection) -> None:
    unlink_from_all_collections(obj)
    col.objects.link(obj)


def classify_region(name: str) -> str:
    n = name.lower().replace("-", "_").replace(" ", "_")
    for region, words in REGION_RULES:
        if any(w in n for w in words):
            return region
    return "MISC_BODY"


def parse_xyz(text: str | None, default=(0.0, 0.0, 0.0)) -> tuple[float, float, float]:
    if not text:
        return tuple(default)
    vals = [float(x) for x in text.replace(",", " ").split()]
    while len(vals) < 3:
        vals.append(default[len(vals)])
    return tuple(vals[:3])


def urdf_pose_matrix(origin_elem: ET.Element | None) -> Matrix:
    """Return the URDF pose in native SI metres.

    The canonical current xacro already applies its model_scale property to all
    relevant xyz origins.  Do not perform any millimetre conversion here.
    """
    if origin_elem is None:
        xyz = (0.0, 0.0, 0.0)
        rpy = (0.0, 0.0, 0.0)
    else:
        xyz = parse_xyz(origin_elem.get("xyz"))
        rpy = parse_xyz(origin_elem.get("rpy"))
    roll, pitch, yaw = rpy
    rx = Matrix.Rotation(roll, 4, "X")
    ry = Matrix.Rotation(pitch, 4, "Y")
    rz = Matrix.Rotation(yaw, 4, "Z")
    rot = rz @ ry @ rx
    trans = Matrix.Translation(Vector(xyz))
    return trans @ rot


def mesh_scale_matrix(mesh_elem: ET.Element) -> Matrix:
    # URDF <mesh scale="..."> is dimensionless.  The current maintained
    # xacro leaves DAE mesh scale at 1 1 1 and bakes model_scale into origins.
    s = parse_xyz(mesh_elem.get("scale"), default=(1.0, 1.0, 1.0))
    return Matrix.Diagonal((s[0], s[1], s[2], 1.0))


def build_file_index(roots: list[Path]) -> tuple[dict[str, list[Path]], list[Path]]:
    by_basename: dict[str, list[Path]] = {}
    all_files: list[Path] = []
    for root in roots:
        if not root or not root.exists():
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            all_files.append(p)
            by_basename.setdefault(p.name.lower(), []).append(p)
    return by_basename, all_files


def read_current_model_scale(current_root: Path) -> float | None:
    props = current_root / "description" / "robot_description" / "urdf" / "properties.xacro"
    if not props.exists():
        return None
    try:
        txt = props.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r'<xacro:property\s+name=["\']model_scale["\']\s+value=["\']([^"\']+)', txt)
        if m:
            return float(m.group(1))
    except Exception as exc:
        REPORT["warnings"].append(f"Could not read current model_scale: {exc!r}")
    return None


def ensure_xacro_module():
    """Load ROS xacro into Blender's Python without requiring a ROS installation."""
    try:
        import xacro  # type: ignore
        return xacro
    except Exception:
        pass

    deps = CACHE / "python_deps"
    deps.mkdir(parents=True, exist_ok=True)
    if str(deps) not in sys.path:
        sys.path.insert(0, str(deps))

    try:
        import xacro  # type: ignore
        return xacro
    except Exception:
        pass

    log("Python xacro module not found; installing xacro into the local builder cache...")
    cmd = [
        sys.executable, "-m", "pip", "install",
        "--disable-pip-version-check",
        "--target", str(deps),
        "xacro==2.1.1",
    ]
    try:
        subprocess.run(cmd, check=True)
    except Exception as exc:
        raise RuntimeError(
            "Could not install the pure-Python xacro package required to compile the current "
            "InMoov model. Internet access to PyPI is required for the first v1.6 run."
        ) from exc

    # Ensure newly installed modules are visible in this process.
    if str(deps) not in sys.path:
        sys.path.insert(0, str(deps))
    import importlib
    importlib.invalidate_caches()
    import xacro  # type: ignore
    return xacro


def compile_current_xacro(current_root: Path) -> Path:
    """Compile the repository's canonical runtime xacro into a flat URDF.

    This intentionally refuses to use current_root/archive/urdf/InMoov.urdf.
    The repository documents archive/ as lineage/reference only; the canonical
    runtime entrypoint is description/urdf/inmoov.urdf.xacro.
    """
    entry = current_root / "description" / "urdf" / "inmoov.urdf.xacro"
    description = current_root / "description"
    if not entry.exists():
        raise RuntimeError(f"Canonical current xacro not found: {entry}")

    scale = read_current_model_scale(current_root)
    if scale is not None:
        REPORT["current_model_scale"] = scale
        log(f"Current maintained model_scale = {scale}")

    xacro = ensure_xacro_module()
    generated = CACHE / "generated_current_inmoov.urdf"
    mappings = {
        "base_path": description.as_posix(),
        "use_gazebo_sim": "false",
        "use_mock_hardware": "true",
    }
    log(f"Compiling canonical xacro: {entry}")
    try:
        doc = xacro.process_file(str(entry), mappings=mappings)
        xml = doc.toxml()
    except Exception as exc:
        raise RuntimeError(f"Canonical xacro compilation failed: {exc}") from exc

    generated.write_text(xml, encoding="utf-8")
    REPORT["urdf"] = {
        "path": str(generated),
        "source": "sentience_current_canonical_xacro",
        "xacro": str(entry),
    }
    return generated


def candidate_urdfs(root: Path) -> list[tuple[int, Path]]:
    out = []
    if not root or not root.exists():
        return out
    for p in root.rglob("*.urdf"):
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if "<robot" not in txt or "<mesh" not in txt:
            continue
        stl_refs = txt.lower().count(".stl")
        dae_refs = txt.lower().count(".dae")
        score = (
            txt.count("<joint") * 20
            + txt.count("<link") * 10
            + txt.count("<mesh") * 5
            + stl_refs * 8
            - dae_refs * 2
            + min(len(txt) // 1000, 100)
        )
        # Strong preference for names that look like the complete robot.
        low = p.name.lower()
        if low in {"inmoov.urdf", "robot.urdf", "main.urdf"}:
            score += 1000
        if "full" in low or "complete" in low:
            score += 500
        out.append((score, p))
    return sorted(out, reverse=True, key=lambda x: x[0])


def choose_urdf(source_roots: dict[str, Path | None]) -> Path:
    # Prefer the actively maintained/current URDF.  The archived simulator contains
    # several historically corrupted STL meshes that can create gigantic scene
    # bounds in Blender, so it is now a fallback rather than the primary source.
    priority = ["sentience_current", "sentience_archived", "alan_ros"]
    combined = []
    for idx, key in enumerate(priority):
        root = source_roots.get(key)
        if not root:
            continue
        cands = candidate_urdfs(root)
        if cands:
            log(f"Top URDF in {key}: {cands[0][1]} (score {cands[0][0]})")
            # Prefer a plausible complete model even if another repo has a slightly bigger file.
            score, path = cands[0]
            combined.append((score + (len(priority)-idx)*200, path, key))
    if not combined:
        raise RuntimeError("No standalone URDF containing mesh visuals was found in downloaded sources.")
    combined.sort(reverse=True, key=lambda x: x[0])
    _, path, source = combined[0]
    REPORT["urdf"] = {"path": str(path), "source": source}
    return path


def strip_package_uri(uri: str) -> tuple[str | None, str]:
    raw = uri.strip()
    norm = raw.replace("\\", "/")
    if norm.startswith("package://"):
        rest = norm[len("package://"):]
        parts = rest.split("/", 1)
        if len(parts) == 2:
            return parts[0], parts[1]
        return parts[0], ""
    if norm.startswith("file://"):
        parsed = urllib.parse.urlparse(norm)
        path = urllib.parse.unquote(parsed.path or "")
        # Windows file:///C:/path -> C:/path
        if re.match(r"^/[A-Za-z]:/", path):
            path = path[1:]
        if parsed.netloc and not path:
            path = parsed.netloc
        return None, path
    return None, norm


def resolve_mesh(uri: str, urdf_path: Path, roots: list[Path], basename_index: dict[str, list[Path]], all_files: list[Path]) -> Path | None:
    pkg, rel = strip_package_uri(uri)
    rel_norm = rel.replace("\\", "/")

    # 0) Current canonical xacro emits absolute file:// mesh paths. Honor those
    # directly before any basename fallback.
    direct = Path(rel_norm)
    if direct.is_absolute() and direct.exists():
        return direct.resolve()

    # Windows drive paths can arrive on non-Windows parsers as non-absolute strings;
    # still compare normalized suffixes against the downloaded repository index.
    local = (urdf_path.parent / rel_norm.lstrip("/")).resolve()
    if local.exists():
        return local

    suffixes = [rel_norm.strip("/").lower()]
    if pkg:
        suffixes.insert(0, f"{pkg}/{rel_norm.strip('/')}".lower())
    exact_matches = []
    for candidate in all_files:
        ps = candidate.as_posix().lower()
        if any(ps.endswith("/" + suffix) or ps.endswith(suffix) for suffix in suffixes if suffix):
            exact_matches.append(candidate)
    if exact_matches:
        # Canonical current DAE assets win.  Archive is lineage-only.
        exact_matches.sort(key=lambda candidate: (
            0 if "/description/robot_description/meshes/dae/" in candidate.as_posix().lower() else 1,
            1 if "/archive/" in candidate.as_posix().lower() else 0,
            len(candidate.as_posix()),
        ))
        return exact_matches[0]

    base = Path(rel_norm).name.lower()
    choices = basename_index.get(base, [])
    if choices:
        choices = sorted(choices, key=lambda candidate: (
            0 if "/description/robot_description/meshes/dae/" in candidate.as_posix().lower() else 1,
            1 if "/archive/" in candidate.as_posix().lower() else 0,
            len(candidate.as_posix()),
        ))
        return choices[0]
    return None


def ensure_pycollada_module():
    """Load PyCOLLADA for Blender 5.x, where native COLLADA I/O was removed.

    Blender 5.0 removed bpy.ops.wm.collada_import.  The maintained InMoov
    description uses 290 DAE meshes, so v1.6 parses those files directly via
    PyCOLLADA instead of requiring a Blender extension.
    """
    try:
        import collada  # type: ignore
        return collada
    except Exception:
        pass

    deps = CACHE / "python_deps"
    deps.mkdir(parents=True, exist_ok=True)
    if str(deps) not in sys.path:
        sys.path.insert(0, str(deps))

    try:
        import collada  # type: ignore
        return collada
    except Exception:
        pass

    log("PyCOLLADA not found; installing it into the local builder cache for Blender 5.x DAE support...")
    cmd = [
        sys.executable, "-m", "pip", "install",
        "--disable-pip-version-check",
        "--target", str(deps),
        "pycollada==0.9.3",
    ]
    try:
        subprocess.run(cmd, check=True)
    except Exception as exc:
        raise RuntimeError(
            "Blender 5.x no longer includes COLLADA import and the builder could not install "
            "PyCOLLADA. Internet access to PyPI is required for the first v1.6 run."
        ) from exc

    if str(deps) not in sys.path:
        sys.path.insert(0, str(deps))
    import importlib
    importlib.invalidate_caches()
    import collada  # type: ignore
    return collada


def _dae_axis_convert_xyz(x: float, y: float, z: float, upaxis: str) -> tuple[float, float, float]:
    """Convert a COLLADA document's declared up-axis to Blender/URDF Z-up."""
    up = str(upaxis or "Z_UP").upper()
    if "Y_UP" in up:
        # +90 degrees about X: Y-up -> Z-up.
        return (x, -z, y)
    if "X_UP" in up:
        # -90 degrees about Y: X-up -> Z-up.
        return (-z, y, x)
    return (x, y, z)


def import_dae_pycollada(path: Path) -> list[bpy.types.Object]:
    """Import COLLADA geometry without Blender's removed COLLADA operator.

    PyCOLLADA's bound geometry API applies the DAE scene-node transforms before
    exposing vertex arrays.  We additionally honor the COLLADA asset unit
    metadata (meters per document unit) and up-axis.  Materials/textures are not
    required for this engineering-reference scene, so geometry is intentionally
    the priority.
    """
    collada = ensure_pycollada_module()
    try:
        dae = collada.Collada(str(path))
    except Exception as exc:
        raise RuntimeError(f"PyCOLLADA could not parse {path.name}: {exc}") from exc

    asset = getattr(dae, "assetInfo", None)
    unitmeter = getattr(asset, "unitmeter", None) if asset is not None else None
    try:
        unitmeter = float(unitmeter) if unitmeter not in (None, 0) else 1.0
    except Exception:
        unitmeter = 1.0
    upaxis = str(getattr(asset, "upaxis", "Z_UP") if asset is not None else "Z_UP")

    # BoundGeometry applies any transforms authored inside the DAE.  If a DAE has
    # no active visual scene, fall back to its raw geometry primitives.
    bound_geometries = []
    scene = getattr(dae, "scene", None)
    if scene is not None:
        try:
            bound_geometries = list(scene.objects("geometry"))
        except Exception:
            bound_geometries = []

    if not bound_geometries:
        # Minimal adapter for files that only contain library_geometries.
        import numpy as np  # Blender ships NumPy; PyCOLLADA also depends on it.
        identity = np.identity(4, dtype=float)
        for geom in getattr(dae, "geometries", []):
            try:
                bound_geometries.append(geom.bind(identity, {}))
            except Exception:
                continue

    created: list[bpy.types.Object] = []
    for geom_i, bound_geom in enumerate(bound_geometries):
        verts: list[tuple[float, float, float]] = []
        faces: list[tuple[int, int, int]] = []

        try:
            primitives = list(bound_geom.primitives())
        except Exception:
            primitives = []

        for prim in primitives:
            # TriangleSet is already triangular; Polylist/Polygons expose a
            # triangleset() fan triangulation.  Lines are intentionally ignored.
            tri = prim
            clsname = type(prim).__name__.lower()
            if "triangle" not in clsname and hasattr(prim, "triangleset"):
                try:
                    tri = prim.triangleset()
                except Exception:
                    continue

            if not hasattr(tri, "vertex") or not hasattr(tri, "vertex_index"):
                continue
            try:
                vertex_array = tri.vertex
                index_array = tri.vertex_index
                if vertex_array is None or index_array is None:
                    continue
                base = len(verts)
                for row in vertex_array:
                    x, y, z = float(row[0]) * unitmeter, float(row[1]) * unitmeter, float(row[2]) * unitmeter
                    verts.append(_dae_axis_convert_xyz(x, y, z, upaxis))
                for row in index_array:
                    # triangleset() guarantees triangles, but be defensive about
                    # NumPy shape/sequence types.
                    inds = [int(v) for v in row]
                    if len(inds) < 3:
                        continue
                    if len(inds) == 3:
                        faces.append((base + inds[0], base + inds[1], base + inds[2]))
                    else:
                        # Fan triangulate any unexpected n-gon index row.
                        for k in range(1, len(inds) - 1):
                            faces.append((base + inds[0], base + inds[k], base + inds[k + 1]))
            except Exception as exc:
                log(f"  PyCOLLADA primitive skipped in {path.name}: {exc}")
                continue

        if not verts or not faces:
            continue

        mesh = bpy.data.meshes.new(f"DAE::{path.stem}::{geom_i:02d}")
        mesh.from_pydata(verts, [], faces)
        try:
            mesh.validate(verbose=False, clean_customdata=True)
        except TypeError:
            mesh.validate(verbose=False)
        mesh.update()
        obj = bpy.data.objects.new(f"DAE::{path.stem}::{geom_i:02d}", mesh)
        bpy.context.scene.collection.objects.link(obj)
        obj["dae_import_backend"] = "pycollada"
        obj["dae_unitmeter"] = unitmeter
        obj["dae_upaxis"] = upaxis
        created.append(obj)

    if not created:
        raise RuntimeError(
            f"PyCOLLADA parsed {path.name}, but no triangle/polylist/polygon geometry was produced"
        )

    REPORT["dae_import_backend"] = "pycollada_direct_geometry"
    return created


def import_mesh_file(path: Path) -> list[bpy.types.Object]:
    ext = path.suffix.lower()

    # Blender 5.0 removed native COLLADA import/export.  Try a native operator
    # only on versions that still expose it; otherwise use the direct parser.
    if ext == ".dae":
        if bpy.app.version < (5, 0, 0):
            before = set(bpy.data.objects)
            try:
                bpy.ops.wm.collada_import(filepath=str(path))
                after = set(bpy.data.objects)
                imported = list(after - before)
                if imported:
                    REPORT["dae_import_backend"] = "blender_native_collada"
                    return imported
            except Exception as exc:
                log(f"Native COLLADA importer failed for {path.name}; falling back to PyCOLLADA: {exc}")
        return import_dae_pycollada(path)

    before = set(bpy.data.objects)
    if ext == ".stl":
        if hasattr(bpy.ops.wm, "stl_import"):
            bpy.ops.wm.stl_import(filepath=str(path))
        else:
            bpy.ops.import_mesh.stl(filepath=str(path))
    elif ext == ".obj":
        if hasattr(bpy.ops.wm, "obj_import"):
            bpy.ops.wm.obj_import(filepath=str(path))
        else:
            bpy.ops.import_scene.obj(filepath=str(path))
    elif ext == ".ply":
        if hasattr(bpy.ops.wm, "ply_import"):
            bpy.ops.wm.ply_import(filepath=str(path))
        else:
            bpy.ops.import_mesh.ply(filepath=str(path))
    else:
        raise RuntimeError(f"Unsupported mesh format: {ext}")
    after = set(bpy.data.objects)
    return list(after - before)


def parse_urdf(urdf_path: Path):
    tree = ET.parse(urdf_path)
    robot = tree.getroot()
    if robot.tag != "robot":
        # Namespaced XML fallback.
        found = robot.find(".//robot")
        if found is not None:
            robot = found
    links = {elem.get("name"): elem for elem in robot.findall("link") if elem.get("name")}
    joints = []
    children = set()
    for elem in robot.findall("joint"):
        parent = elem.find("parent")
        child = elem.find("child")
        if parent is None or child is None:
            continue
        p = parent.get("link")
        c = child.get("link")
        if not p or not c:
            continue
        joints.append((elem, p, c))
        children.add(c)
    roots = [name for name in links if name not in children]
    if not roots:
        raise RuntimeError("URDF has no root link")
    # Prefer conventional base names.
    roots.sort(key=lambda x: (0 if any(k in x.lower() for k in ("base", "root", "torso", "body")) else 1, x))
    return robot, links, joints, roots[0]


def create_link_hierarchy(links, joints, root_name, region_cols):
    root_col = get_or_create_collection("00_URDF_ASSEMBLY")
    link_objs: dict[str, bpy.types.Object] = {}
    for name in links:
        empty = bpy.data.objects.new(f"LINK::{name}", None)
        empty.empty_display_type = "PLAIN_AXES"
        empty.empty_display_size = 0.015
        empty["urdf_link_name"] = name
        region = classify_region(name)
        col = region_cols.get(region, root_col)
        col.objects.link(empty)
        link_objs[name] = empty

    # Root at scene origin.
    link_objs[root_name].matrix_world = Matrix.Identity(4)
    link_objs[root_name]["urdf_root"] = True

    # Apply parent/child transforms. URDF is a tree, but loop until parents are resolved.
    remaining = list(joints)
    resolved = {root_name}
    safety = 0
    while remaining and safety < len(joints) + 5:
        safety += 1
        next_remaining = []
        progress = False
        for joint_elem, parent_name, child_name in remaining:
            if parent_name not in resolved or child_name not in link_objs or parent_name not in link_objs:
                next_remaining.append((joint_elem, parent_name, child_name))
                continue
            parent_obj = link_objs[parent_name]
            child_obj = link_objs[child_name]
            child_obj.parent = parent_obj
            child_obj.matrix_parent_inverse = Matrix.Identity(4)
            child_obj.matrix_basis = urdf_pose_matrix(joint_elem.find("origin"))
            child_obj["urdf_joint_name"] = joint_elem.get("name", "")
            child_obj["urdf_joint_type"] = joint_elem.get("type", "")
            axis_elem = joint_elem.find("axis")
            child_obj["urdf_joint_axis"] = axis_elem.get("xyz", "1 0 0") if axis_elem is not None else "1 0 0"
            limit_elem = joint_elem.find("limit")
            if limit_elem is not None:
                for key in ("lower", "upper", "effort", "velocity"):
                    if limit_elem.get(key) is not None:
                        try:
                            child_obj[f"joint_{key}"] = float(limit_elem.get(key))
                        except ValueError:
                            child_obj[f"joint_{key}"] = limit_elem.get(key)
            resolved.add(child_name)
            progress = True
        remaining = next_remaining
        if not progress:
            break
    if remaining:
        REPORT["warnings"].append(f"{len(remaining)} URDF joints could not be connected into the root tree")
    return link_objs


def object_world_dimensions(obj: bpy.types.Object) -> Vector:
    """Axis-aligned world-space dimensions in the scene's current internal units."""
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    if not corners:
        return Vector((0.0, 0.0, 0.0))
    mins = Vector((min(v.x for v in corners), min(v.y for v in corners), min(v.z for v in corners)))
    maxs = Vector((max(v.x for v in corners), max(v.y for v in corners), max(v.z for v in corners)))
    return maxs - mins


def body_mesh_objects() -> list[bpy.types.Object]:
    return [
        o for o in bpy.data.objects
        if o.type == "MESH" and o.name.startswith("MESH::") and not o.get("quarantine_reason")
    ]


def compute_body_bounds_raw() -> dict | None:
    mins = Vector((float("inf"), float("inf"), float("inf")))
    maxs = Vector((float("-inf"), float("-inf"), float("-inf")))
    found = False
    for obj in body_mesh_objects():
        found = True
        for corner in obj.bound_box:
            world = obj.matrix_world @ Vector(corner)
            mins.x = min(mins.x, world.x); mins.y = min(mins.y, world.y); mins.z = min(mins.z, world.z)
            maxs.x = max(maxs.x, world.x); maxs.y = max(maxs.y, world.y); maxs.z = max(maxs.z, world.z)
    if not found:
        return None
    dims = maxs - mins
    return {
        "min": [float(mins.x), float(mins.y), float(mins.z)],
        "max": [float(maxs.x), float(maxs.y), float(maxs.z)],
        "dimensions": [float(dims.x), float(dims.y), float(dims.z)],
    }


def log_largest_body_meshes(label: str, unit_label: str, limit: int = 12) -> list[tuple[float, bpy.types.Object, Vector]]:
    rows = []
    for obj in body_mesh_objects():
        dims = object_world_dimensions(obj)
        m = max(abs(dims.x), abs(dims.y), abs(dims.z))
        if math.isfinite(m):
            rows.append((m, obj, dims))
    rows.sort(key=lambda x: x[0], reverse=True)
    log(f"Largest body meshes {label}:")
    for m, obj, dims in rows[:limit]:
        log(f"  {obj.name}: {dims.x:.6f} x {dims.y:.6f} x {dims.z:.6f} {unit_label}")
    return rows


def validate_si_assembly() -> None:
    """Refuse to save another misleading build if the canonical SI model is implausible."""
    bpy.context.view_layer.update()
    bounds = compute_body_bounds_raw()
    if not bounds:
        failures = REPORT.get("visuals_failed", [])
        if failures:
            log("No body meshes exist after import. First visual import failures:")
            for failure in failures[:12]:
                log(f"  {failure}")
        raise RuntimeError(
            f"Canonical xacro compiled, but no body meshes were imported "
            f"({len(failures)} visual imports failed). See the console/report for the first failure reasons."
        )

    dims = bounds["dimensions"]
    REPORT["si_assembly_bounds_m"] = {
        "min_m": [round(v, 6) for v in bounds["min"]],
        "max_m": [round(v, 6) for v in bounds["max"]],
        "dimensions_m": [round(v, 6) for v in dims],
    }
    log(f"Canonical SI assembly bounds: {dims[0]:.4f} x {dims[1]:.4f} x {dims[2]:.4f} m")
    rows = log_largest_body_meshes("in canonical SI build", "m")
    finite_sizes = sorted(m for m, _, _ in rows if m > 0 and math.isfinite(m))
    median = finite_sizes[len(finite_sizes)//2] if finite_sizes else 0.0
    REPORT["si_mesh_median_max_dimension_m"] = median

    # The maintained repository documents model_scale as targeting a measured crown
    # height of 1.80 m.  Allow generous pose/axis tolerance, but fail hard on the
    # kilometre/mm-scale pathologies seen in v1.0-v1.4.
    max_dim = max(dims)
    if max_dim < 0.5 or max_dim > 3.5:
        raise RuntimeError(
            f"Canonical current model assembled to {dims} m, outside the expected humanoid range. "
            "Build aborted before millimetre baking so no misleading engineering file is saved."
        )
    if median and (median < 0.002 or median > 2.0):
        raise RuntimeError(
            f"Canonical mesh median size {median:.6f} m is implausible; refusing to bake dimensions."
        )


def bake_urdf_assembly_m_to_mm(link_objs: dict[str, bpy.types.Object]) -> None:
    """Bake the validated URDF hierarchy from metres to true millimetre coordinates.

    We scale mesh vertex coordinates and every local translation by 1000 while
    leaving rotations and dimensionless object scales untouched.  The result is a
    scene where 1 Blender Unit really is 1 mm, including in Edit Mode.
    """
    factor = 1000.0
    body = body_mesh_objects()

    # Scale each unique mesh datablock exactly once.
    seen_data = set()
    for obj in body:
        data = obj.data
        key = data.as_pointer()
        if key in seen_data:
            continue
        seen_data.add(key)
        for vert in data.vertices:
            vert.co *= factor
        data.update()

    # Scale local translations for link empties and visual mesh objects.  Parenting
    # then produces a uniform 1000x world conversion without disturbing rotations.
    for obj in list(link_objs.values()) + body:
        m = obj.matrix_basis.copy()
        m.translation = m.translation * factor
        obj.matrix_basis = m
        if obj.type == "EMPTY":
            obj.empty_display_size *= factor

    bpy.context.view_layer.update()
    finalize_mm_units()
    REPORT["meter_to_mm_bake_factor"] = factor

    bounds = compute_body_bounds_raw()
    if bounds:
        dims = bounds["dimensions"]
        log(f"Baked millimetre assembly bounds: {dims[0]:.1f} x {dims[1]:.1f} x {dims[2]:.1f} mm")


def frame_assembly_in_viewports() -> None:
    body = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("MESH::") and not o.hide_get()]
    if not body:
        return
    try:
        # Select only valid body meshes.
        for o in bpy.context.view_layer.objects:
            o.select_set(False)
        for o in body:
            o.select_set(True)
        bpy.context.view_layer.objects.active = body[0]

        for window in bpy.context.window_manager.windows:
            screen = window.screen
            if not screen:
                continue
            for area in screen.areas:
                if area.type != "VIEW_3D":
                    continue
                region = next((r for r in area.regions if r.type == "WINDOW"), None)
                if region is None:
                    continue
                with bpy.context.temp_override(window=window, screen=screen, area=area, region=region):
                    bpy.ops.view3d.view_selected(use_all_regions=False)
    except Exception as exc:
        REPORT["warnings"].append(f"Could not auto-frame assembly: {exc!r}")


def add_visuals(links, link_objs, urdf_path, search_roots, basename_index, all_files, region_cols):
    count = 0
    failures = []
    for link_name, link_elem in links.items():
        link_obj = link_objs[link_name]
        visuals = link_elem.findall("visual")
        for visual_i, visual in enumerate(visuals):
            geom = visual.find("geometry")
            if geom is None:
                continue
            mesh_elem = geom.find("mesh")
            if mesh_elem is None or not mesh_elem.get("filename"):
                continue
            uri = mesh_elem.get("filename")
            path = resolve_mesh(uri, urdf_path, search_roots, basename_index, all_files)
            if path is None:
                failures.append({"link": link_name, "uri": uri, "reason": "not found"})
                continue
            try:
                imported = import_mesh_file(path)
                if not imported:
                    raise RuntimeError("import created no objects")
                relative = urdf_pose_matrix(visual.find("origin")) @ mesh_scale_matrix(mesh_elem)
                region = classify_region(link_name)
                dest_col = region_cols.get(region, bpy.data.collections.get("00_URDF_ASSEMBLY"))
                for n, obj in enumerate(imported):
                    old_local = obj.matrix_world.copy()
                    obj.parent = link_obj
                    obj.matrix_parent_inverse = Matrix.Identity(4)
                    obj.matrix_basis = relative @ old_local
                    obj.name = f"MESH::{link_name}::{visual_i:02d}::{n:02d}::{path.stem}"
                    obj["source_mesh"] = str(path)
                    obj["source_uri"] = uri
                    obj["provenance"] = "URDF_ASSEMBLY_SOURCE"
                    if path.name in KNOWN_SUSPECT_MESHES and "sentience_archived" in path.as_posix().lower():
                        obj["source_warning"] = "Known-corrupt archived simulator mesh; should have been replaced or quarantined"
                    move_object_to_collection(obj, dest_col)
                count += 1
            except Exception as exc:
                failures.append({"link": link_name, "uri": uri, "resolved": str(path), "reason": repr(exc)})
                log(f"Mesh import failed: {link_name} -> {path.name}: {exc}")
    REPORT["visuals_imported"] = count
    REPORT["visuals_failed"] = failures
    log(f"Visual import summary: {count} URDF visual entries imported, {len(failures)} failed")
    if failures:
        for failure in failures[:12]:
            log(f"  visual failure: {failure}")
        if len(failures) > 12:
            log(f"  ... {len(failures) - 12} additional visual failures recorded in the JSON report")


def import_hardware_references(solidworks_root: Path | None) -> None:
    if not solidworks_root or not solidworks_root.exists():
        REPORT["warnings"].append("Community SolidWorks repository unavailable; servo reference collection omitted")
        return
    hw_col = get_or_create_collection("90_HARDWARE_REFERENCE_UNPLACED")
    note_col = get_or_create_collection("99_NOTES_REFERENCE")
    candidates = []
    for p in solidworks_root.rglob("*.stl"):
        low = p.name.lower()
        # Chinese 舵机 = servo. Also catch English servo/motor names.
        if "舵机" in p.name or "servo" in low or "motor" in low:
            candidates.append(p)
    # De-duplicate by basename and keep a manageable set.
    seen = set()
    unique = []
    for p in candidates:
        if p.name.lower() in seen:
            continue
        seen.add(p.name.lower())
        unique.append(p)
    x0, y0, z0 = 850.0, 0.0, 1000.0
    spacing = 180.0
    # v3.3: no longer capped at the first 16 matches. That cap silently
    # dropped any hardware piece beyond it with no warning in the report;
    # since this repo is a live "master" branch that can gain files over
    # time, a hard cap here is exactly the kind of thing that produces
    # "several missing pieces" without any visible error.
    for i, path in enumerate(unique):
        try:
            imported = import_mesh_file(path)
            for j, obj in enumerate(imported):
                # SolidWorks STL exports are generally millimeter-valued. Keep raw scale.
                obj.location += Vector((x0 + (i % 4) * spacing, y0 + (i // 4) * spacing, z0))
                obj.name = f"HW_REF_UNPLACED::{path.stem}::{j:02d}"
                obj["source_mesh"] = str(path)
                obj["provenance"] = "COMMUNITY_REVERSE_ENGINEERED_REFERENCE"
                obj["measurement_warning"] = "UNPLACED hardware reference. Dimensions may be useful; installed position is NOT authoritative."
                move_object_to_collection(obj, hw_col)
                REPORT["hardware_reference_imported"].append(path.name)
        except Exception as exc:
            REPORT["warnings"].append(f"Hardware reference import failed: {path.name}: {exc}")

    # Add an explanatory text object near the reference shelf.
    font_curve = bpy.data.curves.new("HardwareReferenceWarningText", type="FONT")
    font_curve.body = "HARDWARE REFERENCES — UNPLACED\nCommunity reverse-engineered servo/motor meshes.\nDo not use installed position for fit-critical measurements."
    font_curve.size = 35
    font_obj = bpy.data.objects.new("NOTE::HARDWARE_REFERENCE_WARNING", font_curve)
    font_obj.location = (800.0, -300.0, 1300.0)
    font_obj.rotation_euler = (math.radians(90), 0, 0)
    note_col.objects.link(font_obj)


OFFICIAL_INMOOV_PARTS_BASE = "https://inmoov.fr/wp-content/uploads/stl"

# v3.7 addition: the official Gael Langevin / inmoov.fr parts library for the
# knee and ankle (https://inmoov.fr/inmoov-stl-parts-viewer/?bodyparts=Legs-Knee
# and ?bodyparts=Legs-Ankle). This is a different, authoritative source from
# the wei1224hf community SolidWorks reverse-engineering used for the main
# thigh/calf/foot/toe shells -- it's the designer's own CC BY-NC-licensed STLs,
# fetched directly (not a git repo, so acquire_repo()/extract_zip() don't
# apply; each file is downloaded individually with the existing download()
# helper). Unprefixed filenames are the right-side/shared part; an explicit
# "Left"-prefixed file is its own separate mesh, not a mirror -- InMoov's
# official parts are generally NOT simple mirror pairs, so no duplicate_mirrored()
# is used here.
OFFICIAL_KNEE_ANKLE_PARTS = {
    "Legs-Knee": [
        "KneeBoltsV1.stl", "KneeClampLeftV1.stl", "KneeClampRightV1.stl",
        "KneeHighLeftV3.stl", "KneeHighRightV3.stl", "KneeLowLeftV3.stl",
        "KneeLowRightV3.stl", "KneeSmallBoltsV1.stl",
    ],
    "Legs-Ankle": [
        "AnkBackFootV1.stl", "AnkHolderV1.stl", "AnkMidleFootV1.stl",
        "AnkToesBoltV1.stl", "AnkToesFootV2.stl", "AnkleBaseV1.stl",
        "AnkleDownV2.stl", "AnkpartV1.stl", "FootBoltHolder.stl",
        "LeftAnkBackFootV1.stl", "LeftAnkHolderV1.stl", "LeftAnkMidleFootV1.stl",
        "LeftAnkToesFootV2.stl", "LeftAnkleDownV2.stl", "LeftAnkpartV1.stl",
        "leftAnkleBaseV1.stl",
    ],
}


def import_official_knee_ankle_hardware() -> None:
    """Download and import the official inmoov.fr knee/ankle STL sets.

    Same "unplaced reference shelf" treatment as import_hardware_references():
    this script has no mate/joint data for how these many small interlocking
    parts actually stack together (that information lives in the designer's
    own assembly drawings, not in the individual STLs), so fabricating exact
    positions here would be a guess presented as fact. They're imported,
    clearly labeled, and left for visual/dimensional reference rather than
    installed -- consistent with how every other "we don't have mate data"
    part in this file is handled.
    """
    dest_dir = SOURCES / "official_inmoov_knee_ankle"
    dest_dir.mkdir(parents=True, exist_ok=True)
    hw_col = get_or_create_collection("91_OFFICIAL_KNEE_ANKLE_HARDWARE_UNPLACED")

    x0, y0, z0 = 850.0, 600.0, 1000.0
    spacing = 140.0
    imported_names = []
    i = 0
    for section, filenames in OFFICIAL_KNEE_ANKLE_PARTS.items():
        for filename in filenames:
            url = f"{OFFICIAL_INMOOV_PARTS_BASE}/{section}/{filename}"
            dest = dest_dir / f"{section}__{filename}"
            try:
                download(url, dest)
                imported = import_mesh_file(dest)
                for j, obj in enumerate(imported):
                    obj.location += Vector((x0 + (i % 4) * spacing, y0 + (i // 4) * spacing, z0))
                    obj.name = f"OFFICIAL_HW_UNPLACED::{section}::{Path(filename).stem}::{j:02d}"
                    obj["source_mesh"] = url
                    obj["provenance"] = "OFFICIAL_INMOOV_FR_CC_BY_NC"
                    obj["measurement_warning"] = (
                        "UNPLACED official reference part. No mate/assembly transform "
                        "is available to this script; do not treat installed position "
                        "as authoritative."
                    )
                    move_object_to_collection(obj, hw_col)
                    imported_names.append(f"{section}/{filename}")
                i += 1
            except Exception as exc:
                REPORT["warnings"].append(
                    f"Official knee/ankle hardware import failed: {section}/{filename}: {exc}"
                )

    REPORT["official_knee_ankle_hardware_imported"] = imported_names
    REPORT["source_manifest"].append({
        "name": "Official InMoov.fr parts library (Legs-Knee, Legs-Ankle)",
        "url": "https://inmoov.fr/inmoov-stl-parts-viewer/?bodyparts=Legs-Knee",
        "purpose": "official designer-provided knee/ankle hardware, unplaced reference only",
    })

    note_col = get_or_create_collection("99_NOTES_REFERENCE")
    font_curve = bpy.data.curves.new("OfficialKneeAnkleHardwareText", type="FONT")
    font_curve.body = (
        "OFFICIAL KNEE/ANKLE HARDWARE — UNPLACED\n"
        "From inmoov.fr (Gael Langevin, CC BY-NC), not the community SolidWorks source.\n"
        "No mate transforms available; do not use installed position for fit-critical work."
    )
    font_curve.size = 35
    font_obj = bpy.data.objects.new("NOTE::OFFICIAL_KNEE_ANKLE_HARDWARE_WARNING", font_curve)
    font_obj.location = (800.0, 550.0, 1300.0)
    font_obj.rotation_euler = (math.radians(90), 0, 0)
    note_col.objects.link(font_obj)


def apply_calibration_overrides() -> None:
    """Apply any entries in MANUAL_CALIBRATION_OVERRIDES as the final,
    absolute transform for the named objects. Runs last in main(), after
    every procedural placement/correction step, so a calibrated part is
    never re-adjusted by a heuristic afterward.
    """
    if not MANUAL_CALIBRATION_OVERRIDES:
        return
    ref_col = bpy.data.collections.get("93_CALIBRATION_REFERENCE_POINTS")
    ref_points = {}
    if ref_col:
        for obj in ref_col.objects:
            if obj.name.startswith("REF::"):
                ref_points[obj.name[len("REF::"):]] = obj.location.copy()

    applied = []
    for obj_name, cal in MANUAL_CALIBRATION_OVERRIDES.items():
        obj = bpy.data.objects.get(obj_name)
        if obj is None:
            REPORT["warnings"].append(f"Calibration override target not found: {obj_name}")
            continue
        ref_name = cal.get("reference_point")
        ref_point = ref_points.get(ref_name)
        if ref_point is None:
            REPORT["warnings"].append(
                f"Calibration override for {obj_name}: unknown reference point {ref_name!r}"
            )
            continue
        offset = Vector(cal.get("position_offset_mm", (0.0, 0.0, 0.0)))
        rot_deg = cal.get("rotation_euler_deg", (0.0, 0.0, 0.0))
        rot_mat = (
            Matrix.Rotation(math.radians(rot_deg[0]), 4, "X")
            @ Matrix.Rotation(math.radians(rot_deg[1]), 4, "Y")
            @ Matrix.Rotation(math.radians(rot_deg[2]), 4, "Z")
        )
        obj.matrix_world = Matrix.Translation(ref_point + offset) @ rot_mat
        applied.append(obj_name)

    if applied:
        REPORT.setdefault("alignment", {})["manual_calibration_overrides_applied"] = applied
    bpy.context.view_layer.update()


def add_calibration_helper_text() -> None:
    """Embed a standalone, runnable helper in the .blend's Scripting tab so
    calibrating a part doesn't require finding/reading this whole file.
    """
    text = bpy.data.texts.get("CALIBRATION_HELPER") or bpy.data.texts.new("CALIBRATION_HELPER")
    text.clear()
    text.write(
        '"""\n'
        "How to calibrate a part's position by hand and bake it into the build script.\n\n"
        "1. Unhide the '93_CALIBRATION_REFERENCE_POINTS' collection in the Outliner.\n"
        "   It has REF::R_HIP / L_HIP / R_KNEE / L_KNEE / R_ANKLE / L_ANKLE empties\n"
        "   sitting at this build's actual hip/knee/ankle points.\n"
        "2. Manually move/rotate the part you want to fix (e.g. LEG_REF::R::TOE, or\n"
        "   one of the OFFICIAL_HW_UNPLACED:: knee/ankle hardware pieces) into place,\n"
        "   using a reference photo.\n"
        "3. Select that object in the viewport, then in this console run:\n"
        "       print_calibration_offset(bpy.context.object, 'R_ANKLE')\n"
        "   (swap 'R_ANKLE' for whichever REF point makes sense as the parent --\n"
        "   R_HIP/L_HIP for hip hardware, R_ANKLE/L_ANKLE for a foot/toe, etc.)\n"
        "4. Copy the printed dict entry into MANUAL_CALIBRATION_OVERRIDES near the\n"
        "   top of build_inmoov_complete.py and re-run the full script. That entry\n"
        "   is applied as the final, absolute transform for that object -- it\n"
        "   overrides whatever the procedural placement did.\n"
        '"""\n'
        "import bpy, math\n"
        "from mathutils import Vector\n\n"
        "def print_calibration_offset(obj, reference_point_name):\n"
        "    ref = bpy.data.objects.get('REF::' + reference_point_name)\n"
        "    if ref is None:\n"
        "        print(f'No such reference point: REF::{reference_point_name}')\n"
        "        return\n"
        "    offset = obj.matrix_world.translation - ref.location\n"
        "    euler = obj.matrix_world.to_euler('XYZ')\n"
        "    rot_deg = tuple(round(math.degrees(a), 3) for a in euler)\n"
        "    pos_mm = tuple(round(v, 3) for v in offset)\n"
        "    print('\"' + obj.name + '\": {')\n"
        "    print(f'    \"reference_point\": \"{reference_point_name}\",')\n"
        "    print(f'    \"position_offset_mm\": {pos_mm},')\n"
        "    print(f'    \"rotation_euler_deg\": {rot_deg},')\n"
        "    print('},')\n"
    )


def add_measurement_reference() -> None:
    col = get_or_create_collection("99_NOTES_REFERENCE")
    # 100 mm cube placed away from body as a sanity reference.
    bpy.ops.mesh.primitive_cube_add(size=100.0, location=(650.0, 0.0, 50.0))
    cube = bpy.context.active_object
    cube.name = "REFERENCE::100mm_CUBE"
    cube["reference_dimensions_mm"] = "100 x 100 x 100"
    move_object_to_collection(cube, col)


def compute_bounds_mm() -> dict | None:
    mins = Vector((float("inf"), float("inf"), float("inf")))
    maxs = Vector((float("-inf"), float("-inf"), float("-inf")))
    found = False
    for obj in bpy.data.objects:
        if obj.type != "MESH" or not obj.name.startswith(("MESH::", "LEG_REF::")):
            continue
        if obj.get("quarantine_reason"):
            continue
        found = True
        for corner in obj.bound_box:
            world = obj.matrix_world @ Vector(corner)
            mins.x = min(mins.x, world.x); mins.y = min(mins.y, world.y); mins.z = min(mins.z, world.z)
            maxs.x = max(maxs.x, world.x); maxs.y = max(maxs.y, world.y); maxs.z = max(maxs.z, world.z)
    if not found:
        return None
    dims = maxs - mins
    return {
        "min_mm": [round(mins.x, 3), round(mins.y, 3), round(mins.z, 3)],
        "max_mm": [round(maxs.x, 3), round(maxs.y, 3), round(maxs.z, 3)],
        "dimensions_mm": [round(dims.x, 3), round(dims.y, 3), round(dims.z, 3)],
    }


def add_internal_notes(source_roots: dict[str, Path | None], urdf_path: Path) -> None:
    readme = bpy.data.texts.get("README_INMOOV_REFERENCE") or bpy.data.texts.new("README_INMOOV_REFERENCE")
    readme.clear()
    readme.write(
        "INMOOV COMPLETE ENGINEERING REFERENCE — MILLIMETER SCENE + RIG\n"
        "===============================================\n\n"
        "Scene units: 1 Blender Unit = 1 millimeter.\n"
        "Primary upper-body assembly: generated from the maintained Sentience Robotics canonical InMoov Xacro and its DAE meshes.\n"
        f"Selected URDF: {urdf_path}\n\n"
        "IMPORTANT MEASUREMENT NOTES\n"
        "- URDF_ASSEMBLY_SOURCE objects were assembled in native SI metres from the canonical current Xacro, validated, then baked uniformly to true millimetre coordinates.\n"
        "- HARDWARE_REFERENCE_UNPLACED objects come from community reverse-engineered CAD/STL sources.\n"
        "  Their dimensions can be inspected, but their displayed shelf position is NOT an installed position.\n"
        "- Do not infer fit-critical servo clearances from an unplaced hardware reference.\n"
        "- InMoov has multiple historical revisions; compare any modified printable part against the exact revision you intend to build.\n\n"
        "LICENSE / ATTRIBUTION\n"
        "Original InMoov design: Gael Langevin — https://inmoov.fr/\n"
        "InMoov-derived 3D assets are distributed under CC BY-NC terms by the cited repositories.\n"
        "Sentience Robotics repository code may additionally be GPL-3.0; see its LICENSE.\n"
        "Community SolidWorks reverse-engineering repository is a separate source; see its LICENSE.\n"
    )
    prov = bpy.data.texts.get("SOURCE_PROVENANCE_JSON") or bpy.data.texts.new("SOURCE_PROVENANCE_JSON")
    prov.clear()
    prov.write(json.dumps({k: str(v) if v else None for k, v in source_roots.items()}, indent=2, ensure_ascii=False))



def write_report_safely() -> Path:
    """Write exactly one consolidated JSON report for this build."""
    REPORT["output"]["blend"] = OUTPUT_BLEND.name
    REPORT["output"]["json"] = REPORT_JSON.name
    payload = json.dumps(REPORT, indent=2, ensure_ascii=False)

    try:
        REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
        REPORT_JSON.write_text(payload, encoding="utf-8")
        return REPORT_JSON
    except Exception as exc:
        # Do not create multiple fallback JSON files. Surface the error instead.
        log(f"WARNING: Could not write consolidated build report: {exc!r}")
        raise



def save_report_and_blend() -> None:
    bounds = compute_bounds_mm()
    REPORT["assembly_bounds"] = bounds
    if bounds:
        dims = bounds["dimensions_mm"]
        log(f"Assembly AABB dimensions: {dims[0]:.1f} x {dims[1]:.1f} x {dims[2]:.1f} mm")
        max_dim = max(dims)
        if max_dim < 500 or max_dim > 5000:
            REPORT["warnings"].append(
                f"Assembly size ({dims}) is outside the expected broad human-scale range; verify source mesh units before fit-critical use."
            )
    report_path = write_report_safely()
    bpy.context.scene["INMOOV_BUILD_REPORT"] = json.dumps(REPORT, ensure_ascii=False)

    # ROOT has already been resolved away from protected drive roots. Make it explicit here too.
    OUTPUT_BLEND.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT_BLEND), compress=True)
    log(f"Saved: {OUTPUT_BLEND}")
    log(f"Report: {report_path}")

# ---------------------------------------------------------------------------
# v1.8 INTEGRATED STAGE
# The functions below are folded in from the former v1.7 upgrade script.
# Unlike v1.7, this file does not require a prebuilt .blend: main() calls these
# functions immediately after the canonical v1.6 body has been generated.
# ---------------------------------------------------------------------------


def world_bounds(objects) -> tuple[Vector, Vector] | None:
    mins = Vector((float("inf"), float("inf"), float("inf")))
    maxs = Vector((float("-inf"), float("-inf"), float("-inf")))
    found = False
    for obj in objects:
        if not obj or obj.type != "MESH" or obj.hide_get():
            continue
        found = True
        for c in obj.bound_box:
            p = obj.matrix_world @ Vector(c)
            mins.x = min(mins.x, p.x)
            mins.y = min(mins.y, p.y)
            mins.z = min(mins.z, p.z)
            maxs.x = max(maxs.x, p.x)
            maxs.y = max(maxs.y, p.y)
            maxs.z = max(maxs.z, p.z)
    return (mins, maxs) if found else None


def object_world_dims(obj: bpy.types.Object) -> Vector:
    b = world_bounds([obj])
    return (b[1] - b[0]) if b else Vector((0, 0, 0))


def body_meshes():
    return [
        o for o in bpy.data.objects
        if o.type == "MESH" and o.name.startswith("MESH::") and not o.hide_get()
    ]


def get_link_objects() -> dict[str, bpy.types.Object]:
    result = {}
    for obj in bpy.data.objects:
        if obj.type != "EMPTY":
            continue
        name = obj.get("urdf_link_name")
        if name:
            result[str(name)] = obj
        elif obj.name.startswith("LINK::"):
            result[obj.name[len("LINK::"):]] = obj
    return result


def find_root_link(link_objs: dict[str, bpy.types.Object]) -> tuple[str, bpy.types.Object]:
    for name, obj in link_objs.items():
        if bool(obj.get("urdf_root")):
            return name, obj
    # Fall back to the only LINK object without a LINK parent.
    roots = []
    for name, obj in link_objs.items():
        if obj.parent not in link_objs.values():
            roots.append((name, obj))
    if roots:
        roots.sort(key=lambda item: (0 if "base" in item[0].lower() else 1, item[0]))
        return roots[0]
    raise RuntimeError("Could not identify the URDF root LINK:: object")


def get_collection_meshes(name: str):
    col = bpy.data.collections.get(name)
    if not col:
        return []
    return [o for o in col.all_objects if o.type == "MESH" and not o.hide_get()]


def preserve_world_unparent(obj: bpy.types.Object) -> Matrix:
    mw = obj.matrix_world.copy()
    obj.parent = None
    obj.matrix_world = mw
    return mw


def parent_object_to_bone_keep_world(obj: bpy.types.Object, arm_obj: bpy.types.Object, bone_name: str) -> None:
    mw = obj.matrix_world.copy()
    obj.parent = arm_obj
    obj.parent_type = "BONE"
    obj.parent_bone = bone_name
    # Reassign after parent change so the rest pose remains visually identical.
    obj.matrix_world = mw


def find_solidworks_root() -> Path:
    # v1.6 embeds this text datablock.
    text = bpy.data.texts.get("SOURCE_PROVENANCE_JSON")
    if text:
        try:
            data = json.loads(text.as_string())
            candidate = data.get("community_solidworks")
            if candidate:
                p = Path(candidate)
                if p.exists():
                    REPORT["leg_source_root"] = str(p)
                    return p
        except Exception as exc:
            REPORT["warnings"].append(f"Could not parse SOURCE_PROVENANCE_JSON: {exc!r}")

    override = os.environ.get("INMOOV_SOLIDWORKS_ROOT", "").strip()
    if override:
        p = Path(override).expanduser().resolve()
        if p.exists():
            REPORT["leg_source_root"] = str(p)
            return p

    # Search the builder cache near the .blend. Limit depth by checking common patterns first.
    candidates = [
        ROOT / "_inmoov_cache" / "sources" / "community_solidworks-main" / "inmoov-solidworks-main",
        ROOT.parent / "_inmoov_cache" / "sources" / "community_solidworks-main" / "inmoov-solidworks-main",
    ]
    for p in candidates:
        if p.exists():
            REPORT["leg_source_root"] = str(p)
            return p

    # Last resort: search a few parents for the exact repository folder.
    for base in [ROOT, ROOT.parent, ROOT.parent.parent if ROOT.parent.parent != ROOT.parent else ROOT.parent]:
        if not base.exists():
            continue
        try:
            for p in base.glob("**/inmoov-solidworks-main"):
                if p.is_dir():
                    REPORT["leg_source_root"] = str(p)
                    return p
        except Exception:
            pass

    raise RuntimeError(
        "Could not find the cached wei1224hf/inmoov-solidworks repository. "
        "Keep the v1.6 _inmoov_cache folder beside/above this .blend, or set "
        "INMOOV_SOLIDWORKS_ROOT to the extracted repository folder."
    )


def find_named_stl(root: Path, preferred_names: list[str], fallback_contains: list[str]) -> Path:
    # Exact Unicode basename match first.
    for name in preferred_names:
        hits = list(root.rglob(name))
        if hits:
            return hits[0]

    stls = list(root.rglob("*.stl"))
    for token in fallback_contains:
        token_l = token.lower()
        hits = [p for p in stls if token_l in p.stem.lower()]
        if hits:
            # Prefer shorter names; these are usually aggregate parts rather than variants.
            hits.sort(key=lambda p: (len(p.name), p.name))
            return hits[0]
    raise FileNotFoundError(f"No STL found for {preferred_names!r} / {fallback_contains!r}")


def remove_root_stand_visuals(link_objs: dict[str, bpy.types.Object]) -> None:
    root_name, root = find_root_link(link_objs)
    candidates = [
        o for o in bpy.data.objects
        if o.type == "MESH"
        and o.name.startswith(f"MESH::{root_name}::")
        and o.parent == root
    ]

    # Some import paths may preserve the name but alter parenting; include name match.
    if not candidates:
        candidates = [
            o for o in bpy.data.objects
            if o.type == "MESH" and o.name.startswith(f"MESH::{root_name}::")
        ]

    if not candidates:
        REPORT["warnings"].append(
            f"No direct visual meshes found on root link {root_name}; stand may already be absent."
        )
        return

    for obj in candidates:
        REPORT["stand_removed"].append(obj.name)
        bpy.data.objects.remove(obj, do_unlink=True)

    log(f"Removed {len(candidates)} stand/root visual object(s) from {root_name}")


def import_stl(path: Path) -> bpy.types.Object:
    before = set(bpy.data.objects)
    if hasattr(bpy.ops.wm, "stl_import"):
        bpy.ops.wm.stl_import(filepath=str(path))
    else:
        bpy.ops.import_mesh.stl(filepath=str(path))
    imported = [o for o in (set(bpy.data.objects) - before) if o.type == "MESH"]
    if not imported:
        raise RuntimeError(f"Import created no mesh object: {path}")
    if len(imported) == 1:
        return imported[0]

    # Join a multi-object STL import into one rigid reference object.
    bpy.ops.object.select_all(action="DESELECT")
    for o in imported:
        o.select_set(True)
    bpy.context.view_layer.objects.active = imported[0]
    bpy.ops.object.join()
    return bpy.context.view_layer.objects.active


def normalized_vertices_numpy(obj: bpy.types.Object):
    import numpy as np
    if not obj.data.vertices:
        raise RuntimeError(f"{obj.name} has no vertices")
    return np.array([[v.co.x, v.co.y, v.co.z] for v in obj.data.vertices], dtype=float)




def normalize_long_segment(obj: bpy.types.Object, segment_kind: str) -> dict:
    """Translate a native Z-up thigh/calf; never rotate or reshape it."""
    import numpy as np

    pts = normalized_vertices_numpy(obj)
    raw_min = pts.min(axis=0)
    raw_max = pts.max(axis=0)
    raw_dims = raw_max - raw_min

    if int(np.argmax(raw_dims)) != 2:
        raise RuntimeError(
            f"{segment_kind} STL is not native Z-up as expected: "
            f"bbox={raw_dims.tolist()}"
        )

    z = pts[:, 2]
    top = pts[z >= np.quantile(z, 0.92)]
    bottom = pts[z <= np.quantile(z, 0.08)]

    top_c = top.mean(axis=0) if len(top) else (raw_min + raw_max) / 2.0
    bottom_c = bottom.mean(axis=0) if len(bottom) else (raw_min + raw_max) / 2.0
    top_c[2] = raw_max[2]
    bottom_c[2] = raw_min[2]

    local = pts - top_c
    bottom_local = bottom_c - top_c

    for v, p in zip(obj.data.vertices, local):
        v.co = (float(p[0]), float(p[1]), float(p[2]))
    obj.data.update()
    obj.matrix_world = Matrix.Identity(4)

    mins = local.min(axis=0)
    maxs = local.max(axis=0)
    dims = maxs - mins

    return {
        "length": float(dims[2]),
        "width": float(dims[0]),
        "depth": float(dims[1]),
        "raw_bbox_dimensions_mm": [float(x) for x in raw_dims],
        "raw_bbox_min_mm": [float(x) for x in raw_min],
        "raw_bbox_max_mm": [float(x) for x in raw_max],
        "source_axes": "native X=lateral, Y=front/back, Z=vertical",
        "top_connector_local_mm": [0.0, 0.0, 0.0],
        "bottom_connector_local_mm": [
            float(bottom_local[0]),
            float(bottom_local[1]),
            float(bottom_local[2]),
        ],
        "local_bbox_min_mm": [float(x) for x in mins],
        "local_bbox_max_mm": [float(x) for x in maxs],
        "assembly_method": "native CAD axes; translation only",
        "arbitrary_rotation_used": False,
    }








def normalize_foot(obj: bpy.types.Object) -> dict:
    """Translate the native upright foot using its actual ankle mounting cap.

    Previous versions averaged the upper ~12% of the entire foot shell. On this
    source mesh that includes a large sloped shell region and shifts the ankle
    origin roughly 30 mm in Y.

    v3.2 identifies only the highest ~7% / ~8 mm mounting-cap region:
      * X/Y = centroid of the top mounting cap
      * Z   = exact top surface

    v3.4 additionally measures the foot's actual toe<->heel heading and
    rotates it about the ankle's vertical axis to square it with world -Y
    if that heading is skewed -- see the "yaw correction" block below.
    """
    import numpy as np

    pts = normalized_vertices_numpy(obj)
    raw_min = pts.min(axis=0)
    raw_max = pts.max(axis=0)
    raw_dims = raw_max - raw_min

    if int(np.argmax(raw_dims)) != 1:
        raise RuntimeError(
            f"foot STL is not native Y-long/Z-up as expected: "
            f"bbox={raw_dims.tolist()}. Refusing to guess orientation."
        )

    # The upper ankle interface is a small raised cap/ring at the absolute top
    # of the aggregate foot. Limit the sample to that cap instead of the broad
    # upper shell.
    cap_depth = min(10.0, max(6.0, float(raw_dims[2]) * 0.07))
    z_floor = float(raw_max[2]) - cap_depth
    mount_group = pts[pts[:, 2] >= z_floor]

    if len(mount_group) < 24:
        # Conservative fallback: top 1% of vertices.
        z_cut = np.quantile(pts[:, 2], 0.99)
        mount_group = pts[pts[:, 2] >= z_cut]

    ankle = mount_group.mean(axis=0) if len(mount_group) else (raw_min + raw_max) / 2.0
    ankle[2] = raw_max[2]

    # v3.4 FIX ("feet rotated incorrectly"): the check above only confirms Y
    # is the *longest* raw axis -- it says nothing about whether the
    # footprint is skewed within the XY plane. A yaw baked in by whatever
    # exported this particular STL can survive that check completely (a
    # mesh rotated 15-30 degrees is still clearly "Y-long") while still
    # visibly not pointing straight down the leg's forward axis, which is
    # exactly what the front-view renders showed. Rather than assume the
    # raw axes are already square, measure the actual toe<->heel heading
    # from the shape itself (same extreme-Y-band technique used just below
    # for the toe edge) and rotate the whole foot about the ankle's
    # vertical axis so that heading lines up with world -Y -- the same
    # "toward the toes" convention used for the thigh, calf and toe cap
    # everywhere else in this file.
    rel = pts - ankle
    y0 = rel[:, 1]
    yaw_band = max(8.0, float(raw_dims[1]) * 0.05)
    toe_band = rel[y0 <= y0.min() + yaw_band]
    heel_band = rel[y0 >= y0.max() - yaw_band]
    yaw_correction_deg = 0.0
    if len(toe_band) >= 4 and len(heel_band) >= 4:
        toe_c = toe_band[:, :2].mean(axis=0)
        heel_c = heel_band[:, :2].mean(axis=0)
        heading = heel_c - toe_c  # should already point toward +Y (0,1)
        yaw = math.atan2(float(heading[0]), float(heading[1]))
        if abs(yaw) > math.radians(1.0):
            c, s = math.cos(-yaw), math.sin(-yaw)
            x0, yv = pts[:, 0], pts[:, 1]
            pts = np.column_stack((x0 * c - yv * s, x0 * s + yv * c, pts[:, 2]))
            ax, ay = ankle[0] * c - ankle[1] * s, ankle[0] * s + ankle[1] * c
            ankle = np.array([ax, ay, ankle[2]])
            yaw_correction_deg = math.degrees(-yaw)

    local = pts - ankle

    # Native source points toward decreasing Y. Use a narrow front slice to
    # locate the actual toe-edge lateral center rather than assuming ankle X.
    y = local[:, 1]
    front_band = max(8.0, float(raw_dims[1]) * 0.05)
    front_group = local[y <= y.min() + front_band]
    if len(front_group):
        toe_edge_center_x = float(front_group[:, 0].mean())
    else:
        toe_edge_center_x = float((local[:, 0].min() + local[:, 0].max()) * 0.5)

    for v, p in zip(obj.data.vertices, local):
        v.co = (float(p[0]), float(p[1]), float(p[2]))
    obj.data.update()
    obj.matrix_world = Matrix.Identity(4)

    mins = local.min(axis=0)
    maxs = local.max(axis=0)
    dims = maxs - mins

    return {
        "length": float(dims[1]),
        "width": float(dims[0]),
        "height": float(dims[2]),
        "raw_bbox_dimensions_mm": [float(x) for x in raw_dims],
        "raw_bbox_min_mm": [float(x) for x in raw_min],
        "raw_bbox_max_mm": [float(x) for x in raw_max],
        "source_axes": "native X=lateral, Y=foot length, Z=vertical",
        "ankle_connector_local_mm": [0.0, 0.0, 0.0],
        "ankle_mount_source_mm": [
            float(ankle[0]), float(ankle[1]), float(ankle[2])
        ],
        "ankle_mount_cap_depth_mm": float(cap_depth),
        "ankle_mount_sample_vertices": int(len(mount_group)),
        "sole_z_local_mm": float(mins[2]),
        "toe_y_local_mm": float(mins[1]),
        "heel_y_local_mm": float(maxs[1]),
        "toe_edge_center_x_local_mm": toe_edge_center_x,
        "assembly_method": "native CAD axes; top mounting-cap ankle origin",
        "yaw_correction_deg_applied": float(yaw_correction_deg),
        "arbitrary_rotation_used": False,
        "native_sole_preserved": True,
    }








def rotate_leg_local_z(obj: bpy.types.Object, info: dict, degrees: float) -> dict:
    """Rotate an already-normalized leg segment around local Z only.

    This is the deliberately narrow v3.2 fix: v3.2 scale and longitudinal
    alignment stay untouched. Only the part's facing direction changes.

    Connector X/Y metadata is rotated with the mesh so knee/ankle continuity is
    preserved exactly.
    """
    angle = math.radians(float(degrees))
    c = math.cos(angle)
    s = math.sin(angle)

    def rot_xy(x, y):
        return (c * x - s * y, s * x + c * y)

    for v in obj.data.vertices:
        x, y = rot_xy(v.co.x, v.co.y)
        v.co.x = x
        v.co.y = y
    obj.data.update()

    if "bottom_connector_local_mm" in info:
        x, y, z = info["bottom_connector_local_mm"]
        x2, y2 = rot_xy(float(x), float(y))
        info["bottom_connector_local_mm"] = [x2, y2, float(z)]

    # Useful foot metadata, if present.
    if "ankle_connector_local_mm" in info:
        x, y, z = info["ankle_connector_local_mm"]
        x2, y2 = rot_xy(float(x), float(y))
        info["ankle_connector_local_mm"] = [x2, y2, float(z)]

    info["orientation_correction_z_deg"] = float(degrees)
    return info




def normalize_toe(obj: bpy.types.Object) -> dict:
    """Prepare the toe cap for attachment to the native right-foot frame.

    Preferred source is 右脚趾.stl, whose native axes are:
      X = lateral width
      Y = fore/aft length
      Z = vertical

    The older generic 脚趾.stl has X/Y swapped; v3.2 only corrects that fallback
    with one exact 90-degree axis swap. No heuristic/PCA orientation is used.
    """
    import numpy as np

    pts = normalized_vertices_numpy(obj)
    raw_min = pts.min(axis=0)
    raw_max = pts.max(axis=0)
    raw_dims = raw_max - raw_min

    axis_mode = "native_right_toe_y_long"

    if int(np.argmax(raw_dims)) == 1:
        oriented = pts.copy()
    elif int(np.argmax(raw_dims)) == 0:
        # Generic fallback: rotate +90 degrees about Z so old X-length becomes Y.
        # x'=-y, y'=x preserves a proper rigid rotation.
        oriented = np.column_stack((-pts[:, 1], pts[:, 0], pts[:, 2]))
        axis_mode = "generic_toe_rotated_90deg_fallback"
    else:
        raise RuntimeError(
            f"toe STL has unexpected axes: bbox={raw_dims.tolist()}. "
            "Refusing to infer a non-orthogonal orientation."
        )

    # v3.6 FIX ("toes still rotated"): v3.4 fixed this same class of bug for
    # the foot (Y being the longest raw axis only proves axis identity, not
    # that the footprint is square in the XY plane) but never applied the
    # same check to the toe cap, which is a separate mesh with its own
    # potentially-skewed native orientation. Measure the toe's actual
    # tip<->rear heading here too and rotate about its own vertical (Z) axis
    # so that heading lines up with world Y, matching the foot/thigh/calf
    # convention used everywhere else.
    y0 = oriented[:, 1]
    yaw_band = max(6.0, float(raw_dims[1]) * 0.05)
    tip_band = oriented[y0 <= y0.min() + yaw_band]
    rear_band = oriented[y0 >= y0.max() - yaw_band]
    toe_yaw_correction_deg = 0.0
    if len(tip_band) >= 4 and len(rear_band) >= 4:
        tip_c = tip_band[:, :2].mean(axis=0)
        rear_c = rear_band[:, :2].mean(axis=0)
        heading = rear_c - tip_c  # should already point toward +Y (0,1)
        yaw = math.atan2(float(heading[0]), float(heading[1]))
        if abs(yaw) > math.radians(1.0):
            c, s = math.cos(-yaw), math.sin(-yaw)
            xo, yo = oriented[:, 0], oriented[:, 1]
            oriented = np.column_stack((xo * c - yo * s, xo * s + yo * c, oriented[:, 2]))
            toe_yaw_correction_deg = math.degrees(-yaw)

    mn = oriented.min(axis=0)
    mx = oriented.max(axis=0)

    # Rear edge = local Y 0. Toe extends toward the same native -Y direction
    # as the right foot. Sole remains local Z 0.
    local = oriented.copy()
    local[:, 0] -= (mn[0] + mx[0]) * 0.5
    local[:, 1] -= mx[1]
    local[:, 2] -= mn[2]

    for v, p in zip(obj.data.vertices, local):
        v.co = (float(p[0]), float(p[1]), float(p[2]))
    obj.data.update()
    obj.matrix_world = Matrix.Identity(4)

    mins = local.min(axis=0)
    maxs = local.max(axis=0)
    dims = maxs - mins

    return {
        "length": float(dims[1]),
        "width": float(dims[0]),
        "height": float(dims[2]),
        "raw_bbox_dimensions_mm": [float(x) for x in raw_dims],
        "rear_edge_local_y_mm": 0.0,
        "toe_tip_local_y_mm": float(mins[1]),
        "sole_z_local_mm": 0.0,
        "axis_mode": axis_mode,
        "yaw_correction_deg_applied": float(toe_yaw_correction_deg),
        "assembly_method": "foot-aligned orthogonal CAD axes; rear-edge attachment",
    }



def duplicate_mirrored(obj: bpy.types.Object, name: str) -> bpy.types.Object:
    """Create a true mirrored mesh copy and recalculate face normals."""
    import bmesh

    dup = obj.copy()
    dup.data = obj.data.copy()
    dup.name = name
    for col in obj.users_collection:
        col.objects.link(dup)
        break

    # Reflect actual vertex coordinates instead of leaving a negative object scale.
    for v in dup.data.vertices:
        v.co.x = -v.co.x
    dup.data.update()

    # Reflection reverses winding; restore outward normals.
    bm = bmesh.new()
    bm.from_mesh(dup.data)
    try:
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(dup.data)
    finally:
        bm.free()
    dup.data.update()
    dup.matrix_world = Matrix.Identity(4)
    return dup



def torso_bounds() -> tuple[Vector, Vector]:
    torso = get_collection_meshes("10_TORSO")
    b = world_bounds(torso)
    if b:
        return b
    b = world_bounds(body_meshes())
    if not b:
        raise RuntimeError("Could not determine body bounds after stand removal")
    REPORT["warnings"].append("10_TORSO collection had no meshes; leg attachment used whole-body bounds")
    return b


def torso_mount_reference() -> Vector:
    """Locate the actual low-stomach mounting band instead of guessing from
    the whole-torso bounding box.

    v3.2 used the *center of the entire torso bounding box* for both the
    front/back (Y) and left/right (X) hip position. That box includes the
    chest, shoulders and back, which are not laterally/front-back symmetric
    the same way the low-stomach disc is, so its center does not sit above
    where the legs actually bolt on -- this is the "hips don't align with
    the mounting position" symptom. InMoov's low-stomach plate is a distinct
    disc at the very bottom of the torso (see inmoov.fr/low-stomach/: leg
    supports mount "screwed from the sides, right under low stomach"), so
    the fix samples only the lowest thin slice of TORSO geometry -- the same
    "sample the actual feature, not the whole shell" approach already used
    for the thigh's top pivot and the foot's ankle cap -- and uses that
    slice's own centroid as the hip mounting reference.
    """
    import numpy as np

    torso_objs = get_collection_meshes("10_TORSO") or body_meshes()
    if not torso_objs:
        raise RuntimeError("No torso geometry available to locate the hip mounting band")

    pts = []
    for obj in torso_objs:
        mat = obj.matrix_world
        for v in obj.data.vertices:
            w = mat @ v.co
            pts.append((w.x, w.y, w.z))
    if not pts:
        raise RuntimeError("Torso meshes had no vertices to locate the hip mounting band")

    arr = np.array(pts, dtype=float)
    z = arr[:, 2]
    z_min = float(z.min())
    z_span = float(z.max() - z_min)
    band = max(10.0, z_span * 0.03)
    low = arr[z <= z_min + band]
    if len(low) < 8:
        low = arr[z <= np.quantile(z, 0.02)]

    centroid = low.mean(axis=0)
    return Vector((float(centroid[0]), float(centroid[1]), z_min))


def make_leg_collection() -> bpy.types.Collection:
    col = bpy.data.collections.get("20_STANDING_LEGS")
    if col is None:
        col = bpy.data.collections.new("20_STANDING_LEGS")
        bpy.context.scene.collection.children.link(col)
    return col


def move_to_collection(obj, col):
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    col.objects.link(obj)





def rotate_object_about_world_z(
    obj: bpy.types.Object,
    pivot: Vector,
    degrees: float,
) -> None:
    """Rigidly rotate an object's world transform around Z through `pivot`."""
    angle = math.radians(float(degrees))
    rot = Matrix.Rotation(angle, 4, "Z")
    about = Matrix.Translation(pivot) @ rot @ Matrix.Translation(-pivot)
    obj.matrix_world = about @ obj.matrix_world


def import_and_fit_standing_legs(solidworks_root: Path) -> dict:
    """Build the complete standing legs with corrected anatomical side assignment.

    Preserves native part orientation (no source mesh is arbitrarily rotated)
    while fixing:
      1) the complete left/right assemblies being on opposite sides,
      2) the missing separate toe caps,
      3) toe/foot pivot metadata for the animation rig,
      4) (v3.3) hip spacing that is too tight for the actual thigh shell,
      5) (v3.3) a hip mounting reference taken from the whole torso bbox
         instead of the actual low-stomach mounting band.
    """
    thigh_path = find_named_stl(
        solidworks_root, ["大腿右.stl"], ["大腿右", "thigh"]
    )
    calf_path = find_named_stl(
        solidworks_root, ["右小腿.stl"], ["右小腿", "calf", "shin"]
    )
    foot_path = find_named_stl(
        solidworks_root, ["右脚.stl"], ["右脚", "foot"]
    )
    toe_path = find_named_stl(
        solidworks_root, ["右脚趾.stl", "脚趾.stl"], ["右脚趾", "脚趾", "toe"]
    )

    REPORT["leg_source_files"] = {
        "right_thigh": str(thigh_path),
        "right_calf": str(calf_path),
        "right_foot": str(foot_path),
        "toe_cap": str(toe_path),
    }

    leg_col = make_leg_collection()

    r_thigh = import_stl(thigh_path)
    r_calf = import_stl(calf_path)
    r_foot = import_stl(foot_path)
    r_toe = import_stl(toe_path)

    # v3.7 FIX ("wrong side below the knee" / toes point outward / shins bow
    # away from each other): confirmed against real InMoov reference photos.
    # The calf/foot/toe files are named with the Chinese word for "right"
    # (\u53f3), but the raw geometry itself is chirality-flipped -- it
    # actually MODELS a left-side part despite the filename. This is
    # different from (and was hiding behind) the R/L *placement* bug fixed
    # in v3.2: placement was always internally self-consistent (see
    # alignment.side_consistency_check), but a self-consistent placement of
    # a mislabeled/wrong-handed shape still comes out backwards on both
    # legs at once -- which is exactly the "both big toes point outward,
    # both shins bow the wrong way" symptom, rather than a simple left<->
    # right swap (which would instead show each leg individually normal,
    # just standing under the other hip).
    #
    # X is this file's own lateral axis (checked below), so mirroring the
    # raw import through X here -- before any other processing -- flips its
    # chirality to match its filename. Everything downstream (normalization,
    # duplicate_mirrored, offset math, yaw correction) operates purely on
    # whatever the mesh data says and needs no other changes. Thigh is left
    # untouched: no report or photo comparison has indicated it's wrong, and
    # its shape is close enough to rotationally symmetric that a chirality
    # error there wouldn't be visually obvious either way -- so this is not
    # evidence it's fine, just that there's no basis yet to change it.
    for _obj in (r_calf, r_foot, r_toe):
        for v in _obj.data.vertices:
            v.co.x = -v.co.x
        _obj.data.update()

    r_thigh.name = "LEG_REF::R::THIGH"
    r_calf.name = "LEG_REF::R::CALF"
    r_foot.name = "LEG_REF::R::FOOT"
    r_toe.name = "LEG_REF::R::TOE"

    for obj in (r_thigh, r_calf, r_foot, r_toe):
        obj["provenance"] = "COMMUNITY_REVERSE_ENGINEERED_LEG_REFERENCE"
        obj["placement_warning"] = (
            "Native source orientation preserved. Standing-leg articulation is "
            "synthetic for Blender animation/reference."
        )
        move_to_collection(obj, leg_col)

    thigh_info = normalize_long_segment(r_thigh, "thigh")
    calf_info = normalize_long_segment(r_calf, "calf")
    foot_info = normalize_foot(r_foot)
    toe_info = normalize_toe(r_toe)

    # Correct only an unmistakable mm/metre import mismatch.
    dims = [
        thigh_info["length"], calf_info["length"],
        foot_info["length"], toe_info["length"]
    ]
    median = sorted(dims)[len(dims)//2]
    correction = 1.0
    if median < 2.0:
        correction = 1000.0
    elif median > 5000.0:
        correction = 0.001

    if correction != 1.0:
        log(f"Applying obvious leg STL unit correction {correction:g}x")
        for obj in (r_thigh, r_calf, r_foot, r_toe):
            for v in obj.data.vertices:
                v.co *= correction
            obj.data.update()

        thigh_info = normalize_long_segment(r_thigh, "thigh")
        calf_info = normalize_long_segment(r_calf, "calf")
        foot_info = normalize_foot(r_foot)
        toe_info = normalize_toe(r_toe)

    if not (300.0 <= thigh_info["length"] <= 600.0):
        raise RuntimeError(
            f"Community thigh STL has implausible length {thigh_info['length']:.1f} mm"
        )
    if not (250.0 <= calf_info["length"] <= 500.0):
        raise RuntimeError(
            f"Community calf STL has implausible length {calf_info['length']:.1f} mm"
        )
    if not (160.0 <= foot_info["length"] <= 330.0):
        raise RuntimeError(
            f"Community foot STL has implausible length {foot_info['length']:.1f} mm"
        )
    if not (60.0 <= toe_info["length"] <= 180.0):
        raise RuntimeError(
            f"Community toe STL has implausible length {toe_info['length']:.1f} mm"
        )

    # One deliberate mirror creates the opposite anatomical side.
    l_thigh = duplicate_mirrored(r_thigh, "LEG_REF::L::THIGH")
    l_calf = duplicate_mirrored(r_calf, "LEG_REF::L::CALF")
    l_foot = duplicate_mirrored(r_foot, "LEG_REF::L::FOOT")
    l_toe = duplicate_mirrored(r_toe, "LEG_REF::L::TOE")

    for obj in (l_thigh, l_calf, l_foot, l_toe):
        obj["provenance"] = "COMMUNITY_REVERSE_ENGINEERED_LEG_REFERENCE_MIRRORED"
        obj["placement_warning"] = (
            "Mirrored opposite-side reference; native orientation otherwise preserved."
        )
        move_to_collection(obj, leg_col)

    tmin,tmax = torso_bounds()
    torso_width=max(tmax.x-tmin.x,1.0)

    # v3.3 FIX ("hips don't align with mounting position"): use the actual
    # low-stomach mounting band, not the whole-torso bbox center, for both
    # the front/back (Y) and left/right (X) hip reference. See
    # torso_mount_reference() for why.
    mount_ref = torso_mount_reference()
    hip_x_center = mount_ref.x
    hip_y = mount_ref.y
    hip_z = mount_ref.z + HIP_MOUNT_Z_CLEARANCE_MM

    # v3.3 FIX ("legs too close together and clipping"): start from the same
    # geometry-based guess as before, but treat it only as a starting point.
    # See the long comment on LEG_HIP_SPACING_FALLBACK_MIN_MM near the top of
    # this file for why a pure width-based number under-measures the real
    # clearance this shell needs. The guess is verified below, once both
    # thighs are actually placed, against the *measured* gap between them.
    geometry_spacing = float(thigh_info["width"]) + LEG_SIDE_CLEARANCE_MM
    torso_spacing = torso_width * 0.42
    hip_spacing = max(LEG_HIP_SPACING_FALLBACK_MIN_MM, geometry_spacing, torso_spacing)
    hip_spacing = min(LEG_HIP_SPACING_MAX_MM, hip_spacing)

    r_thigh_bottom=Vector(thigh_info["bottom_connector_local_mm"])
    r_calf_bottom=Vector(calf_info["bottom_connector_local_mm"])
    l_thigh_bottom=Vector((-r_thigh_bottom.x,r_thigh_bottom.y,r_thigh_bottom.z))
    l_calf_bottom=Vector((-r_calf_bottom.x,r_calf_bottom.y,r_calf_bottom.z))

    assembled={}

    def place_side(side,sign,thigh,calf,foot,toe,thigh_bottom,calf_bottom,spacing):
        hip=Vector((
            hip_x_center+sign*spacing/2.0,
            hip_y,
            hip_z,
        ))
        thigh.location=hip

        knee=hip+thigh_bottom
        calf.location=knee

        ankle=knee+calf_bottom
        foot.location=ankle

        # Separate toe cap: rear edge inserts slightly into the native foot's
        # forward (low-Y) edge. Sole planes are shared.
        toe_attach_y = foot_info["toe_y_local_mm"] + LEG_TOE_OVERLAP_MM
        toe_x_offset = float(foot_info["toe_edge_center_x_local_mm"])
        if side == "L":
            toe_x_offset *= -1.0

        toe_joint = Vector((
            foot.location.x + toe_x_offset,
            foot.location.y + toe_attach_y,
            foot.location.z + foot_info["sole_z_local_mm"],
        ))
        toe.location = toe_joint
        toe_tip = toe_joint + Vector((0.0, toe_info["toe_tip_local_y_mm"], 0.0))

        return {
            "thigh":thigh,
            "calf":calf,
            "foot":foot,
            "toe":toe,
            "hip":hip,
            "knee":knee,
            "ankle":ankle,
            "toe_joint":toe_joint,
            "toe_tip":toe_tip,
            "foot_len":foot_info["length"],
            "toe_len":toe_info["length"],
        }

    # IMPORTANT v3.2 side correction (kept in v3.3):
    # The user's verified front view shows the entire side groups were reversed
    # in an earlier iteration. Swap the complete assemblies spatially without
    # changing any component orientation:
    #
    #   source RIGHT group -> +X
    #   mirrored LEFT group -> -X
    side_specs = (
        ("R",+1.0,r_thigh,r_calf,r_foot,r_toe,r_thigh_bottom,r_calf_bottom),
        ("L",-1.0,l_thigh,l_calf,l_foot,l_toe,l_thigh_bottom,l_calf_bottom),
    )
    for side,sign,thigh,calf,foot,toe,thigh_bottom,calf_bottom in side_specs:
        assembled[side]=place_side(
            side,sign,thigh,calf,foot,toe,thigh_bottom,calf_bottom,hip_spacing
        )

    bpy.context.view_layer.update()

    def measure_thigh_gap():
        rtb = world_bounds([r_thigh])
        ltb = world_bounds([l_thigh])
        if not (rtb and ltb):
            return None
        # right thigh is +X; left thigh is -X
        return float(rtb[0].x - ltb[1].x)

    # v3.3 FIX: actually enforce a minimum thigh clearance instead of only
    # reporting the AABB overlap and continuing anyway (that "informational
    # only" behavior is exactly what produced the 56.82 mm overlap this build
    # shipped with -- see README_FIRST.md). Widening hip_spacing shifts each
    # complete, already-placed leg chain outward by one rigid translation, so
    # it can be applied after the fact without redoing the connector math.
    initial_hip_spacing = hip_spacing
    thigh_aabb_gap = measure_thigh_gap()
    correction_applied_mm = 0.0
    if thigh_aabb_gap is not None and thigh_aabb_gap < LEG_HIP_MIN_THIGH_CLEARANCE_MM:
        shortfall = LEG_HIP_MIN_THIGH_CLEARANCE_MM - thigh_aabb_gap
        new_hip_spacing = min(LEG_HIP_SPACING_MAX_MM, hip_spacing + shortfall)
        delta = new_hip_spacing - hip_spacing
        if delta > 1e-6:
            for side_key, sign in (("R", +1.0), ("L", -1.0)):
                shift = Vector((sign * delta / 2.0, 0.0, 0.0))
                for key in ("thigh", "calf", "foot", "toe"):
                    assembled[side_key][key].location += shift
                for key in ("hip", "knee", "ankle", "toe_joint", "toe_tip"):
                    assembled[side_key][key] += shift
            correction_applied_mm = delta
            hip_spacing = new_hip_spacing
            bpy.context.view_layer.update()
            thigh_aabb_gap = measure_thigh_gap()

    REPORT.setdefault("alignment", {})["hip_spacing_basis"] = {
        "native_thigh_width_mm": float(thigh_info["width"]),
        "shell_clearance_requested_mm": LEG_SIDE_CLEARANCE_MM,
        "geometry_spacing_mm": geometry_spacing,
        "torso_spacing_candidate_mm": torso_spacing,
        "initial_guess_hip_spacing_mm": initial_hip_spacing,
        "measured_correction_applied_mm": correction_applied_mm,
        "chosen_hip_spacing_mm": hip_spacing,
        "method": (
            "geometry-based initial guess, then verified against the measured "
            f"thigh AABB gap and widened until {LEG_HIP_MIN_THIGH_CLEARANCE_MM:.1f} mm "
            f"clearance is achieved, clamped to {LEG_HIP_SPACING_FALLBACK_MIN_MM:.0f}-"
            f"{LEG_HIP_SPACING_MAX_MM:.0f} mm"
        ),
        "hip_mount_reference": {
            "source": "centroid of the lowest ~10 mm slice of 10_TORSO geometry (low-stomach band)",
            "x_mm": hip_x_center,
            "y_mm": hip_y,
            "z_mm": hip_z,
        },
    }

    if thigh_aabb_gap is None:
        REPORT["warnings"].append(
            "Could not measure thigh AABB gap; hip spacing was not verified against actual geometry."
        )
    else:
        REPORT["alignment"]["thigh_aabb_gap_mm"] = thigh_aabb_gap
        REPORT["alignment"]["thigh_aabb_note"] = (
            "Positive value is clear space between the thigh AABBs after the "
            "v3.3 self-correcting spacing pass. A negative value means the "
            "correction could not reach the target clearance within the "
            f"{LEG_HIP_SPACING_MAX_MM:.0f} mm anatomical spacing limit -- see "
            "the RuntimeError this build raises in that case."
        )
        if thigh_aabb_gap < 0.0:
            raise RuntimeError(
                f"Thighs still overlap by {-thigh_aabb_gap:.2f} mm even after widening "
                f"hip spacing to the {LEG_HIP_SPACING_MAX_MM:.0f} mm limit. The community "
                "thigh source mesh likely changed shape since these constants were tuned; "
                "inspect 大腿右.stl directly rather than raising the limit blindly."
            )
        log(
            f"Thigh AABB gap after v3.3 spacing correction: {thigh_aabb_gap:.2f} mm "
            f"(hip spacing {hip_spacing:.2f} mm = {initial_hip_spacing:.2f} mm guess "
            f"+ {correction_applied_mm:.2f} mm measured correction)"
        )

    # v3.4 diagnostic ("legs on the wrong side" reports): make sidedness
    # independently checkable from the JSON alone, without opening the
    # .blend or eyeballing a render (which is very easy to mirror-flip by
    # eye on a front view). Every leg part on one side is placed from the
    # SAME (side, sign) pair in the loop above -- thigh/calf/foot/toe on a
    # given side cannot end up split across +X/-X by anything in this
    # function -- so this check mainly catches: (a) the side-vs-sign mapping
    # itself being backwards relative to the rest of the body, or (b) a
    # future edit accidentally breaking that invariant.
    side_consistency = {}
    for side_key in ("R", "L"):
        parts = {}
        xs = []
        for part_key in ("thigh", "calf", "foot", "toe"):
            obj = assembled[side_key][part_key]
            bounds = world_bounds([obj])
            cx = float((bounds[0].x + bounds[1].x) * 0.5) if bounds else float(obj.location.x)
            parts[part_key] = {"object_name": obj.name, "world_x_center_mm": cx}
            xs.append(cx)
        side_consistency[side_key] = {
            "parts": parts,
            "all_same_sign": (all(x >= 0 for x in xs) or all(x <= 0 for x in xs)),
        }
    side_consistency["R_and_L_on_opposite_sides"] = (
        side_consistency["R"]["all_same_sign"]
        and side_consistency["L"]["all_same_sign"]
        and (
            (sum(p["world_x_center_mm"] for p in side_consistency["R"]["parts"].values()) > 0)
            != (sum(p["world_x_center_mm"] for p in side_consistency["L"]["parts"].values()) > 0)
        )
    )
    # v3.5 addition: cross-check against the URDF's OWN right/left arm and
    # hand regions. Those are placed entirely by the upstream xacro's forward
    # kinematics -- nothing in this file's leg-placement code touches them --
    # so if "RIGHT_ARM"/"RIGHT_HAND" land on the same X sign as our "R" leg
    # parts, that's independent, authoritative confirmation that R=that sign
    # is the correct convention for the whole robot, not just something this
    # script assumed. If a leg part disagrees with its matching arm/hand
    # while being self-consistent within the leg (see side_consistency
    # above), the disagreement is the actual bug to chase, not the leg code.
    urdf_reference = {}
    for region in ("RIGHT_ARM", "RIGHT_HAND", "LEFT_ARM", "LEFT_HAND"):
        objs = get_collection_meshes(f"10_{region}")
        b = world_bounds(objs) if objs else None
        if b:
            cx = float((b[0].x + b[1].x) * 0.5)
            urdf_reference[region] = {"mesh_count": len(objs), "world_x_center_mm": cx}
        else:
            urdf_reference[region] = {"mesh_count": 0, "world_x_center_mm": None}

    def _sign(x):
        return None if x is None else (x > 0)

    r_arm_sign = _sign(urdf_reference["RIGHT_ARM"]["world_x_center_mm"])
    r_leg_sign = _sign(side_consistency["R"]["parts"]["thigh"]["world_x_center_mm"])
    side_consistency["urdf_reference"] = urdf_reference
    side_consistency["leg_matches_urdf_right_arm"] = (
        None if r_arm_sign is None else (r_arm_sign == r_leg_sign)
    )

    REPORT.setdefault("alignment", {})["side_consistency_check"] = side_consistency
    if not (side_consistency["R"]["all_same_sign"] and side_consistency["L"]["all_same_sign"]):
        REPORT["warnings"].append(
            "Thigh/calf/foot/toe on one leg are not all on the same side of X=0 -- "
            "this should be impossible given how place_side() cascades hip->knee->"
            "ankle->toe, and points to a bug introduced since v3.3/v3.4."
        )
    if side_consistency["leg_matches_urdf_right_arm"] is False:
        REPORT["warnings"].append(
            "RIGHT_ARM (URDF forward-kinematics, authoritative) is on the opposite "
            "side of X=0 from LEG_REF::R::* (this file's synthetic leg placement). "
            "The R/L -> sign mapping in import_and_fit_standing_legs() is backwards "
            "relative to the rest of the body and should be flipped."
        )

    # Floor on actual foot/toe soles.
    floor_bounds=world_bounds([
        r_foot,l_foot,r_toe,l_toe
    ])
    if not floor_bounds:
        raise RuntimeError("Could not compute foot/toe floor bounds")
    floor_z=floor_bounds[0].z
    lift=-floor_z

    link_objs=get_link_objects()
    _,root_link=find_root_link(link_objs)
    root_world=root_link.matrix_world.copy()
    root_world.translation.z += lift
    root_link.matrix_world=root_world

    for side in ("R","L"):
        for key in ("thigh","calf","foot","toe"):
            assembled[side][key].location.z += lift
        for key in ("hip","knee","ankle","toe_joint","toe_tip"):
            assembled[side][key].z += lift

    bpy.context.view_layer.update()

    continuity={}
    for side in ("R","L"):
        s=assembled[side]
        thigh_bottom=Vector(thigh_info["bottom_connector_local_mm"])
        calf_bottom=Vector(calf_info["bottom_connector_local_mm"])
        if side=="L":
            thigh_bottom.x *= -1.0
            calf_bottom.x *= -1.0

        knee_from_thigh=s["thigh"].matrix_world @ thigh_bottom
        knee_from_calf=s["calf"].matrix_world.translation
        ankle_from_calf=s["calf"].matrix_world @ calf_bottom
        ankle_from_foot=s["foot"].matrix_world.translation

        continuity[side]={
            "knee_gap_mm":float((knee_from_thigh-knee_from_calf).length),
            "ankle_gap_mm":float((ankle_from_calf-ankle_from_foot).length),
        }

    REPORT["leg_dimensions_mm"]={
        "thigh":thigh_info,
        "calf":calf_info,
        "foot":foot_info,
        "toe":toe_info,
        "hip_spacing_mm":hip_spacing,
        "body_lift_to_floor_mm":lift,
        "continuity":continuity,
        "placement":(
            "native CAD axes; complete side groups swapped per verified front view; "
            "v2.6 geometry baseline; no pre-floor foot/toe rotation"
        ),
        "pre_floor_foot_yaw_correction_deg": 0.0,
        "side_assignment":{
            "positive_x":"repository RIGHT aggregate",
            "negative_x":"mirrored LEFT aggregate",
        },
    }

    log(
        "Standing-leg connector gaps: "
        f"R knee {continuity['R']['knee_gap_mm']:.4f} mm, "
        f"R ankle {continuity['R']['ankle_gap_mm']:.4f} mm, "
        f"L knee {continuity['L']['knee_gap_mm']:.4f} mm, "
        f"L ankle {continuity['L']['ankle_gap_mm']:.4f} mm"
    )
    log(
        f"Added toe caps from {toe_path.name}; "
        f"toe length {toe_info['length']:.1f} mm"
    )

    # v3.8: persistent reference-point empties for manual calibration (see
    # MANUAL_CALIBRATION_OVERRIDES and print_calibration_offset() near the
    # top of this file, and the embedded CALIBRATION_HELPER text block).
    # These are real objects saved in the .blend, not values computed only
    # during the script run, so a human can select something, nudge it into
    # place next to a reference photo, and read its offset from one of
    # these points directly in Blender -- no need to re-derive hip/knee/
    # ankle positions by hand.
    ref_col = get_or_create_collection("93_CALIBRATION_REFERENCE_POINTS")
    for side_key in ("R", "L"):
        for point_key in ("hip", "knee", "ankle"):
            empty = bpy.data.objects.new(f"REF::{side_key}_{point_key.upper()}", None)
            empty.empty_display_type = "PLAIN_AXES"
            empty.empty_display_size = 30.0
            empty.location = assembled[side_key][point_key]
            ref_col.objects.link(empty)
    ref_col.hide_viewport = True
    ref_col.hide_render = True

    return assembled








def axis_from_link(link_obj: bpy.types.Object) -> Vector:
    raw = str(link_obj.get("urdf_joint_axis", "0 1 0"))
    try:
        vals = [float(v) for v in raw.replace(",", " ").split()]
        while len(vals) < 3:
            vals.append(0.0)
        axis_local = Vector(vals[:3])
    except Exception:
        axis_local = Vector((0, 1, 0))
    if axis_local.length < 1e-8:
        axis_local = Vector((0, 1, 0))
    # Joint axis is expressed in the joint/link frame in the rest pose.
    axis_world = link_obj.matrix_world.to_3x3() @ axis_local
    if axis_world.length < 1e-8:
        axis_world = Vector((0, 1, 0))
    return axis_world.normalized()






def capture_rest_alignment(link_objs: dict[str, bpy.types.Object], legs: dict) -> dict:
    """Capture the correct visible geometry before any bone parenting/IK evaluation.

    The animation rig is intentionally left unchanged. This snapshot lets us
    re-bake object-local offsets after Blender evaluates its IK constraints,
    keeping the zero/rest pose visually identical to the engineering assembly.
    """
    snapshot = {
        "links": {
            name: obj.matrix_world.copy()
            for name, obj in link_objs.items()
        },
        "legs": {},
    }

    for side in ("R", "L"):
        for key in ("thigh", "calf", "foot", "toe"):
            obj = legs[side].get(key)
            if obj is not None:
                snapshot["legs"][(side, key)] = obj.matrix_world.copy()

    return snapshot


def restore_rest_alignment(snapshot: dict, link_objs: dict[str, bpy.types.Object], legs: dict) -> None:
    """Restore pre-rig world transforms against the already-evaluated bones.

    This changes ONLY object-to-bone offset matrices. It does not create, move,
    rename, resize, constrain, or otherwise alter any bone.
    """
    bpy.context.view_layer.update()

    max_before = 0.0

    def matrix_translation_error(obj, target):
        return float((obj.matrix_world.translation - target.translation).length)

    for name, target in snapshot.get("links", {}).items():
        obj = link_objs.get(name)
        if obj is not None:
            max_before = max(max_before, matrix_translation_error(obj, target))

    for (side, key), target in snapshot.get("legs", {}).items():
        obj = legs.get(side, {}).get(key)
        if obj is not None:
            max_before = max(max_before, matrix_translation_error(obj, target))

    # Two passes are intentional: Blender's dependency graph may re-evaluate
    # constrained parent bones after the first batch of object matrix writes.
    for _ in range(2):
        for name, target in snapshot.get("links", {}).items():
            obj = link_objs.get(name)
            if obj is not None:
                obj.matrix_world = target.copy()

        for (side, key), target in snapshot.get("legs", {}).items():
            obj = legs.get(side, {}).get(key)
            if obj is not None:
                obj.matrix_world = target.copy()

        bpy.context.view_layer.update()

    max_after = 0.0
    for name, target in snapshot.get("links", {}).items():
        obj = link_objs.get(name)
        if obj is not None:
            max_after = max(max_after, matrix_translation_error(obj, target))

    for (side, key), target in snapshot.get("legs", {}).items():
        obj = legs.get(side, {}).get(key)
        if obj is not None:
            max_after = max(max_after, matrix_translation_error(obj, target))

    REPORT.setdefault("alignment", {})["post_rig_rest_restore"] = {
        "method": "re-bake rigid object offsets against evaluated v3.2 bones",
        "max_translation_error_before_restore_mm": max_before,
        "max_translation_error_after_restore_mm": max_after,
        "bones_modified": False,
    }

    log(
        f"Rest-pose alignment re-baked without changing bones: "
        f"max drift {max_before:.3f} -> {max_after:.6f} mm"
    )




def apply_final_toe_visual_correction(legs: dict) -> None:
    """Finalize visible toe orientation AND mate it to the foot.

    This remains the LAST geometry operation:
      * no effect on floor height
      * no effect on hip/leg/foot placement
      * no effect on any bone or IK constraint

    After the approved 180-degree yaw, the toe is translated so:
      1) its rear Y face overlaps the foot's front Y face by 3 mm,
      2) its sole matches the foot sole,
      3) its lateral center matches the foot's actual front-edge center.
    """
    correction=float(FINAL_TOE_YAW_CORRECTION_DEG)
    applied={}

    def bounds(obj):
        b=world_bounds([obj])
        if not b:
            raise RuntimeError(f"Could not compute bounds for {obj.name}")
        return b

    def front_slice_center_x(obj, toward_negative_y: bool) -> float:
        pts=[]
        for v in obj.data.vertices:
            pts.append(obj.matrix_world @ v.co)
        if not pts:
            return float(obj.matrix_world.translation.x)

        ys=[p.y for p in pts]
        y_min=min(ys); y_max=max(ys)
        band=max(8.0,(y_max-y_min)*0.05)

        if toward_negative_y:
            selected=[p for p in pts if p.y <= y_min+band]
        else:
            selected=[p for p in pts if p.y >= y_max-band]

        if not selected:
            selected=pts
        return float(sum(p.x for p in selected)/len(selected))

    for side in ("R","L"):
        info=legs.get(side,{})
        foot=info.get("foot")
        toe=info.get("toe")
        if foot is None or toe is None:
            continue

        bpy.context.view_layer.update()

        # Rotate only the toe about its own attachment origin.
        pivot=toe.matrix_world.translation.copy()
        before_origin=pivot.copy()
        if abs(correction)>1e-9:
            rotate_object_about_world_z(toe,pivot,correction)
            bpy.context.view_layer.update()

        fb0,fb1=bounds(foot)
        tb0,tb1=bounds(toe)

        foot_cy=(fb0.y+fb1.y)*0.5
        toe_cy=(tb0.y+tb1.y)*0.5
        toe_is_negative_y = toe_cy < foot_cy

        # Mate the toe rear face to the foot front face with controlled overlap.
        if toe_is_negative_y:
            target_rear_y=fb0.y+FINAL_TOE_MATING_OVERLAP_MM
            dy=target_rear_y-tb1.y
        else:
            target_rear_y=fb1.y-FINAL_TOE_MATING_OVERLAP_MM
            dy=target_rear_y-tb0.y

        # Match sole planes.
        dz=fb0.z-tb0.z

        # Center the toe on the actual front slice of the foot shell, not the ankle.
        target_x=front_slice_center_x(foot,toe_is_negative_y)
        toe_center_x=(tb0.x+tb1.x)*0.5
        dx=target_x-toe_center_x

        toe.matrix_world.translation += Vector((dx,dy,dz))
        bpy.context.view_layer.update()

        final0,final1=bounds(toe)

        applied[side]={
            "yaw_deg":correction,
            "rotation_pivot_mm":[float(pivot.x),float(pivot.y),float(pivot.z)],
            "translation_mm":[float(dx),float(dy),float(dz)],
            "foot_front_direction":"-Y" if toe_is_negative_y else "+Y",
            "foot_front_edge_y_mm":float(fb0.y if toe_is_negative_y else fb1.y),
            "toe_rear_edge_y_mm":float(final1.y if toe_is_negative_y else final0.y),
            "sole_error_mm":float(final0.z-fb0.z),
            "origin_translation_after_rotation_mm":float(
                (before_origin-pivot).length
            ),
        }

    REPORT.setdefault("alignment",{})["final_toe_visual_correction"]={
        "stage":"after floor alignment + rig build + rest-pose restore",
        "geometry_only":True,
        "bones_modified":False,
        "feet_modified":False,
        "legs_modified":False,
        "body_floor_height_affected":False,
        "mating_overlap_mm":FINAL_TOE_MATING_OVERLAP_MM,
        "applied":applied,
    }

    log(
        f"Applied final toe yaw + foot-face mating after all placement "
        f"(overlap {FINAL_TOE_MATING_OVERLAP_MM:.1f} mm)."
    )




def import_additional_leg_source_parts(solidworks_root: Path) -> list[str]:
    """Include additional leg/pelvis source pieces that explain the open joints.

    These are imported into a hidden reference collection because the community
    repository does not expose trustworthy SolidWorks mate transforms to Blender.
    It is safer to include them unplaced than to invent engineering positions.

    The official non-motorized InMoov build contains separate hip holders/fixers,
    knee parts/clamps/bolts, tibia shells and ankle pieces. The community
    reverse-engineering repository contains several corresponding source pieces.
    """
    col=bpy.data.collections.get("92_ADDITIONAL_LEG_SOURCE_PARTS")
    if col is None:
        col=bpy.data.collections.new("92_ADDITIONAL_LEG_SOURCE_PARTS")
        bpy.context.scene.collection.children.link(col)

    candidates=[
        "盆腔大腿连接.stl",  # pelvis-to-thigh connector
        "盆腔右.stl",
        "盆腔左.stl",
        "小腿上.stl",        # upper tibia source
        "小腿下.stl",        # lower tibia source
        "大腿右1.stl",
        "大腿右11.stl",
        "大腿右111.stl",
    ]

    imported=[]
    x_cursor=0.0

    for filename in candidates:
        hits=list(solidworks_root.rglob(filename))
        if not hits:
            continue

        try:
            obj=import_stl(hits[0])
        except Exception as exc:
            REPORT["warnings"].append(
                f"Could not import additional leg source {filename}: {exc!r}"
            )
            continue

        obj.name=f"LEG_SOURCE_UNPLACED::{Path(filename).stem}"
        obj["provenance"]="COMMUNITY_REVERSE_ENGINEERED_SOURCE_PART"
        obj["placement_status"]="UNPLACED_REFERENCE"
        obj["engineering_warning"]=(
            "Included because the full static-leg assembly uses additional "
            "hip/knee/tibia connector pieces. Do not use this object's scene "
            "position for measurements; SolidWorks mate transforms are unavailable."
        )

        move_to_collection(obj,col)

        # Put source shelf safely away from the assembled robot.
        dims=object_world_dims(obj)
        obj.location=(900.0+x_cursor,0.0,max(0.0,dims.z*0.5))
        x_cursor += max(120.0,dims.x+40.0)
        imported.append(filename)

    # Hidden by default so the engineering model remains clean.
    try:
        col.hide_viewport=True
        col.hide_render=True
    except Exception:
        pass

    REPORT["additional_leg_source_parts"]={
        "collection":col.name,
        "hidden_by_default":True,
        "placement":"UNPLACED_REFERENCE",
        "imported":imported,
        "reason":(
            "Official static InMoov legs use additional hip/knee/tibia/ankle "
            "components; community source has no Blender-readable mate transforms."
        ),
    }
    return imported


def build_armature_from_links(link_objs: dict[str, bpy.types.Object], legs: dict) -> bpy.types.Object:
    """Build a hidden mechanical rig with intuitive animation controls.

    Control philosophy:
      * Drag IK_HAND.* to position hands; arm proxy chains follow.
      * Drag IK_FINGER.* targets to curl/reach individual fingers.
      * Rotate BODY_CONTROLS for torso/head motion.
      * Rotate FACE_CONTROLS for eyes and jaw.
      * Rotate LEG_CONTROLS for synthetic standing-leg posing.

    The original URDF source-joint bones remain in the armature and preserve
    actual source axes/limits. Key torso/head/eye/jaw source bones are promoted
    into named control collections rather than being hidden.

    All robot geometry remains rigid; no soft character skinning is used.
    """
    root_name,root_link=find_root_link(link_objs)

    parent_link={}
    world_mats={}
    for name,obj in link_objs.items():
        world_mats[name]=obj.matrix_world.copy()
        p=obj.parent
        if p and p.get("urdf_link_name"):
            parent_link[name]=str(p.get("urdf_link_name"))

    def depth(name:str)->int:
        d=0; seen=set(); cur=name
        while cur in parent_link and cur not in seen:
            seen.add(cur); cur=parent_link[cur]; d+=1
        return d

    def side_match(name:str,side:str)->bool:
        n=name.lower().replace("-","_")
        tokens=("right","_r_","r_") if side=="R" else ("left","_l_","l_")
        return any(t in n for t in tokens)

    def choose_links(side:str,keywords,*,deepest=True,exclude=()):
        candidates=[]
        for name in link_objs:
            n=name.lower()
            if not side_match(name,side):
                continue
            if not any(k in n for k in keywords):
                continue
            if any(k in n for k in exclude):
                continue
            candidates.append(name)
        if not candidates:
            return None
        candidates.sort(key=depth,reverse=deepest)
        return candidates[0]

    # Friendly names for actual source-joint bones.
    FRIENDLY_SOURCE_CONTROLS={
        "torso_z_link":"CTRL_TORSO_YAW",
        "torso_y_link":"CTRL_TORSO_BEND",
        "i01.head.neck.001_link":"CTRL_HEAD_NOD",
        "neck_link":"CTRL_HEAD_TILT",
        "i01.head.rothead_link":"CTRL_HEAD_TURN",
        "i01.head.jaw_link":"CTRL_JAW",
        "i01.head.eyeLeft.001_link":"CTRL_EYE.L.PAN",
        "i01.head.eyeLeft_link":"CTRL_EYE.L.TILT",
        "i01.head.eyeRight.001_link":"CTRL_EYE.R.PAN",
        "i01.head.eyeRight_link":"CTRL_EYE.R.TILT",
    }
    BODY_LINKS={
        root_name,
        "torso_z_link","torso_y_link",
        "i01.head.neck.001_link","neck_link","i01.head.rothead_link",
    }
    FACE_LINKS={
        "i01.head.jaw_link",
        "i01.head.eyeLeft.001_link","i01.head.eyeLeft_link",
        "i01.head.eyeRight.001_link","i01.head.eyeRight_link",
    }

    arm_data=bpy.data.armatures.new("InMoov_AnimationRig")
    arm_data.display_type="OCTAHEDRAL"
    arm_data.show_names=False

    arm_obj=bpy.data.objects.new("InMoov_AnimationRig",arm_data)
    bpy.context.scene.collection.objects.link(arm_obj)
    # Rig is hidden by default, so make it easy to work through the shell once enabled.
    arm_obj.show_in_front=True
    arm_obj["scene_units"]="1 Blender Unit = 1 mm"
    arm_obj["hidden_by_default"]=True
    arm_obj["animation_help"]=(
        "Unhide rig, Ctrl+Tab. Drag IK_HAND/IK_FINGER with G; "
        "rotate CTRL_TORSO/CTRL_HEAD/CTRL_EYE/CTRL_JAW with R."
    )

    bpy.ops.object.select_all(action="DESELECT")
    arm_obj.select_set(True)
    bpy.context.view_layer.objects.active=arm_obj
    bpy.ops.object.mode_set(mode="EDIT")

    bone_for_link={}

    root_bone=arm_data.edit_bones.new("CTRL_ROOT")
    root_head=world_mats[root_name].translation.copy()
    root_bone.head=root_head
    root_bone.tail=root_head+Vector((0,0,140.0))
    bone_for_link[root_name]=root_bone.name

    # --------------------------------------------------------------
    # Source URDF bones.
    # --------------------------------------------------------------
    remaining={name for name in link_objs if name!=root_name}
    safety=0
    while remaining and safety<len(link_objs)+10:
        safety+=1; progress=False
        for name in list(remaining):
            pname=parent_link.get(name)
            if pname not in bone_for_link:
                continue

            obj=link_objs[name]
            jname=str(obj.get("urdf_joint_name","") or name)
            jtype=str(obj.get("urdf_joint_type","fixed"))

            friendly=FRIENDLY_SOURCE_CONTROLS.get(name)
            bone_name=friendly or (f"SRC::{jname}" if jtype!="fixed" else f"FIX::{jname}")

            eb=arm_data.edit_bones.new(bone_name)
            head=world_mats[name].translation.copy()
            axis=axis_from_link(obj)
            length=45.0
            low=name.lower()
            if any(k in low for k in ("torso","stomach","shoulder","bicep","forearm","neck")):
                length=70.0
            if any(k in low for k in ("finger","thumb","index","majeure","ring","pinky","eye","jaw")):
                length=22.0

            eb.head=head
            eb.tail=head+axis*length
            eb.parent=arm_data.edit_bones[bone_for_link[pname]]
            eb.use_connect=False
            bone_for_link[name]=eb.name

            remaining.remove(name); progress=True
        if not progress:
            break

    # --------------------------------------------------------------
    # Standing-leg + foot/toe controls.
    # Foot bone intentionally points toward native toe direction (-Y).
    # --------------------------------------------------------------
    leg_bones={}
    for side in ("R","L"):
        info=legs[side]
        hip,knee,ankle=info["hip"],info["knee"],info["ankle"]

        thigh=arm_data.edit_bones.new(f"CTRL_LEG.{side}.THIGH")
        thigh.head=hip; thigh.tail=knee; thigh.parent=root_bone

        shin=arm_data.edit_bones.new(f"CTRL_LEG.{side}.SHIN")
        shin.head=knee; shin.tail=ankle; shin.parent=thigh; shin.use_connect=True

        foot=arm_data.edit_bones.new(f"CTRL_LEG.{side}.FOOT")
        foot.head=ankle
        foot.tail=ankle+Vector((0,-max(90.0,info["foot_len"]*0.50),0))
        foot.parent=shin; foot.use_connect=True

        toe=arm_data.edit_bones.new(f"CTRL_LEG.{side}.TOE")
        toe.head=info["toe_joint"]
        toe.tail=info["toe_tip"]
        toe.parent=foot
        toe.use_connect=False

        leg_bones[side]={
            "thigh":thigh.name,
            "calf":shin.name,
            "foot":foot.name,
            "toe":toe.name,
        }

    # --------------------------------------------------------------
    # Arm IK proxy chains.
    # --------------------------------------------------------------
    ik_arm={}
    proxy_bound_links={}

    for side in ("R","L"):
        shoulder_name=choose_links(
            side,("shoulder",),deepest=False,
            exclude=("finger","thumb","hand")
        )
        elbow_name=choose_links(side,("elbow",),deepest=True)
        wrist_name=choose_links(side,("wrist",),deepest=True)
        hand_name=choose_links(
            side,("hand",),deepest=True,
            exclude=("finger","thumb","index","majeure","middle",
                     "ring","pinky","auriculaire","little")
        )

        if not all((shoulder_name,elbow_name,wrist_name)):
            REPORT["warnings"].append(
                f"Could not create {side} hand IK chain: "
                f"shoulder={shoulder_name}, elbow={elbow_name}, wrist={wrist_name}"
            )
            continue

        shoulder=world_mats[shoulder_name].translation.copy()
        elbow=world_mats[elbow_name].translation.copy()
        wrist=world_mats[wrist_name].translation.copy()

        if hand_name:
            palm=world_mats[hand_name].translation.copy()
        else:
            vec=wrist-elbow
            if vec.length<1.0: vec=Vector((0,-1,0))
            palm=wrist+vec.normalized()*75.0

        if (palm-wrist).length<20.0:
            vec=wrist-elbow
            if vec.length<1.0: vec=Vector((0,-1,0))
            palm=wrist+vec.normalized()*75.0

        # Parent the arm proxy to the actual shoulder parent (torso), so torso/head
        # motion carries the limbs naturally.
        shoulder_parent=parent_link.get(shoulder_name,root_name)
        proxy_parent=arm_data.edit_bones.get(bone_for_link.get(shoulder_parent,""))
        if proxy_parent is None:
            proxy_parent=root_bone

        upper=arm_data.edit_bones.new(f"IKCHAIN_ARM.{side}.UPPER")
        upper.head=shoulder; upper.tail=elbow
        upper.parent=proxy_parent; upper.use_connect=False

        fore=arm_data.edit_bones.new(f"IKCHAIN_ARM.{side}.FORE")
        fore.head=elbow; fore.tail=wrist
        fore.parent=upper; fore.use_connect=True

        hand=arm_data.edit_bones.new(f"IKCHAIN_ARM.{side}.HAND")
        hand.head=wrist; hand.tail=palm
        hand.parent=fore; hand.use_connect=True

        target=arm_data.edit_bones.new(f"IK_HAND.{side}")
        target.head=palm; target.tail=palm+Vector((0,0,45.0))
        target.parent=root_bone; target.use_connect=False; target.use_deform=False

        ik_arm[side]={
            "upper":upper.name,"fore":fore.name,"hand":hand.name,
            "target":target.name,
            "shoulder_link":shoulder_name,
            "elbow_link":elbow_name,
            "wrist_link":wrist_name,
            "hand_link":hand_name,
        }

    # --------------------------------------------------------------
    # Finger IK proxy chains.
    # --------------------------------------------------------------
    finger_specs={
        "THUMB":("thumb","pouce"),
        "INDEX":("index",),
        "MIDDLE":("middle","majeure","majeur"),
        "RING":("ring","annulaire"),
        "PINKY":("pinky","little","auriculaire"),
    }
    finger_rigs={}

    for side in ("R","L"):
        parent_hand_bone=ik_arm.get(side,{}).get("hand")
        if not parent_hand_bone:
            continue

        for finger_label,words in finger_specs.items():
            candidates=[
                name for name in link_objs
                if side_match(name,side)
                and any(w in name.lower() for w in words)
            ]
            if not candidates:
                continue
            candidates.sort(key=depth)

            unique=[]
            for name in candidates:
                p=world_mats[name].translation.copy()
                if not unique or (p-unique[-1][1]).length>3.0:
                    unique.append([name,p])
                else:
                    unique[-1][0]=name

            if len(unique)<2:
                continue

            chain=[]
            for i,(lname,head) in enumerate(unique):
                if i+1<len(unique):
                    tail=unique[i+1][1].copy()
                else:
                    prev=unique[i-1][1]
                    direction=head-prev
                    if direction.length<1.0: direction=Vector((0,-1,0))
                    tail=head+direction.normalized()*22.0

                if (tail-head).length<2.0:
                    continue

                eb=arm_data.edit_bones.new(
                    f"IKCHAIN_FINGER.{side}.{finger_label}.{i+1}"
                )
                eb.head=head; eb.tail=tail
                eb.parent=(
                    arm_data.edit_bones[chain[-1]]
                    if chain else arm_data.edit_bones[parent_hand_bone]
                )
                eb.use_connect=bool(chain)
                chain.append(eb.name)

            if not chain:
                continue

            end=arm_data.edit_bones[chain[-1]]
            target_pos=end.tail.copy()
            target=arm_data.edit_bones.new(f"IK_FINGER.{side}.{finger_label}")
            target.head=target_pos
            target.tail=target_pos+Vector((0,0,18.0))
            target.parent=root_bone
            target.use_connect=False
            target.use_deform=False

            finger_rigs[(side,finger_label)]={
                "chain":list(chain),
                "target":target.name,
                "candidate_links":list(candidates),
            }

    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.update()

    # --------------------------------------------------------------
    # Bone collections.
    # --------------------------------------------------------------
    body_col=face_col=ik_col=legs_col=source_col=fixed_col=None
    try:
        body_col=arm_data.collections.new("BODY_CONTROLS")
        face_col=arm_data.collections.new("FACE_CONTROLS")
        ik_col=arm_data.collections.new("IK_CONTROLS")
        legs_col=arm_data.collections.new("LEG_CONTROLS")
        source_col=arm_data.collections.new("SOURCE_FK")
        fixed_col=arm_data.collections.new("FIXED_MECHANICS")

        body_col.is_visible=True
        face_col.is_visible=True
        ik_col.is_visible=True
        legs_col.is_visible=True
        source_col.is_visible=False
        fixed_col.is_visible=False
    except Exception as exc:
        REPORT["warnings"].append(f"Bone collection setup warning: {exc!r}")

    # --------------------------------------------------------------
    # Configure actual URDF source controls + joint limits.
    # --------------------------------------------------------------
    active_source=0
    body_controls=[]
    face_controls=[]

    for link_name,bone_name in bone_for_link.items():
        pb=arm_obj.pose.bones.get(bone_name)
        if not pb:
            continue

        pb.rotation_mode="XYZ"
        pb.lock_scale=(True,True,True)

        if link_name==root_name:
            pb.lock_location=(False,False,False)
            pb.lock_rotation=(False,False,False)
            if body_col:
                try: body_col.assign(pb.bone)
                except Exception: pass
            body_controls.append(pb.name)
            continue

        obj=link_objs[link_name]
        jtype=str(obj.get("urdf_joint_type","fixed"))
        pb["urdf_link"]=link_name
        pb["urdf_joint_name"]=str(obj.get("urdf_joint_name",link_name))
        pb["urdf_joint_type"]=jtype
        pb["urdf_joint_axis"]=str(obj.get("urdf_joint_axis",""))
        pb.lock_location=(True,True,True)

        if jtype=="fixed":
            pb.lock_rotation=(True,True,True)
            if fixed_col:
                try: fixed_col.assign(pb.bone)
                except Exception: pass
            continue

        active_source+=1

        # Source bone Y is aligned to the URDF joint axis.
        if jtype in {"revolute","continuous"}:
            pb.lock_rotation=(True,False,True)
            lower=obj.get("joint_lower")
            upper=obj.get("joint_upper")
            if jtype=="revolute" and lower is not None and upper is not None:
                try:
                    lower=float(lower); upper=float(upper)
                    con=pb.constraints.new("LIMIT_ROTATION")
                    con.name="URDF joint limits"
                    con.owner_space="LOCAL"
                    con.use_limit_x=True; con.min_x=con.max_x=0.0
                    con.use_limit_z=True; con.min_z=con.max_z=0.0
                    con.use_limit_y=True
                    con.min_y=lower; con.max_y=upper
                except Exception as exc:
                    REPORT["warnings"].append(
                        f"Limit constraint failed for {pb.name}: {exc!r}"
                    )
        elif jtype=="prismatic":
            pb.lock_rotation=(True,True,True)
            pb.lock_location=(True,False,True)

        if link_name in BODY_LINKS:
            if body_col:
                try: body_col.assign(pb.bone)
                except Exception: pass
            body_controls.append(pb.name)
        elif link_name in FACE_LINKS:
            if face_col:
                try: face_col.assign(pb.bone)
                except Exception: pass
            face_controls.append(pb.name)
        else:
            if source_col:
                try: source_col.assign(pb.bone)
                except Exception: pass

    # --------------------------------------------------------------
    # Leg controls, including toe hinges.
    # --------------------------------------------------------------
    for side,names in leg_bones.items():
        for segment,bone_name in names.items():
            pb=arm_obj.pose.bones[bone_name]
            pb.rotation_mode="XYZ"
            pb.lock_location=(True,True,True)
            pb.lock_scale=(True,True,True)
            pb["synthetic_leg_pose_bone"]=True
            if legs_col:
                try: legs_col.assign(pb.bone)
                except Exception: pass

            con=pb.constraints.new("LIMIT_ROTATION")
            con.name="Synthetic posing range"
            con.owner_space="LOCAL"

            if segment=="thigh":
                con.use_limit_x=True
                con.min_x=math.radians(-30)
                con.max_x=math.radians(35)
                con.use_limit_z=True
                con.min_z=math.radians(-15)
                con.max_z=math.radians(15)
            elif segment=="calf":
                con.use_limit_x=True
                con.min_x=math.radians(-5)
                con.max_x=math.radians(70)
            elif segment=="foot":
                con.use_limit_x=True
                con.min_x=math.radians(-20)
                con.max_x=math.radians(20)
            elif segment=="toe":
                con.use_limit_x=True
                con.min_x=math.radians(-10)
                con.max_x=math.radians(30)

    # --------------------------------------------------------------
    # IK hand/finger constraints.
    # --------------------------------------------------------------
    for side,info in ik_arm.items():
        for key in ("upper","fore","hand"):
            pb=arm_obj.pose.bones[info[key]]
            pb.rotation_mode="QUATERNION"
            pb.lock_scale=(True,True,True)
            if fixed_col:
                try: fixed_col.assign(pb.bone)
                except Exception: pass

        target_pb=arm_obj.pose.bones[info["target"]]
        target_pb.lock_location=(False,False,False)
        target_pb.lock_rotation=(False,False,False)
        target_pb.lock_scale=(True,True,True)
        target_pb["control_role"]=f"{side} hand IK target"
        if ik_col:
            try: ik_col.assign(target_pb.bone)
            except Exception: pass

        end_pb=arm_obj.pose.bones[info["hand"]]
        ik=end_pb.constraints.new("IK")
        ik.name=f"Hand IK {side}"
        ik.target=arm_obj
        ik.subtarget=info["target"]
        ik.chain_count=3
        ik.use_stretch=False
        if hasattr(ik,"use_rotation"):
            ik.use_rotation=True

    for (side,finger_label),info in finger_rigs.items():
        for bone_name in info["chain"]:
            pb=arm_obj.pose.bones[bone_name]
            pb.rotation_mode="QUATERNION"
            pb.lock_scale=(True,True,True)
            if fixed_col:
                try: fixed_col.assign(pb.bone)
                except Exception: pass

        target_pb=arm_obj.pose.bones[info["target"]]
        target_pb.lock_location=(False,False,False)
        target_pb.lock_rotation=(True,True,True)
        target_pb.lock_scale=(True,True,True)
        target_pb["control_role"]=f"{side} {finger_label} fingertip IK target"
        if ik_col:
            try: ik_col.assign(target_pb.bone)
            except Exception: pass

        end_pb=arm_obj.pose.bones[info["chain"][-1]]
        ik=end_pb.constraints.new("IK")
        ik.name=f"{finger_label} IK {side}"
        ik.target=arm_obj
        ik.subtarget=info["target"]
        ik.chain_count=len(info["chain"])
        ik.use_stretch=False

    # --------------------------------------------------------------
    # Rigid geometry binding.
    # --------------------------------------------------------------
    for name,obj in link_objs.items():
        parent_object_to_bone_keep_world(obj,arm_obj,bone_for_link[name])
        obj.hide_select=True
        obj.empty_display_size=min(obj.empty_display_size,7.0)

    # v4.0: do NOT rebind robot geometry to the simplified proxy chains in
    # SOURCE_FK mode. Every URDF link is already rigid-parented above to its
    # actual source joint bone, whose local Y axis matches the URDF joint axis.
    # Keeping that relationship makes Blender a visualization adapter for the
    # same joint angles used by the real-robot kinematics.
    if VISUALIZATION_ARM_BINDING_MODE == "LEGACY_PROXY_IK":
        # Retained only for manual experimentation with the old drag-target rig.
        for side,info in ik_arm.items():
            for lname,obj in link_objs.items():
                if not side_match(lname,side):
                    continue
                low=lname.lower()
                if any(k in low for k in (
                    "finger","thumb","index","majeure","middle",
                    "ring","pinky","auriculaire","little"
                )):
                    continue

                target_bone=None
                if any(k in low for k in ("hand","wrist")):
                    target_bone=info["hand"]
                elif any(k in low for k in ("forearm","fore_arm","elbow")):
                    target_bone=info["fore"]
                elif any(k in low for k in ("bicep","upperarm","upper_arm","shoulder")):
                    target_bone=info["upper"]

                if target_bone:
                    parent_object_to_bone_keep_world(obj,arm_obj,target_bone)
                    proxy_bound_links[lname]=target_bone

        for (side,finger_label),info in finger_rigs.items():
            candidates=sorted(info["candidate_links"],key=depth)
            chain=info["chain"]
            if not chain:
                continue

            for i,lname in enumerate(candidates):
                if lname not in link_objs:
                    continue
                idx=min(len(chain)-1,int(i*len(chain)/max(1,len(candidates))))
                target_bone=chain[idx]
                parent_object_to_bone_keep_world(link_objs[lname],arm_obj,target_bone)
                proxy_bound_links[lname]=target_bone

    # Standing leg geometry.
    for side in ("R","L"):
        parent_object_to_bone_keep_world(
            legs[side]["thigh"],arm_obj,leg_bones[side]["thigh"]
        )
        parent_object_to_bone_keep_world(
            legs[side]["calf"],arm_obj,leg_bones[side]["calf"]
        )
        parent_object_to_bone_keep_world(
            legs[side]["foot"],arm_obj,leg_bones[side]["foot"]
        )
        parent_object_to_bone_keep_world(
            legs[side]["toe"],arm_obj,leg_bones[side]["toe"]
        )

    # Clean default engineering view.
    arm_obj.hide_set(True)
    for link_obj in link_objs.values():
        try: link_obj.hide_set(True)
        except Exception: pass

    arm_obj["visualization_arm_binding_mode"] = VISUALIZATION_ARM_BINDING_MODE
    arm_obj["CV_SIM_BINDING_REPAIRED"] = (VISUALIZATION_ARM_BINDING_MODE == "SOURCE_FK")
    arm_obj["CV_SIMULATION_NOTE"] = (
        "SOURCE_FK mode: external joint angles drive published URDF source bones directly"
    )

    REPORT["armature"]={
        "name":arm_obj.name,
        "hidden_by_default":True,
        "source_urdf_bones":len(bone_for_link),
        "active_source_joints":active_source,
        "body_controls":body_controls,
        "face_controls":face_controls,
        "synthetic_leg_controls":8,
        "ik_hand_controls":{
            side:info["target"] for side,info in ik_arm.items()
        },
        "ik_finger_controls":{
            f"{side}_{finger}":info["target"]
            for (side,finger),info in finger_rigs.items()
        },
        "visible_when_rig_enabled":[
            "BODY_CONTROLS","FACE_CONTROLS","IK_CONTROLS","LEG_CONTROLS"
        ],
        "hidden_control_layers":["SOURCE_FK","FIXED_MECHANICS"],
        "binding":(
            "SOURCE_FK: URDF links rigid-parented to actual source joint bones; proxy IK does not own geometry"
            if VISUALIZATION_ARM_BINDING_MODE == "SOURCE_FK"
            else "LEGACY_PROXY_IK: simplified proxy chains own arm/finger geometry"
        ),
        "visualization_arm_binding_mode":VISUALIZATION_ARM_BINDING_MODE,
        "animation_note":(
            "CV bridge should apply solved joint angles directly to SOURCE_FK bones. "
            "Friendly torso/head/eye/jaw controls are promoted source joints. "
            "IK_HAND/IK_FINGER remain optional reference controls only."
        ),
    }

    return arm_obj







def add_rig_note() -> None:
    text=bpy.data.texts.get("README_RIGGED_LEGS") or bpy.data.texts.new("README_RIGGED_LEGS")
    text.clear()
    text.write(
        "INMOOV COMPLETE ENGINEERING REFERENCE v4.0\n"
        "==========================================\n\n"
        "Scene: 1 Blender Unit = 1 mm.\n"
        "Rig is hidden by default.\n\n"
        "ENABLE ANIMATION RIG\n"
        "1. Outliner -> unhide InMoov_AnimationRig.\n"
        "2. Select it -> Ctrl+Tab for Pose Mode.\n\n"
        "SOURCE-FK VISUALIZATION (v4.0 DEFAULT)\n"
        "- Robot arm/hand/finger geometry is bound to the actual URDF source bones.\n"
        "- External CV/IK should drive those published joint angles directly.\n"
        "- IK_HAND/IK_FINGER proxy targets remain for reference/manual experiments,\n"
        "  but they do not own geometry in SOURCE_FK mode.\n\n"
        "BODY CONTROLS (rotate with R)\n"
        "- CTRL_ROOT\n"
        "- CTRL_TORSO_YAW\n"
        "- CTRL_TORSO_BEND\n"
        "- CTRL_HEAD_NOD\n"
        "- CTRL_HEAD_TILT\n"
        "- CTRL_HEAD_TURN\n\n"
        "FACE CONTROLS (rotate with R)\n"
        "- CTRL_JAW\n"
        "- CTRL_EYE.L.PAN / CTRL_EYE.L.TILT\n"
        "- CTRL_EYE.R.PAN / CTRL_EYE.R.TILT\n"
        "The canonical URDF does not expose eyebrow/lip expression joints, so\n"
        "the source-supported facial DOFs are eyes + jaw + head/neck.\n\n"
        "LEG CONTROLS\n"
        "- CTRL_LEG.<side>.THIGH / SHIN / FOOT / TOE\n"
        "These are synthetic pose controls because the published standing legs\n"
        "are non-motorized.\n\n"
        "All mechanical geometry is rigid-parented; no soft character skinning.\n"
    )






def configure_viewport() -> None:
    """Clean viewport with improved depth precision and hidden rig clutter."""
    for window in bpy.context.window_manager.windows:
        screen = window.screen
        if not screen:
            continue
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            for space in area.spaces:
                if space.type == "VIEW_3D":
                    space.clip_start = 1.0
                    space.clip_end = 10000.0
                    try:
                        space.overlay.show_relationship_lines = False
                    except Exception:
                        pass





def frame_robot(arm_obj: bpy.types.Object) -> None:
    """Frame the visible robot meshes and leave everything unselected."""
    try:
        visible = [
            o for o in bpy.context.view_layer.objects
            if o.type == "MESH"
            and not o.hide_get()
            and (o.name.startswith("MESH::") or o.name.startswith("LEG_REF::"))
        ]
        if not visible:
            return

        bpy.ops.object.select_all(action="DESELECT")
        for o in visible:
            o.select_set(True)
        bpy.context.view_layer.objects.active = visible[0]

        for window in bpy.context.window_manager.windows:
            screen = window.screen
            if not screen:
                continue
            for area in screen.areas:
                if area.type != "VIEW_3D":
                    continue
                region = next((r for r in area.regions if r.type == "WINDOW"), None)
                if not region:
                    continue
                with bpy.context.temp_override(
                    window=window, screen=screen, area=area, region=region
                ):
                    bpy.ops.view3d.view_selected(use_all_regions=False)

        bpy.ops.object.select_all(action="DESELECT")
    except Exception as exc:
        REPORT["warnings"].append(f"Could not frame visible robot: {exc!r}")



# ------------------------- Optional alternative head ------------------------

# Geometry from both source builders is authoritative: neither STL/3MF nor
# topology is rescaled or edited. Placement is a scene-level rigid translation,
# initially aligned to the canonical head reference bounds. Mechanical fit
# still needs visual calibration using real neck attachment reference points.
COGLEY_BUILDER_PATH = Path(__file__).resolve().with_name("head_builder.py")
COGLEY_SOURCE_3MF = os.environ.get("TALUS_COGLEY_3MF", "").strip()


def _bounds_center(objects):
    points = []
    for obj in objects:
        if obj.type != "MESH":
            continue
        for corner in obj.bound_box:
            points.append(obj.matrix_world @ Vector(corner))
    if not points:
        raise RuntimeError("Cannot align replacement head: missing source head geometry")
    return Vector(tuple((min(p[i] for p in points)+max(p[i] for p in points))*0.5 for i in range(3)))


def install_cogley_head(body_rig):
    """Build 3MF head in the body scene and attach its own facial rig to the neck.

    Keep source facial mechanisms, mesh transforms, drivers and control properties.
    Do not delete InMoov source geometry until the replacement has built.
    """
    if not COGLEY_BUILDER_PATH.is_file():
        raise FileNotFoundError(f"Missing adjacent head builder: {COGLEY_BUILDER_PATH}")
    # The URDF head meshes are removed only after successful source-guided build.
    # Retain neck shells and URDF bones so the Pi bridge can use its established
    # head yaw/pitch/roll mapping without doubling Cogley's internal rotations.
    source_head = [obj for obj in bpy.data.objects if obj.type == "MESH"
                   and obj.name.startswith("MESH::")
                   and ("head" in obj.name.casefold() or "eye" in obj.name.casefold()
                        or "jaw" in obj.name.casefold())
                   and "neck" not in obj.name.casefold()]
    if not source_head:
        raise RuntimeError("Could not identify canonical head source meshes. No geometry removed.")
    canonical_center = _bounds_center(source_head)
    spec = importlib.util.spec_from_file_location("talus_cogley_head_builder", str(COGLEY_BUILDER_PATH))
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load head_builder.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source_path = COGLEY_SOURCE_3MF or module.find_source_3mf()
    if not source_path:
        raise FileNotFoundError(
            "Cogley head requires BambuPrintfile.3mf. Put it beside head_builder.py, "
            "or set TALUS_COGLEY_3MF to its full path before launching Blender."
        )
    head_rig = module.build(source_path)
    try:
        module.register()  # Restore Cogley Rig's N-panel controls for editing.
    except Exception as exc:
        REPORT["warnings"].append(f"Optional Cogley UI panel unavailable: {exc!r}")
    root_collection = bpy.data.collections.get(module.COL_ROOT)
    if root_collection is None:
        raise RuntimeError("Head builder did not produce its expected assembly collection")
    head_objs = []
    def visit(col):
        head_objs.extend(o for o in col.objects if o.type == "MESH")
        for child in col.children: visit(child)
    visit(root_collection)
    actual_center = _bounds_center(head_objs)
    shift = canonical_center - actual_center
    # Apply rigid assembly translation, never alter the manufacturer's vertices.
    head_rig.matrix_world.translation += shift
    bpy.context.view_layer.update()
    neck_bone = "CTRL_HEAD_TURN"
    if body_rig.pose.bones.get(neck_bone) is None:
        raise RuntimeError(f"Body armature lacks expected attachment bone {neck_bone}")
    head_world = head_rig.matrix_world.copy()
    head_rig.parent = body_rig
    head_rig.parent_type = "BONE"
    head_rig.parent_bone = neck_bone
    head_rig.matrix_world = head_world
    head_rig["talus_head_variant"] = "cogley"
    head_rig["talus_mount_bone"] = neck_bone
    head_rig["talus_alignment"] = "AABB_CENTER_PREVIEW_ONLY; CHECK_MOUNTING_GEOMETRY"
    bpy.context.view_layer.update()
    for old in source_head:
        bpy.data.objects.remove(old, do_unlink=True)
    REPORT["head_variant"] = "cogley"
    REPORT["head_source_3mf"] = str(source_path)
    REPORT["head_replaced_meshes"] = len(source_head)
    REPORT["head_mount"] = neck_bone
    REPORT["warnings"].append(
        "Cogley head alignment is a rigid visual preview based on head envelope centers, "
        "not an authoritative neck mounting-hole mate. Validate orientation, fit and "
        "facial linkage closure before using motion on physical hardware."
    )
    log(f"Cogley head installed: {len(source_head)} old visual meshes replaced; mount={neck_bone}")
    return head_rig


# ---------------------- standalone full-build pipeline -----------------------


def main(head_variant: str = "inmoov") -> None:
    """Build the complete corrected-leg, animation-ready reference in one run."""
    ensure_dirs()
    clear_scene()
    setup_si_units_for_build()

    assembly_root = get_or_create_collection("00_URDF_ASSEMBLY")
    region_cols = {}
    for name in [
        "HEAD_NECK", "TORSO", "LEFT_ARM", "RIGHT_ARM",
        "LEFT_HAND", "RIGHT_HAND", "LEFT_LEG", "RIGHT_LEG", "MISC_BODY"
    ]:
        region_cols[name] = get_or_create_collection(f"10_{name}", assembly_root)

    get_or_create_collection("90_HARDWARE_REFERENCE_UNPLACED")
    get_or_create_collection("99_NOTES_REFERENCE")

    source_roots: dict[str, Path | None] = {}
    for spec in REPOSITORIES:
        source_roots[spec["name"]] = acquire_repo(spec)

    current_root = source_roots.get("sentience_current")
    solidworks_root = source_roots.get("community_solidworks")
    if not current_root:
        raise RuntimeError("Maintained Sentience Robotics inmoov_urdf repository unavailable")
    if not solidworks_root:
        raise RuntimeError("Community inmoov-solidworks repository unavailable")

    REPORT["leg_source_root"] = str(solidworks_root)

    # Canonical upper body.
    urdf_path = compile_current_xacro(current_root)
    log(f"Selected canonical generated URDF: {urdf_path}")
    robot, links, joints, root_name = parse_urdf(urdf_path)
    REPORT["root_link"] = root_name
    REPORT["links"] = len(links)
    REPORT["joints"] = len(joints)
    log(f"URDF: {len(links)} links, {len(joints)} joints, root={root_name}")

    search_roots = [r for r in source_roots.values() if r]
    basename_index, all_files = build_file_index(search_roots)

    link_objs = create_link_hierarchy(links, joints, root_name, region_cols)
    add_visuals(
        links, link_objs, urdf_path, search_roots,
        basename_index, all_files, region_cols
    )
    validate_si_assembly()
    bake_urdf_assembly_m_to_mm(link_objs)
    configure_viewports()

    # Corrected standing legs first.
    link_objs = get_link_objects()
    remove_root_stand_visuals(link_objs)
    legs = import_and_fit_standing_legs(solidworks_root)

    # Snapshot the correct engineering rest pose BEFORE any bone parenting/IK.
    # The armature itself is unchanged from v3.2.
    rest_alignment = capture_rest_alignment(get_link_objects(), legs)

    # Build the exact same v3.2 animation rig/bones.
    armature = build_armature_from_links(get_link_objects(), legs)

    # Re-bake object offsets after Blender evaluates the constraints. This fixes
    # detached/misaligned hands, fingers, feet, etc. without touching the bones.
    restore_rest_alignment(rest_alignment, get_link_objects(), legs)

    # FINAL geometry correction. This occurs after floor placement and after the
    # unchanged rig/rest-pose restoration, so it cannot move any other part.
    apply_final_toe_visual_correction(legs)

    if head_variant == "cogley":
        install_cogley_head(armature)
    elif head_variant != "inmoov":
        raise ValueError(f"Unknown head choice: {head_variant}")
    else:
        REPORT["head_variant"] = "inmoov"

    # Include the extra community hip/knee/tibia source parts in a hidden shelf.
    # They are deliberately unplaced because SolidWorks mate transforms are not
    # available to Blender and we will not fabricate engineering positions.
    import_additional_leg_source_parts(solidworks_root)

    # Unplaced actuator reference shelf remains separate from installed geometry.
    import_hardware_references(solidworks_root)

    # v3.7: official inmoov.fr knee/ankle hardware, unplaced for the same
    # "no mate data available" reason as the community hip/knee/tibia parts.
    import_official_knee_ankle_hardware()

    add_measurement_reference()
    add_internal_notes(source_roots, urdf_path)
    add_rig_note()
    add_calibration_helper_text()
    configure_viewport()

    # Final body/leg validation.
    bounds = compute_bounds_mm()
    REPORT["assembly_bounds"] = bounds
    if bounds:
        dims = bounds["dimensions_mm"]
        log(
            f"Final complete assembly AABB: "
            f"{dims[0]:.1f} x {dims[1]:.1f} x {dims[2]:.1f} mm"
        )
        if max(dims) < 1500.0 or max(dims) > 2400.0:
            raise RuntimeError(
                f"Corrected complete-body height is implausible ({dims}); "
                "refusing to save an engineering-reference result."
            )

    scene = bpy.context.scene
    scene["INMOOV_BUILDER_VERSION"] = "4.0"
    scene["INMOOV_COMPLETE_MODEL"] = True
    scene["INMOOV_ARMATURE"] = armature.name
    scene["INMOOV_LEG_ASSEMBLY_METHOD"] = (
        "v2.6 geometry baseline; hip spacing self-corrected against measured "
        "thigh AABB clearance; hips referenced to low-stomach mount band; "
        "toe mating applied only after complete build, no extra toe yaw"
    )
    scene["INMOOV_UNIT_CONVENTION"] = "1 Blender Unit = 1 millimeter"

    # Rig remains hidden; frame the visible model only.
    frame_robot(armature)

    # v3.8: apply any hand-calibrated overrides last, so they are never
    # re-adjusted by a procedural heuristic afterward.
    apply_calibration_overrides()

    # Exactly one JSON.
    write_report_safely()
    scene["INMOOV_BUILD_REPORT"] = json.dumps(REPORT, ensure_ascii=False)

    # Blender's .blend1 is an automatic save-version backup, not a second model.
    # Disable save versions only for this scripted output and remove any stale
    # backup of this exact generated filename.
    old_save_versions = bpy.context.preferences.filepaths.save_version
    try:
        bpy.context.preferences.filepaths.save_version = 0
        OUTPUT_BLEND.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT_BLEND), compress=True)
    finally:
        bpy.context.preferences.filepaths.save_version = old_save_versions

    stale_backup = Path(str(OUTPUT_BLEND) + "1")
    try:
        if stale_backup.exists():
            stale_backup.unlink()
    except Exception as exc:
        REPORT["warnings"].append(f"Could not remove stale Blender backup: {exc!r}")

    # Rewrite the one report if the cleanup produced a warning.
    write_report_safely()

    # Leave the final file with obvious controls selected. Pose Mode is not forced
    # because Blender can be less predictable when saving from a scripted mode
    # transition; the user can press Ctrl+Tab immediately after opening.
    log(f"Saved complete corrected model: {OUTPUT_BLEND}")
    log(f"Single consolidated JSON: {REPORT_JSON}")
    log(
        "Animation rig is hidden by default. Unhide InMoov_AnimationRig in the Outliner, "
        "select it, then Ctrl+Tab. MAIN_CONTROLS/STANDING_LEGS are available; HAND_CONTROLS can be enabled "
        "from Armature Data > Bone Collections."
    )



def run_chosen_head(head_variant: str):
    try:
        log(f"Builder v4.0, selected head: {head_variant}; directory: {ROOT}")
        main(head_variant=head_variant)
    except Exception as exc:
        REPORT["fatal_error"] = repr(exc)
        REPORT["traceback"] = traceback.format_exc()
        try:
            ensure_dirs()
            write_report_safely()
        except Exception:
            pass
        log("FATAL ERROR")
        log(traceback.format_exc())
        raise


class TALUS_OT_SelectHead(bpy.types.Operator):
    bl_idname = "talus.select_head"
    bl_label = "Select TALUS Head"
    bl_description = "Choose which head to include in the complete humanoid model"

    variant: bpy.props.EnumProperty(
        name="Head model",
        items=[
            ("inmoov", "Original InMoov", "Keep the original InMoov head"),
            ("cogley", "Will Cogley", "Build the supplied 3MF Cogley head and preserve facial controls"),
        ], default="inmoov")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=390)

    def execute(self, context):
        run_chosen_head(self.variant)
        return {'FINISHED'}


if __name__ == "__main__":
    # GUI Scripting-tab runs show a choice dialog. Background builds must
    # explicitly choose via TALUS_HEAD_VARIANT, or default to original InMoov.
    try:
        bpy.utils.register_class(TALUS_OT_SelectHead)
    except ValueError:
        bpy.utils.unregister_class(TALUS_OT_SelectHead)
        bpy.utils.register_class(TALUS_OT_SelectHead)
    selected = os.environ.get("TALUS_HEAD_VARIANT", "").strip().casefold()
    if selected:
        run_chosen_head(selected)
    elif not bpy.app.background and bpy.context.window is not None:
        bpy.ops.talus.select_head('INVOKE_DEFAULT')
    else:
        run_chosen_head("inmoov")
