#!/usr/bin/env python3
"""MHRice の mhrice.json をダウンロードし、カテゴリ別の gzip JSON に分割する。

使い方:
    python3 librechat/mhrise/etl/build_data.py

出力:
    librechat/mhrise/data/{weapons,monsters,armor_skills,items,quests,otomo,misc}.json.gz

依存は標準ライブラリのみ。MHRice は 2024-02 ビルドで更新停止（ゲーム最終版）のため、
再実行は原則不要。詳細は docs/spec/mhrise-mcp.md を参照。
"""

import gzip
import json
import sys
import urllib.request
from pathlib import Path

MHRICE_URL = "https://mhrise.mhrice.info/mhrice.json"
CACHE_PATH = Path("/tmp/mhrice.json")
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data"

WEAPONS = {
    "great_sword", "short_sword", "hammer", "lance", "long_sword", "slash_axe",
    "gun_lance", "dual_blades", "horn", "insect_glaive", "charge_axe",
    "light_bowgun", "heavy_bowgun", "bow",
    "horn_melody", "horn_melody_mr", "hyakuryu_weapon_buildup",
    "weapon_chaos_critical", "weapon_series", "weapon_series_mr",
}
MONSTERS_PREFIX = (
    "monster", "small_monsters", "condition_preset", "parts_type", "hunter_note",
    "species", "enemy_rank", "random_scale", "size_list", "discover_em_set_data",
)
ARMOR_SKILLS_PREFIX = (
    "armor", "overwear", "equip_skill", "player_skill", "hyakuryu_skill",
    "decorations", "hyakuryu_decos", "alchemy_pl_skill",
)
ITEMS_PREFIX = ("items", "material_category", "item_", "insect")
QUESTS_PREFIX = (
    "quest", "normal_quest", "dl_quest", "arena_quest", "difficulty", "reward",
    "mystery_reward", "main_target", "fixed_hyakuryu", "supply_data",
    "time_attack", "talk_condition", "npc_mission", "progress",
)
OTOMO_PREFIX = ("airou", "dog_", "ot_")


def categorize(key: str) -> str:
    if key in WEAPONS:
        return "weapons"
    if key.startswith(OTOMO_PREFIX):
        return "otomo"
    if key.startswith(MONSTERS_PREFIX):
        return "monsters"
    if key.startswith(ARMOR_SKILLS_PREFIX):
        return "armor_skills"
    if key.startswith(ITEMS_PREFIX):
        return "items"
    if key.startswith(QUESTS_PREFIX):
        return "quests"
    return "misc"


def fetch_mhrice() -> dict:
    if not CACHE_PATH.exists():
        print(f"downloading {MHRICE_URL} -> {CACHE_PATH} ...", flush=True)
        urllib.request.urlretrieve(MHRICE_URL, CACHE_PATH)
    else:
        print(f"using cache: {CACHE_PATH}")
    with open(CACHE_PATH) as f:
        return json.load(f)


def main() -> int:
    data = fetch_mhrice()
    print(f"loaded: {len(data)} top-level keys")

    groups: dict[str, dict] = {}
    for key, value in data.items():
        groups.setdefault(categorize(key), {})[key] = value

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    total = 0
    for name, group in sorted(groups.items()):
        out = OUTPUT_DIR / f"{name}.json.gz"
        payload = json.dumps(group, ensure_ascii=False, separators=(",", ":")).encode()
        with gzip.open(out, "wb", compresslevel=9) as f:
            f.write(payload)
        total += out.stat().st_size
        print(f"  {out.name:22s} keys={len(group):3d}  {out.stat().st_size / 1e6:5.1f} MB")
    print(f"total: {total / 1e6:.1f} MB -> {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
