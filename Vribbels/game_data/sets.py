"""
Memory Fragment set definitions for CZN.
Contains set bonus information and derived lists.
"""

# Set definitions - generated from piece_set_option by tools/build_game_data.py (see _gen_sets.py).
# Keyed by the set number embedded in fragment res_ids; "order" is the client's display order.
from ._gen_sets import SETS as _GENERATED_SETS

SETS = dict(sorted(_GENERATED_SETS.items()))

TWO_PIECE_SETS = [sid for sid, s in SETS.items() if s["pieces"] == 2]
FOUR_PIECE_SETS = [sid for sid, s in SETS.items() if s["pieces"] == 4]
