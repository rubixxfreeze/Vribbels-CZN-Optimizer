"""
Character data and related functions for CZN.
Contains character definitions, potential nodes, and helper functions.
"""

# Default character data for unknown characters
DEFAULT_CHARACTER = {
    "name": "Unknown",
    "grade": 0,
    "attribute": "Unknown",
    "class": "Unknown",
    "base_atk": 0,
    "base_def": 0,
    "base_hp": 0,
    "base_crit_rate": 0,
    "base_crit_dmg": 125.0,
    "node_50": None,
    "node_60": None,
}

# Unified character/hero data: res_id -> all character information
# Contains: name, grade, attribute, class, and base stats at level 60.
# Generated from the client tables by tools/build_game_data.py (see _gen_characters.py).
from ._gen_characters import CHARACTERS as _GENERATED_CHARACTERS, CHARACTER_MAX_LEVEL
from ._gen_characters import POTENTIAL_STAT_VALUES as _GENERATED_POTENTIAL_STAT_VALUES

CHARACTERS = {
    0: None,  # Special case for unequipped
    **_GENERATED_CHARACTERS,
}

# Build reverse lookup: name -> character data (for lookups by name)
CHARACTERS_BY_NAME = {
    char_data["name"]: char_data
    for char_data in CHARACTERS.values()
    if char_data is not None
}

# Potential stat values per level (levels 1-5) for nodes 50/60, from potential_node tables.
POTENTIAL_STAT_VALUES = dict(_GENERATED_POTENTIAL_STAT_VALUES)

ATTRIBUTE_COLORS = {
    "Passion": "#FF6B6B",   # Red
    "Void": "#9B59B6",      # Purple
    "Instinct": "#FF8C00",  # Orange
    "Order": "#2ECC71",     # Green
    "Justice": "#3498DB",   # Blue
}


def get_potential_stat_bonus(res_id: int, node: int, level: int) -> tuple[str, float]:
    """
    Get the stat type and bonus value for a potential node at a given level.

    Args:
        res_id: Character's res_id
        node: Node number (50 or 60)
        level: Node level (1-5)

    Returns:
        Tuple of (stat_type, bonus_value) or (None, 0) if not found
    """
    if level <= 0 or level > 5:
        return (None, 0.0)

    # Look up character data from CHARACTERS dictionary
    char_data = CHARACTERS.get(res_id)
    if not char_data:
        return (None, 0.0)

    # Get the stat type for this node from character definition
    node_key = f"node_{node}"
    stat_type = char_data.get(node_key)
    if not stat_type:
        return (None, 0.0)

    stat_values = POTENTIAL_STAT_VALUES.get(stat_type)
    if not stat_values:
        return (None, 0.0)

    # Level is 1-indexed, array is 0-indexed
    bonus_value = stat_values[level - 1]
    return (stat_type, bonus_value)


def parse_potential_node_ids(potential_str: str, res_id: int) -> dict[int, int]:
    """
    Parse potential_node_ids string and extract node levels.

    Args:
        potential_str: String like "[10431001,10432010,10435005]" or "[]"
        res_id: Character's res_id to validate node IDs

    Returns:
        Dict mapping node number to level, e.g., {10: 1, 20: 10, 50: 5}
    """
    result = {}

    if not potential_str or potential_str == "[]":
        return result

    # Parse the string - remove brackets and split by comma
    try:
        # Handle both string format "[...]" and already parsed list
        if isinstance(potential_str, str):
            cleaned = potential_str.strip("[]")
            if not cleaned:
                return result
            node_ids = [int(x.strip()) for x in cleaned.split(",") if x.strip()]
        else:
            node_ids = potential_str

        for node_id in node_ids:
            node_str = str(node_id)
            if len(node_str) != 8:
                continue

            # Parse: XXXX YY ZZ where XXXX=res_id, YY=node, ZZ=level
            parsed_res_id = int(node_str[:4])
            node_num = int(node_str[4:6])
            node_level = int(node_str[6:8])

            # Validate res_id matches
            if parsed_res_id == res_id:
                result[node_num] = node_level
    except (ValueError, TypeError):
        pass

    return result


def get_character(res_id: int) -> dict:
    """Get character data by res_id, returning DEFAULT_CHARACTER if not found."""
    char = CHARACTERS.get(res_id)
    if char is None:
        return DEFAULT_CHARACTER
    return char


def get_character_name(res_id: int) -> str:
    """Get character name by res_id, returning None if not found or if res_id is 0."""
    char = CHARACTERS.get(res_id)
    if char is None:
        return None
    return char.get("name")


def get_character_by_name(name: str) -> dict:
    """Get character data by name, returning DEFAULT_CHARACTER if not found."""
    return CHARACTERS_BY_NAME.get(name, DEFAULT_CHARACTER)
