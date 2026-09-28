#!/usr/bin/env python3
"""モンスターハンターライズのゲームデータを DuckDB で検索する MCP サーバー。

起動時に /data/*.json.gz（etl/build_data.py の生成物）を DuckDB (in-memory) に
ロードし、streamable-http で MCP ツールを公開する。

詳細は docs/spec/mhrise-mcp.md を参照。
"""

import gzip
import json
import os
import re
import tempfile

import duckdb
from fastmcp import FastMCP

DATA_DIR = os.environ.get("DATA_DIR", "/data")
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))
MAX_ROWS = int(os.environ.get("MAX_ROWS", "200"))
MAX_CHARS = int(os.environ.get("MAX_CHARS", "50000"))

INSTRUCTIONS = """\
モンスターハンターライズ（サンブレイク含む）のゲームデータを DuckDB SQL で検索できる。

使い方:
1. 武器を調べるときは、まず v_<武器種> ビュー（例: v_horn）を使うこと。
   武器名（name_ja / name_en）との結合済みで、atk（攻撃力）, affinity（会心率）,
   def_bonus, slots（スロット）, element_type / element_val（属性）, rare（レア度）,
   sort_id, weapon_id, hyakuryu_skill_ids などが平坦化されている。
   - is_test = true はテスト用データ。ユーザーへの回答からは除外すること
   - is_mr = true はサンブレイク（MR）追加分
   武器種: great_sword, long_sword, short_sword, dual_blades, hammer, horn, lance,
   gun_lance, slash_axe, charge_axe, insect_glaive, bow, light_bowgun, heavy_bowgun
2. 狩猟笛の旋律は v_horn.melodies_ja（日本語名の配列）に入っている。
   旋律マスタは v_horn_melody（id, name_ja, name_en）。
   例: SELECT name_ja, melodies_ja FROM v_horn
       WHERE list_contains(melodies_ja, 'スタミナ消費軽減')
3. 百竜スキルは v_hyakuryu_skill（id, name_ja, name_en 結合済み）を使う。
4. 上記で足りない場合のみ生テーブルを調べる。list_tables / describe_table で
   構造を確認してから query で SQL を実行する
   （テーブルはネストした struct を含むため、構造確認してから書くこと）

データ構造上の注意（生テーブルを直接調べる場合）:
- 武器テーブルは <武器種>__base_data に入っている。
  攻撃力などはネストした struct 内にあり、フィールドアクセスはドットではなく
  ブラケット記法を使う（近接武器の例: base['base']['base']['atk']、弓・ガンナーは
  1 段浅く base['base']['atk']）
- 名称テーブル <武器種>__name（無印分）と <武器種>__name_mr（MR 分）の content は
  32 言語の配列。DuckDB は 1-indexed で content[1]=日本語, content[2]=英語
- 名称と base_data は v_* ビューで結合済み。生テーブルを直接結合する場合は、
  名称テーブルの name 列（W_<武器種>_<id>_Name 形式）に含まれる武器 id と
  base_data の id struct でキー結合すること（行の並びは武器種によって一致しない）。
  base_data に対応しない名称行（未使用武器枠）やテスト用データが存在する点に注意
- 派生ツリーは <武器種>__tree、生産素材は <武器種>__product に入っている
- サンブレイク（MR）追加分は *_mr サフィックスのテーブルに入っている
- 属性値などのマイナス値は「未設定」を意味する場合がある
- 「クリア後テスト用」「TU3テスト用」などのテスト用データも含まれる。
  ユーザーへの回答では除外して提示すること
"""

ALLOWED_STATEMENT = re.compile(r"^\s*(select|with|explain|describe|show)\b", re.IGNORECASE)

# 武器種ごとの設定: (武器 id struct のキー, 近接武器かどうか, 属性を持つか)
# 近接武器は struct が 1 段深い（base.base.base.atk）。弓・ガンナーは浅い（base.base.atk）
WEAPON_CONFIG = {
    "great_sword": ("GreatSword", True, True),
    "long_sword": ("LongSword", True, True),
    "short_sword": ("ShortSword", True, True),
    "dual_blades": ("DualBlades", True, True),
    "hammer": ("Hammer", True, True),
    "horn": ("Horn", True, True),
    "lance": ("Lance", True, True),
    "gun_lance": ("GunLance", True, True),
    "slash_axe": ("SlashAxe", True, True),
    "charge_axe": ("ChargeAxe", True, True),
    "insect_glaive": ("InsectGlaive", True, True),
    "bow": ("Bow", False, True),
    "light_bowgun": ("LightBowgun", False, False),
    "heavy_bowgun": ("HeavyBowgun", False, False),
}

mcp = FastMCP("mhrise", instructions=INSTRUCTIONS)
con = duckdb.connect(":memory:")


def to_rows(value):
    """値から行リストを取り出す。"""
    rows = value
    if isinstance(value, dict):
        for unwrap in ("param", "entries", "data_list"):
            if isinstance(value.get(unwrap), list):
                rows = value[unwrap]
                break
        else:
            rows = [value]
    if not isinstance(rows, list):
        rows = [rows]
    return [r if isinstance(r, dict) else {"value": r} for r in rows]


def is_container(value) -> bool:
    """dict/list のみからなり、実質キーが param/entries/data_list 単独でない dict は
    サブグループの入れ物とみなす（例: great_sword = {base_data, name, tree, ...}）。"""
    if not (
        isinstance(value, dict)
        and len(value) > 1
        and all(isinstance(v, (dict, list)) for v in value.values())
    ):
        return False
    payload_keys = [k for k in value if k != "attribute_headers"]
    return not (len(payload_keys) == 1 and payload_keys[0] in ("param", "entries", "data_list"))


def collect_tables(key, value, out: dict) -> None:
    if is_container(value):
        for sub_key, sub_value in value.items():
            collect_tables(f"{key}__{sub_key}", sub_value, out)
    else:
        out[key] = to_rows(value)


def load_data() -> None:
    files = sorted(f for f in os.listdir(DATA_DIR) if f.endswith(".json.gz"))
    if not files:
        raise RuntimeError(f"no .json.gz files found in {DATA_DIR}")
    tables = {}
    for name in files:
        with gzip.open(os.path.join(DATA_DIR, name), "rt", encoding="utf-8") as f:
            category = json.load(f)
        for key, value in category.items():
            collect_tables(key, value, tables)
    with tempfile.TemporaryDirectory() as tmp:
        for key, rows in tables.items():
            ndjson = os.path.join(tmp, f"{key}.ndjson")
            with open(ndjson, "w", encoding="utf-8") as f:
                for row in rows:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            con.execute(
                f'CREATE TABLE "{key}" AS '
                f"SELECT * FROM read_json_auto('{ndjson}', format='newline_delimited')"
            )
    print(f"loaded {len(tables)} tables from {len(files)} files", flush=True)


def create_views() -> None:
    """生テーブルの上に、名称結合済み・よく使う列を平坦化した v_* ビューを作る。

    名称テーブルの name 列（W_<武器種>_<id>_Name 形式）に武器 id が埋め込まれており、
    base_data の id struct とキー結合できる。テスト用データは除外せず is_test フラグで示す。
    """
    con.execute(
        """
        CREATE VIEW v_horn_melody AS
        SELECT id, content[1] AS name_ja, content[2] AS name_en
        FROM (
            SELECT TRY_CAST(regexp_extract(name, '_(\\d+)_Name$', 1) AS INTEGER) AS id, content
            FROM horn_melody
            UNION ALL
            SELECT TRY_CAST(regexp_extract(name, '_(\\d+)_Name$', 1) AS INTEGER), content
            FROM horn_melody_mr
        )
        WHERE id IS NOT NULL
        """
    )
    con.execute(
        """
        CREATE VIEW v_hyakuryu_skill AS
        SELECT h.id['Skill'] AS id, m.content[1] AS name_ja, m.content[2] AS name_en, h.*
        FROM hyakuryu_skill h
        LEFT JOIN (
            SELECT TRY_CAST(regexp_extract(name, '_(\\d+)_Name$', 1) AS INTEGER) AS id, content
            FROM hyakuryu_skill_name_msg
        ) m ON m.id = h.id['Skill']
        """
    )
    for wt, (id_key, deep, has_element) in WEAPON_CONFIG.items():
        stats = "d.base['base']['base']" if deep else "d.base['base']"
        ids = f"{stats}['base']"
        elem = "d.base['base']" if deep else "d.base"
        element_cols = (
            f"{elem}['main_element_type'] AS element_type,\n"
            f"                {elem}['main_element_val'] AS element_val"
            if has_element
            else "NULL AS element_type,\n                NULL AS element_val"
        )
        extra_cols = ""
        extra_join = ""
        if wt == "horn":
            extra_cols = """,
                   list_transform(d.horn_melody_type_list, x -> mm.mp_ja[x]) AS melodies_ja,
                   list_transform(d.horn_melody_type_list, x -> mm.mp_en[x]) AS melodies_en"""
            extra_join = """
            CROSS JOIN (
                SELECT map(list(id), list(name_ja)) AS mp_ja,
                       map(list(id), list(name_en)) AS mp_en
                FROM v_horn_melody
            ) mm"""
        # 名称テーブルの name 列は W_<武器種>_<id>_Name（一部 _Name_MR）形式で
        # 武器 id を含む。base_data の id とキー結合できるため、行位置に依存しない
        con.execute(
            f"""
            CREATE VIEW "v_{wt}" AS
            WITH n AS (
                SELECT * FROM (
                    SELECT TRY_CAST(regexp_extract(name, '^W_\\w+_(\\d+)_Name(?:_MR)?$', 1)
                                    AS INTEGER) AS wid,
                           content[1] AS name_ja, content[2] AS name_en, false AS is_mr
                    FROM "{wt}__name"
                    UNION ALL
                    SELECT TRY_CAST(regexp_extract(name, '^W_\\w+_(\\d+)_Name(?:_MR)?$', 1)
                                    AS INTEGER),
                           content[1], content[2], true
                    FROM "{wt}__name_mr"
                )
                WHERE wid IS NOT NULL
                -- 同名・同 id の重複エントリが稀に存在する（例: gun_lance の
                -- 里守用堅守銃槍）。無印側を優先して 1 件に絞る
                QUALIFY row_number() OVER (PARTITION BY wid ORDER BY is_mr) = 1
            )
            SELECT
                n.name_ja,
                n.name_en,
                coalesce(n.name_ja LIKE '%テスト%', false) AS is_test,
                n.is_mr,
                {ids}['id']['{id_key}'] AS weapon_id,
                {ids}['sort_id'] AS sort_id,
                {ids}['rare_type'] AS rare,
                {stats}['atk'] AS atk,
                {stats}['critical_rate'] AS affinity,
                {stats}['def_bonus'] AS def_bonus,
                {stats}['slot_num_list'] AS slots,
                list_transform({stats}['hyakuryu_skill_id_list'], s -> s['Skill'])
                    AS hyakuryu_skill_ids,
                {element_cols}{extra_cols},
                d.*
            FROM "{wt}__base_data" d
            LEFT JOIN n ON n.wid = {ids}['id']['{id_key}']{extra_join}
            """
        )
    print(f"created views: v_horn_melody, v_hyakuryu_skill, "
          f"{', '.join(f'v_{w}' for w in WEAPON_CONFIG)}", flush=True)


def check_weapon_alignment() -> None:
    """v_<武器種> の名称結合率と行数を検証し、異常があれば警告を出す。"""
    problems = []
    for wt in WEAPON_CONFIG:
        total, named, n_data = con.execute(
            f"""
            SELECT COUNT(*), COUNT(name_ja),
                   (SELECT COUNT(*) FROM "{wt}__base_data")
            FROM "v_{wt}"
            """
        ).fetchone()
        if named != total:
            problems.append(f"{wt}: {named}/{total} named")
        if total != n_data:
            problems.append(f"{wt}: 行数 {total} != base_data {n_data}（名称の重複結合？）")
    if problems:
        print("warning: 武器ビューの整合性異常: " + ", ".join(problems), flush=True)
    else:
        print(f"name join verified: all {len(WEAPON_CONFIG)} weapon views fully named",
              flush=True)


@mcp.tool
def query(sql: str) -> str:
    """DuckDB SQL（SELECT 系のみ）を実行し、結果を JSON 文字列で返す。"""
    if not ALLOWED_STATEMENT.match(sql):
        return "error: SELECT / WITH / EXPLAIN / DESCRIBE / SHOW のみ実行可能です"
    try:
        result = con.execute(sql)
        columns = [d[0] for d in result.description]
        rows = result.fetchmany(MAX_ROWS + 1)
        truncated = len(rows) > MAX_ROWS
        rows = rows[:MAX_ROWS]
        payload = json.dumps(
            {"columns": columns, "rows": rows, "truncated": truncated},
            ensure_ascii=False,
            default=str,
        )
        if len(payload) > MAX_CHARS:
            payload = payload[:MAX_CHARS] + '..."（MAX_CHARS 超過のため打ち切り）'
        return payload
    except Exception as e:
        return f"error: {e}"


@mcp.tool
def list_tables() -> str:
    """利用可能なテーブル名の一覧を返す。"""
    rows = con.execute(
        "SELECT table_name FROM information_schema.tables ORDER BY table_name"
    ).fetchall()
    return json.dumps([r[0] for r in rows], ensure_ascii=False)


@mcp.tool
def describe_table(table: str) -> str:
    """指定テーブルのカラム名と型を返す。"""
    if not re.fullmatch(r"[A-Za-z0-9_]+", table):
        return "error: テーブル名が不正です"
    try:
        rows = con.execute(f'DESCRIBE "{table}"').fetchall()
        return json.dumps(
            [{"column": r[0], "type": r[1]} for r in rows], ensure_ascii=False
        )
    except Exception as e:
        return f"error: {e}"


if __name__ == "__main__":
    load_data()
    create_views()
    check_weapon_alignment()
    mcp.run(transport="http", host=HOST, port=PORT)
