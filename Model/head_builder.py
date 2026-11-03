"""
Will Cogley Animatronic Head
3MF Geometry + Reference-Guided Head Rig
==================================================================

VISIBLE GEOMETRY SOURCE
-----------------------
BambuPrintfile.3mf

ASSEMBLY REFERENCE
------------------
Reference Assembly (Open with Microsoft 3D Viewer or Blender).obj

The OBJ is NOT imported as visible geometry.

The supplied OBJ was used offline to solve the rigid rest-pose transform of
each corresponding printed 3MF component. Those transforms are embedded in
this script. Blender therefore builds the head from the individual 3MF meshes
but places them at the assembled positions defined by the full Onshape OBJ.

78 selected 3MF component volumes are used in the reference-guided assembly.

Duplicate print copies, obsolete alternatives, and 3MF parts that have no
direct OBJ assembly counterpart are deliberately omitted instead of guessed.

RIG
---
All matched 3MF components remain separate Blender objects.

Static structure follows HEAD_ROLL.

Independent functional groups:
    left/right eyeballs
    left/right upper/lower eyelids and linkage pieces
    jaw/lower mouth
    left/right brow linkage
    left/right upper lip linkage
    left/right lower lip linkage

So moving one facial control no longer rigidly moves the entire head.

Coordinate system:
    X  = left/right
    -Y = forward / face
    +Z = up
    numeric coordinates = millimetres

Target: Blender 5.x / recent Blender 4.x
"""

import bpy
import math
import json
import os
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from mathutils import Matrix, Vector


# ============================================================================
# USER CONFIG
# ============================================================================

SOURCE_3MF = r""

PREFERRED_3MF_NAMES = ("BambuPrintfile.3mf",)

# Servo bodies are not present as printable 3MF parts.  V7 therefore includes
# a small servo-only extraction from the supplied authoritative assembly OBJ.
SERVO_REFERENCE_FILENAME = "servos.obj"
BROW_REFERENCE_FILENAME = "eyebrows.obj"
REFERENCE_DATA_FILENAME = "reference.json"
SERVO_OBJ_TO_MM = 1000.0
BROW_OBJ_TO_MM = 1000.0

# The full OBJ contains 17 servo bodies.  Its two high brow MG90 bodies are
# present only on negative X, so two positive-X brow servo bodies are mirrored
# explicitly to complete the bilateral mechanism.
MIRROR_MISSING_LEFT_BROW_SERVOS = True

# ---------------------------------------------------------------------------
# FLEXIBLE EYEBROWS
# ---------------------------------------------------------------------------
ENABLE_FLEXIBLE_EYEBROWS = True

# Two identical top-level Eyebrows.stl copies in the supplied 3MF.
BROW_SOURCE_OBJECT_IDS = (137, 138)

# Eyebrows.stl is ~84 mm long, ~14.8 mm curved in its print plane, and
# ~2.54 mm thick.  +90° about X maps that print plane into the forehead X/Z
# plane while keeping thickness primarily along the front/back Y axis.
BROW_ROT_X_DEG = 90.0

# Rest placement is derived from the OBJ-referenced eye and brow mechanism.
BROW_EYE_RADIUS_MM = 16.5
BROW_FORWARD_CLEARANCE_MM = 2.5
BROW_ABOVE_EYE_MM = 10.0

# V7 keeps the exact V3 object transform (the placement that looked correct)
# but restores the strong forehead wrap implied by the V4/reference mechanism.
# The reference curve produces roughly 20-22 mm of front/back curvature at its
# deepest point; only the RELATIVE curvature profile is reused, never V4's
# misplaced absolute coordinates.
BROW_NEUTRAL_VERTICAL_ARCH_MM = 7.5
BROW_REFERENCE_CURVE_SAMPLES = 72

# Differential motion creates visible living-hinge flex.
BROW_INNER_TRAVEL_MM = 7.0
BROW_MID_TRAVEL_MM = 5.0
BROW_OUTER_TRAVEL_MM = 2.5

# Inner / mid / outer deformation anchor spacing along the 84 mm strip.
BROW_ANCHOR_HALF_SPAN_MM = 34.0

REFERENCE_OBJ_DESCRIPTION = (
    "Reference Assembly (Open with Microsoft 3D Viewer or Blender).obj"
)

# The OBJ has already been used to derive the embedded transforms.
# It does not need to be selected/imported at Blender runtime.

# Mechanical animation starter ranges.
LIMITS_DEG = {
    "HEAD_YAW": (-40.0, 40.0),
    "HEAD_PITCH": (-22.0, 22.0),
    "HEAD_ROLL": (-15.0, 15.0),

    "JAW": (0.0, 28.0),

    "EYE_L_YAW": (-28.0, 28.0),
    "EYE_L_PITCH": (-20.0, 20.0),
    "EYE_R_YAW": (-28.0, 28.0),
    "EYE_R_PITCH": (-20.0, 20.0),

    # Blink rotations around the left/right eye axis.
    "UPPER_LID": (0.0, 26.0),
    "LOWER_LID": (-18.0, 0.0),
}

# Control-property names intentionally remain compatible with the earlier
# MediaPipe controller project.
CONTROL_DEFS = {
    "mouth_open":      (0.0, 0.0, 1.0, "Jaw / mouth open"),

    "eye_left_yaw":    (0.5, 0.0, 1.0, "Left eye horizontal"),
    "eye_left_pitch":  (0.5, 0.0, 1.0, "Left eye vertical"),
    "eye_right_yaw":   (0.5, 0.0, 1.0, "Right eye horizontal"),
    "eye_right_pitch": (0.5, 0.0, 1.0, "Right eye vertical"),

    "blink_left":      (0.0, 0.0, 1.0, "Left blink"),
    "blink_right":     (0.0, 0.0, 1.0, "Right blink"),

    "brow_left":       (0.5, 0.0, 1.0, "Left brow mechanism"),
    "brow_right":      (0.5, 0.0, 1.0, "Right brow mechanism"),

    "smile_left":      (0.5, 0.0, 1.0, "Left lip mechanism"),
    "smile_right":     (0.5, 0.0, 1.0, "Right lip mechanism"),

    # Supplementary ARTIST CONTROLS inspired by the newer Will Cogley head.
    # These are animation offsets only, NOT established physical motor linkages.
    # A neutral value of 0.5 preserves the original scene and all old scripts.
    "lip_upper_left":  (0.5, 0.0, 1.0, "Independent left upper-lip vertical offset (visual guide)"),
    "lip_upper_right": (0.5, 0.0, 1.0, "Independent right upper-lip vertical offset (visual guide)"),
    "lip_lower_left":  (0.5, 0.0, 1.0, "Independent left lower-lip vertical offset (visual guide)"),
    "lip_lower_right": (0.5, 0.0, 1.0, "Independent right lower-lip vertical offset (visual guide)"),
    "corner_left_x":  (0.5, 0.0, 1.0, "Left mouth-corner lateral motion (visual guide)"),
    "corner_right_x": (0.5, 0.0, 1.0, "Right mouth-corner lateral motion (visual guide)"),
    "corner_left_z":  (0.5, 0.0, 1.0, "Left mouth-corner vertical motion (visual guide)"),
    "corner_right_z": (0.5, 0.0, 1.0, "Right mouth-corner vertical motion (visual guide)"),

    "head_yaw":        (0.5, 0.0, 1.0, "Head yaw"),
    "head_pitch":      (0.5, 0.0, 1.0, "Head pitch"),
    "head_roll":       (0.5, 0.0, 1.0, "Head roll"),
}

CONTROL_PROPS = tuple(CONTROL_DEFS.keys())


# ============================================================================
# GENERATED NAMES
# ============================================================================

RIG_NAME = "COGLY_HEAD_RIG"

COL_ROOT = "COGLY_3MF_OBJ_ASSEMBLY"
COL_STATIC = "COGLY_01_STATIC"
COL_EYES = "COGLY_02_EYES"
COL_LIDS = "COGLY_03_LIDS"
COL_BROWS = "COGLY_04_BROW_MECHANISM"
COL_MOUTH = "COGLY_05_MOUTH"
COL_HARDWARE = "COGLY_06_SERVOS"
COL_LINK_RODS = "COGLY_06B_LINK_RODS"
COL_RIG = "COGLY_07_RIG"

SCENE_SOURCE_KEY = "COGLY_3MF_SOURCE"
SCENE_REPORT_KEY = "COGLY_3MF_OBJ_RIG_REPORT"

CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
PROD_NS = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
NS = {"m": CORE_NS}

# key = "<3MF top-level object id>:<flattened volume index>"
# R/t map raw centered 3MF vertices into the supplied OBJ assembled pose.
PART_MAP = {'91:0': {'name': '2xBottomLidLever', 'target': '2xBottomLidLever', 'occ': 55, 'role': 'LID_L_LOWER', 'R': [[1.0, 7.888e-07, -4.1557e-06], [-7.888e-07, 0.9999999999, -1.15768e-05], [4.1557e-06, 1.15769e-05, 0.9999999999]], 't': [54.3508576536, -19.317276307, -17.3624226858], 'center': [54.35085, -19.3173, -17.36235]}, '97:0': {'name': '2xBottomLidLever', 'target': '2xBottomLidLever', 'occ': 32, 'role': 'LID_R_LOWER', 'R': [[0.9999999999, -2.613e-07, -1.62891e-05], [2.615e-07, 0.9999999999, 1.47171e-05], [1.62891e-05, -1.47171e-05, 0.9999999998]], 't': [-53.8502984038, -29.5390801197, -19.0496075983], 'center': [-53.8503, -29.53905, -19.0497]}, '105:0': {'name': '2xTopLidLever', 'target': '2xTopLidLever', 'occ': 60, 'role': 'LID_R_UPPER', 'R': [[0.9999999998, 2.6412e-06, 2.06718e-05], [-2.6404e-06, 0.9999999992, -3.88317e-05], [-2.06719e-05, 3.88316e-05, 0.999999999]], 't': [-53.8502649454, -44.537573065, 18.9151690368], 'center': [-53.8503, -44.5375, 18.9154]}, '107:0': {'name': '2xTopLidLever', 'target': '2xTopLidLever', 'occ': 57, 'role': 'LID_L_UPPER', 'R': [[1.0, 2.4269e-06, 4.296e-06], [-2.427e-06, 0.9999999999, 1.37235e-05], [-4.296e-06, -1.37235e-05, 0.9999999999]], 't': [54.350857538, -38.0657241781, 20.5691292436], 'center': [54.35085, -38.06575, 20.56905]}, '123:0': {'name': '4xTopLidHorn', 'target': '4xTopLidHorn', 'occ': 30, 'role': 'LID_L_UPPER', 'R': [[-0.9999999989, 4.4119e-05, 1.28307e-05], [4.41153e-05, 0.9999999556, -0.00029463], [-1.28437e-05, -0.0002946294, -0.9999999565]], 't': [54.7999566015, -23.4017419719, 10.6892503435], 'center': [54.8, -23.4, 10.6895]}, '117:0': {'name': '4xTopLidHorn', 'target': '4xTopLidHorn', 'occ': 29, 'role': 'LID_R_UPPER', 'R': [[-0.9999999989, 4.40268e-05, 1.28308e-05], [4.40231e-05, 0.9999999556, -0.000294693], [-1.28437e-05, -0.0002946924, -0.9999999565]], 't': [-54.7999566799, 6.6017176239, -10.6892503026], 'center': [-54.8, 6.599975, -10.6895]}, '119:0': {'name': '4xTopLidHorn', 'target': '4xTopLidHorn', 'occ': 31, 'role': 'LID_R_UPPER', 'R': [[-0.9999999998, -1.67476e-05, -9.3397e-06], [-1.67456e-05, 0.9999999769, -0.0002142949], [9.3433e-06, -0.0002142948, -0.999999977]], 't': [-54.7999812274, -23.401309186, 10.6893184088], 'center': [-54.8, -23.4, 10.6895]}, '121:0': {'name': '4xTopLidHorn', 'target': '4xTopLidHorn', 'occ': 28, 'role': 'LID_L_UPPER', 'R': [[-0.9999999991, -3.80334e-05, -1.6308e-05], [-3.80285e-05, 0.9999999542, -0.0003001156], [1.63194e-05, -0.0003001149, -0.9999999548]], 't': [54.7999601088, 6.6017684023, -10.6892317788], 'center': [54.8, 6.599975, -10.6895]}, '77:0': {'name': 'Base', 'target': 'Base', 'occ': 36, 'role': 'HEAD', 'R': [[0.9999999994, -8.6902e-06, -3.32889e-05], [8.6868e-06, 0.9999999946, -0.0001039774], [3.32898e-05, 0.0001039771, 0.999999994]], 't': [-58.5498314591, -41.5691357121, -10.5942167079], 'center': [-58.55, -41.5689, -10.59673]}, '81:0': {'name': 'Base', 'target': 'Base', 'occ': 37, 'role': 'HEAD', 'R': [[0.9999999994, 8.6902e-06, 3.32889e-05], [-8.6868e-06, 0.9999999946, -0.0001039774], [-3.32898e-05, 0.0001039771, 0.999999994]], 't': [58.5498314591, -41.5691357121, -10.5942167079], 'center': [58.55, -41.5689, -10.59673]}, '85:0': {'name': 'Base', 'target': 'Base', 'occ': 49, 'role': 'HEAD', 'R': [[1.0, -1.737e-07, 3.0609e-06], [1.754e-07, 0.9999998448, -0.0005572011], [-3.0608e-06, 0.0005572011, 0.9999998448]], 't': [13.4500003774, -41.5701489697, -10.5840382109], 'center': [13.45, -41.5689, -10.59673]}, '87:0': {'name': 'Base', 'target': 'Base', 'occ': 33, 'role': 'HEAD', 'R': [[0.9999999999, -4.7896e-06, -9.9857e-06], [4.7833e-06, 0.9999998017, -0.0006297447], [9.9887e-06, 0.0006297446, 0.9999998017]], 't': [-13.5500656536, -41.5703115765, -10.5823858324], 'center': [-13.55, -41.5689, -10.59673]}, '115:0': {'name': 'CentralServoHorn', 'target': 'CentralServoHorn', 'occ': 54, 'role': 'HEAD', 'R': [[0.9999999755, -0.0002210688, -1.39659e-05], [0.0002210688, 0.9999999756, -2.959e-07], [1.39659e-05, 2.928e-07, 0.9999999999]], 't': [0.0016429461, -61.0356268202, 10.549980745], 'center': [0.0, -61.0355, 10.55]}, '135:0': {'name': 'CheekBone', 'target': 'CheekBone', 'occ': 27, 'role': 'HEAD', 'R': [[0.999996914, 0.0024226233, -0.0005503147], [-0.0024225922, 0.9999970639, 5.72208e-05], [0.0005504517, -5.58875e-05, 0.9999998469]], 't': [0.002825399, -47.1293710699, -20.1563271885], 'center': [0.0, -47.041265, -20.170549]}, '125:0': {'name': 'EyeAdaptor', 'target': 'EyeAdaptor', 'occ': 41, 'role': 'HEAD', 'R': [[0.9999999985, -4.83851e-05, -2.64491e-05], [4.83855e-05, 0.9999999987, 1.38551e-05], [2.64484e-05, -1.38563e-05, 0.9999999996]], 't': [-37.4998007262, -68.7000031976, -5.4999429328], 'center': [-37.5, -68.7, -5.5]}, '109:0': {'name': 'EyeAdaptor', 'target': 'EyeAdaptor', 'occ': 62, 'role': 'HEAD', 'R': [[0.9999999951, -9.65245e-05, -2.29413e-05], [9.65254e-05, 0.9999999944, 4.26574e-05], [2.29372e-05, -4.26596e-05, 0.9999999988]], 't': [-37.5002891504, -61.7887700908, 6.3504043805], 'center': [-37.5, -61.7888, 6.35]}, '9:0': {'name': 'EyeCorePivotHolder', 'target': 'EyeCorePivotHolder', 'occ': 39, 'role': 'HEAD', 'R': [[0.9999999996, 2.37725e-05, 1.71285e-05], [-2.37649e-05, 0.9999999006, -0.0004451376], [-1.71391e-05, 0.0004451372, 0.9999999008]], 't': [0.0002359076, -63.4540325106, 6.2141277223], 'center': [0.0, -63.45, 6.20935]}, '7:3': {'name': 'FrontPlate', 'target': 'FrontPlate', 'occ': 10, 'role': 'HEAD', 'R': [[0.999999998, -4.91046e-05, -3.91811e-05], [4.91031e-05, 0.9999999981, -3.75817e-05], [3.9183e-05, 3.75798e-05, 0.9999999985]], 't': [0.0001879981, -55.081833787, 104.3038575771], 'center': [0.0003, -55.0812, 104.30335]}, '7:2': {'name': 'FrontVent', 'target': 'FrontVent', 'occ': 26, 'role': 'HEAD', 'R': [[0.9996525647, -0.0249482454, -0.0085049999], [0.02501135, 0.9996598089, 0.0073958724], [0.0083175925, -0.0076060244, 0.999936481]], 't': [0.1733745612, -9.942740143, 97.4211320042], 'center': [0.0, -9.849, 96.9203]}, '51:1': {'name': 'JawBase', 'target': 'JawBase', 'occ': 113, 'role': 'JAW', 'R': [[0.9999999853, 0.0001475121, 8.71541e-05], [-0.0001489848, 0.9998529786, 0.0171463973], [-8.4612e-05, -0.01714641, 0.9998529859]], 't': [-0.123179017, -38.1175103522, -87.8246049577], 'center': [-0.12, -38.147714, -88.2265]}, '51:3': {'name': 'JawLink', 'target': 'JawLink', 'occ': 172, 'role': 'JAW', 'R': [[0.9993266645, -0.0038427237, 0.0364890537], [0.0046442345, 0.9997492368, -0.0219064952], [-0.036395723, 0.0220612085, 0.9990939167]], 't': [38.1912317337, -6.8605098137, -66.5739127762], 'center': [38.3139, -6.83413, -66.8055]}, '16:0': {'name': 'LidBR', 'target': 'LidBR', 'occ': 58, 'role': 'LID_R_UPPER', 'R': [[-0.9981878173, -0.0529495289, -0.0285907117], [0.0561014157, -0.647012595, -0.7604126071], [0.0217649387, -0.7606385799, 0.6488106335]], 't': [-37.5575381989, -70.6677114503, 11.1059251511], 'center': [-37.912, -74.83085, 7.83063]}, '22:0': {'name': 'LidBR', 'target': 'LidBR', 'occ': 50, 'role': 'LID_L_UPPER', 'R': [[-0.9967172349, 0.0697893477, 0.0410390136], [-0.0752355219, -0.6111729106, -0.7879132501], [-0.0299060184, -0.7884143075, 0.6144172115]], 't': [37.4372188906, -70.744240734, 11.0827444731], 'center': [37.912, -74.83085, 7.83063]}, '54:0': {'name': 'LidTR', 'target': 'LidTR', 'occ': 38, 'role': 'LID_R_LOWER', 'R': [[0.9964109359, 0.0817872178, 0.0218196667], [-0.0839620735, 0.9876833472, 0.1320302084], [-0.0107525381, -0.1333883679, 0.9910055127]], 't': [-38.3766935312, -76.2506119371, -6.8217376005], 'center': [-37.6753, -74.831, -7.8302]}, '57:0': {'name': 'LidTR', 'target': 'LidTR', 'occ': 48, 'role': 'LID_L_LOWER', 'R': [[0.9986826482, -0.0484326616, -0.0169483151], [0.0500209975, 0.9925464239, 0.1111282875], [0.0114397508, -0.1118296641, 0.9936615411]], 't': [38.0891008407, -75.8368516177, -7.0054374421], 'center': [37.6753, -74.831, -7.8302]}, '51:10': {'name': 'LowerLeftLip', 'target': 'LowerLeftLip', 'occ': 138, 'role': 'LIP_L_LOWER', 'R': [[0.9994670319, -0.0033595977, -0.03247099], [0.0022587691, 0.9994233784, -0.0338793251], [0.0325660874, 0.033787924, 0.9988983062]], 't': [20.2595128564, -69.9727478643, -88.2031153238], 'center': [20.325875, -70.0323, -87.6987]}, '65:0': {'name': 'Part 12', 'target': 'Part 12', 'occ': 12, 'role': 'BROW_L', 'R': [[0.9874898427, 0.1347621871, -0.0818716285], [-0.1342330014, 0.9908776318, 0.011959104], [0.0827364003, -0.0008196193, 0.9965711296]], 't': [31.3622136133, -78.8311819638, 49.6207356379], 'center': [30.33925, -77.34065, 49.3966]}, '20:0': {'name': 'Part 13', 'target': 'Part 13', 'occ': 4, 'role': 'BROW_L', 'R': [[0.9988943078, -0.0467877577, 0.0045899405], [0.0466949658, 0.998736318, 0.0185835217], [-0.0054536216, -0.0183486469, 0.9998167758]], 't': [61.1559201552, -46.5755150117, 44.4811174317], 'center': [61.44875, -46.2604, 44.5879]}, '51:16': {'name': 'Part 19', 'target': 'Part 19', 'occ': 92, 'role': 'JAW', 'R': [[0.9999999989, -2.85649e-05, 3.61682e-05], [3.62221e-05, 0.9723439088, -0.2335536804], [-2.84965e-05, 0.2335536815, 0.9723439088]], 't': [6.3204999998, -55.732599109, -85.56385], 'center': [6.3205, -55.7326, -85.56385]}, '75:0': {'name': 'Part 2', 'target': 'Part 2', 'occ': 73, 'role': 'BROW_L', 'R': [[0.9999999965, 4.0367e-06, -8.36758e-05], [-4.0195e-06, 0.9999999788, 0.000205982], [8.36766e-05, -0.0002059816, 0.9999999753]], 't': [16.05, -63.2455, 65.5174499999], 'center': [16.05, -63.2455, 65.51745]}, '89:0': {'name': 'Part 2', 'target': 'Part 2', 'occ': 71, 'role': 'BROW_R', 'R': [[0.9999999965, -4.9667e-06, -8.3584e-05], [4.984e-06, 0.9999999788, 0.0002059226], [8.3583e-05, -0.000205923, 0.9999999753]], 't': [-62.65, -28.2358499999, 66.1617999998], 'center': [-62.65, -28.23585, 66.1618]}, '95:0': {'name': 'Part 2', 'target': 'Part 2', 'occ': 74, 'role': 'BROW_R', 'R': [[0.9999999881, -4.1744e-06, -0.0001542364], [4.1333e-06, 0.9999999645, -0.0002663854], [0.0001542375, 0.0002663847, 0.9999999526]], 't': [-14.45, -63.24775, 65.5847999999], 'center': [-14.45, -63.24775, 65.5848]}, '99:0': {'name': 'Part 2', 'target': 'Part 2', 'occ': 70, 'role': 'BROW_L', 'R': [[0.9999999965, -8.2472e-06, -8.31927e-05], [8.2301e-06, 0.9999999787, -0.000206204], [8.31944e-05, 0.0002062033, 0.9999999753]], 't': [63.05, -28.2259999999, 66.2863000002], 'center': [63.05, -28.226, 66.2863]}, '51:15': {'name': 'Part 20', 'target': 'Part 20', 'occ': 82, 'role': 'JAW', 'R': [[0.9999984527, -0.0007013256, -0.0016132762], [0.0003044214, 0.972246428, -0.2339589506], [0.0017325835, 0.2339580975, 0.9722451372]], 't': [-12.7950922279, -7.739374545, -86.3693], 'center': [-12.8, -7.739375, -86.3693]}, '51:6': {'name': 'Part 21', 'target': 'Part 21', 'occ': 164, 'role': 'JAW', 'R': [[0.999999975, 3.26751e-05, 0.0002210089], [-3.62948e-05, 0.9998655509, 0.0163975241], [-0.0002204434, -0.0163975317, 0.9998655271]], 't': [-2.6749331831, -26.6227838267, -76.806486267], 'center': [-2.675, -26.665885, -77.0397]}, '51:26': {'name': 'Part 27', 'target': 'Part 27', 'occ': 148, 'role': 'LIP_L_LOWER', 'R': [[0.9999994683, -0.0009528968, 0.0003941713], [0.0010173745, 0.9740610623, -0.2262830349], [-0.0001683225, 0.2262833157, 0.9740615138]], 't': [34.2840519465, -50.0110018507, -95.25275], 'center': [34.2764, -50.011, -95.25275]}, '51:24': {'name': 'Part 28', 'target': 'Part 28', 'occ': 160, 'role': 'LIP_L_LOWER', 'R': [[0.9999999875, -0.0001045848, 0.0001188664], [0.0001287262, 0.974167753, -0.2258255353], [-9.21779e-05, 0.2258255477, 0.9741677543]], 't': [31.1630934866, -50.0229913661, -83.2779075254], 'center': [31.1636, -50.023, -83.2779]}, '51:11': {'name': 'Part 29', 'target': 'Part 29', 'occ': 171, 'role': 'LIP_L_UPPER', 'R': [[0.9999999992, 9.6579e-06, -3.99137e-05], [-7.5604e-06, 0.9986355894, 0.0522202979], [4.03636e-05, -0.0522202976, 0.9986355886]], 't': [37.2784035829, -55.7207297153, -69.1334550358], 'center': [37.2785, -55.81445, -69.57115]}, '83:0': {'name': 'Part 3', 'target': 'Part 3', 'occ': 78, 'role': 'BROW_R', 'R': [[0.9999996009, 0.0008588339, 0.0002462269], [-0.0008589429, 0.999999533, 0.0004429217], [-0.0002458463, -0.000443133, 0.9999998716]], 't': [-64.1550642746, -27.9888, 50.2476687687], 'center': [-64.15, -27.9888, 50.2473]}, '79:0': {'name': 'Part 3', 'target': 'Part 3', 'occ': 67, 'role': 'BROW_L', 'R': [[0.9999996048, -0.0008253931, 0.0003304562], [0.0008255017, 0.9999996053, -0.0003285958], [-0.0003301849, 0.0003288685, 0.9999998914]], 't': [64.5550822565, -28.03745, 50.1561999997], 'center': [64.55, -28.03745, 50.1562]}, '71:0': {'name': 'Part 3', 'target': 'Part 3', 'occ': 65, 'role': 'BROW_L', 'R': [[0.999999603, 0.0008502579, 0.0002665852], [-0.0008504877, 0.9999992656, 0.0008634053], [-0.0002658508, -0.0008636317, 0.9999995917]], 't': [14.7581526713, -61.7951499998, 50.7542], 'center': [14.7635, -61.79515, 50.7542]}, '93:0': {'name': 'Part 3', 'target': 'Part 3', 'occ': 72, 'role': 'BROW_R', 'R': [[0.9999995983, -0.0008797555, 0.000171671], [0.0008798894, 0.9999993076, -0.0007814414], [-0.0001709834, 0.0007815921, 0.9999996799]], 't': [-12.9447514317, -63.24775, 49.5845435247], 'center': [-12.95, -63.24775, 49.5848]}, '51:7': {'name': 'Part 30', 'target': 'Part 30', 'occ': 98, 'role': 'LIP_L_UPPER', 'R': [[0.9999999906, 9.2232e-05, -0.0001015514], [-9.53467e-05, 0.9995159502, -0.0311103881], [9.86328e-05, 0.0311103975, 0.9995159496]], 't': [39.1998077927, -42.7830519551, -50.4214002881], 'center': [39.2, -42.7835, -50.42135]}, '51:17': {'name': 'Part 31', 'target': 'Part 31', 'occ': 157, 'role': 'LIP_L_UPPER', 'R': [[0.9999991513, -0.0011949373, 0.0005191092], [0.0011711383, 0.9990461089, 0.0436520417], [-0.0005707755, -0.0436513967, 0.9990466605]], 't': [44.2749989176, -25.6039364755, -39.4596328013], 'center': [44.275, -25.60195, -39.46]}, '51:13': {'name': 'Part 32', 'target': 'Part 32', 'occ': 130, 'role': 'LIP_L_UPPER', 'R': [[0.9999987262, -0.0015544266, -0.0003623405], [0.001518622, 0.9964860201, -0.0837454809], [0.0004912434, 0.083744824, 0.9964871114]], 't': [41.675000298, -30.2375371308, -67.8517438346], 'center': [41.675, -30.2354, -67.8515]}, '51:2': {'name': 'Part 33', 'target': 'Part 33', 'occ': 111, 'role': 'JAW', 'R': [[0.9986558442, 0.0036564985, -0.0517023673], [-0.0056735406, 0.9992262311, -0.0389197893], [0.0515200515, 0.0391608105, 0.9979038607]], 't': [-38.3540758957, -6.8684650735, -66.4553838921], 'center': [-38.5539, -6.83413, -66.8055]}, '51:4': {'name': 'Part 34', 'target': 'Part 34', 'occ': 174, 'role': 'LIP_R_UPPER', 'R': [[0.9999588349, 0.0090691107, 0.0002825133], [-0.0090690253, 0.9999588299, -0.0003020132], [-0.0002852407, 0.0002994387, 0.9999999145]], 't': [-19.5963830253, -77.0614321876, -49.2268075862], 'center': [-19.64244, -77.0508, -49.2267]}, '51:22': {'name': 'Part 35', 'target': 'Part 35', 'occ': 106, 'role': 'LIP_R_UPPER', 'R': [[0.9999996739, 0.0007046949, 0.000394577], [-0.000772775, 0.9768645463, 0.2138575718], [-0.000234744, -0.213857807, 0.9768647723]], 't': [-34.9714001806, -59.3696714143, -36.1234071168], 'center': [-34.9714, -59.3689, -36.123]}, '51:19': {'name': 'Part 36', 'target': 'Part 36', 'occ': 146, 'role': 'LIP_R_UPPER', 'R': [[0.9999999727, 0.000163774, 0.0001665396], [-0.000195548, 0.9769531438, 0.213453781], [-0.0001277432, -0.2134538078, 0.9769531491]], 't': [-32.8085000003, -59.3751902224, -48.0954440204], 'center': [-32.8085, -59.3752, -48.09545]}, '51:9': {'name': 'Part 37', 'target': 'Part 37', 'occ': 156, 'role': 'LIP_R_LOWER', 'R': [[0.9994405908, 0.000353135, 0.0334421995], [0.0011694151, 0.998963777, -0.0454973049], [-0.0334236126, 0.0455109612, 0.9984045345]], 't': [-20.2613083587, -69.569927529, -88.8014091774], 'center': [-20.325875, -69.65585, -88.20375]}, '51:25': {'name': 'Part 38', 'target': 'Part 38', 'occ': 183, 'role': 'LIP_R_LOWER', 'R': [[0.9999969764, -3.65051e-05, -0.0024588128], [-0.0005502891, 0.9712107372, -0.2382213281], [0.0023967217, 0.2382219608, 0.9712077806]], 't': [-35.4026429992, -49.4643518453, -95.5366004538], 'center': [-35.3964, -49.46435, -95.5366]}, '51:23': {'name': 'Part 39', 'target': 'Part 39', 'occ': 177, 'role': 'LIP_R_LOWER', 'R': [[0.9999999857, 0.0001492886, -7.9564e-05], [-0.0001638014, 0.9720175689, -0.2349081072], [4.22685e-05, 0.2349081169, 0.9720175795]], 't': [-32.1635999997, -49.5773890667, -83.585451666], 'center': [-32.1636, -49.5774, -83.58545]}, '12:0': {'name': 'Part 4', 'target': 'Part 4', 'occ': 77, 'role': 'HEAD', 'R': [[0.9999998695, -0.0002005644, -0.0004698731], [0.0002007964, 0.999999858, 0.0004937213], [0.000469774, -0.0004938156, 0.9999997677]], 't': [0.0052231143, -31.749695398, 49.5021419365], 'center': [0.0, -31.75, 49.5]}, '51:12': {'name': 'Part 40', 'target': 'Part 40', 'occ': 132, 'role': 'LIP_R_UPPER', 'R': [[0.9999999992, -9.6673e-06, 3.96749e-05], [7.475e-06, 0.9984925283, 0.0548878025], [-4.01457e-05, -0.0548878022, 0.9984925275]], 't': [-35.0784042335, -55.8911213843, -68.9760930023], 'center': [-35.0785, -55.98955, -69.43605]}, '51:8': {'name': 'Part 41', 'target': 'Part 41', 'occ': 181, 'role': 'LIP_R_UPPER', 'R': [[0.9999999842, -0.0001232899, 0.000127733], [0.0001265375, 0.9996685426, -0.0257446878], [-0.0001245166, 0.0257447036, 0.9996685424]], 't': [-36.9997942172, -42.8801814458, -50.3338036929], 'center': [-37.0, -42.88075, -50.33325]}, '51:18': {'name': 'Part 42', 'target': 'Part 42', 'occ': 83, 'role': 'LIP_R_UPPER', 'R': [[0.9999997747, 0.000597434, -0.0003060407], [-0.0005837537, 0.9990790529, 0.0429034412], [0.0003313908, -0.0429032529, 0.9990791766]], 't': [-44.274999666, -25.6012521649, -39.4582837889], 'center': [-44.275, -25.60025, -39.45825]}, '51:14': {'name': 'Part 43', 'target': 'Part 43', 'occ': 144, 'role': 'LIP_R_UPPER', 'R': [[0.9999996705, 0.0005322756, 0.0006129308], [-0.000487741, 0.9975118047, -0.0704979546], [-0.00064893, 0.0704976325, 0.9975117356]], 't': [-41.6750002822, -30.312833586, -67.7663350459], 'center': [-41.675, -30.3115, -67.7661]}, '61:0': {'name': 'Part 8', 'target': 'Part 8', 'occ': 68, 'role': 'BROW_R', 'R': [[0.9999813166, -0.0060005638, 0.0011660835], [0.006007595, 0.9999632095, -0.006122789], [-0.0011293004, 0.0061296799, 0.9999805757]], 't': [-30.1364689751, -78.2306411197, 49.4174332277], 'center': [-30.1257, -78.1002, 49.40775]}, '59:0': {'name': 'Part 9', 'target': 'Part 9', 'occ': 76, 'role': 'BROW_R', 'R': [[0.9999977558, -0.0017677706, 0.0011676265], [0.0017673329, 0.9999983677, 0.0003757369], [-0.0011682888, -0.0003736725, 0.9999992477]], 't': [-59.9431276409, -46.2643206812, 44.2505922867], 'center': [-59.9267, -46.25405, 44.2548]}, '7:0': {'name': 'RearPlate', 'target': 'RearPlate', 'occ': 7, 'role': 'HEAD', 'R': [[0.9999987806, -0.0013061167, 0.0008560149], [0.0013051354, 0.9999984918, 0.0011458805], [-0.0008575103, -0.0011447619, 0.9999989771]], 't': [-0.0105153313, 58.0314450656, 47.0037482634], 'center': [0.0, 57.948143, 46.97875]}, '7:1': {'name': 'RearVent', 'target': 'RearVent', 'occ': 9, 'role': 'HEAD', 'R': [[0.8990684677, 0.1484131611, -0.4118852073], [-0.148362808, 0.9884053641, 0.032300364], [0.4119033474, 0.0320682071, 0.9106630894]], 't': [-0.1628815818, 95.1847943813, 64.4771650052], 'center': [0.0032, 95.4136, 64.49955]}, '67:0': {'name': 'SnapEyemech v20', 'target': 'SnapEyemech v20', 'occ': 45, 'role': 'HEAD', 'R': [[0.9999760484, 0.004804362, -0.0049820361], [-0.004794362, 0.9999864724, 0.0020172216], [0.0049916602, -0.0019932876, 0.999985555]], 't': [-42.3548694113, -6.7745133163, -5.8424746539], 'center': [-42.35, -6.784, -5.8455]}, '69:0': {'name': 'SnapEyemech v20', 'target': 'SnapEyemech v20', 'occ': 59, 'role': 'HEAD', 'R': [[0.9999972424, 0.001457214, -0.0018416506], [-0.0014533238, 0.9999967138, 0.0021119166], [0.001844722, -0.0021092343, 0.9999960741]], 't': [42.6484214465, -6.7740679802, -5.8422986739], 'center': [42.65, -6.784, -5.8455]}, '103:0': {'name': 'SnapEyemech v20', 'target': 'SnapEyemech v20', 'occ': 34, 'role': 'HEAD', 'R': [[-0.9999999691, -0.0002443278, 4.5019e-05], [0.0002443311, -0.9999999675, 7.3129e-05], [4.50011e-05, 7.314e-05, 0.9999999963]], 't': [3.1504755467, -23.398958241, -5.8952636758], 'center': [3.15, -23.4, -5.8955]}, '51:0': {'name': 'TopBase', 'target': 'TopBase', 'occ': 188, 'role': 'HEAD', 'R': [[0.999999661, 0.0004483189, 0.0006906794], [-0.000447836, 0.9999996553, -0.0006991658], [-0.0006909926, 0.0006988562, 0.9999995171]], 't': [-0.0135062825, -29.4721979652, -52.0457826792], 'center': [0.0, -29.48, -52.0233]}, '51:21': {'name': 'ULLLinkA', 'target': 'ULLLinkA', 'occ': 159, 'role': 'LIP_L_UPPER', 'R': [[0.9999996272, -0.0007128248, -0.0004872917], [0.0008003491, 0.9769934676, 0.2132677276], [0.0003240583, -0.2132680381, 0.9769936739]], 't': [33.9713996708, -59.3697106639, -36.1235341895], 'center': [33.9714, -59.3689, -36.123]}, '51:20': {'name': 'ULLLinkB', 'target': 'ULLLinkB', 'occ': 93, 'role': 'LIP_L_UPPER', 'R': [[0.9999999727, -0.000163774, -0.0001665396], [0.000195548, 0.9769531438, 0.213453781], [0.0001277432, -0.2134538078, 0.9769531491]], 't': [31.8085000003, -59.3751902224, -48.0954440204], 'center': [31.8085, -59.3752, -48.09545]}, '51:5': {'name': 'UpperLeftLip', 'target': 'UpperLeftLip', 'occ': 105, 'role': 'LIP_L_UPPER', 'R': [[0.9999879346, -0.0047503466, -0.0012509333], [0.0047492725, 0.9999883521, -0.0008602531], [0.0012550052, 0.0008543017, 0.9999988476]], 't': [19.608488792, -77.0615656207, -49.2280069656], 'center': [19.64244, -77.0508, -49.2267]}, '113:0': {'name': 'VerticalHorn', 'target': 'VerticalHorn', 'occ': 47, 'role': 'HEAD', 'R': [[0.9999999988, 4.8558e-05, -4.716e-06], [-4.85578e-05, 0.999999998, 4.15095e-05], [4.718e-06, -4.15092e-05, 0.9999999991]], 't': [-12.6999008001, -23.4004790657, 8.6894890453], 'center': [-12.7, -23.4, 8.6895]}, '101:0': {'name': 'VerticalLever', 'target': 'VerticalLever', 'occ': 56, 'role': 'HEAD', 'R': [[0.9999999997, 7.057e-07, 2.41474e-05], [-7.038e-07, 0.9999999971, -7.67932e-05], [-2.41475e-05, 7.67932e-05, 0.9999999968]], 't': [-11.7499937639, -46.0511218927, 23.8303805762], 'center': [-11.75, -46.0506, 23.8297]}, '142:0': {'name': 'TheHeadFrame.stl', 'target': 'SkullFrame', 'occ': 0, 'role': 'HEAD', 'R': [[0.9999232972, -0.0072245914, 0.0100600689], [0.0112554266, 0.8690155419, -0.4946567531], [-0.0051686633, 0.4947320419, 0.8690302018]], 't': [-0.044429895, 24.1295991914, 30.7458741698], 'center': [0.0, 16.76105, 23.44985]}, '140:0': {'name': 'EyeModule.stl', 'target': 'SnapEyemech v20', 'occ': 44, 'role': 'HEAD', 'R': [[0.9999999941, -0.0001018526, 3.64673e-05], [0.0001018535, 0.9999999945, -2.49454e-05], [-3.64648e-05, 2.49492e-05, 0.999999999]], 't': [-0.0006537168, -0.937998574, -11.1447382816], 'center': [0.0, -0.9394, -11.1455]}, '133:0': {'name': 'MouthAssembly - Part 1 (1).stl', 'target': 'Part 1', 'occ': 154, 'role': 'HEAD', 'R': [[0.9999991649, 0.0012480694, 0.0003355735], [-0.0012485517, 0.9999981826, 0.001440795], [-0.0003337747, -0.0014412128, 0.9999989057]], 't': [-0.0200743436, -61.6709731774, -59.6148454088], 'center': [5e-05, -61.65115, -59.61065]}, '130:0': {'name': 'MouthAssembly - Part 1 (2).stl', 'target': 'Part 1', 'occ': 134, 'role': 'JAW', 'R': [[0.9999985234, 0.0016234584, 0.0005636224], [-0.0016294476, 0.9999404201, 0.0107935671], [-0.000546066, -0.0107944695, 0.9999415889]], 't': [-0.0206921937, -61.4694301814, -81.5281872702], 'center': [-0.0005, -61.45965, -81.68365]}, '130:1': {'name': 'MouthAssembly - Part 1 (3).stl', 'target': 'Part 1', 'occ': 170, 'role': 'JAW', 'R': [[0.9999982415, 0.000323552, -0.0018472493], [-0.000295753, 0.9998870094, 0.015029335], [0.0018519034, -0.0150287623, 0.9998853468]], 't': [0.0063068657, -64.1663561235, -78.4449093808], 'center': [5e-05, -64.11985, -78.4845]}, '133:1': {'name': 'MouthAssembly - Part 1.stl', 'target': 'Part 1', 'occ': 150, 'role': 'HEAD', 'R': [[0.9999987455, -0.0010945865, 0.0011449721], [0.0010951226, 0.999999291, -0.0004676551], [-0.0011444594, 0.0004689084, 0.9999992352]], 't': [0.0219361297, -63.8208033215, -65.3197029277], 'center': [0.00035, -63.80895, -65.3107]}, '23:0': {'name': 'CameraEye.stl', 'target': 'Component74', 'occ': 53, 'role': 'EYE_R', 'R': [[0.9999672129, 0.0078861038, 0.001839157], [-0.0076377578, 0.9939754813, -0.1093362121], [-0.0026903137, 0.1093185803, 0.9940031238]], 't': [-37.5186062446, -72.552887024, -0.2918390969], 'center': [-37.49685, -73.0501, 0.0]}, '10:0': {'name': 'DecoyEye.stl', 'target': 'Component74', 'occ': 46, 'role': 'EYE_L', 'R': [[0.9999907786, 0.0009786137, -0.0041815024], [-0.0013462545, 0.9960446911, -0.0888434627], [0.0040780199, 0.0888482728, 0.9960368237]], 't': [37.5002939904, -72.6447894167, -0.2374433964], 'center': [37.50315, -73.0501, 0.0]}}



# V10: these Part2 pieces are support/pivot geometry in the reference assembly,
# not serial moving links between Part3 and the installed eyebrow.
for _key in ['75:0', '99:0', '95:0', '89:0']:
    if _key in PART_MAP:
        PART_MAP[_key]["role"] = "HEAD"

# Correct the role labels of the two lower eyelid horns.  These were once
# copied from the upper horns, although their bones were already correct.
# This does not move a mesh or modify its kinematics.
PART_MAP["121:0"]["role"] = "LID_L_LOWER"
PART_MAP["117:0"]["role"] = "LID_R_LOWER"

# ---------------------------------------------------------------------------
# SOURCE-ASSEMBLY CORRECTIONS
# ---------------------------------------------------------------------------
# Correct lower-left 2xBottomLidLever duplicate selection.
PART_MAP["91:0"]["occ"] = 42
PART_MAP["91:0"]["t"] = [
    53.8503076536,
    -29.5390263070,
    -19.0497726858,
]
PART_MAP["91:0"]["center"] = [
    53.8503,
    -29.53905,
    -19.0497,
]

# The reference OBJ positioned the positive-X upper lid lever off its
# mirrored mounting axis. The lever mesh itself is essentially unrotated,
# and its counterpart on negative X supplies a better neutral datum.
# Move the *whole printed lever*, not merely its IK pivots.
# (LINK_HOLE_PAIRS is corrected below from the same mirrored datum.)
_L_UPPER_LEVER_DELTA = (
    -0.500901, -6.471751, -1.652849,
)
for _coord in ("t", "center"):
    PART_MAP["107:0"][_coord] = [
        v + dv for v, dv in zip(
            PART_MAP["107:0"][_coord], _L_UPPER_LEVER_DELTA
        )
    ]

# ============================================================================
# PIVOT-HOLE-ACCURATE KINEMATIC CHAINS
# ============================================================================

# Ordered source-mesh entries used by the Blender *animation proxy*.
# Only the matching pivot locations can be treated as true source-hole centers.
# Nonadjacent vertices and VLINK spans do not prove an actual serial linkage.
KINEMATIC_CHAINS = [{'name': 'LID_L_UPPER',
  'mesh_keys': ['123:0', '107:0'],
  'target_parent': 'LID_L_UPPER',
  'root_parent': 'HEAD_ROLL',
  'source_note': 'OBJ horn center + top-lever rear/front extents'},
 {'name': 'LID_L_LOWER',
  'mesh_keys': ['121:0', '91:0'],
  'target_parent': 'LID_L_LOWER',
  'root_parent': 'HEAD_ROLL',
  'source_note': 'OBJ horn center + bottom-lever rear/front extents'},
 {'name': 'LID_R_UPPER',
  'mesh_keys': ['119:0', '105:0'],
  'target_parent': 'LID_R_UPPER',
  'root_parent': 'HEAD_ROLL',
  'source_note': 'OBJ horn center + top-lever rear/front extents'},
 {'name': 'LID_R_LOWER',
  'mesh_keys': ['117:0', '97:0'],
  'target_parent': 'LID_R_LOWER',
  'root_parent': 'HEAD_ROLL',
  'source_note': 'OBJ horn center + bottom-lever rear/front extents'},
 {'name': 'BROW_L_INNER',
  'mesh_keys': ['71:0', '65:0'],
  'target_parent': 'BROW_L',
  'root_parent': 'HEAD_ROLL',
  'source_note': 'V10 direct reference contact trace; Part2 support removed from serial chain',
  'inferred_root': True},
 {'name': 'BROW_L_OUTER',
  'mesh_keys': ['79:0', '20:0'],
  'target_parent': 'BROW_L_OUTER',
  'root_parent': 'HEAD_ROLL',
  'source_note': 'V10 direct reference contact trace; Part2 support removed from serial chain',
  'inferred_root': True},
 {'name': 'BROW_R_INNER',
  'mesh_keys': ['93:0', '61:0'],
  'target_parent': 'BROW_R',
  'root_parent': 'HEAD_ROLL',
  'source_note': 'V10 direct reference contact trace; Part2 support removed from serial chain'},
 {'name': 'BROW_R_OUTER',
  'mesh_keys': ['83:0', '59:0'],
  'target_parent': 'BROW_R_OUTER',
  'root_parent': 'HEAD_ROLL',
  'source_note': 'V10 direct reference contact trace; Part2 support removed from serial chain'},
 {'name': 'JAW_L_SIDE',
  'mesh_keys': ['51:3'],
  'target_parent': 'JAW',
  'root_parent': 'HEAD_ROLL',
  'source_note': 'OBJ left lower MG90 center -> M4 jaw pivot'},
 {'name': 'JAW_R_SIDE',
  'mesh_keys': ['51:2'],
  'target_parent': 'JAW',
  'root_parent': 'HEAD_ROLL',
  'source_note': 'OBJ right lower MG90 center -> M4 jaw pivot'},
 {'name': 'JAW_CENTER',
  'mesh_keys': ['51:15', '51:6', '51:16'],
  'target_parent': 'JAW',
  'root_parent': 'HEAD_ROLL',
  'source_note': 'OBJ central lower MG90 + Part20/21 + recovered jaw hinge'},
 {'name': 'LIP_L_UPPER_INNER',
  'mesh_keys': ['51:21', '51:20'],
  'target_parent': 'LIP_L_UPPER',
  'root_parent': 'HEAD_ROLL',
  'source_note': 'OBJ MG90 + M3/M4 shoulder pivots'},
 {'name': 'LIP_L_UPPER_OUTER',
  'mesh_keys': ['51:17', '51:7', '51:13', '51:11'],
  'target_parent': 'LIP_L_UPPER',
  'root_parent': 'HEAD_ROLL',
  'source_note': 'OBJ MG90 + four M3 shoulder pivots'},
 {'name': 'LIP_R_UPPER_INNER',
  'mesh_keys': ['51:22', '51:19'],
  'target_parent': 'LIP_R_UPPER',
  'root_parent': 'HEAD_ROLL',
  'source_note': 'OBJ MG90 + M3/M4 shoulder pivots'},
 {'name': 'LIP_R_UPPER_OUTER',
  'mesh_keys': ['51:18', '51:8', '51:14', '51:12'],
  'target_parent': 'LIP_R_UPPER',
  'root_parent': 'HEAD_ROLL',
  'source_note': 'OBJ MG90 + four M3 shoulder pivots'},
 {'name': 'LIP_L_LOWER',
  'mesh_keys': ['51:24', '51:26'],
  'target_parent': 'LIP_L_LOWER',
  'root_parent': 'JAW',
  'source_note': 'OBJ lower-left MG90 + M4/M3 shoulder pivots'},
 {'name': 'LIP_R_LOWER',
  'mesh_keys': ['51:23', '51:25'],
  'target_parent': 'LIP_R_LOWER',
  'root_parent': 'JAW',
  'source_note': 'OBJ lower-right MG90 + M4/M3 shoulder pivots'},
 {'name': 'EYE_PITCH_SHARED',
  'mesh_keys': ['115:0', '101:0', '113:0'],
  'target_parent': 'EYE_PITCH_SHARED',
  'root_parent': 'HEAD_ROLL',
  'source_note': 'OBJ CentralServoHorn -> VerticalLever -> VerticalHorn'}]

# Exact assembled hole-center pairs recovered from the matched 3MF mesh
# cylinder geometry. Coordinates are millimetres in the authoritative OBJ
# assembly frame.
LINK_HOLE_PAIRS = {'101:0': ([-11.750175, -68.702173, 17.001447], [-11.750141, -23.400789, 17.052351]),
 '105:0': ([-53.850248, -23.400729, 17.051816], [-53.850361, -66.075229, 17.035591]),
 '107:0': ([54.350901, -16.928978, 18.704665], [54.350797, -59.603479, 18.690683]),
 '113:0': ([-15.59986, -23.400705, 0.00273], [-16.749907, -23.400226, 10.027724]),
 '115:0': ([0.003342, -68.697334, 12.799979], [0.004429, -58.197376, 13.949981]),
 '117:0': ([-57.700042, 6.603811, -4.00254], [-58.849958, 6.601944, -10.527556]),
 '119:0': ([-57.700043, -23.402792, 4.002598], [-58.849982, -23.401415, 10.52761]),
 '121:0': ([57.700069, 6.603881, -4.002531], [58.849962, 6.601972, -10.527552]),
 '123:0': ([57.700042, -23.403837, 4.00254], [58.849958, -23.401972, 10.527556]),
 '20:0': ([66.514805, -54.779053, 25.257606], [59.340662, -33.966672, 66.255014]),
 '51:11': ([41.025223, -37.17309, -74.109352], [40.449775, -54.615356, -66.279252]),
 '51:12': ([-38.825223, -37.35684, -74.00152], [-38.249776, -54.778127, -66.124853]),
 '51:13': ([41.623887, -23.298989, -61.590672], [43.363613, -37.173818, -74.112854]),
 '51:14': ([-41.630073, -23.291489, -61.598041], [-43.357429, -37.333439, -73.934436]),
 '51:15': ([-13.35671, -12.791909, -93.205699], [-11.308476, -2.686491, -79.531362]),
 '51:16': ([5.995512, -50.67741, -78.730469], [6.320488, -60.787833, -92.397195]),
 '51:17': ([44.228443, -20.259051, -44.357051], [45.959052, -30.947053, -34.561927]),
 '51:18': ([-44.232755, -20.252574, -44.351749], [-45.954743, -30.949024, -34.564182]),
 '51:19': ([-29.169102, -52.741962, -46.449091], [-36.397897, -66.008528, -49.741991]),
 '51:2': ([-31.558728, -15.148885, -98.175711], [-54.717817, -2.833354, -33.773763]),
 '51:20': ([28.169102, -52.741962, -46.449091], [35.397897, -66.008528, -49.741991]),
 '51:21': ([34.053068, -52.741704, -34.499689], [35.40223, -65.997168, -37.746759]),
 '51:22': ([-35.053397, -52.740684, -34.503558], [-36.401902, -65.998147, -37.742757]),
 '51:23': ([-29.879696, -43.029246, -85.114781], [-34.397503, -56.125579, -82.056055]),
 '51:24': ([28.879699, -43.489403, -84.86826], [33.400847, -56.556699, -81.687568]),
 '51:25': ([-35.695486, -42.916478, -97.019933], [-34.409804, -56.012726, -94.051249]),
 '51:26': ([34.577148, -43.481745, -96.815963], [33.290958, -56.541141, -93.689357]),
 '51:3': ([31.875973, -15.679693, -98.24472], [54.057067, -2.271163, -33.717717]),
 '51:6': ([-7.549665, -2.683995, -79.531867], [-4.793538, -21.995932, -73.928286]),
 '51:7': ([42.799372, -30.953394, -34.563742], [36.200244, -54.613864, -66.278744]),
 '51:8': ([-34.000253, -54.795874, -66.127467], [-40.599336, -30.965713, -34.53976]),
 '59:0': ([-58.594161, -33.988032, 66.131098], [-66.103436, -54.677657, 24.904392]),
 '61:0': ([-18.54518, -69.399076, 65.469267], [-18.563838, -69.301117, 49.469605]),
 '65:0': ([19.764102, -68.190459, 64.539212], [21.074048, -68.381786, 48.592849]),
 '71:0': ([14.713483, -55.946939, 52.094839], [16.252822, -67.644814, 49.413232]),
 '75:0': ([16.050005, -57.25003, 65.748837], [16.049995, -69.241111, 65.286286]),
 '79:0': ([64.600001, -22.052946, 49.726488], [63.060165, -34.02335, 50.586332]),
 '83:0': ([-64.199999, -21.998018, 49.916826], [-62.660129, -33.98102, 50.578235]),
 '89:0': ([-62.649995, -22.250145, 65.748859], [-62.650005, -34.221674, 66.574977]),
 '91:0': ([53.850328, 6.597429, -17.04975], [53.85027, -66.07707, -17.036024]),
 '93:0': ([-12.9, -57.250247, 49.754424], [-14.439503, -69.246725, 49.414821]),
 '95:0': ([-14.450051, -57.250131, 65.751456], [-14.449949, -69.245494, 65.417912]),
 '97:0': ([-53.85034, 6.597428, -17.050535], [-53.850322, -66.077071, -17.034898]),
 '99:0': ([63.049995, -22.24998, 65.751153], [63.050005, -34.202173, 66.821231])}

# Both upper lid levers are copies of the same nominal hardware. The
# positive-X lever in the supplied reference was displaced by ~6.47 mm
# along Y and ~1.65 mm along Z. Restore bilateral matching pivots.
LINK_HOLE_PAIRS["107:0"] = tuple(
    [abs(point[0]), point[1], point[2]]
    for point in LINK_HOLE_PAIRS["105:0"]
)

LINK_BONE_FOR_KEY = {'101:0': 'LINK_EYE_PITCH_SHARED_02',
 '105:0': 'LINK_LID_R_UPPER_02',
 '107:0': 'LINK_LID_L_UPPER_02',
 '113:0': 'LINK_EYE_PITCH_SHARED_03',
 '115:0': 'LINK_EYE_PITCH_SHARED_01',
 '117:0': 'LINK_LID_R_LOWER_01',
 '119:0': 'LINK_LID_R_UPPER_01',
 '121:0': 'LINK_LID_L_LOWER_01',
 '123:0': 'LINK_LID_L_UPPER_01',
 '20:0': 'LINK_BROW_L_OUTER_02',
 '51:11': 'LINK_LIP_L_UPPER_OUTER_04',
 '51:12': 'LINK_LIP_R_UPPER_OUTER_04',
 '51:13': 'LINK_LIP_L_UPPER_OUTER_03',
 '51:14': 'LINK_LIP_R_UPPER_OUTER_03',
 '51:15': 'LINK_JAW_CENTER_01',
 '51:16': 'LINK_JAW_CENTER_03',
 '51:17': 'LINK_LIP_L_UPPER_OUTER_01',
 '51:18': 'LINK_LIP_R_UPPER_OUTER_01',
 '51:19': 'LINK_LIP_R_UPPER_INNER_02',
 '51:2': 'LINK_JAW_R_SIDE_01',
 '51:20': 'LINK_LIP_L_UPPER_INNER_02',
 '51:21': 'LINK_LIP_L_UPPER_INNER_01',
 '51:22': 'LINK_LIP_R_UPPER_INNER_01',
 '51:23': 'LINK_LIP_R_LOWER_01',
 '51:24': 'LINK_LIP_L_LOWER_01',
 '51:25': 'LINK_LIP_R_LOWER_02',
 '51:26': 'LINK_LIP_L_LOWER_02',
 '51:3': 'LINK_JAW_L_SIDE_01',
 '51:6': 'LINK_JAW_CENTER_02',
 '51:7': 'LINK_LIP_L_UPPER_OUTER_02',
 '51:8': 'LINK_LIP_R_UPPER_OUTER_02',
 '59:0': 'LINK_BROW_R_OUTER_02',
 '61:0': 'LINK_BROW_R_INNER_02',
 '65:0': 'LINK_BROW_L_INNER_02',
 '71:0': 'LINK_BROW_L_INNER_01',
 '79:0': 'LINK_BROW_L_OUTER_01',
 '83:0': 'LINK_BROW_R_OUTER_01',
 '91:0': 'LINK_LID_L_LOWER_02',
 '93:0': 'LINK_BROW_R_INNER_01',
 '97:0': 'LINK_LID_R_LOWER_02'}

# ============================================================================
# V8 FACE-ENDPOINT HOLES / SERVO ROOTS
# ============================================================================

# These centers were recovered from cylindrical surfaces in the actual matched
# 3MF meshes.  They are not object centers.
BROW_SOURCE_MOUNT_HOLES = {'inner': (-36.3050229473, -1.6973294298, 0.0), 'outer': (37.5744995528, 1.06302, 0.0)}
BROW_ATTACHMENT_HOLES = {'L': {'inner': (33.757868, -89.4929, 43.330482), 'outer': (66.236223, -56.245099, 22.11783)},
 'R': {'inner': (-27.714199, -89.353677, 34.645198), 'outer': (-66.112106, -56.786537, 21.723301)}}
# V10 exact neutral contact chains traced directly from the reference assembly.
REFERENCE_CHAIN_POINTS = {'LID_L_UPPER': [(56.544063, -23.500503, 3.278401),
                 (56.17525, -19.449571, 16.912403),
                 (54.397696, -64.007512, 19.153186)],
 'LID_L_LOWER': [(56.390774, 6.641586, -3.461891),
                 (53.922952, 6.841033, -17.82589),
                 (54.174936, -66.61141, -17.105883)],
 'LID_R_UPPER': [(-57.946188, -23.49417, 2.101196),
                 (-53.922952, -23.162329, 17.802332),
                 (-54.174887, -66.61141, 17.104864)],
 'LID_R_LOWER': [(-57.974638, 6.820815, -1.897622),
                 (-53.922952, 6.841033, -17.82589),
                 (-54.174936, -66.61141, -17.105883)],
 'BROW_L_INNER': [(13.125, -57.25, 49.75), (17.714782, -67.714324, 49.085457), (33.757868, -89.4929, 43.330482)],
 'BROW_L_OUTER': [(63.975, -21.997766, 49.919155),
                  (61.098486, -39.059855, 51.129148),
                  (66.236223, -56.245099, 22.11783)],
 'BROW_R_INNER': [(-13.125, -57.25, 49.75), (-16.45, -69.353465, 49.253769), (-27.714199, -89.353677, 34.645198)],
 'BROW_R_OUTER': [(-63.975, -21.997766, 49.919155),
                  (-60.695694, -35.240584, 50.449034),
                  (-66.112106, -56.786537, 21.723301)]}

BROW_REFERENCE_MID = {'L': (44.2295, -72.7455, 30.2735), 'R': (-44.2295, -72.7455, 30.2735)}

# ============================================================================
# MECHANICAL TOPOLOGY REVIEW (NOT AUTOMATIC RE-PARENTING)
# ============================================================================
# The audited joint centers identify closer possible neighbors in the upper
# lip, but swapping those two links would leave a ~50 mm terminal span.  The
# printed hardware does not identify a unique serial connection or branch.
# Do not silently 'fix' this by reordering bones, inventing pushrods, or
# snapping mesh origins.  These candidate orders are evaluated and included
# in the scene's build metadata and the next linkage-audit output instead.
# The jaw-center's Part19 similarly has no verified hinge mate in its current
# serial chain.  It remains in the animation until physical connectivity can
# be established with assembly evidence.
TOPOLOGY_REVIEW_CANDIDATES = {
    "LIP_L_UPPER_OUTER": ["51:17", "51:7", "51:11", "51:13"],
    "LIP_R_UPPER_OUTER": ["51:18", "51:8", "51:12", "51:14"],
}
TOPOLOGY_REVIEW_NOTES = {
    "JAW_CENTER": "Part19 (51:16) may belong to another branch; the 31 mm link is not verified.",
    "LIP_L_UPPER_OUTER": "Closer internal pivots do not close the final face attachment.",
    "LIP_R_UPPER_OUTER": "Closer internal pivots do not close the final face attachment.",
    "EYELIDS": "Approximately 0.63 mm lid-to-lever landmark offsets; axial stack not validated.",
    "EYEBROWS": "Contact points are reference proxies rather than independently fitted bores.",
    "EYE_YAW": "No printed physical horn-to-eye coupling is supplied.",
}
# Diagnostic screening only, not a joint manufacturing tolerance.
UNVERIFIED_CONNECTOR_REVIEW_MM = 0.5

# ============================================================================
# CENTRAL EYE MECHANISM
# ============================================================================
#
# Reference-assembly contact tracing shows TWO independent central SG90
# branches, not the old single serial chain:
#
#   FRONT / eye yaw:
#       SG90 occurrence 35 -> CentralServoHorn occurrence 54
#       The free horn hole has no modeled mate in the reference OBJ.
#
#   REAR / eye pitch:
#       SG90 occurrence 61 -> VerticalHorn occurrence 47
#       -> VerticalLever occurrence 56
#       -> upper EyeCorePivotHolder clip occurrence 39
#
# The previous EYE_PITCH_SHARED chain serialised CentralServoHorn,
# VerticalLever, and VerticalHorn, which is mechanically wrong.
KINEMATIC_CHAINS = [
    chain
    for chain in KINEMATIC_CHAINS
    if chain["name"] != "EYE_PITCH_SHARED"
]

for _eye_key in ("115:0", "101:0", "113:0"):
    LINK_BONE_FOR_KEY.pop(_eye_key, None)

# Actual 3MF/reference pivots in assembled mm coordinates.
EYE_YAW_SERVO_PIVOT = Vector((
    0.003342,
    -68.697334,
    12.799979,
))
EYE_YAW_HORN_FREE = Vector((
    0.004429,
    -58.197376,
    13.949981,
))

EYE_PITCH_SERVO_PIVOT = Vector((
    -15.599860,
    -23.400705,
    0.002730,
))

# The VerticalLever's actual two cylindrical pivot-hole centers.
EYE_PITCH_REAR_JOINT = Vector((
    -11.750141,
    -23.400789,
    17.052351,
))
EYE_PITCH_HOLDER_JOINT = Vector((
    -11.750175,
    -68.702173,
    17.001447,
))

# Combined two-axis holder pivot. This remains the lower central axis of the
# EyeCorePivotHolder while the pitch linkage terminates at its upper clip.
EYE_SHARED_ORIGIN = Vector((
    -0.000005,
    -68.901268,
    0.002683,
))

# Explicit part -> mechanism-bone relationships.
EYE_MECH_PART_BONES = {
    "115:0": "MECH_EYE_YAW_HORN",
    "113:0": "MECH_EYE_PITCH_HORN",
    "101:0": "MECH_EYE_PITCH_LEVER",
    "9:0": "EYE_PITCH_SHARED",

    # Both EyeAdaptor pieces physically contact the negative-X eye in the
    # reference assembly, so they follow that eyeball rather than the skull.
    "125:0": "EYE_R_PITCH",
    "109:0": "EYE_R_PITCH",
}

# Preserve this source limitation explicitly rather than generating geometry
# that is not present in the reference assembly.
EYE_YAW_COUPLING_IS_UNMODELED = True

# Update semantic roles for the two physical eye adaptors.
PART_MAP["125:0"]["role"] = "EYE_R"
PART_MAP["109:0"]["role"] = "EYE_R"


ENDPOINT_SPECS = {'LID_L_UPPER': {'mesh_key': '22:0',
                 'bone': 'LID_L_UPPER',
                 'origin': (37.5, -69.646502, 0.909458),
                 'holes': {'pivot': (37.5, -69.646502, 0.909458), 'attach': (54.397696, -64.007512, 19.153186)}},
 'LID_L_LOWER': {'mesh_key': '57:0',
                 'bone': 'LID_L_LOWER',
                 'origin': (37.5, -69.843083, -0.13041),
                 'holes': {'pivot': (37.5, -69.843083, -0.13041), 'attach': (54.174936, -66.61141, -17.105883)}},
 'LID_R_UPPER': {'mesh_key': '16:0',
                 'bone': 'LID_R_UPPER',
                 'origin': (-37.5, -69.667981, 0.977328),
                 'holes': {'pivot': (-37.5, -69.667981, 0.977328), 'attach': (-54.174887, -66.61141, 17.104864)}},
 'LID_R_LOWER': {'mesh_key': '54:0',
                 'bone': 'LID_R_LOWER',
                 'origin': (-37.5, -70.77552, -0.086472),
                 'holes': {'pivot': (-37.5, -70.77552, -0.086472), 'attach': (-54.174936, -66.61141, -17.105883)}},
 'LIP_L_UPPER': {'mesh_key': '51:5',
                 'bone': 'LIP_L_UPPER',
                 'origin': (32.554398, -65.966451, -43.702258),
                 'holes': {'outer': (32.546892, -65.971612, -37.702264), 'inner': (32.561903, -65.961289, -49.702251)}},
 'LIP_R_UPPER': {'mesh_key': '51:4',
                 'bone': 'LIP_R_UPPER',
                 'origin': (-32.499568, -65.907379, -43.719792),
                 'holes': {'outer': (-32.497873, -65.90919, -37.719792),
                           'inner': (-32.501263, -65.905568, -49.719791)}},
 'LIP_L_LOWER': {'mesh_key': '51:10',
                 'bone': 'LIP_L_LOWER',
                 'origin': (30.530722, -56.478224, -87.411444),
                 'holes': {'upper': (30.335896, -56.6815, -81.418054), 'lower': (30.725548, -56.274948, -93.404834)}},
 'LIP_R_LOWER': {'mesh_key': '51:9',
                 'bone': 'LIP_R_LOWER',
                 'origin': (-30.572768, -56.116995, -87.842869),
                 'holes': {'upper': (-30.372115, -56.389979, -81.852441),
                           'lower': (-30.773422, -55.84401, -93.833296)}},
 'JAW': {'mesh_key': '51:1',
         'bone': 'JAW',
         'origin': (-0.123731, -43.489481, -84.856113),
         'holes': {'left_side': (24.379111, -16.819132, -98.26752),
                   'right_side': (-24.620888, -16.811832, -98.263375),
                   'center': (14.873057, -60.794151, -92.382055)}},
 'EYE_PITCH_SHARED': {'mesh_key': '9:0',
                      'bone': 'EYE_PITCH_SHARED',
                      'origin': (-5e-06, -68.901268, 0.002683),
                      'holes': {'left': (-14.700005, -68.900918, 0.002934),
                                'right': (14.699995, -68.901617, 0.002431)}}}
CHAIN_ENDPOINT_POINTS = {'LID_L_UPPER': (54.397696, -64.007512, 19.153186),
 'LID_L_LOWER': (54.174936, -66.61141, -17.105883),
 'LID_R_UPPER': (-54.174887, -66.61141, 17.104864),
 'LID_R_LOWER': (-54.174936, -66.61141, -17.105883),
 'BROW_L_INNER': (16.049995, -69.241111, 65.286286),
 'BROW_L_OUTER': (63.050005, -34.202173, 66.821231),
 'BROW_R_INNER': (-14.450051, -57.250131, 65.751456),
 'BROW_R_OUTER': (-62.650005, -34.221674, 66.574977),
 'JAW_L_SIDE': (24.379111, -16.819132, -98.26752),
 'JAW_R_SIDE': (-24.620888, -16.811832, -98.263375),
 'JAW_CENTER': (14.873057, -60.794151, -92.382055),
 'LIP_L_UPPER_INNER': (32.561903, -65.961289, -49.702251),
 'LIP_L_UPPER_OUTER': (32.546892, -65.971612, -37.702264),
 'LIP_R_UPPER_INNER': (-32.501263, -65.905568, -49.719791),
 'LIP_R_UPPER_OUTER': (-32.497873, -65.90919, -37.719792),
 'LIP_L_LOWER': (30.725548, -56.274948, -93.404834),
 'LIP_R_LOWER': (-30.773422, -55.84401, -93.833296),
 'EYE_PITCH_SHARED': (-14.700005, -68.900918, 0.002934)}
CHAIN_ROOT_POINTS = {'LID_L_UPPER': (54.8, -23.4, 10.6895),
 'LID_L_LOWER': (54.8, 6.599975, -10.6895),
 'LID_R_UPPER': (-54.8, -23.4, 10.6895),
 'LID_R_LOWER': (-54.8, 6.599975, -10.6895),
 'BROW_L_INNER': (29.1, -57.25, 44.5),
 'BROW_L_OUTER': (48.0, -21.998, 44.669),
 'BROW_R_INNER': (-29.1, -57.25, 44.5),
 'BROW_R_OUTER': (-48.0, -21.998, 44.669),
 'JAW_L_SIDE': (25.35, -24.207, -66.762),
 'JAW_R_SIDE': (-25.65, -24.207, -66.762),
 'JAW_CENTER': (1.38, -11.797, -88.048),
 'LIP_L_UPPER_INNER': (17.896, -47.491, -34.5),
 'LIP_L_UPPER_OUTER': (27.95, -19.344, -39.187),
 'LIP_R_UPPER_INNER': (-18.396, -47.491, -34.5),
 'LIP_R_UPPER_OUTER': (-27.95, -19.344, -39.187),
 'LIP_L_LOWER': (18.276, -38.44, -96.903),
 'LIP_R_LOWER': (-18.116, -38.44, -96.903),
 'EYE_PITCH_SHARED': (0.0, -61.0355, 10.55)}
ENDPOINT_PART_BONES = {'16:0': 'LID_R_UPPER',
 '22:0': 'LID_L_UPPER',
 '51:1': 'JAW',
 '51:10': 'LIP_L_LOWER',
 '51:4': 'LIP_R_UPPER',
 '51:5': 'LIP_L_UPPER',
 '51:9': 'LIP_R_LOWER',
 '54:0': 'LID_R_LOWER',
 '57:0': 'LID_L_LOWER',
 '9:0': 'EYE_PITCH_SHARED'}

# ============================================================================
# EYELID JOINT RECONSTRUCTION (based on circular mesh geometry)
# ============================================================================
# The original 3MF horn-hole extractor mistakenly classified a surface point
# between the horn's two circular pivot rings as the upper/lever-side joint.
# In the actual mesh, each horn has circular axes at z=+/-4.003 and +/-17.05,
# with the same y as the corresponding long lever's rear hole.  The short horn
# therefore connects its servo-side axle DIRECTLY to the long lever axle.
# No mechanically nonexistent root or intermediate rod is inserted here.
# The X coordinate of the shared joint uses the lever-hole central plane; the
# printed horn's joint ring is on an adjacent, axially staggered face.  Thus
# it represents a shared AXIS, not a claim that the two printed solids occupy
# the same 3-D point or that a screw has been included in the printed mesh.
#
# Likewise, the positive-X upper lid's original 'attach' landmark lies over
# 3 mm from its nearly bilateral counterpart.  The neutral mesh geometry is
# within approx. 0.2 mm of its reflected counterpart (median vertex-to-surface
# distance), so use the opposite upper lid's reference hole as the datum.
# This is a pivot landmark correction, NOT a modification of the printed lid.

EYELID_SERVO_AXES = {
    "LID_L_UPPER": (57.700042, -23.403837, 4.002540),
    "LID_R_UPPER": (-57.700043, -23.402792, 4.002598),
    "LID_L_LOWER": (57.700069, 6.603881, -4.002531),
    "LID_R_LOWER": (-57.700042, 6.603811, -4.002540),
}
EYELID_CHAIN_MESHES = {
    "LID_L_UPPER": ("123:0", "107:0"),
    "LID_R_UPPER": ("119:0", "105:0"),
    "LID_L_LOWER": ("121:0", "91:0"),
    "LID_R_LOWER": ("117:0", "97:0"),
}
for _chain, (_horn_key, _lever_key) in EYELID_CHAIN_MESHES.items():
    _shaft = EYELID_SERVO_AXES[_chain]
    # The lever's rear pivot is the hole at the same Y as the horn axis.
    _lever_rear = min(
        LINK_HOLE_PAIRS[_lever_key],
        key=lambda _p: abs(_p[1] - _shaft[1]),
    )
    LINK_HOLE_PAIRS[_horn_key] = (tuple(_shaft), tuple(_lever_rear))
    CHAIN_ROOT_POINTS[_chain] = tuple(_shaft)

# The former landmark (54.397696, -64.007512, 19.153186) was not centered on
# the source left lid's attachment bore.  The positive-X counterpart of the
# right upper lid's detected attachment is a better neutral centerline.
_LID_L_UPPER_ATTACHMENT = tuple(
    (abs(_v) if _axis == 0 else _v)
    for _axis, _v in enumerate(CHAIN_ENDPOINT_POINTS["LID_R_UPPER"])
)
CHAIN_ENDPOINT_POINTS["LID_L_UPPER"] = _LID_L_UPPER_ATTACHMENT
ENDPOINT_SPECS["LID_L_UPPER"]["holes"]["attach"] = _LID_L_UPPER_ATTACHMENT
REFERENCE_CHAIN_POINTS["LID_L_UPPER"][-1] = _LID_L_UPPER_ATTACHMENT

# Duplicate horns have misleading 'UPPER' role metadata in the reference;
# correct the semantics without changing the printed horn shape.
PART_MAP["121:0"]["role"] = "LID_L_LOWER"
PART_MAP["117:0"]["role"] = "LID_R_LOWER"

# Any remaining submillimetre lever-to-lid discrepancy stays explicitly
# modeled as a virtual joint for validation; no fabricated pushrod mesh is
# generated and no source part is translated to conceal the discrepancy.

# ============================================================================
# CLOSED-LOOP EYELID REST ASSEMBLY (no mesh modifications or manufactured rods)
# ============================================================================
# All distances and pose transforms derive from preidentified printed hole
# centers. The servo shaft is the center of the first horn pivot. Its second
# hole and the long lever's first hole have the same projected Y/Z axis.
# The long lever's second hole must meet the clip arc-center in the eyelid.
#
# The output axis of these particular servos lies along world X, so the
# mechanism's plane is the corresponding Y/Z plane. This is an axis-driven
# choice; no requirement is imposed that any link be horizontal or vertical.
# Other possible head orientations require deriving a plane from the actual
# servo shaft direction rather than globally assuming Y/Z.
#
# Solve intersection of the A-centered horn-tip circle (radius |AB|) and
# the C-centered connecting-link circle (radius |BC|). The solution nearest
# the original assembled B is chosen to avoid flipping to the other elbow.
# Printed meshes are ONLY repositioned rigidly. Neither mesh vertices nor
# hole-to-hole distances are changed.

EYELID_SOLVED_REST = {}
EYELID_RIG_TARGET_POINTS = {}
EYELID_AXIAL_OFFSETS_MM = {}


def _r_x(point, angle):
    c, s = math.cos(angle), math.sin(angle)
    x, y, z = point
    return (x, y*c-z*s, y*s+z*c)


def _xyplane_len(a, b):
    return math.hypot(b[1]-a[1], b[2]-a[2])


def _circle_joint_candidates(a, h, c, lever_length):
    ay, az, cy, cz = float(a[1]), float(a[2]), float(c[1]), float(c[2])
    dy, dz = cy-ay, cz-az
    separation = math.hypot(dy, dz)
    if separation < 1e-9 or separation > h + lever_length + 1e-6 or separation < abs(h-lever_length)-1e-6:
        raise RuntimeError('Impossible printed eyelid circle closure: '
                           'servo/eyelid pivots and original link lengths disagree')
    along = (h*h - lever_length*lever_length + separation*separation)/(2*separation)
    radial = math.sqrt(max(0., h*h-along*along))
    uy, uz = dy/separation, dz/separation
    center_y, center_z = ay+along*uy, az+along*uz
    return ((center_y-radial*uz, center_z+radial*uy),
            (center_y+radial*uz, center_z-radial*uy))


def _angular_difference(v_from, v_to):
    return math.atan2(v_from[0]*v_to[1]-v_from[1]*v_to[0],
                      v_from[0]*v_to[0]+v_from[1]*v_to[1])


def _update_placement_rigid(key, origin, angle, translation=(0.,0.,0.)):
    # p' = origin + R_x(angle) * (p - origin) + translation
    entry = PART_MAP[key]
    cr, sr = math.cos(angle), math.sin(angle)
    rot = ((1.,0.,0.), (0.,cr,-sr), (0.,sr,cr))
    old_r = entry['R']
    entry['R'] = [
        [sum(rot[i][k] * old_r[k][j] for k in range(3)) for j in range(3)]
        for i in range(3)
    ]
    def move(point):
        return tuple(origin[i]+_r_x(tuple(point[k]-origin[k] for k in range(3)),angle)[i]
                     + translation[i] for i in range(3))
    entry['t'] = list(move(entry['t']))
    entry['center'] = list(move(entry['center']))


# The physically located eyelid-clip pivots are fitted from the 3MF at build
# time, after the user-selected file has been resolved. A no-mesh audit cannot
# safely substitute a mirrored reference coordinate for an actual clip.
EYELID_CLIP_ARC_FITS = {}
EYELID_BUILDER_CALIBRATED = False
from copy import deepcopy as _cogly_deepcopy
_EYELID_SOURCE_PART_BASELINE = {
    key: _cogly_deepcopy(PART_MAP[key])
    for pair in EYELID_CHAIN_MESHES.values() for key in pair
}
_EYELID_SOURCE_PART_BASELINE.update({
    ENDPOINT_SPECS[name]['mesh_key']: _cogly_deepcopy(PART_MAP[ENDPOINT_SPECS[name]['mesh_key']])
    for name in EYELID_CHAIN_MESHES
})
_EYELID_SOURCE_HOLE_BASELINE = {
    key: _cogly_deepcopy(LINK_HOLE_PAIRS[key])
    for pair in EYELID_CHAIN_MESHES.values() for key in pair
}
_EYELID_SOURCE_TARGET_BASELINE = {
    name: tuple(CHAIN_ENDPOINT_POINTS[name]) for name in EYELID_CHAIN_MESHES
}

# Optional conceptual connector geometry (not instantiated as printed parts).
LINK_ROD_RADIUS_MM = 1.15
LINK_ROD_SEGMENTS = 14
LINK_CONNECT_EPS_MM = 0.05


# ============================================================================
# BASIC HELPERS
# ============================================================================

def log(*args):
    print("[COGLY 3MF/OBJ]", *args)


def ensure_collection(name, parent=None):
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)

    if parent is None:
        if col.name not in {c.name for c in bpy.context.scene.collection.children}:
            try:
                bpy.context.scene.collection.children.link(col)
            except RuntimeError:
                pass
    else:
        if col.name not in {c.name for c in parent.children}:
            try:
                parent.children.link(col)
            except RuntimeError:
                pass

        # If it was also linked to the Scene root, unlink to keep hierarchy tidy.
        if col.name in {c.name for c in bpy.context.scene.collection.children}:
            try:
                bpy.context.scene.collection.children.unlink(col)
            except RuntimeError:
                pass

    return col


def delete_collection_recursive(col):
    for child in list(col.children):
        delete_collection_recursive(child)

    for obj in list(col.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

    try:
        bpy.data.collections.remove(col)
    except Exception:
        pass


def cleanup_previous_build():
    rig = bpy.data.objects.get(RIG_NAME)
    if rig is not None:
        data = rig.data
        bpy.data.objects.remove(rig, do_unlink=True)
        if data is not None and data.users == 0:
            try:
                bpy.data.armatures.remove(data)
            except Exception:
                pass

    root = bpy.data.collections.get(COL_ROOT)
    if root is not None:
        delete_collection_recursive(root)

    rig_col = bpy.data.collections.get(COL_RIG)
    if rig_col is not None:
        delete_collection_recursive(rig_col)


def base_group_name(obj):
    # Blender adds .001 / .002 to repeated OBJ group names.
    return re.sub(r"\.\d{3}$", "", obj.name)


def object_world_bounds(obj):
    if obj.type != "MESH" or not obj.data.vertices:
        p = obj.matrix_world.translation.copy()
        return p.copy(), p.copy()

    mn = Vector((float("inf"), float("inf"), float("inf")))
    mx = Vector((float("-inf"), float("-inf"), float("-inf")))

    for corner in obj.bound_box:
        p = obj.matrix_world @ Vector(corner)
        for i in range(3):
            mn[i] = min(mn[i], p[i])
            mx[i] = max(mx[i], p[i])

    return mn, mx


def object_center(obj):
    mn, mx = object_world_bounds(obj)
    return (mn + mx) * 0.5


def average_points(points, fallback=(0.0, 0.0, 0.0)):
    if not points:
        return Vector(fallback)

    total = Vector((0.0, 0.0, 0.0))
    for p in points:
        total += Vector(p)
    return total / len(points)


def side_from_x(x):
    # Anatomical convention used by this project.
    return "L" if x < 0.0 else "R"


def is_fastener_name(name):
    low = name.lower()
    return any(token in low for token in (
        "screw",
        "washer",
        "shoulder",
        "insert",
    ))


def move_object_to_collection(obj, target):
    for col in list(obj.users_collection):
        try:
            col.objects.unlink(obj)
        except RuntimeError:
            pass

    if obj.name not in {o.name for o in target.objects}:
        target.objects.link(obj)


# ============================================================================
# SOURCE DISCOVERY
# ============================================================================

def candidate_3mf_paths():
    seen = set()

    def add(path):
        if not path:
            return

        try:
            path = os.path.abspath(os.path.expanduser(str(path)))
        except Exception:
            return

        if path not in seen:
            seen.add(path)
            yield path

    yield from add(SOURCE_3MF)
    yield from add(bpy.context.scene.get(SCENE_SOURCE_KEY, ""))

    roots = []

    if bpy.data.filepath:
        roots.append(os.path.dirname(bpy.data.filepath))

    try:
        if "__file__" in globals():
            roots.append(os.path.dirname(os.path.abspath(__file__)))
    except Exception:
        pass

    roots.append(os.getcwd())

    for root in roots:
        if not root or not os.path.isdir(root):
            continue

        for filename in PREFERRED_3MF_NAMES:
            yield from add(os.path.join(root, filename))

        try:
            candidates = [
                str(p)
                for p in Path(root).glob("*.3mf")
                if p.is_file()
            ]
            if len(candidates) == 1:
                yield from add(candidates[0])
        except Exception:
            pass


def find_source_3mf():
    for path in candidate_3mf_paths():
        if os.path.isfile(path) and path.lower().endswith(".3mf"):
            return path

    return None


# ============================================================================
# SERVO REFERENCE GEOMETRY
# ============================================================================

def candidate_servo_reference_paths():
    roots = []

    if bpy.data.filepath:
        roots.append(os.path.dirname(bpy.data.filepath))

    try:
        if "__file__" in globals():
            roots.append(os.path.dirname(os.path.abspath(__file__)))
    except Exception:
        pass

    roots.append(os.getcwd())

    seen = set()

    for root in roots:
        if not root:
            continue
        path = os.path.abspath(
            os.path.join(root, SERVO_REFERENCE_FILENAME)
        )
        if path not in seen:
            seen.add(path)
            yield path


def find_servo_reference():
    for path in candidate_servo_reference_paths():
        if os.path.isfile(path):
            return path
    return None



def candidate_brow_reference_paths():
    seen = set()

    def add(path):
        if not path:
            return

        try:
            path = os.path.abspath(
                os.path.expanduser(str(path))
            )
        except Exception:
            return

        if path not in seen:
            seen.add(path)
            yield path

    roots = []

    if bpy.data.filepath:
        roots.append(
            os.path.dirname(bpy.data.filepath)
        )

    try:
        if "__file__" in globals():
            roots.append(
                os.path.dirname(
                    os.path.abspath(__file__)
                )
            )
    except Exception:
        pass

    roots.append(os.getcwd())

    for root in roots:
        if not root:
            continue

        yield from add(
            os.path.join(
                root,
                BROW_REFERENCE_FILENAME,
            )
        )


def find_brow_reference():
    for path in candidate_brow_reference_paths():
        if os.path.isfile(path):
            return path

    return None



def _create_servo_mesh_object(name, vertices, faces, collection):
    mesh = bpy.data.meshes.new(name + "__MESH")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()

    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj["cogly_geometry_source"] = "OBJ_SERVO_REFERENCE"
    obj["cogly_servo_body"] = True
    return obj


def import_reference_servos():
    """
    Load only the servo bodies extracted from the user's reference assembly.

    The packaged servo OBJ is intentionally tiny compared with the full
    assembly and already contains each servo in its authoritative assembled
    coordinates. It is used only for servo bodies absent from the 3MF.
    """
    path = find_servo_reference()

    if not path:
        raise FileNotFoundError(
            f"{SERVO_REFERENCE_FILENAME} was not found beside the script. "
            "Keep the packaged servo OBJ with this V7 script."
        )

    root = ensure_collection(COL_ROOT)
    collection = ensure_collection(COL_HARDWARE, root)

    global_vertices = []
    object_faces = []
    current = None

    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            if line.startswith("v "):
                fields = line.split()
                global_vertices.append((
                    float(fields[1]) * SERVO_OBJ_TO_MM,
                    float(fields[2]) * SERVO_OBJ_TO_MM,
                    float(fields[3]) * SERVO_OBJ_TO_MM,
                ))

            elif line.startswith("o "):
                current = {
                    "name": line[2:].strip(),
                    "faces": [],
                }
                object_faces.append(current)

            elif current is not None and line.startswith("f "):
                ids = []
                for token in line.split()[1:]:
                    idx = int(token.split("/")[0])
                    if idx < 0:
                        idx = len(global_vertices) + 1 + idx
                    ids.append(idx - 1)

                if len(ids) >= 3:
                    for i in range(1, len(ids) - 1):
                        current["faces"].append((
                            ids[0],
                            ids[i],
                            ids[i + 1],
                        ))

    created = []

    for record in object_faces:
        if not record["faces"]:
            continue

        used = sorted({
            index
            for face in record["faces"]
            for index in face
        })
        remap = {
            old: new
            for new, old in enumerate(used)
        }

        vertices = [global_vertices[i] for i in used]
        faces = [
            tuple(remap[i] for i in face)
            for face in record["faces"]
        ]

        obj = _create_servo_mesh_object(
            record["name"],
            vertices,
            faces,
            collection,
        )
        obj["cogly_servo_reference"] = "DIRECT_OBJ"
        created.append(obj)

    # The full reference export omits the two positive-X high-brow MG90
    # bodies even though the bilateral linkage exists. Mirror those exact
    # negative-X servo bodies so both brow mechanisms visibly start at a servo.
    if MIRROR_MISSING_LEFT_BROW_SERVOS:
        source_names = (
            "MG90s_servo_FIX v1(Mirror)_01",
            "MG90s_servo_FIX v1(Mirror)_02",
        )

        for source_name in source_names:
            src = next(
                (obj for obj in created if obj.name == source_name),
                None,
            )
            if src is None:
                continue

            vertices = [
                (-v.co.x, v.co.y, v.co.z)
                for v in src.data.vertices
            ]
            faces = [
                tuple(reversed(tuple(poly.vertices)))
                for poly in src.data.polygons
            ]

            suffix = (
                "INNER" if source_name.endswith("_01")
                else "OUTER"
            )
            mirrored = _create_servo_mesh_object(
                f"MG90_BROW_L_{suffix}_INFERRED",
                vertices,
                faces,
                collection,
            )
            mirrored["cogly_servo_reference"] = (
                "MIRRORED_BILATERAL_INFERENCE"
            )
            created.append(mirrored)

    log("Imported servo bodies:", len(created))
    return created


def parent_servo_bodies(arm, servos):
    """Parent static servo cases to their mounting assembly."""
    for obj in servos:
        # Two low MG90 bodies are mounted with the lower moving mouth/jaw
        # mechanism in the reference assembly; everything else is frame-fixed.
        lower_moving = (
            obj.name.endswith("_03")
            or obj.name.endswith("_08")
        )
        bone = "JAW" if lower_moving else "HEAD_ROLL"

        world = obj.matrix_world.copy()
        obj.parent = arm
        obj.parent_type = "BONE"
        obj.parent_bone = bone
        obj.matrix_world = world
        obj["cogly_bone"] = bone


# ============================================================================
# 3MF IMPORT + OBJ-REFERENCE TRANSFORMS
# ============================================================================

class Cogly3MF:
    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.z = zipfile.ZipFile(self.path, "r")
        self.cache = {}
        self.main_path = "3D/3dmodel.model"

        settings = ET.fromstring(
            self.z.read("Metadata/model_settings.config")
        )

        self.metadata = {}

        for obj in settings.findall("object"):
            oid = int(obj.attrib["id"])

            ometa = {
                m.attrib.get("key"): m.attrib.get("value", "")
                for m in obj.findall("metadata")
                if m.attrib.get("key")
            }

            parts = []

            for part in obj.findall("part"):
                pmeta = {
                    m.attrib.get("key"): m.attrib.get("value", "")
                    for m in part.findall("metadata")
                    if m.attrib.get("key")
                }
                parts.append(
                    pmeta.get("name", f"Part_{len(parts)}")
                )

            self.metadata[oid] = {
                "name": ometa.get("name", f"Object_{oid}"),
                "parts": parts,
            }

    def close(self):
        try:
            self.z.close()
        except Exception:
            pass

    def root(self, path):
        path = path.lstrip("/")

        if path not in self.cache:
            self.cache[path] = ET.fromstring(
                self.z.read(path)
            )

        return self.cache[path]

    def object_node(self, path, object_id):
        return self.root(path).find(
            f"m:resources/m:object[@id='{int(object_id)}']",
            NS,
        )

    def flatten_resource(self, path, object_id):
        node = self.object_node(path, object_id)

        if node is None:
            return []

        mesh = node.find("m:mesh", NS)

        if mesh is not None:
            vv = mesh.find("m:vertices", NS)
            tt = mesh.find("m:triangles", NS)

            vertices = [
                (
                    float(v.attrib["x"]),
                    float(v.attrib["y"]),
                    float(v.attrib["z"]),
                )
                for v in vv.findall("m:vertex", NS)
            ]

            faces = [
                (
                    int(t.attrib["v1"]),
                    int(t.attrib["v2"]),
                    int(t.attrib["v3"]),
                )
                for t in tt.findall("m:triangle", NS)
            ]

            return [{
                "vertices": vertices,
                "faces": faces,
            }]

        comps = node.find("m:components", NS)

        if comps is None:
            return []

        result = []

        for comp in comps.findall("m:component", NS):
            child_id = int(comp.attrib["objectid"])
            child_path = comp.attrib.get(
                f"{{{PROD_NS}}}path",
                path,
            ).lstrip("/")

            result.extend(
                self.flatten_resource(
                    child_path,
                    child_id,
                )
            )

        return result

    def flatten_object(self, object_id):
        leaves = self.flatten_resource(
            self.main_path,
            object_id,
        )

        meta = self.metadata.get(object_id, {})
        part_names = meta.get("parts", [])

        for index, leaf in enumerate(leaves):
            leaf["oid"] = object_id
            leaf["vid"] = index
            leaf["key"] = f"{object_id}:{index}"

            if index < len(part_names):
                leaf["name"] = part_names[index]
            else:
                leaf["name"] = meta.get(
                    "name",
                    f"Object_{object_id}",
                )

        return leaves


# ============================================================================
# REAL 3MF EYELID CLIP-FIT ARC FITTING + REST-POSE ASSEMBLY
# ============================================================================
# The older "corrected" upper endpoint (Y=-66.611,Z=+17.105) was a
# detached reference point, NOT the source mesh's C-shaped clip.
# Fit the curved ring from actual vertices before placing any mesh. The lower
# lid arc is at a different region. The ring ROI is a feature-selection window,
# never an orientation constraint on either linkage or its IK solver.
# The 3MF print meshes remain untouched; transforms only are updated.

def _fit_lid_clip_from_source(project, part_key):
    import numpy as np
    oid, volume = [int(x) for x in part_key.split(':')]
    leaf = project.flatten_object(oid)[volume]
    entry = PART_MAP[part_key]
    verts = np.asarray(leaf['vertices'], dtype=float)
    rr = np.asarray(entry['R'], dtype=float)
    verts = verts @ rr.T + np.asarray(entry['t'], dtype=float)
    x_abs = np.abs(verts[:, 0])
    upper = part_key in ('22:0', '16:0')
    mask = (x_abs > 56.8) & (x_abs < 57.2)
    if upper:
        mask &= (verts[:, 1] < -79.0) & (verts[:, 2] > 6.0)
    else:
        mask &= (verts[:, 1] > -73.0) & (verts[:, 1] < -63.0) & (verts[:, 2] < -12.0)
    pts = verts[mask]
    if len(pts) < 35:
        raise RuntimeError(
            f'{part_key}: insufficient authentic 3MF clip vertices: {len(pts)}. '
            'Do not silently reuse the old guessed landmark.')
    yz = pts[:, 1:3]
    a = np.column_stack((2. * yz[:, 0], 2. * yz[:, 1], np.ones(len(pts))))
    rhs = np.sum(yz * yz, axis=1)
    params, *_ = np.linalg.lstsq(a, rhs, rcond=None)
    center = params[:2]
    radii = np.linalg.norm(yz - center, axis=1)
    scatter = float(np.std(radii))
    if scatter > 0.3 or not (1.5 < float(np.median(radii)) < 4.0):
        raise RuntimeError(
            f'{part_key}: source clip arc circle fit is not reliable '
            f'(scatter={scatter:.3f} mm).')
    # The ring curves are found on the outer clip wall, around |X|=57 mm.
    # Choosing that wall's central axial plane records the printed clip's
    # true location, not an assumed coincident point inside the long lever.
    return (float(np.mean(pts[:, 0])), float(center[0]), float(center[1])), {
        'sample_count': len(pts),
        'radius_mm': round(float(np.median(radii)), 5),
        'radial_scatter_mm': round(scatter, 5),
        'source_part': part_key,
        'method': 'least_squares_circle_of_outer_axial_C_clip_arc_vertices',
    }


def _rotate_point_about_servo_axis(point, center, theta):
    return tuple(center[i] + _r_x(tuple(point[j] - center[j] for j in range(3)), theta)[i]
                 for i in range(3))


def calibrate_eyelid_rest_pose(source_path):
    """Solve the *actual printed* eyelid clips, then horn/lever rigid placement.

    Must run exactly once after a fresh module import, before mesh import.
    This does not change vertices or resize links. The open eyelid angle is
    allowed to move when its original reference pose makes closure impossible.
    """
    global EYELID_BUILDER_CALIBRATED
    if EYELID_BUILDER_CALIBRATED:
        # A user may click the Build button again without rerunning the .py.
        # Never rotate parts cumulatively or reuse landmarks from the last solve.
        for key, rest in _EYELID_SOURCE_PART_BASELINE.items():
            PART_MAP[key] = _cogly_deepcopy(rest)
        for key, rest in _EYELID_SOURCE_HOLE_BASELINE.items():
            LINK_HOLE_PAIRS[key] = _cogly_deepcopy(rest)
        for name, center in _EYELID_SOURCE_TARGET_BASELINE.items():
            CHAIN_ENDPOINT_POINTS[name] = center
            ENDPOINT_SPECS[name]['holes']['attach'] = center
            if name in REFERENCE_CHAIN_POINTS:
                REFERENCE_CHAIN_POINTS[name][-1] = center
        EYELID_SOLVED_REST.clear()
        EYELID_RIG_TARGET_POINTS.clear()
        EYELID_AXIAL_OFFSETS_MM.clear()
        EYELID_CLIP_ARC_FITS.clear()
        EYELID_BUILDER_CALIBRATED = False
    project = Cogly3MF(source_path)
    try:
        for name, (horn_key, lever_key) in EYELID_CHAIN_MESHES.items():
            lid_key = ENDPOINT_SPECS[name]['mesh_key']
            C_raw, arc_fit = _fit_lid_clip_from_source(project, lid_key)
            root = tuple(EYELID_SERVO_AXES[name])
            initial_pivot = tuple(ENDPOINT_SPECS[name]['origin'])
            B_raw, end_raw = [tuple(p) for p in LINK_HOLE_PAIRS[lever_key]]
            if _xyplane_len(root, B_raw) > _xyplane_len(root, end_raw):
                B_raw, end_raw = end_raw, B_raw
            horn_len = _xyplane_len(root, B_raw)
            lever_len = _xyplane_len(B_raw, end_raw)
            # Find the closest *feasible* eyelid rest angle to the reference
            # while keeping 2 mm away from straight-arm toggle singularities.
            # Upper clip is beyond total two-link reach when the original
            # eyelid is left at its reference angle. Rotating the LID mesh
            # (not stretching either link) is mandatory for true closure.
            samples = (k * 0.1 for k in range(-750, 751))
            choices = []
            for degrees in samples:
                candidate = _rotate_point_about_servo_axis(
                    C_raw, initial_pivot, math.radians(degrees))
                separation = _xyplane_len(root, candidate)
                if abs(lever_len - horn_len) + 2.0 <= separation <= horn_len + lever_len - 2.0:
                    possible_joints = _circle_joint_candidates(root, horn_len, candidate, lever_len)
                    joint = min(possible_joints,
                                key=lambda q: (q[0]-B_raw[1])**2+(q[1]-B_raw[2])**2)
                    horn_preload = math.degrees(_angular_difference(
                        (B_raw[1]-root[1], B_raw[2]-root[2]),
                        (joint[0]-root[1], joint[1]-root[2])))
                    choices.append((abs(degrees), degrees, candidate, abs(horn_preload)))
            if not choices:
                raise RuntimeError(f'{name}: no source-mesh rigid closure with the actual clip.')
            # Prefer the closest eyelid orientation in which the printed servo
            # horn is still at a SLIGHT preloaded angle, rather than forcing
            # a near-straight linkage at the edge of its reachable workspace.
            safe = [row for row in choices if row[3] <= 12.0]
            if not safe:
                raise RuntimeError(f'{name}: no rest solution with a 12-degree servo-horn preload.')
            _, lid_angle_deg, C_world, _ = min(safe, key=lambda row: (row[0], row[1]))
            lid_angle = math.radians(lid_angle_deg)
            # 3D motion is a rigid rotation about this eyelid's physical
            # rotational axis; no vertex positions inside the mesh are edited.
            _update_placement_rigid(lid_key, initial_pivot, lid_angle)
            # Geometry-based physical eyelid target replaces the imaginary
            # attachment landmark that the previous audit always "passed".
            ENDPOINT_SPECS[name]['holes']['attach'] = tuple(C_world)
            CHAIN_ENDPOINT_POINTS[name] = tuple(C_world)
            if name in REFERENCE_CHAIN_POINTS:
                REFERENCE_CHAIN_POINTS[name][-1] = tuple(C_world)
            choices_B = _circle_joint_candidates(root, horn_len, C_world, lever_len)
            nearest_B = min(choices_B, key=lambda p: (p[0]-B_raw[1])**2+(p[1]-B_raw[2])**2)
            B_world = (B_raw[0], nearest_B[0], nearest_B[1])
            end_world = (end_raw[0], C_world[1], C_world[2])
            horn_angle = _angular_difference(
                (B_raw[1]-root[1], B_raw[2]-root[2]),
                (B_world[1]-root[1], B_world[2]-root[2]))
            lever_angle = _angular_difference(
                (end_raw[1]-B_raw[1], end_raw[2]-B_raw[2]),
                (end_world[1]-B_world[1], end_world[2]-B_world[2]))
            _update_placement_rigid(horn_key, root, horn_angle)
            _update_placement_rigid(
                lever_key, B_raw, lever_angle,
                (0.0, B_world[1]-B_raw[1], B_world[2]-B_raw[2]))
            LINK_HOLE_PAIRS[horn_key] = (root, B_world)
            LINK_HOLE_PAIRS[lever_key] = (B_world, end_world)
            CHAIN_ROOT_POINTS[name] = root
            EYELID_RIG_TARGET_POINTS[name] = end_world
            EYELID_AXIAL_OFFSETS_MM[name] = round(abs(end_world[0] - C_world[0]), 5)
            EYELID_CLIP_ARC_FITS[name] = arc_fit
            EYELID_SOLVED_REST[name] = {
                'servo_root': list(root), 'horn_joint': list(B_world),
                'lever_end': list(end_world), 'printed_lid_arc_center': list(C_world),
                'lid_rotation_deg': round(lid_angle_deg, 5),
                'horn_rotation_deg': round(math.degrees(horn_angle), 5),
                'lever_rotation_deg': round(math.degrees(lever_angle), 5),
                'horn_planar_span_mm': round(horn_len, 5),
                'lever_planar_span_mm': round(lever_len, 5),
                'projected_joint_error_mm': round(_xyplane_len(end_world, C_world), 8),
                'axial_layer_offset_mm': EYELID_AXIAL_OFFSETS_MM[name],
                'clip_arc_fit': arc_fit,
                'source': 'actual 3MF mesh C-clip circle fit + rigid closed-loop rest solve',
            }
            if (abs(_xyplane_len(root, B_world) - horn_len) > 1e-5
                or abs(_xyplane_len(B_world, end_world) - lever_len) > 1e-5):
                raise AssertionError(f'{name}: printed link length changed')
            print('COGLY PHYSICAL EYELID REST', name,
                  'lid', round(lid_angle_deg,2), 'horn',round(math.degrees(horn_angle),2),
                  'C', tuple(round(x,3) for x in C_world))
    finally:
        project.close()
    EYELID_BUILDER_CALIBRATED = True


def reference_matrix(entry):
    R = entry["R"]
    t = entry["t"]

    return Matrix((
        (R[0][0], R[0][1], R[0][2], t[0]),
        (R[1][0], R[1][1], R[1][2], t[1]),
        (R[2][0], R[2][1], R[2][2], t[2]),
        (0.0, 0.0, 0.0, 1.0),
    ))


def target_collection_for_role(role):
    root = ensure_collection(COL_ROOT)

    if role.startswith("EYE_"):
        return ensure_collection(COL_EYES, root)

    if role.startswith("LID_"):
        return ensure_collection(COL_LIDS, root)

    if role.startswith("BROW_"):
        return ensure_collection(COL_BROWS, root)

    if role == "JAW" or role.startswith("LIP_"):
        return ensure_collection(COL_MOUTH, root)

    return ensure_collection(COL_STATIC, root)


def import_3mf_reference_assembly(path):
    project = Cogly3MF(path)
    imported = []
    assignment = {}

    needed_oids = sorted({
        int(key.split(":")[0])
        for key in PART_MAP
    })

    try:
        for oid in needed_oids:
            leaves = project.flatten_object(oid)

            for leaf in leaves:
                key = leaf["key"]

                if key not in PART_MAP:
                    continue

                entry = PART_MAP[key]
                role = entry["role"]

                name = (
                    f"{entry['name']}__OBJ"
                    f"{int(entry['occ']):03d}"
                )

                mesh = bpy.data.meshes.new(
                    name + "__MESH"
                )
                mesh.from_pydata(
                    leaf["vertices"],
                    [],
                    leaf["faces"],
                )
                mesh.update()

                obj = bpy.data.objects.new(name, mesh)
                target_collection_for_role(role).objects.link(obj)

                obj.matrix_world = reference_matrix(entry)
                # Preserve the undeformed source-to-world transform so the
                # motion auditor can measure real source-hole displacement,
                # not trivially align landmarks to an already IK-moved mesh.
                obj["cogly_neutral_matrix_rowmajor"] = [
                    float(obj.matrix_world[row][col])
                    for row in range(4) for col in range(4)
                ]
                obj.rotation_mode = "XYZ"

                obj["cogly_3mf_key"] = key
                obj["cogly_source_name"] = entry["name"]
                obj["cogly_obj_target"] = entry["target"]
                obj["cogly_obj_occurrence"] = int(entry["occ"])
                obj["cogly_role"] = role
                obj["cogly_geometry_source"] = "3MF"
                obj["cogly_placement_source"] = "OBJ_REFERENCE"

                imported.append(obj)
                assignment[obj] = role

    finally:
        project.close()

    if len(imported) != len(PART_MAP):
        got = {
            obj.get("cogly_3mf_key")
            for obj in imported
        }
        missing = sorted(set(PART_MAP) - got)

        raise RuntimeError(
            "Mapped 3MF part count mismatch. "
            f"Expected {len(PART_MAP)}, "
            f"built {len(imported)}. "
            f"Missing: {missing[:10]}"
        )

    log("Imported mapped 3MF components:", len(imported))
    return imported, assignment


# ============================================================================
# FLEXIBLE EYEBROWS
# ============================================================================

def mapped_role_centers(role):
    return [
        Vector(entry["center"])
        for entry in PART_MAP.values()
        if entry["role"] == role
    ]


def _mapped_brow_entry(role, source_name, choose=None):
    entries = [
        entry
        for entry in PART_MAP.values()
        if entry["role"] == role
        and entry["name"] == source_name
    ]

    if not entries:
        raise RuntimeError(
            f"Missing reference brow component {source_name!r} for {role}."
        )

    if choose == "inner":
        return min(entries, key=lambda e: abs(float(e["center"][0])))
    if choose == "outer":
        return max(entries, key=lambda e: abs(float(e["center"][0])))
    return entries[0]


def _catmull_rom_2d(p0, p1, p2, p3, t):
    t2 = t * t
    t3 = t2 * t
    return 0.5 * (
        (2.0 * p1)
        + (-p0 + p2) * t
        + (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * t2
        + (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * t3
    )


def reference_brow_wrap_samples(side):
    """
    Reconstruct only the RELATIVE front/back curvature used by V4.

    The absolute V4 brow coordinates were wrong. V7 keeps the correct V3
    object transform and applies this reference-derived normal offset locally.
    """
    role = f"BROW_{side}"

    inner = Vector(
        _mapped_brow_entry(role, "Part 2", "inner")["center"][:2]
    )
    outer = Vector(
        _mapped_brow_entry(role, "Part 2", "outer")["center"][:2]
    )

    if side == "L":
        mid_a = Vector(_mapped_brow_entry(role, "Part 12")["center"][:2])
        mid_b = Vector(_mapped_brow_entry(role, "Part 13")["center"][:2])
    else:
        mid_a = Vector(_mapped_brow_entry(role, "Part 8")["center"][:2])
        mid_b = Vector(_mapped_brow_entry(role, "Part 9")["center"][:2])

    controls = [inner, mid_a, mid_b, outer]
    padded = [controls[0]] + controls + [controls[-1]]
    raw = []

    for segment in range(1, len(padded) - 2):
        for step in range(BROW_REFERENCE_CURVE_SAMPLES):
            raw.append(
                _catmull_rom_2d(
                    padded[segment - 1],
                    padded[segment],
                    padded[segment + 1],
                    padded[segment + 2],
                    step / float(BROW_REFERENCE_CURVE_SAMPLES),
                )
            )

    raw.append(controls[-1].copy())

    cumulative = [0.0]
    for i in range(1, len(raw)):
        cumulative.append(
            cumulative[-1] + (raw[i] - raw[i - 1]).length
        )
    total = max(cumulative[-1], 1e-9)

    chord = controls[-1] - controls[0]
    if chord.length <= 1e-9:
        chord = Vector((1.0, 0.0))
    else:
        chord.normalize()
    normal = Vector((-chord.y, chord.x))

    samples = []
    for point, distance in zip(raw, cumulative):
        offset = abs((point - controls[0]).dot(normal))
        samples.append((distance / total, offset))

    return samples


def evaluate_brow_wrap(samples, u):
    u = max(0.0, min(1.0, float(u)))

    if u <= 0.0:
        return samples[0][1]
    if u >= 1.0:
        return samples[-1][1]

    lo = 0
    hi = len(samples) - 1
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if samples[mid][0] < u:
            lo = mid
        else:
            hi = mid

    ua, va = samples[lo]
    ub, vb = samples[hi]
    alpha = (u - ua) / max(1e-9, ub - ua)
    return va * (1.0 - alpha) + vb * alpha


def _brow_source_mounts(side):
    inner = Vector(BROW_SOURCE_MOUNT_HOLES["inner"])
    outer = Vector(BROW_SOURCE_MOUNT_HOLES["outer"])

    if side == "R":
        inner.x = -inner.x
        outer.x = -outer.x

    return inner, outer


def _solve_arc_theta(chord_length, arc_length):
    if arc_length <= chord_length + 1e-6:
        return 0.0

    target = chord_length / arc_length
    lo = 1e-7
    hi = math.pi * 1.999

    for _ in range(80):
        mid = (lo + hi) * 0.5
        ratio = (
            2.0 * math.sin(mid * 0.5) / mid
        )

        if ratio > target:
            lo = mid
        else:
            hi = mid

    return (lo + hi) * 0.5


def _brow_arc_data(side):
    """
    Build a constant-length 3D arc between the two ACTUAL brow-link endpoint
    holes.

    The source eyebrow has ~73.93 mm between its mounting-hole centers.
    The linkage attachment chord is shorter, so the correct neutral state must
    be curved rather than scaled.  This is precisely what a living-hinge brow
    is expected to do.
    """
    target_inner = Vector(
        BROW_ATTACHMENT_HOLES[side]["inner"]
    )
    target_outer = Vector(
        BROW_ATTACHMENT_HOLES[side]["outer"]
    )

    source_inner, source_outer = _brow_source_mounts(
        side
    )

    source_span = (
        Vector((
            source_outer.x - source_inner.x,
            source_outer.y - source_inner.y,
            0.0,
        )).length
    )

    chord = target_outer - target_inner
    chord_length = chord.length

    if chord_length <= 1e-8:
        raise RuntimeError(
            f"Degenerate brow attachment chord for {side}."
        )

    e_chord = chord.normalized()

    # Bulge toward the front of the face (-Y), projected perpendicular to the
    # endpoint chord.
    forward = Vector((0.0, -1.0, 0.0))
    e_bulge = forward - e_chord * forward.dot(
        e_chord
    )

    if e_bulge.length <= 1e-8:
        e_bulge = Vector((0.0, 0.0, 1.0))
        e_bulge -= e_chord * e_bulge.dot(
            e_chord
        )

    e_bulge.normalize()

    theta = _solve_arc_theta(
        chord_length,
        source_span,
    )

    if theta <= 1e-7:
        radius = 1e12
        center = (target_inner + target_outer) * 0.5
        alpha = 0.0
    else:
        radius = source_span / theta
        alpha = theta * 0.5
        half_chord = chord_length * 0.5
        h = math.sqrt(
            max(
                0.0,
                radius * radius
                - half_chord * half_chord,
            )
        )
        center = (
            (target_inner + target_outer) * 0.5
            - e_bulge * h
        )

    return {
        "source_inner": source_inner,
        "source_outer": source_outer,
        "source_span": source_span,
        "target_inner": target_inner,
        "target_outer": target_outer,
        "e_chord": e_chord,
        "e_bulge": e_bulge,
        "center": center,
        "radius": radius,
        "alpha": alpha,
        "theta": theta,
    }


def _brow_arc_sample(side, u):
    data = _brow_arc_data(side)
    u = float(u)

    if data["theta"] <= 1e-7:
        point = (
            data["target_inner"] * (1.0 - u)
            + data["target_outer"] * u
        )
        tangent = data["e_chord"].copy()
    else:
        phi = -data["alpha"] + data["theta"] * u

        point = (
            data["center"]
            + data["radius"] * (
                math.sin(phi) * data["e_chord"]
                + math.cos(phi) * data["e_bulge"]
            )
        )

        tangent = (
            math.cos(phi) * data["e_chord"]
            - math.sin(phi) * data["e_bulge"]
        )
        tangent.normalize()

    # Small additional visible arch in global Z.  It is exactly zero at both
    # mounting holes, so those holes remain mechanically coincident.
    if 0.0 <= u <= 1.0:
        arch = math.sin(math.pi * u) ** 2
        point.z += (
            BROW_NEUTRAL_VERTICAL_ARCH_MM
            * arch
        )

    return point, tangent


def compute_flexible_brow_layout():
    """
    Used by the landmark/report layer.  The flex-strip center is now the
    mechanically solved midpoint between the real inner/outer mount holes.
    """
    layout = {}

    for side in ("L", "R"):
        point, _tangent = _brow_arc_sample(
            side,
            0.5,
        )
        layout[side] = point

    return layout


def _bend_brow_vertices_to_mounts(vertices, side, mirror_x):
    """
    Isometrically bend the source eyebrow ribbon from one real mount hole to
    the other.

    Source in-plane longitudinal distance is mapped to arc length, so the mesh
    is curved without scaling.  Source transverse width maps approximately
    upward, and source thickness maps across the local ribbon normal.
    """
    source_inner, source_outer = _brow_source_mounts(
        side
    )

    source_axis_2d = Vector((
        source_outer.x - source_inner.x,
        source_outer.y - source_inner.y,
        0.0,
    ))
    source_length = source_axis_2d.length

    if source_length <= 1e-8:
        raise RuntimeError(
            f"Degenerate source eyebrow mount span for {side}."
        )

    source_axis_2d.normalize()
    source_trans_2d = Vector((
        -source_axis_2d.y,
        source_axis_2d.x,
        0.0,
    ))

    result = []

    for raw_x, raw_y, raw_z in vertices:
        x = -raw_x if mirror_x else raw_x

        rel = Vector((
            x - source_inner.x,
            raw_y - source_inner.y,
            0.0,
        ))

        s = rel.dot(source_axis_2d)
        transverse = rel.dot(source_trans_2d)
        u = s / source_length

        if u < 0.0:
            endpoint, tangent = _brow_arc_sample(
                side,
                0.0,
            )
            center = endpoint + tangent * (
                u * source_length
            )
        elif u > 1.0:
            endpoint, tangent = _brow_arc_sample(
                side,
                1.0,
            )
            center = endpoint + tangent * (
                (u - 1.0) * source_length
            )
        else:
            center, tangent = _brow_arc_sample(
                side,
                u,
            )

        # A vertical-ish ribbon vector orthogonal to the local tangent.
        up = Vector((0.0, 0.0, 1.0))
        up = up - tangent * up.dot(tangent)

        if up.length <= 1e-8:
            up = Vector((0.0, 1.0, 0.0))
            up = up - tangent * up.dot(tangent)

        up.normalize()

        thickness_axis = tangent.cross(up)

        if thickness_axis.length <= 1e-8:
            thickness_axis = Vector((0.0, -1.0, 0.0))
        else:
            thickness_axis.normalize()

        # Keep the material thickness generally facing the front/back direction.
        if thickness_axis.dot(
            Vector((0.0, -1.0, 0.0))
        ) < 0.0:
            thickness_axis.negate()

        position = (
            center
            + up * transverse
            + thickness_axis * float(raw_z)
        )

        result.append(tuple(position))

    return result


def flexible_brow_world_matrix(center):
    # V8 eyebrow vertices are authored directly in assembled head coordinates.
    return Matrix.Identity(4)


def _load_reference_brow_obj_direct(path):
    """Load packaged reference eyebrows without Blender OBJ axis conversion."""
    global_vertices = []
    groups = {}
    current = None

    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            if line.startswith("g "):
                current = line[2:].strip()
                groups.setdefault(current, {"faces": []})
            elif line.startswith("v "):
                p = line.split()
                global_vertices.append(Vector((
                    float(p[1]) * 1000.0,
                    float(p[2]) * 1000.0,
                    float(p[3]) * 1000.0,
                )))
            elif line.startswith("f ") and current:
                ids = []
                for token in line.split()[1:]:
                    idx = int(token.split("/")[0])
                    if idx < 0:
                        idx = len(global_vertices) + idx + 1
                    ids.append(idx - 1)
                for i in range(1, len(ids) - 1):
                    groups[current]["faces"].append((ids[0], ids[i], ids[i + 1]))

    built = []
    for group_name, payload in groups.items():
        faces = payload["faces"]
        if not faces:
            continue
        used = sorted({idx for face in faces for idx in face})
        remap = {old: new for new, old in enumerate(used)}
        verts = [tuple(global_vertices[i]) for i in used]
        local_faces = [tuple(remap[i] for i in face) for face in faces]
        mesh = bpy.data.meshes.new(group_name + "__MESH")
        mesh.from_pydata(verts, [], local_faces)
        mesh.update()
        obj = bpy.data.objects.new(group_name, mesh)
        obj.matrix_world = Matrix.Identity(4)
        built.append(obj)
    return built


def import_flexible_eyebrows(path):
    """Use exact raw Part11/Part14 reference coordinates and keep them flexible."""
    if not ENABLE_FLEXIBLE_EYEBROWS:
        return []

    ref_path = find_brow_reference()
    if not ref_path:
        raise FileNotFoundError(
            f"{BROW_REFERENCE_FILENAME} was not found beside the script."
        )

    created = _load_reference_brow_obj_direct(ref_path)
    if len(created) != 2:
        raise RuntimeError(f"Expected 2 reference eyebrows, got {len(created)}.")

    result = []
    for obj in created:
        center_x = sum(v.co.x for v in obj.data.vertices) / max(1, len(obj.data.vertices))
        side = "L" if center_x > 0.0 else "R"
        obj.name = f"EyebrowFlex__{side}"
        target_collection_for_role(f"BROW_{side}").objects.link(obj)
        obj["cogly_role"] = f"FLEX_BROW_{side}"
        obj["cogly_brow_side"] = side
        obj["cogly_geometry_source"] = "REFERENCE_OBJ_PART14" if side == "L" else "REFERENCE_OBJ_PART11"
        obj["cogly_placement_source"] = "REFERENCE_RAW_COORDINATES_NO_AXIS_CONVERSION"
        obj["cogly_reference_brow"] = True
        result.append(obj)

    log("Imported exact reference eyebrows with raw coordinates:", len(result))
    return result


def setup_flexible_eyebrow_deform(arm, brow_objects):
    """
    Deform each living-hinge eyebrow continuously across three anchors.

    INNER moves the most, MID somewhat less, and OUTER least. Smooth vertex
    weights between those bones create bending instead of rigid translation.
    """
    for obj in brow_objects:
        side = str(obj.get("cogly_brow_side", ""))

        if side not in {"L", "R"}:
            continue

        inner_name = f"BROW_{side}"
        mid_name = f"BROW_{side}_MID"
        outer_name = f"BROW_{side}_OUTER"

        for bone_name in (
            inner_name,
            mid_name,
            outer_name,
        ):
            if bone_name not in arm.pose.bones:
                raise RuntimeError(
                    f"Missing flexible-brow bone {bone_name}."
                )

        for group_name in (
            inner_name,
            mid_name,
            outer_name,
        ):
            old = obj.vertex_groups.get(group_name)
            if old is not None:
                obj.vertex_groups.remove(old)

        vg_inner = obj.vertex_groups.new(name=inner_name)
        vg_mid = obj.vertex_groups.new(name=mid_name)
        vg_outer = obj.vertex_groups.new(name=outer_name)

        inner_point = Vector(
            BROW_ATTACHMENT_HOLES[side]["inner"]
        )
        outer_point = Vector(
            BROW_ATTACHMENT_HOLES[side]["outer"]
        )

        axis = outer_point - inner_point
        axis_len_sq = max(
            1e-9,
            axis.length_squared,
        )

        for v in obj.data.vertices:
            p = v.co.copy()

            # Keep the real screw-hole neighborhoods rigidly attached to the
            # exact corresponding endpoint bone.
            d_inner = (p - inner_point).length
            d_outer = (p - outer_point).length

            if d_inner <= 4.0:
                w_inner, w_mid, w_outer = (
                    1.0,
                    0.0,
                    0.0,
                )
            elif d_outer <= 4.0:
                w_inner, w_mid, w_outer = (
                    0.0,
                    0.0,
                    1.0,
                )
            else:
                t = (
                    (p - inner_point).dot(axis)
                    / axis_len_sq
                )
                t = max(0.0, min(1.0, t))

                w_inner = max(
                    0.0,
                    1.0 - 2.0 * t,
                )
                w_outer = max(
                    0.0,
                    2.0 * t - 1.0,
                )
                w_mid = max(
                    0.0,
                    1.0 - abs(2.0 * t - 1.0),
                )

                total = (
                    w_inner
                    + w_mid
                    + w_outer
                )

                if total <= 1e-8:
                    w_mid = 1.0
                    total = 1.0

                w_inner /= total
                w_mid /= total
                w_outer /= total

            if w_inner > 0.0:
                vg_inner.add(
                    [v.index],
                    w_inner,
                    "REPLACE",
                )

            if w_mid > 0.0:
                vg_mid.add(
                    [v.index],
                    w_mid,
                    "REPLACE",
                )

            if w_outer > 0.0:
                vg_outer.add(
                    [v.index],
                    w_outer,
                    "REPLACE",
                )

        # Follow the whole rig as an object while the Armature modifier handles
        # the local flexible deformation.
        world_before_parent = obj.matrix_world.copy()

        obj.parent = arm
        obj.parent_type = "OBJECT"
        obj.parent_bone = ""
        obj.matrix_parent_inverse = arm.matrix_world.inverted()
        obj.matrix_world = world_before_parent

        for mod in list(obj.modifiers):
            if mod.type == "ARMATURE":
                obj.modifiers.remove(mod)

        mod = obj.modifiers.new(
            name="COGLY Flexible Eyebrow",
            type="ARMATURE",
        )
        mod.object = arm
        mod.use_deform_preserve_volume = True

        obj["cogly_flexible_brow_ready"] = True


# ============================================================================
# COMPONENT CLASSIFICATION
# ============================================================================

BROW_GROUP_NAMES = {
    "Part 2",
    "Part 3",
    "Part 8",
    "Part 9",
    "Part 11",
    "Part 12",
    "Part 13",
    "Part 14",
}

MOUTH_NUMBERED_NAMES = {
    f"Part {i}" for i in range(19, 44)
}

UPPER_LIP_NAMES = {
    "UpperLeftLip",
    "Part 34",
    "ULLLinkA",
    "ULLLinkB",
    "Part 35",
    "Part 36",
}

LOWER_LIP_NAMES = {
    "LowerLeftLip",
    "Part 37",
}


def classify_nonhardware(obj):
    name = base_group_name(obj)
    c = object_center(obj)
    x, y, z = c
    side = side_from_x(x)

    # ------------------------------------------------------------------
    # Visible eyeballs.
    # In this assembly Component74 occurs exactly twice at X ~= +/-37.5 mm.
    # ------------------------------------------------------------------
    if name == "Component74":
        return f"EYE_{side}"

    # ------------------------------------------------------------------
    # Eyelids.
    # In the authoritative assembly:
    #   LidBR centers at Z ~= +7.8 mm -> upper lid
    #   LidTR centers at Z ~= -7.8 mm -> lower lid
    # ------------------------------------------------------------------
    if name == "LidBR":
        return f"LID_{side}_UPPER"

    if name == "LidTR":
        return f"LID_{side}_LOWER"

    # Direct eyelid linkages.
    if name == "2xTopLidLever":
        return f"LID_{side}_UPPER"

    if name == "2xBottomLidLever":
        return f"LID_{side}_LOWER"

    if name == "4xTopLidHorn":
        # The authored assembly has two front/top horns and two rear/lower
        # horns. Use assembled Z rather than assuming the repeated name tells
        # us which one this is.
        return (
            f"LID_{side}_UPPER"
            if z >= 0.0
            else f"LID_{side}_LOWER"
        )

    # ------------------------------------------------------------------
    # Eyebrow drive mechanism.
    # These numbered groups form the high-Z left/right brow mechanism in the
    # assembled OBJ. Part 4 spans the center and is deliberately left static.
    # ------------------------------------------------------------------
    if name in BROW_GROUP_NAMES and z > 20.0:
        return f"BROW_{side}"

    # ------------------------------------------------------------------
    # Main jaw / lower mouth.
    # ------------------------------------------------------------------
    if name in {"JawBase", "JawLink", "Part 33", "Part 21"}:
        return "JAW"

    if name == "TopBase":
        return "HEAD"

    if name in UPPER_LIP_NAMES:
        return f"LIP_{side}_UPPER"

    if name in LOWER_LIP_NAMES:
        return f"LIP_{side}_LOWER"

    if name in MOUTH_NUMBERED_NAMES:
        # Very low components are lower-jaw/lower-lip mechanics.
        if z < -72.0:
            if abs(x) > 5.0:
                return f"LIP_{side}_LOWER"
            return "JAW"

        # Upper/side linkages.
        if abs(x) > 5.0:
            return f"LIP_{side}_UPPER"

        return "JAW"

    # The four Part 1 groups include upper/lower mouth pieces in this export.
    if name == "Part 1":
        return "JAW" if z < -70.0 else "HEAD"

    # Ambiguous servo bodies, frame, screws, plates, eye housings, etc. are
    # intentionally static unless handled separately below.
    return "HEAD"


def classify_components(objects):
    assignment = {}
    moving_centers = []

    # First pass: non-hardware mechanisms.
    for obj in objects:
        name = base_group_name(obj)

        if is_fastener_name(name):
            continue

        role = classify_nonhardware(obj)
        assignment[obj] = role

        if role != "HEAD":
            moving_centers.append(
                (object_center(obj), role)
            )

    # Second pass: hardware.
    for obj in objects:
        name = base_group_name(obj)
        if not is_fastener_name(name):
            continue

        role = "HEAD"

        if AUTO_ATTACH_NEARBY_FASTENERS and moving_centers:
            c = object_center(obj)
            nearest_role = None
            nearest_dist = float("inf")

            for p, candidate_role in moving_centers:
                d = (c - p).length
                if d < nearest_dist:
                    nearest_dist = d
                    nearest_role = candidate_role

            if nearest_dist <= FASTENER_FOLLOW_DISTANCE_MM:
                role = nearest_role

        assignment[obj] = role

    return assignment


def role_collection(role, is_hardware):
    root = ensure_collection(COL_ROOT)

    if is_hardware:
        return ensure_collection(COL_HARDWARE, root)

    if role.startswith("EYE_"):
        return ensure_collection(COL_EYES, root)

    if role.startswith("LID_"):
        return ensure_collection(COL_LIDS, root)

    if role.startswith("BROW_"):
        return ensure_collection(COL_BROWS, root)

    if (
        role == "JAW"
        or role.startswith("LIP_")
    ):
        return ensure_collection(COL_MOUTH, root)

    return ensure_collection(COL_STATIC, root)


def organize_components(assignment):
    counts = {}

    for obj, role in assignment.items():
        obj["cogly_role"] = role

        name = base_group_name(obj)
        target = role_collection(
            role,
            is_fastener_name(name),
        )
        move_object_to_collection(obj, target)

        counts[role] = counts.get(role, 0) + 1

    return counts


# ============================================================================
# RIG LANDMARKS
# ============================================================================

def objects_with_role(assignment, role):
    return [obj for obj, r in assignment.items() if r == role]


def centers_for_role(assignment, role):
    return [object_center(obj) for obj in objects_with_role(assignment, role)]


def find_group_objects(objects, group_name):
    return [
        obj for obj in objects
        if base_group_name(obj) == group_name
    ]


def derive_landmarks(objects, assignment):
    def mapped_centers(role):
        return [
            Vector(entry["center"])
            for entry in PART_MAP.values()
            if entry["role"] == role
        ]

    landmarks = {}

    landmarks["EYE_L"] = average_points(
        mapped_centers("EYE_L")
    )
    landmarks["EYE_R"] = average_points(
        mapped_centers("EYE_R")
    )

    # From the two lower M4 shoulder-pivot centers in the OBJ reference.
    landmarks["JAW"] = Vector((
        -0.5,
        -43.25885,
        -84.99145,
    ))

    for side in ("L", "R"):
        landmarks[f"BROW_{side}"] = average_points(
            mapped_centers(f"BROW_{side}"),
            fallback=(
                38.0 if side == "L" else -38.0,
                -55.0,
                55.0,
            ),
        )

        landmarks[f"LIP_{side}_UPPER"] = average_points(
            mapped_centers(f"LIP_{side}_UPPER"),
            fallback=(
                28.0 if side == "L" else -28.0,
                -55.0,
                -50.0,
            ),
        )

        landmarks[f"LIP_{side}_LOWER"] = average_points(
            mapped_centers(f"LIP_{side}_LOWER"),
            fallback=(
                28.0 if side == "L" else -28.0,
                -58.0,
                -86.0,
            ),
        )

    brow_layout = compute_flexible_brow_layout()
    landmarks["BROW_FLEX_L"] = brow_layout["L"]
    landmarks["BROW_FLEX_R"] = brow_layout["R"]

    # Animation-friendly whole-head pivot near the lower/rear skull.
    landmarks["HEAD"] = Vector((0.0, 45.0, -78.0))

    return landmarks


# ============================================================================
# ARMATURE

def add_link_bone_between(
    data,
    bones,
    name,
    start,
    end,
    parent=None,
    connect=False,
):
    start = Vector(start)
    end = Vector(end)

    if (end - start).length < 0.001:
        end = start + Vector((0.0, 0.0, 1.0))

    b = data.edit_bones.new(name)
    b.head = start
    b.tail = end
    b.use_deform = False

    if parent is not None:
        b.parent = bones[parent]
        b.use_connect = bool(connect)

    bones[name] = b
    return b


def add_target_bone(
    data,
    bones,
    name,
    position,
    parent,
):
    p = Vector(position)

    b = data.edit_bones.new(name)
    b.head = p
    b.tail = p + Vector((0.0, 0.0, 4.0))
    b.parent = bones[parent]
    b.use_deform = False

    bones[name] = b
    return b


# ============================================================================

def add_edit_bone(data, table, name, head, parent=None, length=10.0):
    b = data.edit_bones.new(name)
    b.head = Vector(head)

    # Bones are aligned with world Z.
    # Therefore:
    #   local X ~= world X
    #   local Y ~= world Z
    #   local Z ~= world -Y
    b.tail = Vector(head) + Vector((0.0, 0.0, length))

    if parent is not None:
        b.parent = table[parent]

    table[name] = b
    return b


def add_rotation_limit(pb, axis, low_deg, high_deg):
    c = pb.constraints.new("LIMIT_ROTATION")
    c.name = "COGLY Mechanical Limit"
    c.owner_space = "LOCAL"

    low = math.radians(low_deg)
    high = math.radians(high_deg)

    if axis == 0:
        c.use_limit_x = True
        c.min_x = low
        c.max_x = high
    elif axis == 1:
        c.use_limit_y = True
        c.min_y = low
        c.max_y = high
    else:
        c.use_limit_z = True
        c.min_z = low
        c.max_z = high

    c.use_transform_limit = True


def orient_link_hole_pairs(mesh_keys, root_hint, target_hint):
    """
    Choose each link's hole-to-hole direction so adjacent links require the
    shortest connector rods and the final hole is nearest the facial endpoint.

    Every returned actual-link endpoint remains an exact detected pivot center.
    """
    pairs = [
        (
            Vector(LINK_HOLE_PAIRS[key][0]),
            Vector(LINK_HOLE_PAIRS[key][1]),
        )
        for key in mesh_keys
    ]

    # Dynamic programming over two possible directions per rigid link.
    states = []
    for index, (a, b) in enumerate(pairs):
        options = ((a, b), (b, a))
        current = []

        if index == 0:
            root_hint_v = Vector(root_hint)
            current = [
                (
                    (option[0] - root_hint_v).length,
                    -1,
                    option,
                )
                for option in options
            ]
        else:
            previous = states[-1]
            for option in options:
                best = None
                for prev_index, prev_state in enumerate(previous):
                    prev_cost, _prev_parent, prev_option = prev_state
                    cost = prev_cost + (
                        prev_option[1] - option[0]
                    ).length
                    candidate = (cost, prev_index, option)
                    if best is None or candidate[0] < best[0]:
                        best = candidate
                current.append(best)

        states.append(current)

    target_hint = Vector(target_hint)
    last_states = states[-1]
    winner = min(
        range(len(last_states)),
        key=lambda i: (
            last_states[i][0]
            + (last_states[i][2][1] - target_hint).length
        ),
    )

    oriented = [None] * len(mesh_keys)
    state_index = winner

    for i in range(len(mesh_keys) - 1, -1, -1):
        cost, parent_index, option = states[i][state_index]
        oriented[i] = option
        state_index = parent_index
        if i == 0:
            break

    return oriented


def topology_gap_profile(chain_name, mesh_keys):
    """Return rest-pose hole-center gaps for a hypothesized serial order.

    This reports the geometry; it does not assert the order is mechanically
    correct and does not change transforms, mesh parents, or IK constraints.
    """
    root = Vector(CHAIN_ROOT_POINTS[chain_name])
    end = Vector(CHAIN_ENDPOINT_POINTS[chain_name])
    oriented = orient_link_hole_pairs(mesh_keys, root, end)
    spans = [("servo_to_first", (root - oriented[0][0]).length)]
    for index in range(len(oriented) - 1):
        spans.append((f"link_{index+1:02d}_to_{index+2:02d}",
                      (oriented[index][1] - oriented[index+1][0]).length))
    spans.append(("last_to_face", (oriented[-1][1] - end).length))
    return {
        "mesh_keys": list(mesh_keys),
        "spans_mm": {name: round(distance, 4) for name, distance in spans},
        "total_unmodeled_distance_mm": round(sum(distance for _, distance in spans), 4),
        "largest_span_mm": round(max(distance for _, distance in spans), 4),
    }


def get_topology_review():
    """Compare the present and candidate graphs without modifying either."""
    results = {}
    for chain_name, candidate in TOPOLOGY_REVIEW_CANDIDATES.items():
        current = next(chain["mesh_keys"] for chain in KINEMATIC_CHAINS
                       if chain["name"] == chain_name)
        results[chain_name] = {
            "active": topology_gap_profile(chain_name, current),
            "candidate_not_applied": topology_gap_profile(chain_name, candidate),
            "note": TOPOLOGY_REVIEW_NOTES[chain_name],
        }
    results["other_unverified"] = TOPOLOGY_REVIEW_NOTES
    return results


def build_pivot_accurate_chain(
    data,
    bones,
    chain,
):
    """
    Build one continuous mechanical chain:

        servo/output center
            -> optional visible connector rod
            -> exact hole-to-hole printed links
            -> optional visible connector rods
            -> ACTUAL pivot hole in the manipulated facial part

    Every parent/child joint is connected in the armature when the coordinates
    coincide, so the IK chain cannot drift apart at the joints.
    """
    chain_name = chain["name"]
    target_parent = chain["target_parent"]

    # Reference-contact chains for brow mechanisms.
    # Brows use the reference-contact chain.
    # Eyelids use actual detected hole-to-hole link bones so the rig
    # overlays the physical lever/horn geometry at neutral.
    if (
        chain_name in REFERENCE_CHAIN_POINTS
        and not chain_name.startswith("LID_")
    ):
        points = [Vector(p) for p in REFERENCE_CHAIN_POINTS[chain_name]]
        if len(points) != len(chain["mesh_keys"]) + 1:
            raise RuntimeError(
                f"Reference chain {chain_name}: points must equal mesh_keys + 1."
            )

        target_name = f"TARGET_{chain_name}"
        add_target_bone(data, bones, target_name, points[-1], target_parent)

        previous_bone = None
        for index, key in enumerate(chain["mesh_keys"], start=1):
            bone_name = LINK_BONE_FOR_KEY[key]
            add_link_bone_between(
                data, bones, bone_name, points[index - 1], points[index],
                chain["root_parent"] if previous_bone is None else previous_bone,
                previous_bone is not None,
            )
            previous_bone = bone_name

        return {
            "last_bone": previous_bone,
            "target": target_name,
            "chain_count": len(chain["mesh_keys"]),
            "root_hole": tuple(points[0]),
            "target_hole": tuple(points[-1]),
            "connectors": [],
            "reference_traced": True,
        }

    root_point = Vector(
        CHAIN_ROOT_POINTS[chain_name]
    )
    target_point = Vector(
        EYELID_RIG_TARGET_POINTS.get(chain_name, CHAIN_ENDPOINT_POINTS[chain_name])
    )

    oriented = orient_link_hole_pairs(
        chain["mesh_keys"],
        root_point,
        target_point,
    )

    target_name = f"TARGET_{chain_name}"
    add_target_bone(
        data,
        bones,
        target_name,
        target_point,
        target_parent,
    )

    previous_bone = None
    previous_tail = None
    segment_count = 0
    connector_records = []

    # Servo/output -> first printed link.
    first_start = oriented[0][0]
    root_gap = (first_start - root_point).length

    if root_gap > LINK_CONNECT_EPS_MM:
        root_connector = (
            f"VLINK_{chain_name}_ROOT"
        )

        add_link_bone_between(
            data,
            bones,
            root_connector,
            root_point,
            first_start,
            chain["root_parent"],
            False,
        )

        connector_records.append({
            "bone": root_connector,
            "p0": tuple(root_point),
            "p1": tuple(first_start),
            "kind": "servo_to_link",
            "chain": chain_name,
        })

        previous_bone = root_connector
        previous_tail = first_start
        segment_count += 1

    for index, (key, endpoints) in enumerate(
        zip(chain["mesh_keys"], oriented),
        start=1,
    ):
        start, end = (
            endpoints[0].copy(),
            endpoints[1].copy(),
        )

        if previous_tail is not None:
            gap = (start - previous_tail).length

            if gap > LINK_CONNECT_EPS_MM:
                connector_name = (
                    f"VLINK_{chain_name}_{index - 1:02d}"
                )

                add_link_bone_between(
                    data,
                    bones,
                    connector_name,
                    previous_tail,
                    start,
                    previous_bone,
                    True,
                )

                connector_records.append({
                    "bone": connector_name,
                    "p0": tuple(previous_tail),
                    "p1": tuple(start),
                    "kind": "between_links",
                    "chain": chain_name,
                })

                previous_bone = connector_name
                previous_tail = start
                segment_count += 1
            else:
                # Snap the next rigid bone to the exact previous tail so the
                # armature joint is genuinely connected.
                start = previous_tail.copy()

        bone_name = LINK_BONE_FOR_KEY[key]

        parent = (
            chain["root_parent"]
            if previous_bone is None
            else previous_bone
        )

        add_link_bone_between(
            data,
            bones,
            bone_name,
            start,
            end,
            parent,
            previous_bone is not None,
        )

        previous_bone = bone_name
        previous_tail = end
        segment_count += 1

    # Final printed linkage -> actual hole in the manipulated face part.
    endpoint_gap = (
        target_point - previous_tail
    ).length

    if endpoint_gap > LINK_CONNECT_EPS_MM:
        endpoint_connector = (
            f"VLINK_{chain_name}_ENDPOINT"
        )

        add_link_bone_between(
            data,
            bones,
            endpoint_connector,
            previous_tail,
            target_point,
            previous_bone,
            True,
        )

        connector_records.append({
            "bone": endpoint_connector,
            "p0": tuple(previous_tail),
            "p1": tuple(target_point),
            "kind": "link_to_face_hole",
            "chain": chain_name,
        })

        previous_bone = endpoint_connector
        previous_tail = target_point
        segment_count += 1

    return {
        "last_bone": previous_bone,
        "target": target_name,
        "chain_count": segment_count,
        "root_hole": tuple(root_point),
        "target_hole": tuple(target_point),
        "connectors": connector_records,
    }



def _make_rod_object(
    name,
    p0,
    p1,
    collection,
    radius=LINK_ROD_RADIUS_MM,
    segments=LINK_ROD_SEGMENTS,
):
    p0 = Vector(p0)
    p1 = Vector(p1)
    direction = p1 - p0
    length = direction.length

    if length <= 1e-6:
        return None

    direction.normalize()

    helper = (
        Vector((0.0, 0.0, 1.0))
        if abs(direction.z) < 0.9
        else Vector((0.0, 1.0, 0.0))
    )

    axis_u = direction.cross(helper)

    if axis_u.length <= 1e-8:
        helper = Vector((1.0, 0.0, 0.0))
        axis_u = direction.cross(helper)

    axis_u.normalize()
    axis_v = direction.cross(axis_u)
    axis_v.normalize()

    vertices = []
    faces = []

    for ring_point in (p0, p1):
        for i in range(segments):
            angle = (
                2.0 * math.pi
                * i / float(segments)
            )

            offset = (
                math.cos(angle) * axis_u
                + math.sin(angle) * axis_v
            ) * radius

            vertices.append(
                tuple(ring_point + offset)
            )

    for i in range(segments):
        j = (i + 1) % segments

        faces.append((
            i,
            j,
            segments + j,
        ))
        faces.append((
            i,
            segments + j,
            segments + i,
        ))

    mesh = bpy.data.meshes.new(
        name + "__MESH"
    )
    mesh.from_pydata(
        vertices,
        [],
        faces,
    )
    mesh.update()

    obj = bpy.data.objects.new(
        name,
        mesh,
    )
    collection.objects.link(obj)
    obj.matrix_world = Matrix.Identity(4)
    obj["cogly_generated_link_rod"] = True
    return obj


def create_visible_connector_rods_DISABLED_V10(
    arm,
    chain_runtime,
):
    root = ensure_collection(COL_ROOT)
    collection = ensure_collection(
        COL_LINK_RODS,
        root,
    )

    created = []

    for info in chain_runtime:
        for record in info.get(
            "connectors",
            [],
        ):
            p0 = Vector(record["p0"])
            p1 = Vector(record["p1"])

            if (p1 - p0).length <= 0.25:
                continue

            obj = _make_rod_object(
                "Rod__"
                + record["chain"]
                + "__"
                + record["kind"],
                p0,
                p1,
                collection,
            )

            if obj is None:
                continue

            world = obj.matrix_world.copy()

            obj.parent = arm
            obj.parent_type = "BONE"
            obj.parent_bone = record["bone"]
            obj.matrix_world = world

            obj["cogly_chain"] = record["chain"]
            obj["cogly_connector_kind"] = record["kind"]
            created.append(obj)

    return created


def build_armature(landmarks):
    rig_col = ensure_collection(COL_RIG)

    data = bpy.data.armatures.new(RIG_NAME + "__DATA")
    data.display_type = "STICK"

    arm = bpy.data.objects.new(RIG_NAME, data)
    rig_col.objects.link(arm)
    arm.show_in_front = True

    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")

    bones = {}

    head = landmarks["HEAD"]
    root_head = head + Vector((0.0, 0.0, -20.0))

    add_edit_bone(data, bones, "ROOT", root_head, None, 18.0)
    add_edit_bone(data, bones, "HEAD_YAW", head, "ROOT", 14.0)
    add_edit_bone(data, bones, "HEAD_PITCH", head, "HEAD_YAW", 14.0)
    add_edit_bone(data, bones, "HEAD_ROLL", head, "HEAD_PITCH", 14.0)

    # Jaw control is centered on the actual coaxial JawBase hinge-hole axis.
    add_edit_bone(
        data, bones,
        "JAW",
        Vector(ENDPOINT_SPECS["JAW"]["origin"]),
        "HEAD_ROLL",
        12.0,
    )

    # Eyes
    # ------------------------------------------------------------------
    # Shared physical two-axis eye mechanism.
    # ------------------------------------------------------------------
    # The real head has one left/right servo and one up/down servo for both
    # eyes. Independent L/R properties are retained as residual animation
    # overrides, but their average drives the actual shared mechanism.
    add_edit_bone(
        data,
        bones,
        "EYE_YAW_SHARED",
        EYE_SHARED_ORIGIN,
        "HEAD_ROLL",
        10.0,
    )
    add_edit_bone(
        data,
        bones,
        "EYE_PITCH_SHARED",
        EYE_SHARED_ORIGIN,
        "EYE_YAW_SHARED",
        10.0,
    )

    # Front SG90 / CentralServoHorn branch.
    # One-bone IK makes the real horn free end follow a hidden holder-coupling
    # target. The target is hidden because the reference OBJ does not contain
    # a physical mesh bridging this connection.
    add_link_bone_between(
        data,
        bones,
        "MECH_EYE_YAW_HORN",
        EYE_YAW_SERVO_PIVOT,
        EYE_YAW_HORN_FREE,
        "HEAD_ROLL",
        False,
    )
    add_target_bone(
        data,
        bones,
        "TARGET_EYE_YAW_COUPLING",
        EYE_YAW_HORN_FREE,
        "EYE_YAW_SHARED",
    )

    # Rear SG90 -> VerticalHorn -> VerticalLever -> upper holder clip.
    # These two rigid links form a source-supported two-link IK chain.
    add_link_bone_between(
        data,
        bones,
        "MECH_EYE_PITCH_HORN",
        EYE_PITCH_SERVO_PIVOT,
        EYE_PITCH_REAR_JOINT,
        "HEAD_ROLL",
        False,
    )
    add_link_bone_between(
        data,
        bones,
        "MECH_EYE_PITCH_LEVER",
        EYE_PITCH_REAR_JOINT,
        EYE_PITCH_HOLDER_JOINT,
        "MECH_EYE_PITCH_HORN",
        True,
    )
    add_target_bone(
        data,
        bones,
        "TARGET_EYE_PITCH_HOLDER",
        EYE_PITCH_HOLDER_JOINT,
        "EYE_PITCH_SHARED",
    )

    for side in ("L", "R"):
        eye = landmarks[f"EYE_{side}"]

        add_edit_bone(
            data, bones,
            f"EYE_{side}_YAW",
            eye,
            "EYE_PITCH_SHARED",
            9.0,
        )
        add_edit_bone(
            data, bones,
            f"EYE_{side}_PITCH",
            eye,
            f"EYE_{side}_YAW",
            9.0,
        )

        upper_name = f"LID_{side}_UPPER"
        lower_name = f"LID_{side}_LOWER"

        for lid_name in (upper_name, lower_name):
            lid_origin = Vector(
                ENDPOINT_SPECS[lid_name]["origin"]
            )

            # Actual endpoint/deform bone.
            add_edit_bone(
                data,
                bones,
                lid_name,
                lid_origin,
                "HEAD_ROLL",
                8.0,
            )

            # Hidden automatic blink driver bone.
            add_edit_bone(
                data,
                bones,
                f"AUTO_{lid_name}",
                lid_origin,
                "HEAD_ROLL",
                11.0,
            )

            # Visible manual control bone. This bone has no rotation driver;
            # X remains freely poseable while Y/Z are locked.
            add_edit_bone(
                data,
                bones,
                f"CTRL_{lid_name}",
                lid_origin,
                "HEAD_ROLL",
                15.0,
            )

        # The flexible eyebrow's deform anchors ARE its real mounting-hole
        # centers, which are also the final holes of the inner/outer brow
        # linkage chains.
        inner = Vector(
            BROW_ATTACHMENT_HOLES[side]["inner"]
        )
        outer = Vector(
            BROW_ATTACHMENT_HOLES[side]["outer"]
        )
        flex_center = Vector(
            BROW_REFERENCE_MID[side]
        )

        add_edit_bone(
            data, bones,
            f"BROW_{side}",
            inner,
            "HEAD_ROLL",
            7.0,
        )
        add_edit_bone(
            data, bones,
            f"BROW_{side}_MID",
            flex_center,
            "HEAD_ROLL",
            7.0,
        )
        add_edit_bone(
            data, bones,
            f"BROW_{side}_OUTER",
            outer,
            "HEAD_ROLL",
            7.0,
        )

        upper_lip_name = f"LIP_{side}_UPPER"
        lower_lip_name = f"LIP_{side}_LOWER"

        add_edit_bone(
            data,
            bones,
            upper_lip_name,
            Vector(
                ENDPOINT_SPECS[
                    upper_lip_name
                ]["origin"]
            ),
            "HEAD_ROLL",
            8.0,
        )

        add_edit_bone(
            data,
            bones,
            lower_lip_name,
            Vector(
                ENDPOINT_SPECS[
                    lower_lip_name
                ]["origin"]
            ),
            "JAW",
            8.0,
        )

    # ------------------------------------------------------------------
    # Pivot-hole-accurate servo-to-face linkage chains.
    # ------------------------------------------------------------------
    chain_runtime = []

    for chain in KINEMATIC_CHAINS:
        info = build_pivot_accurate_chain(
            data,
            bones,
            chain,
        )
        info["name"] = chain["name"]
        chain_runtime.append(info)

    bpy.ops.object.mode_set(mode="POSE")

    for pb in arm.pose.bones:
        pb.rotation_mode = "XYZ"

    # ------------------------------------------------------------------
    # V11 lid-control architecture
    # ------------------------------------------------------------------
    # AUTO lid bones receive blink-property drivers.
    # CTRL lid bones are directly poseable around X.
    # The actual LID endpoint bones add both rotations together.
    for side in ("L", "R"):
        for level in ("UPPER", "LOWER"):
            lid_name = f"LID_{side}_{level}"
            auto_name = f"AUTO_{lid_name}"
            ctrl_name = f"CTRL_{lid_name}"

            endpoint_pb = arm.pose.bones[lid_name]
            auto_pb = arm.pose.bones[auto_name]
            ctrl_pb = arm.pose.bones[ctrl_name]

            # Manual controls rotate only on the physical eyelid hinge axis.
            ctrl_pb.lock_location = (True, True, True)
            ctrl_pb.lock_rotation = (False, True, True)
            ctrl_pb.lock_scale = (True, True, True)

            auto_pb.lock_location = (True, True, True)
            auto_pb.lock_rotation = (False, True, True)
            auto_pb.lock_scale = (True, True, True)

            endpoint_pb.lock_location = (True, True, True)
            endpoint_pb.lock_rotation = (False, True, True)
            endpoint_pb.lock_scale = (True, True, True)

            c_auto = endpoint_pb.constraints.new("COPY_ROTATION")
            c_auto.name = "COGLY Auto Blink"
            c_auto.target = arm
            c_auto.subtarget = auto_name
            c_auto.owner_space = "LOCAL"
            c_auto.target_space = "LOCAL"
            if hasattr(c_auto, "mix_mode"):
                c_auto.mix_mode = "REPLACE"

            c_manual = endpoint_pb.constraints.new("COPY_ROTATION")
            c_manual.name = "COGLY Manual Lid Offset"
            c_manual.target = arm
            c_manual.subtarget = ctrl_name
            c_manual.owner_space = "LOCAL"
            c_manual.target_space = "LOCAL"
            if hasattr(c_manual, "mix_mode"):
                c_manual.mix_mode = "ADD"

    # ------------------------------------------------------------------
    # V12 central eye mechanism constraints
    # ------------------------------------------------------------------

    # Front yaw horn: source has the horn and servo, but no visible coupling
    # piece from the horn's free hole to the moving eye core. A hidden one-link
    # IK relation preserves that source gap while keeping the horn mechanically
    # related to eye yaw.
    yaw_horn_pb = arm.pose.bones[
        "MECH_EYE_YAW_HORN"
    ]
    yaw_ik = yaw_horn_pb.constraints.new("IK")
    yaw_ik.name = "COGLY Eye Yaw Servo Coupling"
    yaw_ik.target = arm
    yaw_ik.subtarget = "TARGET_EYE_YAW_COUPLING"
    yaw_ik.chain_count = 1
    yaw_ik.use_tail = True
    yaw_ik.iterations = 64
    if hasattr(yaw_ik, "use_stretch"):
        yaw_ik.use_stretch = False

    # Rear pitch branch: a genuine two-link solution using the actual servo
    # pivot, VerticalHorn-to-VerticalLever joint, and upper holder clip.
    pitch_lever_pb = arm.pose.bones[
        "MECH_EYE_PITCH_LEVER"
    ]
    pitch_ik = pitch_lever_pb.constraints.new("IK")
    pitch_ik.name = "COGLY Eye Pitch Servo Linkage"
    pitch_ik.target = arm
    pitch_ik.subtarget = "TARGET_EYE_PITCH_HOLDER"
    pitch_ik.chain_count = 2
    pitch_ik.use_tail = True
    pitch_ik.iterations = 96
    if hasattr(pitch_ik, "use_stretch"):
        pitch_ik.use_stretch = False

    # IK now runs across actual hole-to-hole rigid link bones plus hidden
    # connector rods.  The target itself is also centered on a detected hole.
    for info in chain_runtime:
        pb = arm.pose.bones[info["last_bone"]]
        ik = pb.constraints.new("IK")
        ik.name = "COGLY Pivot-Hole Linkage IK"
        ik.target = arm
        ik.subtarget = info["target"]
        ik.chain_count = info["chain_count"]
        ik.use_tail = True
        ik.iterations = 96

        if hasattr(ik, "use_stretch"):
            ik.use_stretch = False

        # The IK solver includes virtual spans where no printed pushrod or
        # mating bore has been established.  Expose this fact on the pose bones
        # rather than allowing a visually closed IK line to suggest hardware.
        for connector in info.get("connectors", []):
            helper_pb = arm.pose.bones.get(connector["bone"])
            if helper_pb is not None:
                rest_length = (
                    Vector(connector["p1"]) - Vector(connector["p0"])
                ).length
                helper_pb["cogly_virtual_connector"] = True
                helper_pb["cogly_physical_connection_verified"] = False
                helper_pb["cogly_rest_span_mm"] = round(rest_length, 4)
                helper_pb["cogly_connection_type"] = connector["kind"]

        # Eyelid horn/lever systems are planar mechanisms. Restrict every
        # solver link/helper to X-axis hinge rotation to prevent neutral
        # twisting/flipping in Blender IK.
        if info["name"].startswith("LID_"):
            chain_def = next(
                (
                    c
                    for c in KINEMATIC_CHAINS
                    if c["name"] == info["name"]
                ),
                None,
            )

            if chain_def is not None:
                for key in chain_def["mesh_keys"]:
                    bone_name = LINK_BONE_FOR_KEY[key]
                    link_pb = arm.pose.bones.get(
                        bone_name
                    )
                    if link_pb is not None:
                        link_pb.lock_rotation = (
                            False,
                            True,
                            True,
                        )

            for connector in info.get(
                "connectors",
                [],
            ):
                helper_pb = arm.pose.bones.get(
                    connector["bone"]
                )
                if helper_pb is not None:
                    helper_pb.lock_rotation = (
                        False,
                        True,
                        True,
                    )

    add_rotation_limit(
        arm.pose.bones["HEAD_YAW"],
        1,
        *LIMITS_DEG["HEAD_YAW"],
    )
    add_rotation_limit(
        arm.pose.bones["HEAD_PITCH"],
        0,
        *LIMITS_DEG["HEAD_PITCH"],
    )
    add_rotation_limit(
        arm.pose.bones["HEAD_ROLL"],
        2,
        *LIMITS_DEG["HEAD_ROLL"],
    )

    add_rotation_limit(
        arm.pose.bones["JAW"],
        0,
        *LIMITS_DEG["JAW"],
    )

    add_rotation_limit(
        arm.pose.bones["EYE_YAW_SHARED"],
        1,
        *LIMITS_DEG["EYE_L_YAW"],
    )
    add_rotation_limit(
        arm.pose.bones["EYE_PITCH_SHARED"],
        0,
        *LIMITS_DEG["EYE_L_PITCH"],
    )

    for side in ("L", "R"):
        add_rotation_limit(
            arm.pose.bones[f"EYE_{side}_YAW"],
            1,
            *LIMITS_DEG[f"EYE_{side}_YAW"],
        )
        add_rotation_limit(
            arm.pose.bones[f"EYE_{side}_PITCH"],
            0,
            *LIMITS_DEG[f"EYE_{side}_PITCH"],
        )

        # V11: no Limit Rotation constraint is added to the eyelid endpoint
        # or CTRL bones. Their Y/Z axes are locked, leaving X as the single
        # freely poseable hinge axis.

    bpy.ops.object.mode_set(mode="OBJECT")

    # V10: physically nonexistent generated rod meshes are disabled.
    arm["cogly_visible_connector_rods"] = 0

    return arm


# ============================================================================
# OBJECT -> BONE PARENTING
# ============================================================================

def bone_for_role(role):
    if role == "HEAD":
        return "HEAD_ROLL"

    if role == "JAW":
        return "JAW"

    if role == "EYE_L":
        return "EYE_L_PITCH"

    if role == "EYE_R":
        return "EYE_R_PITCH"

    if role.startswith("LID_"):
        return role

    if role.startswith("BROW_"):
        return role

    if role.startswith("LIP_"):
        return role

    return "HEAD_ROLL"


def parent_components(arm, assignment):
    counts = {}

    for obj, role in assignment.items():
        key = str(obj.get("cogly_3mf_key", ""))

        if key in EYE_MECH_PART_BONES:
            bone = EYE_MECH_PART_BONES[key]
            obj["cogly_eye_mechanism_part"] = True
        elif key in LINK_BONE_FOR_KEY:
            bone = LINK_BONE_FOR_KEY[key]
        elif key in ENDPOINT_PART_BONES:
            bone = ENDPOINT_PART_BONES[key]
            obj["cogly_is_face_endpoint"] = True
        else:
            bone = bone_for_role(role)

        # Split any remaining brow items that are not part of a kinematic chain.
        # drivers so the visible mechanism relates to the flexible strip.
        if (
            key not in LINK_BONE_FOR_KEY
            and role in {"BROW_L", "BROW_R"}
        ):
            entry = PART_MAP.get(key)

            if entry is not None:
                center_x = float(entry["center"][0])

                if abs(center_x) >= 45.0:
                    bone = role + "_OUTER"

        if bone not in arm.pose.bones:
            bone = "HEAD_ROLL"

        world = obj.matrix_world.copy()

        obj.parent = arm
        obj.parent_type = "BONE"
        obj.parent_bone = bone
        obj.matrix_world = world

        obj["cogly_bone"] = bone

        counts[bone] = counts.get(bone, 0) + 1

    return counts


# ============================================================================
# CONTROL PROPERTIES + DRIVERS
# ============================================================================

def create_control_properties(arm):
    for name, (default, low, high, description) in CONTROL_DEFS.items():
        arm[name] = default

        try:
            ui = arm.id_properties_ui(name)
            ui.update(
                min=low,
                max=high,
                soft_min=low,
                soft_max=high,
                default=default,
                description=description,
            )
        except Exception:
            pass


def add_driver(arm, bone_name, data_path, index, prop_name, expression):
    pb = arm.pose.bones[bone_name]

    try:
        pb.driver_remove(data_path, index)
    except Exception:
        pass

    fcurve = pb.driver_add(data_path, index)
    driver = fcurve.driver
    driver.type = "SCRIPTED"

    var = driver.variables.new()
    var.name = "v"
    var.type = "SINGLE_PROP"
    var.targets[0].id = arm
    var.targets[0].data_path = f'["{prop_name}"]'

    driver.expression = expression


def add_two_prop_driver(
    arm,
    bone_name,
    data_path,
    index,
    prop_a,
    prop_b,
    expression,
):
    pb = arm.pose.bones[bone_name]

    try:
        pb.driver_remove(data_path, index)
    except Exception:
        pass

    fcurve = pb.driver_add(data_path, index)
    driver = fcurve.driver
    driver.type = "SCRIPTED"

    va = driver.variables.new()
    va.name = "a"
    va.type = "SINGLE_PROP"
    va.targets[0].id = arm
    va.targets[0].data_path = f'["{prop_a}"]'

    vb = driver.variables.new()
    vb.name = "b"
    vb.type = "SINGLE_PROP"
    vb.targets[0].id = arm
    vb.targets[0].data_path = f'["{prop_b}"]'

    driver.expression = expression


def add_three_prop_driver(arm, bone_name, data_path, index, props, expression):
    """Evaluate three independently-keyable controls, retaining the old one."""
    pb = arm.pose.bones[bone_name]
    try:
        pb.driver_remove(data_path, index)
    except Exception:
        pass
    driver = pb.driver_add(data_path, index).driver
    driver.type = "SCRIPTED"
    for variable_name, prop_name in zip(("a", "b", "c"), props):
        var = driver.variables.new()
        var.name = variable_name
        var.type = "SINGLE_PROP"
        var.targets[0].id = arm
        var.targets[0].data_path = f'["{prop_name}"]'
    driver.expression = expression


def range_expr(low_deg, high_deg):
    low = math.radians(low_deg)
    span = math.radians(high_deg - low_deg)
    return f"({low:.12g}) + ({span:.12g}) * v"


def zero_to_deg(deg):
    return f"({math.radians(deg):.12g}) * v"


def centered_mm(mm):
    return f"({float(mm):.12g}) * (v - 0.5) * 2.0"


def create_drivers(arm):
    # Head
    add_driver(
        arm,
        "HEAD_YAW",
        "rotation_euler",
        1,
        "head_yaw",
        range_expr(*LIMITS_DEG["HEAD_YAW"]),
    )
    add_driver(
        arm,
        "HEAD_PITCH",
        "rotation_euler",
        0,
        "head_pitch",
        range_expr(*LIMITS_DEG["HEAD_PITCH"]),
    )
    add_driver(
        arm,
        "HEAD_ROLL",
        "rotation_euler",
        2,
        "head_roll",
        range_expr(*LIMITS_DEG["HEAD_ROLL"]),
    )

    # Jaw: +X opens down/forward with this coordinate convention.
    add_driver(
        arm,
        "JAW",
        "rotation_euler",
        0,
        "mouth_open",
        zero_to_deg(LIMITS_DEG["JAW"][1]),
    )

    # Eyes
    # ------------------------------------------------------------------
    # The physical mechanism has one shared yaw servo and one shared pitch
    # servo. Their average follows the L/R requested controls.
    eye_yaw_low = math.radians(
        LIMITS_DEG["EYE_L_YAW"][0]
    )
    eye_yaw_span = math.radians(
        LIMITS_DEG["EYE_L_YAW"][1]
        - LIMITS_DEG["EYE_L_YAW"][0]
    )
    eye_pitch_low = math.radians(
        LIMITS_DEG["EYE_L_PITCH"][0]
    )
    eye_pitch_span = math.radians(
        LIMITS_DEG["EYE_L_PITCH"][1]
        - LIMITS_DEG["EYE_L_PITCH"][0]
    )

    add_two_prop_driver(
        arm,
        "EYE_YAW_SHARED",
        "rotation_euler",
        1,
        "eye_left_yaw",
        "eye_right_yaw",
        (
            f"({eye_yaw_low:.12g}) + "
            f"({eye_yaw_span:.12g}) * ((a + b) * 0.5)"
        ),
    )
    add_two_prop_driver(
        arm,
        "EYE_PITCH_SHARED",
        "rotation_euler",
        0,
        "eye_left_pitch",
        "eye_right_pitch",
        (
            f"({eye_pitch_low:.12g}) + "
            f"({eye_pitch_span:.12g}) * ((a + b) * 0.5)"
        ),
    )

    # Differential residuals preserve the existing independent-eye UI without
    # double-applying the shared motion. When both eyes request the same pose,
    # these residuals are zero and the hardware representation moves exactly
    # as a real two-servo shared eye mechanism.
    add_two_prop_driver(
        arm,
        "EYE_L_YAW",
        "rotation_euler",
        1,
        "eye_left_yaw",
        "eye_right_yaw",
        f"({eye_yaw_span:.12g}) * ((a - b) * 0.5)",
    )
    add_two_prop_driver(
        arm,
        "EYE_R_YAW",
        "rotation_euler",
        1,
        "eye_left_yaw",
        "eye_right_yaw",
        f"({eye_yaw_span:.12g}) * ((b - a) * 0.5)",
    )
    add_two_prop_driver(
        arm,
        "EYE_L_PITCH",
        "rotation_euler",
        0,
        "eye_left_pitch",
        "eye_right_pitch",
        f"({eye_pitch_span:.12g}) * ((a - b) * 0.5)",
    )
    add_two_prop_driver(
        arm,
        "EYE_R_PITCH",
        "rotation_euler",
        0,
        "eye_left_pitch",
        "eye_right_pitch",
        f"({eye_pitch_span:.12g}) * ((b - a) * 0.5)",
    )

    # Blink: upper lid down, lower lid up.
    add_driver(
        arm,
        "AUTO_LID_L_UPPER",
        "rotation_euler",
        0,
        "blink_left",
        zero_to_deg(LIMITS_DEG["UPPER_LID"][1]),
    )
    add_driver(
        arm,
        "AUTO_LID_L_LOWER",
        "rotation_euler",
        0,
        "blink_left",
        zero_to_deg(LIMITS_DEG["LOWER_LID"][0]),
    )

    add_driver(
        arm,
        "AUTO_LID_R_UPPER",
        "rotation_euler",
        0,
        "blink_right",
        zero_to_deg(LIMITS_DEG["UPPER_LID"][1]),
    )
    add_driver(
        arm,
        "AUTO_LID_R_LOWER",
        "rotation_euler",
        0,
        "blink_right",
        zero_to_deg(LIMITS_DEG["LOWER_LID"][0]),
    )

    # Flexible living-hinge brows.
    # Bone local Y ~= world Z.
    for side, prop in (
        ("L", "brow_left"),
        ("R", "brow_right"),
    ):
        add_driver(
            arm,
            f"BROW_{side}",
            "location",
            1,
            prop,
            centered_mm(BROW_INNER_TRAVEL_MM),
        )
        add_driver(
            arm,
            f"BROW_{side}_MID",
            "location",
            1,
            prop,
            centered_mm(BROW_MID_TRAVEL_MM),
        )
        add_driver(
            arm,
            f"BROW_{side}_OUTER",
            "location",
            1,
            prop,
            centered_mm(BROW_OUTER_TRAVEL_MM),
        )

    # Newer Cogley head: the main lip has separately controlled up/down
    # sections and each mouth corner uses coordinated orthogonal motion.
    # Source evidence establishes control INTENT, not the particular pivot
    # assignments/fasteners in this supplied 3MF. Keep the legacy smile
    # channel fully intact and make all new offsets exactly neutral at 0.5.
    # No parts, VLINK bones or source pivots are moved by this change.
    for side, sign, prop, side_word in (
        ("L", -1.0, "smile_left", "left"),
        ("R", 1.0, "smile_right", "right"),
    ):
        upper = f"LIP_{side}_UPPER"
        lower = f"LIP_{side}_LOWER"
        # The current head has one animated lip-surface attachment on each
        # side/level. Dedicated corner-hardware pivots are not established;
        # these influence the EXISTING target bones as visual proxies.
        for bone, main_prop, old_travel in (
            (upper, f"lip_upper_{side_word}", 4.0),
            (lower, f"lip_lower_{side_word}", 3.0),
        ):
            add_three_prop_driver(
                arm, bone, "location", 1,
                (prop, main_prop, f"corner_{side_word}_z"),
                f"({old_travel:.6g})*(a-0.5)*2.0 + 2.0*(b-0.5)*2.0 + 2.0*(c-0.5)*2.0",
            )
        for bone, scale in ((upper, 1.0), (lower, 0.75)):
            signed_travel = 2.0 * sign * scale
            add_two_prop_driver(
                arm, bone, "location", 0,
                prop, f"corner_{side_word}_x",
                f"({signed_travel:.6g})*((a-0.5)*2.0 + (b-0.5)*2.0)",
            )


def reset_controls(arm):
    for name, (default, _low, _high, _desc) in CONTROL_DEFS.items():
        arm[name] = default


def keyframe_controls(arm):
    frame = bpy.context.scene.frame_current

    for prop in CONTROL_PROPS:
        arm.keyframe_insert(
            data_path=f'["{prop}"]',
            frame=frame,
            group="COGLY_CONTROLS",
        )


# ============================================================================
# BUILD REPORT
# ============================================================================

def create_report(source, objects, role_counts, bone_counts, landmarks):
    report = {
        "geometry_source": source,
        "visible_geometry": "3MF assembly plus OBJ-reference servo bodies",
        "placement_reference": REFERENCE_OBJ_DESCRIPTION,
        "obj_imported_at_runtime": False,
        "servo_reference_geometry": SERVO_REFERENCE_FILENAME,
        "mapped_3mf_components": len(objects),
        "role_counts": role_counts,
        "bone_parent_counts": bone_counts,
        "landmarks_mm": {
            key: [float(v) for v in value]
            for key, value in landmarks.items()
        },
        "excluded": [
            "LateralFrame: no direct OBJ counterpart",
            "Eyebrows.stl x2: positioned from OBJ-referenced brow mechanism and deformed as flexible living hinges",
            "alternate/obsolete EyeCorePivotHolder",
            "duplicate CameraEye/DecoyEye print copies",
            "duplicate EyeAdaptor print copies",
        ],
        "notes": [
            (
                "Visible meshes are the individual Bambu 3MF parts."
            ),
            (
                "Their rest transforms were estimated from the supplied "
                "reference OBJ and may contain assembly errors."
            ),
            (
                "Functional groups are rigid-parented to separate bones, "
                "so controls move independently."
            ),
            (
                "Eyebrows.stl retain the V3-correct placement, use a curved "
                "neutral mesh, and remain three-anchor flexible."
            ),
            (
                "Facial target bones are placed at nominated attachment holes; "
                "large source-to-target spans remain unverified."
            ),
            (
                "Virtual VLINK armature helpers are NOT printed rods and "
                "do not prove mechanical connectivity."
            ),
            (
                "Eyebrow attachment estimates remain reference-based proxies; "
                "collision and hardware fit are not tested."
            ),
        ],
    }

    bpy.context.scene[SCENE_REPORT_KEY] = repr(report)
    return report


# ============================================================================
# BUILD
# ============================================================================

def configure_scene():
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 0.001
    scene.unit_settings.length_unit = "MILLIMETERS"

    # User previously preferred practical CAD-like clipping for mm models.
    for window in bpy.context.window_manager.windows:
        screen = window.screen
        if screen is None:
            continue

        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue

            for space in area.spaces:
                if space.type == "VIEW_3D":
                    space.clip_start = 1.0
                    space.clip_end = 10000.0


def build(source_path=None):
    source_path = source_path or find_source_3mf()

    if not source_path:
        raise FileNotFoundError(
            "BambuPrintfile.3mf was not found."
        )

    source_path = os.path.abspath(
        os.path.expanduser(source_path)
    )

    if not os.path.isfile(source_path):
        raise FileNotFoundError(source_path)

    if not source_path.lower().endswith(".3mf"):
        raise ValueError(
            "Please select BambuPrintfile.3mf."
        )

    configure_scene()
    cleanup_previous_build()

    bpy.context.scene[SCENE_SOURCE_KEY] = source_path

    root = ensure_collection(COL_ROOT)
    ensure_collection(COL_STATIC, root)
    ensure_collection(COL_EYES, root)
    ensure_collection(COL_LIDS, root)
    ensure_collection(COL_BROWS, root)
    ensure_collection(COL_MOUTH, root)
    ensure_collection(COL_HARDWARE, root)
    ensure_collection(COL_RIG)

    # Locate actual C-shaped eyelid clips in the selected 3MF and solve the
    # default rigid rest pose before any Blender object/bone is constructed.
    calibrate_eyelid_rest_pose(source_path)

    objects, assignment = import_3mf_reference_assembly(
        source_path
    )

    # Add the two 3MF living-hinge eyebrow strips without changing any of the
    # 78 OBJ-referenced V2 component transforms.
    flexible_brows = import_flexible_eyebrows(
        source_path
    )

    role_counts = {}
    for role in assignment.values():
        role_counts[role] = role_counts.get(role, 0) + 1

    landmarks = derive_landmarks(
        objects,
        assignment,
    )

    arm = build_armature(landmarks)
    bone_counts = parent_components(
        arm,
        assignment,
    )

    servo_bodies = import_reference_servos()
    parent_servo_bodies(arm, servo_bodies)

    setup_flexible_eyebrow_deform(
        arm,
        flexible_brows,
    )

    create_control_properties(arm)
    create_drivers(arm)
    reset_controls(arm)

    create_report(
        source_path,
        objects + flexible_brows + servo_bodies,
        role_counts,
        bone_counts,
        landmarks,
    )

    # Source-supported topology review, explicitly non-authoritative.
    # This metadata is consumed by head_linkage_audit.py and is safe to keep
    # inside the saved scene.  It does not change animated geometry.
    topology_review = get_topology_review()
    # Explicitly separate published control behavior from 3MF-based topology.
    # This is an animation approximation until the newer jaw/lip joint
    # connectivity can be confirmed from CAD or assembly photos.
    arm["cogly_authoritative_link_holes_json"] = json.dumps({
        key: [list(p) for p in LINK_HOLE_PAIRS[key]]
        for chain in EYELID_CHAIN_MESHES.values() for key in chain
    })
    arm["cogly_eyelid_closed_loop_rest_json"] = json.dumps(EYELID_SOLVED_REST)
    arm["cogly_eyelid_physical_arc_fits_json"] = json.dumps(EYELID_CLIP_ARC_FITS)
    arm["cogly_builder_geometry_basis"] = "Source 3MF C-clip circle fits; actual neutral rest pose, no rescaled meshes"
    arm["cogly_eyelid_axial_layer_offsets_json"] = json.dumps(EYELID_AXIAL_OFFSETS_MM)
    arm["cogly_mouth_control_basis"] = "Cogley newer head: independent linear lip motion and paired orthogonal corner actuation; visual proxies only"
    arm["cogly_mouth_control_unverified"] = True
    arm["cogly_topology_review_json"] = json.dumps(topology_review)
    bpy.context.scene["cogly_topology_review_json"] = json.dumps(topology_review)

    # All large virtual connectors remain visible to the reviewer as data;
    # none represents a proven physical pushrod, regardless of IK motion.
    unverified = []
    for chain in KINEMATIC_CHAINS:
        if chain["name"] in REFERENCE_CHAIN_POINTS and not chain["name"].startswith("LID_"):
            continue  # Brows use reference-proxy points, not source bores.
        profile = topology_gap_profile(chain["name"], chain["mesh_keys"])
        for part, distance in profile["spans_mm"].items():
            if distance >= UNVERIFIED_CONNECTOR_REVIEW_MM:
                unverified.append({"chain": chain["name"], "span": part,
                                   "neutral_gap_mm": distance,
                                   "status": "UNVERIFIED_PHYSICAL_CONNECTION"})
    arm["cogly_unverified_connections_json"] = json.dumps(unverified)
    log("UNVERIFIED source-hole connector spans:", len(unverified))
    log("Topology candidates are advisory; active rig orders unchanged.")

    # Keep the viewport usable: show only user-facing controls by default.
    # All hidden mechanism bones continue to solve normally.
    set_mechanism_bones_visible(
        arm,
        False,
    )

    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm

    log("=" * 70)
    log("3MF + OBJ-REFERENCE BUILD COMPLETE")
    log("Visible geometry: 3MF assembly + OBJ-reference servo bodies")
    log(
        "Reference transforms:",
        REFERENCE_OBJ_DESCRIPTION,
    )
    log("Mapped components:", len(objects))
    log("Open 3D View > N > Cogly Rig")
    log("=" * 70)

    return arm


# ============================================================================
# RIG SELECTION / VISIBILITY HELPERS
# ============================================================================

CONTROL_BONE_GROUPS = {
    "HEAD": (
        "HEAD_YAW",
        "HEAD_PITCH",
        "HEAD_ROLL",
        "JAW",
    ),
    "EYES": (
        "EYE_L_YAW",
        "EYE_L_PITCH",
        "EYE_R_YAW",
        "EYE_R_PITCH",
    ),
    "LIDS_L": (
        "CTRL_LID_L_UPPER",
        "CTRL_LID_L_LOWER",
    ),
    "LIDS_R": (
        "CTRL_LID_R_UPPER",
        "CTRL_LID_R_LOWER",
    ),
    "BROW_L": (
        "BROW_L",
        "BROW_L_MID",
        "BROW_L_OUTER",
    ),
    "BROW_R": (
        "BROW_R",
        "BROW_R_MID",
        "BROW_R_OUTER",
    ),
    "LIPS_L": (
        "LIP_L_UPPER",
        "LIP_L_LOWER",
    ),
    "LIPS_R": (
        "LIP_R_UPPER",
        "LIP_R_LOWER",
    ),
}

MECHANISM_BONE_PREFIXES = (
    "LINK_",
    "TARGET_",
    "VLINK_",
    "AUTO_",
    "MECH_EYE_",
)

INTERNAL_ENDPOINT_BONES = {
    "LID_L_UPPER",
    "LID_L_LOWER",
    "LID_R_UPPER",
    "LID_R_LOWER",
    "EYE_YAW_SHARED",
    "EYE_PITCH_SHARED",
}


def _is_mechanism_bone_name(name):
    return (
        name in INTERNAL_ENDPOINT_BONES
        or any(
            name.startswith(prefix)
            for prefix in MECHANISM_BONE_PREFIXES
        )
    )


def set_mechanism_bones_visible(
    arm,
    visible,
):
    for bone in arm.data.bones:
        if _is_mechanism_bone_name(
            bone.name
        ):
            bone.hide = not bool(visible)

    arm["cogly_show_mechanism_bones"] = bool(
        visible
    )


def select_control_group(
    context,
    group_name,
):
    arm = bpy.data.objects.get(RIG_NAME)

    if arm is None:
        return False

    names = CONTROL_BONE_GROUPS.get(
        group_name,
        (),
    )

    if not names:
        return False

    if context.object is not None:
        try:
            if context.object.mode != "OBJECT":
                bpy.ops.object.mode_set(
                    mode="OBJECT"
                )
        except Exception:
            pass

    bpy.ops.object.select_all(
        action="DESELECT"
    )
    arm.select_set(True)
    context.view_layer.objects.active = arm

    try:
        bpy.ops.object.mode_set(
            mode="POSE"
        )
    except Exception:
        return False

    bpy.ops.pose.select_all(
        action="DESELECT"
    )

    first = None

    for name in names:
        bone = arm.data.bones.get(name)

        if bone is None:
            continue

        bone.hide = False
        bone.select = True

        if first is None:
            first = bone

    if first is not None:
        arm.data.bones.active = first

    return first is not None


# ============================================================================
# UI
# ============================================================================

class COGLYOBJ_OT_SelectSource(bpy.types.Operator):
    bl_idname = "coglyobj.select_source"
    bl_label = "Choose Bambu 3MF"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(
        default="*.3mf",
        options={"HIDDEN"},
    )

    def invoke(self, context, event):
        existing = context.scene.get(SCENE_SOURCE_KEY, "")
        if existing:
            self.filepath = existing

        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        context.scene[SCENE_SOURCE_KEY] = self.filepath

        try:
            build(self.filepath)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            raise

        return {"FINISHED"}


class COGLYOBJ_OT_Rebuild(bpy.types.Operator):
    bl_idname = "coglyobj.rebuild"
    bl_label = "Rebuild OBJ Head"

    def execute(self, context):
        path = context.scene.get(SCENE_SOURCE_KEY, "") or find_source_3mf()

        if not path:
            bpy.ops.coglyobj.select_source("INVOKE_DEFAULT")
            return {"FINISHED"}

        try:
            build(path)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        return {"FINISHED"}


class COGLYOBJ_OT_SelectRig(bpy.types.Operator):
    bl_idname = "coglyobj.select_rig"
    bl_label = "Select Rig"

    def execute(self, context):
        arm = bpy.data.objects.get(RIG_NAME)
        if arm is None:
            return {"CANCELLED"}

        if context.object and context.object.mode != "OBJECT":
            try:
                bpy.ops.object.mode_set(mode="OBJECT")
            except Exception:
                pass

        bpy.ops.object.select_all(action="DESELECT")
        arm.select_set(True)
        context.view_layer.objects.active = arm
        return {"FINISHED"}


class COGLYOBJ_OT_SelectControlGroup(bpy.types.Operator):
    bl_idname = "coglyobj.select_control_group"
    bl_label = "Select Control Group"

    group: bpy.props.StringProperty(
        default="HEAD"
    )

    def execute(self, context):
        if not select_control_group(
            context,
            self.group,
        ):
            self.report(
                {"WARNING"},
                f"Control group {self.group!r} is unavailable.",
            )
            return {"CANCELLED"}

        return {"FINISHED"}


class COGLYOBJ_OT_ToggleMechanismBones(bpy.types.Operator):
    bl_idname = "coglyobj.toggle_mechanism_bones"
    bl_label = "Show/Hide Mechanism Bones"

    def execute(self, context):
        arm = bpy.data.objects.get(RIG_NAME)

        if arm is None:
            return {"CANCELLED"}

        currently_visible = bool(
            arm.get(
                "cogly_show_mechanism_bones",
                False,
            )
        )

        set_mechanism_bones_visible(
            arm,
            not currently_visible,
        )
        return {"FINISHED"}


class COGLYOBJ_OT_Reset(bpy.types.Operator):
    bl_idname = "coglyobj.reset"
    bl_label = "Reset Controls"

    def execute(self, context):
        arm = bpy.data.objects.get(RIG_NAME)
        if arm is None:
            return {"CANCELLED"}

        reset_controls(arm)
        return {"FINISHED"}


class COGLYOBJ_OT_Keyframe(bpy.types.Operator):
    bl_idname = "coglyobj.keyframe"
    bl_label = "Keyframe Controls"

    def execute(self, context):
        arm = bpy.data.objects.get(RIG_NAME)
        if arm is None:
            return {"CANCELLED"}

        keyframe_controls(arm)
        return {"FINISHED"}


class COGLYOBJ_OT_ToggleHardware(bpy.types.Operator):
    bl_idname = "coglyobj.toggle_hardware"
    bl_label = "Toggle Hardware"

    def execute(self, context):
        col = bpy.data.collections.get(COL_HARDWARE)
        if col is None:
            return {"CANCELLED"}

        col.hide_viewport = not col.hide_viewport
        col.hide_render = col.hide_viewport
        return {"FINISHED"}


class COGLYOBJ_PT_Rig(bpy.types.Panel):
    bl_label = "Cogly 3MF / OBJ Rig"
    bl_idname = "COGLYOBJ_PT_RIG"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Cogly Rig"

    def draw(self, context):
        layout = self.layout
        arm = bpy.data.objects.get(RIG_NAME)
        scene = context.scene

        box = layout.box()
        box.label(text="3MF Geometry / OBJ Placement")

        source = scene.get(SCENE_SOURCE_KEY, "")
        box.label(
            text=os.path.basename(source)
            if source
            else "No OBJ selected"
        )

        row = box.row(align=True)
        row.operator("coglyobj.select_source", text="Choose 3MF")
        row.operator("coglyobj.rebuild", text="Rebuild")

        box.operator(
            "coglyobj.select_rig",
            text="Select Whole Rig Object",
        )

        if arm is None:
            layout.label(text="Rig not built.")
            return

        select_box = layout.box()
        select_box.label(text="Quick Select Controls")

        row = select_box.row(align=True)
        op = row.operator(
            "coglyobj.select_control_group",
            text="Head / Jaw",
        )
        op.group = "HEAD"
        op = row.operator(
            "coglyobj.select_control_group",
            text="Eyes",
        )
        op.group = "EYES"

        row = select_box.row(align=True)
        op = row.operator(
            "coglyobj.select_control_group",
            text="Left Lids",
        )
        op.group = "LIDS_L"
        op = row.operator(
            "coglyobj.select_control_group",
            text="Right Lids",
        )
        op.group = "LIDS_R"

        row = select_box.row(align=True)
        op = row.operator(
            "coglyobj.select_control_group",
            text="Left Brow",
        )
        op.group = "BROW_L"
        op = row.operator(
            "coglyobj.select_control_group",
            text="Right Brow",
        )
        op.group = "BROW_R"

        row = select_box.row(align=True)
        op = row.operator(
            "coglyobj.select_control_group",
            text="Left Lips",
        )
        op.group = "LIPS_L"
        op = row.operator(
            "coglyobj.select_control_group",
            text="Right Lips",
        )
        op.group = "LIPS_R"

        select_box.operator(
            "coglyobj.toggle_mechanism_bones",
            text="Show / Hide Mechanism Bones",
        )

        box = layout.box()
        box.label(text="Head")
        box.prop(arm, '["head_yaw"]', text="Yaw")
        box.prop(arm, '["head_pitch"]', text="Pitch")
        box.prop(arm, '["head_roll"]', text="Roll")
        box.prop(arm, '["mouth_open"]', text="Jaw Open")

        box = layout.box()
        box.label(text="Eyes")
        box.prop(arm, '["eye_left_yaw"]', text="Left Yaw")
        box.prop(arm, '["eye_left_pitch"]', text="Left Pitch")
        box.prop(arm, '["eye_right_yaw"]', text="Right Yaw")
        box.prop(arm, '["eye_right_pitch"]', text="Right Pitch")

        box = layout.box()
        box.label(text="Lids")
        box.prop(arm, '["blink_left"]', text="Blink Left")
        box.prop(arm, '["blink_right"]', text="Blink Right")
        box.label(text="Use Quick Select for individual manual X rotation.")

        box = layout.box()
        box.label(text="Expression")
        box.prop(arm, '["brow_left"]', text="Brow Left")
        box.prop(arm, '["brow_right"]', text="Brow Right")
        box.prop(arm, '["smile_left"]', text="Smile Left")
        box.prop(arm, '["smile_right"]', text="Smile Right")

        mouth_box = layout.box()
        mouth_box.label(text="Mouth / lip articulation (visual controls)")
        mouth_box.label(text="0.5 neutral; not verified physical servo linkage")
        row = mouth_box.row(align=True)
        row.prop(arm, '["lip_upper_left"]', text="Upper L")
        row.prop(arm, '["lip_upper_right"]', text="Upper R")
        row = mouth_box.row(align=True)
        row.prop(arm, '["lip_lower_left"]', text="Lower L")
        row.prop(arm, '["lip_lower_right"]', text="Lower R")
        mouth_box.label(text="Corners: independent lateral / vertical animation")
        row = mouth_box.row(align=True)
        row.prop(arm, '["corner_left_x"]', text="Left X")
        row.prop(arm, '["corner_left_z"]', text="Left Z")
        row = mouth_box.row(align=True)
        row.prop(arm, '["corner_right_x"]', text="Right X")
        row.prop(arm, '["corner_right_z"]', text="Right Z")

        row = layout.row(align=True)
        row.operator("coglyobj.reset", text="Reset")
        row.operator("coglyobj.keyframe", text="Keyframe")

        box = layout.box()
        box.label(text="Display")
        box.operator(
            "coglyobj.toggle_hardware",
            text="Show/Hide Hardware",
        )

        box = layout.box()
        box.label(text="Build provenance")
        box.label(text="Visible meshes: 3MF + reference servos")
        box.label(text="Placement: supplied OBJ transform reference")
        box.label(text="Lids: real pivot-hole bones + reference clip targets")
        box.label(text="No fabricated Link Rod objects")
        box.label(text="Pivots: detected 3MF hole centers")
        box.label(text="Servos: 17 reference + 2 mirrored brow")
        box.label(text="Brows: V3 placement + reference curvature")
        box.label(text="Mechanism bones hidden by default; Quick Select added")


CLASSES = (
    COGLYOBJ_OT_SelectSource,
    COGLYOBJ_OT_Rebuild,
    COGLYOBJ_OT_SelectRig,
    COGLYOBJ_OT_SelectControlGroup,
    COGLYOBJ_OT_ToggleMechanismBones,
    COGLYOBJ_OT_Reset,
    COGLYOBJ_OT_Keyframe,
    COGLYOBJ_OT_ToggleHardware,
    COGLYOBJ_PT_Rig,
)


def register():
    for cls in reversed(CLASSES):
        old = getattr(bpy.types, cls.__name__, None)
        if old is not None:
            try:
                bpy.utils.unregister_class(old)
            except Exception:
                pass

    for cls in CLASSES:
        bpy.utils.register_class(cls)


def auto_build():
    source = find_source_3mf()

    if source:
        try:
            build(source)
            return
        except Exception as exc:
            log("Automatic OBJ build failed:", exc)

    log("Select BambuPrintfile.3mf.")
    try:
        bpy.ops.coglyobj.select_source("INVOKE_DEFAULT")
    except Exception as exc:
        log("Could not open file picker:", exc)
        log("Set SOURCE_3MF near the top of the script and rerun.")


if __name__ == "__main__":
    register()
    auto_build()
