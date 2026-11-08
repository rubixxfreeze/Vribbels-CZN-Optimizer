"""Smoke tests for the generated game data and the optimizer core (no Tk needed).

Run: python3 -m unittest discover -s tests -v   (from the repo root)
"""
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "Vribbels"))

import game_data as gd  # noqa: E402
from optimizer.optimizer import GearOptimizer  # noqa: E402


class GameDataTests(unittest.TestCase):
    def test_counts_and_schema(self):
        chars = {k: v for k, v in gd.CHARACTERS.items() if v}
        self.assertGreaterEqual(len(chars), 39)
        self.assertGreaterEqual(len(gd.PARTNERS), 50)
        self.assertGreaterEqual(len(gd.SETS), 22)
        for rid, c in chars.items():
            for key in gd.DEFAULT_CHARACTER:
                self.assertIn(key, c, (rid, key))
            self.assertIn(c["attribute"], gd.ATTRIBUTE_COLORS)
            self.assertIn(c["node_50"], gd.POTENTIAL_STAT_VALUES)
            self.assertIn(c["node_60"], gd.POTENTIAL_STAT_VALUES)
        for rid, p in gd.PARTNERS.items():
            for key in gd.DEFAULT_PARTNER:
                self.assertIn(key, p, (rid, key))
            for stat, values in p["stats"].items():
                self.assertEqual(len(values), 5, (rid, stat))
        for sid, s in gd.SETS.items():
            self.assertIn(s["pieces"], (2, 4))
            if s["type"] == "stat":
                self.assertIn(s["stat"], ("ATK%", "DEF%", "HP%", "Crit DMG", "Crit Rate"))

    def test_partner_and_character_ids_do_not_overlap(self):
        # the optimizer tells partners from combatants by PARTNERS membership
        self.assertFalse(set(gd.PARTNERS) & {k for k, v in gd.CHARACTERS.items() if v})

    def test_known_values(self):
        nia = gd.get_character(1003)
        self.assertEqual((nia["base_atk"], nia["base_def"], nia["base_hp"]), (392, 186, 313))
        self.assertEqual(gd.get_character(1004)["base_atk"], 491)
        self.assertEqual(gd.SETS[9]["stat"], "ATK%")
        self.assertEqual(gd.SETS[9]["value"], 12)
        self.assertEqual(gd.get_level_from_exp(720000), 60)
        self.assertEqual(gd.get_partner_level_from_exp(36300), 30)
        self.assertEqual(gd.get_partner(20039)["name"], "Tina")  # legacy id alias

    def test_every_main_stat_is_a_known_stat(self):
        names = {s[0] for s in gd.STATS.values()}
        for slot, mains in gd.SLOT_MAIN_STATS.items():
            self.assertTrue(mains, slot)
            self.assertTrue(set(mains) <= names, slot)


def _fragment(fid, slot, set_id, main_key, subs, char_res_id=0):
    stat_list = [{"stat": main_key, "slot": 0, "type": 0, "value": 10}]
    for i, (key, value) in enumerate(subs, start=1):
        stat_list.append({"stat": key, "slot": i, "type": 1, "value": value})
    return {"id": fid, "res_id": int(f"11{slot}4{set_id:03d}"), "level": 5, "lock": False,
            "char_res_id": char_res_id, "stat_list": stat_list}


class OptimizerSmokeTest(unittest.TestCase):
    def test_optimize_with_new_set_and_character(self):
        rng = random.Random(7)
        mains = {1: ["S_ATK_INC_ADD_OUT"], 2: ["S_DEF_INC_ADD_OUT"], 3: ["S_HP_INC_ADD_OUT"],
                 4: ["S_CRI_DMG_RATE_INC_ADD", "S_ATK_INC_RATE_OUT"],
                 5: ["S_BLUE_DMG_RATE_INC_ADD", "S_ATK_INC_RATE_OUT"],
                 6: ["S_ATK_INC_RATE_OUT", "S_CHARGING_POWER_INC_ADD"]}
        subs = ["S_ATK_INC_RATE_OUT", "S_CRI_INC_ADD", "S_CRI_DMG_RATE_INC_ADD", "S_ADDI_ATK_DMG_RATE_INC_ADD"]
        pieces, fid = [], 1
        for slot in range(1, 7):
            for set_id in (31, 9, 11, 6):  # 31 = Snowflake of Our First Meeting (new)
                for main in mains[slot]:
                    pieces.append(_fragment(fid, slot, set_id, main,
                                            [(k, round(rng.uniform(1, 3), 1)) for k in subs]))
                    fid += 1
        capture = {
            "piece_items": pieces,
            "characters": {"characters": [
                {"id": 1, "res_id": 30134, "exp": 720000, "ascend": 5, "limit_break": 0,
                 "partner_id": 2, "friendship_reward_index": 5},  # Rossweisse (new)
                {"id": 2, "res_id": 30135, "exp": 346000, "ascend": 5, "limit_break": 4},  # Sig (new)
            ]},
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(capture, fh)
        opt = GearOptimizer()
        opt.load_data(fh.name)
        self.assertEqual(len(opt.fragments), len(pieces))
        self.assertTrue(all(not f.set_name.startswith("Unknown") for f in opt.fragments))
        info = opt.character_info["Rossweisse"]
        self.assertEqual(info.partner_name, "Sig")
        self.assertEqual(info.level, 60)
        results = opt.optimize("Rossweisse", {"four_piece_sets": [31], "two_piece_sets": [],
                                              "main_stat_4": ["CDmg"], "max_results": 5})
        self.assertTrue(results)
        gear, score, stats = results[0]
        self.assertGreaterEqual(sum(1 for g in gear if g.set_id == 31), 4)
        # base 467 ATK, +24% partner passive ATK at E4, +155 partner ATK, + gear
        self.assertGreaterEqual(stats["ATK%"], 24)
        self.assertGreater(stats["ATK"], 467 * 1.24 + 155)


if __name__ == "__main__":
    unittest.main()
