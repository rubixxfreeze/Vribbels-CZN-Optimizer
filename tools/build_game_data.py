#!/usr/bin/env python3
"""Regenerate the optimizer's game data from a Chaos Zero Nightmare client table dump.

Usage:
    python3 tools/build_game_data.py --dump /path/to/czn-data/build-133
    python3 tools/build_game_data.py --dump ... --oracle /path/to/old/game_data   # diff against old hand data
    python3 tools/build_game_data.py --dump ... --check                           # don't write, just report

The dump layout is `db/<dbset>@<table>.json` (lists of row dicts, every value a string) plus
`text/en/text.json` (a list of {"id", "text"} rows). Stdlib only.

Writes (data only - the hand-written helpers stay in the non-underscore modules, which import these):
    Vribbels/game_data/_gen_characters.py   CHARACTERS, POTENTIAL_STAT_VALUES, CHARACTER_MAX_LEVEL
    Vribbels/game_data/_gen_partners.py     PARTNERS
    Vribbels/game_data/_gen_sets.py         SETS
    Vribbels/game_data/_gen_constants.py    CHARACTER_EXP_TABLE, PARTNER_EXP_TABLE, SUBSTAT_ROLLS,
                                            SLOT_MAIN_STATS_KEYS, MAIN_STAT_VALUES

Table conventions (verified against the hand-entered v1.7.0 data, see CHANGELOG 1.8.0):
  * Playable combatant  = char_base@char_base row with char_type CHAR_COMBATANT, char_use_playable YES,
    an English name, and a char_base@char_combatant row. (Test/NPC/enemy-only variants are NO.)
  * Level-60 stat       = char_combatant.s_<stat> (level-1 value) + sum(combatant_level group rows, level 2..60)
    + sum(combatant_ascend group rows, ascend 1..5).
  * Potential node 50/60 = potential_node rows with node_num 5_0 / 6_0 (type N_ADD_<stat>).
  * Partner             = partner_base@char_partner row whose partner_base@char_base row is playable.
    Passive values come from the 5 levels of passive class 1 and class 2 text (<cc>N</> numbers that change
    with level); unconditional stats come from the class-1 EFF_STAT_UP_PARTNER nb effects (stat_up_eff) and
    unconditional DMG_ATTR_ADDITIONAL_ATTACK damage-amount passives (Extra DMG%).
    Level-60 base stats = default_*_add + sum(partner_level group, 1..60) + sum(partner_ascend group).
  * Memory fragment set = piece_set_option rows set_public_* with order > 0 (the ones the client lists);
    the numeric set id is the one embedded in the piece item ids (item_piece res_id[4:]).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from pprint import pformat

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "Vribbels" / "game_data"

GRADES = {"RARITY_R": 3, "RARITY_SR": 4, "RARITY_SSR": 5}
ATTRIBUTES = {"RED": "Passion", "PURPLE": "Void", "ORANGE": "Instinct", "GREEN": "Order", "BLUE": "Justice"}
CLASSES = {c: c.capitalize() for c in ("controller", "hunter", "psionic", "ranger", "striker", "vanguard")}

# Stat-list ids -> the short names the app uses (game_data.constants.STATS second column / node names)
NODE_STATS = {
    "S_HP_INC_RATE_OUT": "HP%", "S_ATK_INC_RATE_OUT": "ATK%", "S_DEF_INC_RATE_OUT": "DEF%",
    "S_CRI_INC_ADD": "CRate", "S_CRI_DMG_RATE_INC_ADD": "CDmg",
}
PARTNER_STATS = {"S_ATK_INC_RATE_IN": "ATK%", "S_DEF_INC_RATE_IN": "DEF%", "S_HP_INC_RATE_IN": "HP%"}
SET_STATS = {
    "S_ATK_INC_RATE_OUT": "ATK%", "S_DEF_INC_RATE_OUT": "DEF%", "S_HP_INC_RATE_OUT": "HP%",
    "S_CRI_DMG_RATE_INC_ADD": "Crit DMG", "S_CRI_INC_ADD": "Crit Rate",
}
CC = re.compile(r"<cc>([-\d.]+)</>")


# ---------------------------------------------------------------- loading
class Dump:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.db = self.root / "db"
        self._cache = {}
        self.text = {}
        for row in json.loads((self.root / "text" / "en" / "text.json").read_text(encoding="utf-8")):
            self.text.setdefault(row["id"], row["text"])

    def table(self, name):
        if name not in self._cache:
            self._cache[name] = json.loads((self.db / name).read_text(encoding="utf-8"))
        return self._cache[name]

    def glob(self, pattern):
        rows = []
        for path in sorted(self.db.glob(pattern)):
            rows += self.table(path.name)
        return rows

    def index(self, pattern, key="id"):
        out = {}
        for row in self.glob(pattern):
            out.setdefault(row[key], row)
        return out

    def t(self, key, default=None):
        return self.text.get(key, default)


def id_list(value):
    return [v for v in re.findall(r"[^\[\],\s]+", value or "")]


def num(value):
    f = float(value)
    return int(f) if f == int(f) else round(f, 4)


def norm_name(s):
    return (s or "").replace("\u2019", "'").replace("\u2018", "'").strip()


def clean_text(text, dump=None):
    """Turn client markup into plain text (same rules as czn-pilot's build_game_data.clean_description)."""
    if dump is not None:
        text = re.sub(r"\^card@([^^]+)\^", lambda m: dump.t("card@name@" + m.group(1), "that card"), text)
    text = re.sub(r"\^[^^]+\^", "", text)
    text = text.replace("<br>", "\n")
    text = re.sub(r"\$([^$#]+)(?:#\d+)?\$", r"\1", text)
    text = re.sub(r"\[/?[a-z_]{0,15}\]", "", text)
    text = re.sub(r"</?[a-z_]{0,40}>", "", text)
    text = text.replace("\u2019", "'")
    text = re.sub(r"[ \t]+", " ", text)
    return "\n".join(line.strip() for line in text.split("\n") if line.strip())


# ---------------------------------------------------------------- characters
def build_characters(d: Dump):
    bases = d.index("char_base@char_base.json")
    combatants = d.index("char_base@char_combatant.json")
    level_rows = d.table("char_base@combatant_level.json")
    ascend_rows = d.table("char_base@combatant_ascend.json")

    def group_sum(rows, group, key, lo, hi):
        total = [0, 0, 0]
        for r in rows:
            if r["group"] == group and lo <= int(r[key]) <= hi:
                for i in range(3):
                    total[i] += int(float(r[f"stat{i + 1}_value"]))
        return total

    # potential nodes 50 / 60
    nodes = defaultdict(dict)
    node_values = defaultdict(dict)
    effects = d.index("potential_node@potential_node_effect.json")
    for r in d.table("potential_node@potential_node.json"):
        if r["node_num"] not in ("5_0", "6_0"):
            continue
        kind = r["link_potential_node_type_define_id"]
        if not kind.startswith("N_ADD_"):
            continue
        stat = NODE_STATS.get(kind[len("N_ADD_"):])
        nodes[r["link_char_combatant_id"]][r["node_num"]] = stat
        # standard per-level rows have 8-digit ids <res_id(4)><node(2)><level(2)>
        if len(r["id"]) == 8 and stat:
            eff = effects[id_list(r["link_potential_node_effect_id"])[0]]
            node_values[stat][int(r["node_level"])] = num(eff["value"])

    potential_values = {s: tuple(v[i] for i in range(1, 6)) for s, v in sorted(node_values.items())}

    max_level = max(int(r["level"]) for r in level_rows)
    chars = {}
    for cid, c in combatants.items():
        b = bases.get(cid)
        name = d.t(f"char_base@name@{cid}")
        if not b or not name or b.get("char_type") != "CHAR_COMBATANT" or b.get("char_use_playable") != "YES":
            continue
        if "test" in name.lower():
            continue
        lv = group_sum(level_rows, c["link_combatant_level_group"], "level", 2, 60)
        asc = group_sum(ascend_rows, c["link_combatant_ascend_group"], "ascend", 1, 99)
        n = nodes.get(cid, {})
        chars[int(cid)] = {
            "name": norm_name(name),
            "grade": GRADES[b["rarity"]],
            "attribute": ATTRIBUTES[c["link_ego_type_id"]],
            "class": CLASSES[c["link_base_class_define_id"]],
            "base_atk": int(c["s_atk"]) + lv[0] + asc[0],
            "base_def": int(c["s_def"]) + lv[1] + asc[1],
            "base_hp": int(c["s_hp"]) + lv[2] + asc[2],
            "base_crit_rate": float(c["s_cri"]),
            "base_crit_dmg": float(c["s_cri_dmg_rate"]),
            "node_50": n.get("5_0"),
            "node_60": n.get("6_0"),
        }
    return dict(sorted(chars.items())), potential_values, max_level


# ---------------------------------------------------------------- partners
PERCENT_EFFECTS = {"SKILL_EFF_DMG", "SKILL_EFF_SHIELD", "SKILL_EFF_CURE", "SKILL_EFF_DAMAGE_VALUE_ADD"}


def resolve_card(d: Dump, text, card, effects, all_cs, all_effects):
    links = id_list(card.get("link_skill_eff_id"))
    # drop client-side formula blocks such as "({cal}m(...){/})"
    text = re.sub(r"\(?\{cal\}.*?\{/\}\)?", "", text)

    def repl_cs(m):
        # #cs_ev_A_B#: linked effect A -> its status (cs) -> that status' effect B -> value
        kind, a, b = m.group(1), int(m.group(2)), int(m.group(3))
        eff = effects.get(links[a]) if a < len(links) else None
        cs_ids = id_list(eff.get("link_cs_id")) if eff else []
        cs_row = all_cs.get(cs_ids[0]) if cs_ids else None
        sub = id_list(cs_row.get("link_skill_eff_id")) if cs_row else []
        target = all_effects.get(sub[b]) if b < len(sub) else None
        if not target:
            return m.group(0)
        return str(num(target["eff_count_value" if kind == "ecv" else "eff_value"]))

    text = re.sub(r"#cs_(ev|ecv)_(\d+)_(\d+)#", repl_cs, text)

    def repl(m):
        family, idx = m.group(1), int(m.group(2))
        eff = effects.get(links[idx]) if idx < len(links) else None
        if not eff or family.startswith("cs_"):
            return m.group(0)
        parts = set(family.split("_"))
        if "ecv" in parts:
            return num(eff["eff_count_value"]).__str__()
        if "ev" in parts or "damage" in parts:
            v = str(num(eff["eff_value"]))
            rest = re.sub(r"^(\[/?[a-z_]*\]|</?[a-z]{0,3}>)+", "", text[m.end():])
            if eff.get("eff") in PERCENT_EFFECTS and not rest.startswith("%"):
                v += "%"
            return v
        return m.group(0)

    text = re.sub(r"#([a-z][a-z0-9_]*)_(\d+)#", repl, text)
    text = re.sub(r"\s*#[a-z_]*comb[a-z_]*#", " the assigned Combatant", text)
    text = clean_text(text, d).replace("\u2018", "'")
    text = re.sub(r"\(#[a-zA-Z0-9_]+#\)", "", text)       # "for each(#n#)" counters shown in-battle only
    return re.sub(r"#[a-zA-Z0-9_]+#", "X", text)         # value only known at runtime


def build_partners(d: Dump):
    bases = d.index("partner_base@char_base.json")
    partners = d.table("partner_base@char_partner.json")
    passive_groups = defaultdict(list)
    for r in d.glob("partner_passive*@partner_passive.json"):
        passive_groups[r["group"]].append(r)
    nb = d.index("*@nb_eff.json")
    stat_up = d.index("stat_up_eff@stat_up_eff.json")
    cs = d.index("*partner*@cs.json")
    skill = d.index("*partner*@skill_eff.json")
    cards = d.index("card(partner)@card.json")
    card_effects = d.index("card(partner)@skill_eff.json")
    all_cs = d.index("*@cs.json")
    all_effects = d.index("*@skill_eff.json")
    level_rows = d.table("partner_base@partner_level.json")
    ascend_rows = d.table("partner_base@partner_ascend.json")

    def group_sum(rows, group, key):
        total = [0, 0, 0]
        for r in rows:
            if r["group"] == group and int(r[key]) <= 60:
                for i in range(3):
                    total[i] += int(float(r[f"stat{i + 1}_value"]))
        return total

    out, problems = {}, []
    for p in partners:
        pid = p["id"]
        b = bases.get(pid)
        name = d.t(f"char_base@name@{pid}")
        if not b or not name or b.get("char_use_playable") != "YES":
            continue
        rows = passive_groups.get(p["link_partner_passive_group"], [])
        classes = {}
        for cls in ("1", "2"):
            lv = sorted((r for r in rows if r["class"] == cls), key=lambda r: int(r["level"]))
            if lv:
                classes[cls] = lv
        passive_name = norm_name(d.t(rows[0]["name"])) if rows else "Unknown"

        # description template + varying values
        values, desc_parts, key_no = {}, [], 0
        stats = {}
        # unconditional stat-ups (class 1 and 2)
        for cls, lv in classes.items():
            per_stat = defaultdict(list)
            for r in lv:
                for nid in id_list(r["link_nb_eff_id"]):
                    n = nb.get(nid)
                    if not n or n["nb_eff"] != "EFF_STAT_UP_PARTNER":
                        continue
                    s = stat_up.get(n["opt_multiple_link"])
                    for sid in id_list(s["link_stat_list_id"]) if s else []:
                        if sid in PARTNER_STATS and s["target_job"] == "NONE" and s["target_formation"] == "NONE":
                            per_stat[PARTNER_STATS[sid]].append(num(s["stat_min"]))
                # unconditional Extra-Attack damage amount
                for cid in id_list(r["link_cs_id"]):
                    for eid in id_list(cs.get(cid, {}).get("link_skill_eff_id")):
                        e = skill.get(eid)
                        if (e and e["eff"] == "SKILL_EFF_DAMAGE_VALUE_ADD" and e["operation"] == "OPERATION_PASSIVE"
                                and e.get("eff_attr") == "[DMG_ATTR_ADDITIONAL_ATTACK]"
                                and e.get("eff_link_condition_id", "none") in ("none", "")
                                and e.get("target_unit_type") == "TARGET_UNIT_OWNER"):
                            per_stat["Extra DMG%"].append(num(e["eff_value"]))
            for stat, vals in per_stat.items():
                if len(vals) == 5:
                    stats[stat] = tuple(vals)

        stat_by_values = {v: k for k, v in stats.items()}
        for cls, lv in classes.items():
            texts = [d.t(r["description"], "") for r in lv]
            toks = [CC.findall(t) for t in texts]
            if len(lv) != 5 or len({len(t) for t in toks}) != 1:
                problems.append(f"partner {pid} {name}: passive class {cls} has irregular levels")
                desc_parts.append(clean_text(texts[-1] if texts else "", d))
                continue
            columns = [tuple(num(t[i]) for t in toks) for i in range(len(toks[0]))]
            pieces = re.split(r"(<cc>[-\d.]+</>)", texts[0])
            ti = 0
            for i, piece in enumerate(pieces):
                if CC.fullmatch(piece):
                    col = columns[ti]
                    ti += 1
                    if len(set(col)) > 1:
                        key = stat_by_values.get(col)
                        if key is None or key in values:
                            key_no += 1
                            key = f"V{key_no}"
                        values[key] = col
                        pieces[i] = "{" + key + "}"
                    else:
                        pieces[i] = str(col[0])
            # #n# stack markers in $Term#n$ differ per level only cosmetically
            desc_parts.append(clean_text("".join(pieces), d))
        card = cards.get(p["link_card_id"], {})
        ego_desc = resolve_card(d, d.t(card.get("desc", ""), ""), card, card_effects, all_cs, all_effects) if card else ""
        lvl = group_sum(level_rows, p["link_partner_level_group"], "level")
        asc = group_sum(ascend_rows, p["link_partner_ascend_group"], "ascend")
        out[int(pid)] = {
            "name": norm_name(name),
            "grade": GRADES[b["rarity"]],
            "class": CLASSES.get(p["passive_condition_link_base_class_define_id"], "Unknown"),
            "passive_name": passive_name,
            "passive_desc": "\n".join(desc_parts),
            "values": values,
            "stats": stats,
            "ego_name": norm_name(d.t(card.get("name", ""), "Unknown")),
            "ego_cost": int(card.get("cost", 0) or 0),
            "ego_desc": ego_desc,
            "base_stats": {
                "atk": int(p["default_atk_add"]) + lvl[0] + asc[0],
                "def": int(p["default_def_add"]) + lvl[1] + asc[1],
                "hp": int(p["default_hp_add"]) + lvl[2] + asc[2],
            },
        }
    return dict(sorted(out.items())), problems


# ---------------------------------------------------------------- sets
def build_sets(d: Dump):
    set_ids = {}
    for r in d.table("item_piece@item_piece.json"):
        set_ids.setdefault(r["link_piece_set_option_id"], int(r["id"][4:]))
    sets = {}
    for r in d.table("piece_set_option@piece_set_option.json"):
        if not r["id"].startswith("set_public_") or int(r["order"]) <= 0:
            continue
        pieces = int(r["set_option_type"])
        sid = set_ids.get(r["id"], int(r["id"].rsplit("_", 1)[1]))
        bonus = clean_text(d.t(r[f"set{pieces}_description"], ""), d).replace("\n", " / ")
        entry = {"name": norm_name(d.t(r["name"])), "pieces": pieces, "bonus": bonus, "type": "conditional"}
        if r[f"set{pieces}_type"] == "SET_TYPE_STAT" and r[f"set{pieces}_option_multiple_link"] in SET_STATS:
            entry.update(type="stat", stat=SET_STATS[r[f"set{pieces}_option_multiple_link"]],
                         value=num(r[f"set{pieces}_value"]))
        entry["order"] = int(r["order"])
        sets[sid] = entry
    return dict(sorted(sets.items()))


# ---------------------------------------------------------------- constants
def build_constants(d: Dump):
    rows = sorted(d.table("char_growth@char_exp.json"), key=lambda r: int(r["level"]))

    def cumulative(col):
        table, total = [(0, 1)], 0
        for r in rows:
            v = int(r[col])
            if v < 0:
                break
            total += v
            table.append((total, int(r["level"]) + 1))
        return table

    char_exp = cumulative("combatant_rarity_ssr_require_exp")
    partner_exp = cumulative("supporter_rarity_ssr_require_exp")
    for col in ("combatant_rarity_sr_require_exp",):
        assert cumulative(col) == char_exp, col
    for col in ("supporter_rarity_sr_require_exp", "supporter_rarity_r_require_exp"):
        assert cumulative(col) == partner_exp, col

    opts = d.table("piece_option@piece_option.json")
    rolls, mains, main_values = {}, {}, {}
    for r in opts:
        if r["group"] == "random_option":
            vals = [num(v) for v in id_list(r["legend_value"])]
            rolls[r["link_stat_list_id"]] = (max(vals), min(vals))
        elif r["group"].startswith("main_piece_"):
            slot = int(r["group"].rsplit("_", 1)[1])
            mains.setdefault(slot, []).append(r["link_stat_list_id"])
            main_values[r["link_stat_list_id"], slot] = (num(id_list(r["legend_value"])[0]),
                                                         num(id_list(r["legend_reinforce_value"])[0]))
    return {
        "CHARACTER_EXP_TABLE": char_exp,
        "PARTNER_EXP_TABLE": partner_exp,
        "SUBSTAT_ROLLS": dict(sorted(rolls.items())),
        "SLOT_MAIN_STATS_KEYS": dict(sorted(mains.items())),
        "MAIN_STAT_VALUES": {f"{k[0]}@{k[1]}": v for k, v in sorted(main_values.items(), key=lambda x: (x[0][1], x[0][0]))},
    }


# ---------------------------------------------------------------- writing
HEADER = '''"""
AUTO-GENERATED by tools/build_game_data.py - do not edit by hand.
Source: {source} (generated {today}).
Re-run: python3 tools/build_game_data.py --dump <czn-data build dir>
"""
'''


def write_module(path, source, assignments, extra=""):
    body = HEADER.format(source=source, today=date.today().isoformat())
    for name, value in assignments:
        body += f"\n{name} = {pformat(value, width=110, sort_dicts=False)}\n"
    path.write_text(body + extra, encoding="utf-8")


# ---------------------------------------------------------------- oracle
def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def oracle(old_dir, chars, partners, sets, potential, consts):
    old_dir = Path(old_dir)
    sys.path.insert(0, str(old_dir.parent))
    pkg = old_dir.name
    oc = __import__(f"{pkg}.characters", fromlist=["x"])
    op = __import__(f"{pkg}.partners", fromlist=["x"])
    osets = __import__(f"{pkg}.sets", fromlist=["x"])
    ocon = __import__(f"{pkg}.constants", fromlist=["x"])
    report, matched, total = [], 0, 0

    for rid, old in oc.CHARACTERS.items():
        if not old:
            continue
        total += 1
        new = chars.get(rid)
        if not new:
            report.append(f"CHAR {rid} {old['name']}: not playable/absent in client tables")
            continue
        diffs = [f"{k}: {old.get(k)!r} -> {new.get(k)!r}" for k in old if float_ne(old.get(k), new.get(k))]
        if diffs:
            report.append(f"CHAR {rid} {old['name']}: " + "; ".join(diffs))
        else:
            matched += 1
    for stat, vals in oc.POTENTIAL_STAT_VALUES.items():
        if tuple(map(float, vals)) != tuple(map(float, potential.get(stat, ()))):
            report.append(f"POTENTIAL_STAT_VALUES {stat}: {vals} -> {potential.get(stat)}")

    for rid, old in op.PARTNERS.items():
        total += 1
        new = partners.get(rid)
        if not new:
            report.append(f"PARTNER {rid} {old['name']}: absent from client tables (kept old entry)")
            continue
        diffs = []
        for k in ("name", "grade", "class", "passive_name", "ego_name", "ego_cost"):
            if float_ne(old.get(k), new.get(k)) and str(old.get(k)).lower() != str(new.get(k)).lower():
                diffs.append(f"{k}: {old.get(k)!r} -> {new.get(k)!r}")
        oldv = sorted(tuple(map(float, v)) for v in old["values"].values())
        newv = sorted(tuple(map(float, v)) for v in new["values"].values())
        if oldv != newv:
            diffs.append(f"values: {sorted(old['values'].items())} -> {sorted(new['values'].items())}")
        olds = {("Extra DMG%" if k == "ExtraDMG%" else k): tuple(map(float, v)) for k, v in old["stats"].items()}
        news = {k: tuple(map(float, v)) for k, v in new["stats"].items()}
        if olds != news:
            diffs.append(f"stats: {old['stats']} -> {new['stats']}")
        cls_stats = op.PARTNER_CLASS_STATS.get((old["grade"], old["class"]))
        if cls_stats and cls_stats != new["base_stats"]:
            diffs.append(f"lv60 stats (PARTNER_CLASS_STATS): {cls_stats} -> {new['base_stats']}")
        oe = re.findall(r"\d+(?:\.\d+)?", old.get("ego_desc", ""))
        ne = re.findall(r"\d+(?:\.\d+)?", new.get("ego_desc", ""))
        if sorted(oe) != sorted(ne):
            diffs.append(f"ego_desc numbers: {old.get('ego_desc')!r} -> {new.get('ego_desc')!r}")
        if diffs:
            report.append(f"PARTNER {rid} {old['name']}: " + " | ".join(diffs))
        else:
            matched += 1

    for sid, old in osets.SETS.items():
        total += 1
        new = sets.get(sid)
        if not new:
            report.append(f"SET {sid} {old['name']}: absent")
            continue
        diffs = [f"{k}: {old.get(k)!r} -> {new.get(k)!r}" for k in ("name", "pieces", "type", "stat", "value")
                 if float_ne(old.get(k), new.get(k))]
        if diffs:
            report.append(f"SET {sid} {old['name']}: " + "; ".join(diffs))
        else:
            matched += 1

    for name in ("CHARACTER_EXP_TABLE", "PARTNER_EXP_TABLE"):
        new = dict((lvl, e) for e, lvl in consts[name])
        bad = [(lvl, e, new.get(lvl)) for e, lvl in getattr(ocon, name) if new.get(lvl) != e]
        if bad:
            report.append(f"{name}: anchor points differing (level, old, new): {bad}")
    for key, info in ocon.STATS.items():
        r = consts["SUBSTAT_ROLLS"].get(key)
        if r and (float(info[3]), float(info[4])) != (float(r[0]), float(r[1])):
            report.append(f"STATS {key} roll range: {info[3:]} -> {r}")
    return matched, total, report


def float_ne(a, b):
    try:
        return float(a) != float(b)
    except (TypeError, ValueError):
        return a != b


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dump", required=True, help="czn-data build dir (contains db/ and text/)")
    ap.add_argument("--oracle", help="old game_data package dir to validate against")
    ap.add_argument("--check", action="store_true", help="do not write files")
    args = ap.parse_args()

    d = Dump(Path(args.dump))
    source = Path(args.dump).name
    chars, potential, max_level = build_characters(d)
    partners, problems = build_partners(d)
    sets = build_sets(d)
    consts = build_constants(d)

    print(f"characters={len(chars)} partners={len(partners)} sets={len(sets)} "
          f"substats={len(consts['SUBSTAT_ROLLS'])} char_max_level={max_level}")
    for p in problems:
        print("WARN", p)

    if args.oracle:
        matched, total, report = oracle(args.oracle, chars, partners, sets, potential, consts)
        print(f"ORACLE: {matched}/{total} old entries reproduced exactly; {len(report)} findings")
        for line in report:
            print("  -", line)

    if args.check:
        return
    write_module(OUT_DIR / "_gen_characters.py", source, [
        ("CHARACTER_MAX_LEVEL", max_level),
        ("POTENTIAL_STAT_VALUES", potential),
        ("CHARACTERS", chars),
    ])
    write_module(OUT_DIR / "_gen_partners.py", source, [("PARTNERS", partners)])
    write_module(OUT_DIR / "_gen_sets.py", source, [("SETS", sets)])
    write_module(OUT_DIR / "_gen_constants.py", source, [(k, v) for k, v in consts.items()])
    print("wrote", ", ".join(p.name for p in sorted(OUT_DIR.glob("_gen_*.py"))))


if __name__ == "__main__":
    main()
