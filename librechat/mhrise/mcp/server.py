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
1. list_tables でテーブル一覧を確認する
2. describe_table で対象テーブルの構造を確認してから query で SQL を実行する
   （テーブルはネストした struct を含むため、構造確認してから書くこと）

データ構造上の注意:
- 武器テーブルは <武器種>__base_data（例: great_sword__base_data）に入っている。
  武器種: great_sword, long_sword, short_sword, dual_blades, hammer, horn, lance,
  gun_lance, slash_axe, charge_axe, insect_glaive, bow, light_bowgun, heavy_bowgun
- 攻撃力などはネストした struct 内にある。struct のフィールドアクセスは
  ドットではなくブラケット記法を使うこと（大剣の例）:
  base['base']['base']['atk']（攻撃力）, base['base']['main_element_type']（属性）
  深さは武器種で異なる場合があるため、必ず describe_table で確認すること
- 武器名は <武器種>__name（無印分）と <武器種>__name_mr（MR 分）に分かれており、
  content カラムが 32 言語の配列。DuckDB は 1-indexed で content[1]=日本語, content[2]=英語。
  base_data は無印分→MR 分の順に並んでおり、name の後ろに name_mr を連結すると
  行の並びが対応する。JOIN 例:
    WITH w AS (SELECT row_number() OVER () AS i, * FROM great_sword__base_data),
         n AS (SELECT row_number() OVER () AS i, content FROM great_sword__name
               UNION ALL
               SELECT row_number() OVER () + (SELECT COUNT(*) FROM great_sword__name), content
               FROM great_sword__name_mr)
    SELECT n.content[1] AS name, w.base['base']['base']['atk'] FROM w JOIN n USING (i)
- 派生ツリーは <武器種>__tree、生産素材は <武器種>__product に入っている
- サンブレイク（MR）追加分は *_mr サフィックスのテーブルに入っている
- 属性値などのマイナス値は「未設定」を意味する場合がある
- 「クリア後テスト用」「TU3テスト用」などのテスト用データも含まれる。
  ユーザーへの回答では除外して提示すること
"""

ALLOWED_STATEMENT = re.compile(r"^\s*(select|with|explain|describe|show)\b", re.IGNORECASE)

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
    mcp.run(transport="http", host=HOST, port=PORT)
