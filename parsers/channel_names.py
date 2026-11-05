"""AiM channel name → MoTeC i2 standard name mapping.

Sourced from aim2motec by ludovicb1239 (MIT licensed).
"""
# AIM_NAME → (MOTEC_NAME, MOTEC_SHORT_NAME)
NAME_MAP = {
    "ASteering":  ("Steered Angle", "Str Ang"),
    "Brake":      ("Brake Pos",     "Brk Pos"),
    "SpeedVeh":   ("Ground Speed",  "Gnd Spd"),
    "RPM":        ("Engine RPM",    "RPM"),
    "GLat":       ("G Force Lat",   "G Lat"),
    "GVert":      ("G Force Vert",  "G Vert"),
    "GLong":      ("G Force Long",  "G Long"),
    "VWheelFL":   ("Wheel Speed FL", "WSpd FL"),
    "VWheelFR":   ("Wheel Speed FR", "WSpd FR"),
    "VWheelRL":   ("Wheel Speed RL", "WSpd RL"),
    "VWheelRR":   ("Wheel Speed RR", "WSpd RR"),
    "WaterTemps": ("Eng Water Temp", "WaterTemp"),
}


def map_name(aim_name: str):
    """Return (motec_name, motec_short) for an AiM channel, or pass-through."""
    if aim_name in NAME_MAP:
        return NAME_MAP[aim_name]
    # Default: keep AiM name, derive short name (max 8 chars)
    short = aim_name[:8]
    return (aim_name, short)
