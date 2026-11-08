"""
Partner card data and related functions for CZN.
Contains partner definitions, stats, passives, and helper functions.
"""

# Default partner data for unknown partners
DEFAULT_PARTNER = {
    "name": "Unknown",
    "grade": 3,
    "class": "Controller",
    "passive_name": "Unknown Passive",
    "passive_desc": "Unknown passive effect.",
    "values": {},
    "stats": {},
    "ego_name": "Unknown Skill",
    "ego_cost": 2,
    "ego_desc": "Unknown effect.",
}

# Unified partner card data: res_id -> all partner information
# Contains: name, grade, class, passive_name, passive_desc, values, stats, ego_name, ego_cost, ego_desc
# Note: Values marked with # EST are estimated (linear interpolation) - update when real data is available
from ._gen_partners import PARTNERS as _GENERATED_PARTNERS

# Generated from the client tables by tools/build_game_data.py (see _gen_partners.py).
# Each entry also carries "base_stats" (level-60 ATK/DEF/HP from partner_level/partner_ascend).
PARTNERS = dict(_GENERATED_PARTNERS)

# v1.7.0 listed Tina under res_id 20039; the client tables only have her as 20038.
# Keep the old id as an alias so nothing that stored 20039 loses the data.
LEGACY_PARTNER_ALIASES = {20039: 20038}
for _old_id, _new_id in LEGACY_PARTNER_ALIASES.items():
    if _old_id not in PARTNERS and _new_id in PARTNERS:
        PARTNERS[_old_id] = PARTNERS[_new_id]

# Base stats by grade and class at level 60
# Offensive classes (Hunter, Psionic, Ranger, Striker): High ATK, low DEF
# Defensive classes (Controller, Vanguard): Low ATK, high DEF
PARTNER_CLASS_STATS = {
    # 3-star classes
    (3, "Hunter"):     {"atk": 89, "def": 5, "hp": 85},
    (3, "Psionic"):    {"atk": 89, "def": 5, "hp": 85},
    (3, "Ranger"):     {"atk": 89, "def": 5, "hp": 85},
    (3, "Striker"):    {"atk": 89, "def": 5, "hp": 85},
    (3, "Controller"): {"atk": 5, "def": 36, "hp": 85},
    (3, "Vanguard"):   {"atk": 5, "def": 36, "hp": 85},
    # 4-star classes
    (4, "Hunter"):     {"atk": 101, "def": 5, "hp": 95},
    (4, "Psionic"):    {"atk": 101, "def": 5, "hp": 95},
    (4, "Ranger"):     {"atk": 101, "def": 5, "hp": 95},
    (4, "Striker"):    {"atk": 101, "def": 5, "hp": 95},
    (4, "Controller"): {"atk": 5, "def": 40, "hp": 95},
    (4, "Vanguard"):   {"atk": 5, "def": 40, "hp": 95},
    # 5-star classes
    (5, "Hunter"):     {"atk": 111, "def": 5, "hp": 105},
    (5, "Psionic"):    {"atk": 111, "def": 5, "hp": 105},
    (5, "Ranger"):     {"atk": 111, "def": 5, "hp": 105},
    (5, "Striker"):    {"atk": 111, "def": 5, "hp": 105},
    (5, "Controller"): {"atk": 5, "def": 44, "hp": 105},
    (5, "Vanguard"):   {"atk": 5, "def": 44, "hp": 105},
}


def get_partner(res_id: int) -> dict:
    """Get partner data by res_id, returning DEFAULT_PARTNER if not found."""
    return PARTNERS.get(res_id, DEFAULT_PARTNER)


def get_value_for_ego_level(values_tuple: tuple, limit_break: int) -> float:
    """Get the value from a 5-element tuple based on limit_break (0-4)."""
    if not values_tuple or len(values_tuple) < 5:
        return 0
    index = max(0, min(4, limit_break))  # Clamp to 0-4
    return values_tuple[index]


def get_partner_base_stats(res_id: int) -> dict:
    """Get base stats for a partner card based on its grade and class."""
    partner = get_partner(res_id)
    if partner.get("base_stats"):
        return partner["base_stats"]
    grade = partner.get("grade", 3)
    partner_class = partner.get("class", "Controller")
    base = PARTNER_CLASS_STATS.get((grade, partner_class), {"atk": 85, "def": 5, "hp": 90})
    return base


def get_partner_stats(res_id: int, level: int) -> dict:
    """Calculate partner card stats based on level.
    Stats scale linearly from base values to max at level 60."""
    base = get_partner_base_stats(res_id)
    scale = level / 60.0
    return {
        "atk": int(base["atk"] * scale),
        "def": int(base["def"] * scale),
        "hp": int(base["hp"] * scale),
    }


def get_partner_passive_stats(res_id: int, limit_break: int) -> dict:
    """Get unconditional passive stat bonuses for a partner card.
    Returns stat bonuses based on limit_break (0=E0 through 4=E4)."""
    partner = get_partner(res_id)
    stats = {}
    for stat_name, values_tuple in partner.get("stats", {}).items():
        stats[stat_name] = get_value_for_ego_level(values_tuple, limit_break)
    return stats


def format_passive_description(res_id: int, limit_break: int) -> str:
    """Format the passive description with values based on limit_break."""
    partner = get_partner(res_id)

    desc = partner.get("passive_desc", "Unknown passive effect.")
    values = partner.get("values", {})

    # Replace each placeholder with the value for this ego level
    for placeholder, values_tuple in values.items():
        current_val = get_value_for_ego_level(values_tuple, limit_break)
        # Format as integer if whole number, otherwise one decimal
        if current_val == int(current_val):
            val_str = str(int(current_val))
        else:
            val_str = f"{current_val:.1f}"
        desc = desc.replace("{" + placeholder + "}", val_str)

    return desc


def get_partner_passive_info(res_id: int, limit_break: int) -> dict:
    """Get full passive information for display.
    Returns dict with passive_name, formatted description, ego_name, ego_cost, ego_desc."""
    partner = get_partner(res_id)

    return {
        "passive_name": partner.get("passive_name", "Unknown"),
        "passive_desc": format_passive_description(res_id, limit_break),
        "ego_name": partner.get("ego_name", "Unknown"),
        "ego_cost": partner.get("ego_cost", 0),
        "ego_desc": partner.get("ego_desc", "Unknown effect."),
    }
