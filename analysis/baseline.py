"""Run a baseline SQL file against an existing DuckDB database, read-only.

The default SQL is a draft schema mapping, NOT the missing Section 7.3 source.
Use --query to provide the confirmed query. Never creates or seeds source data.
"""
import argparse
import json
from pathlib import Path

import duckdb


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--query", type=Path,
                        default=Path(__file__).resolve().parents[1] / "sql/00_baseline_30d.sql")
    args = parser.parse_args()
    if not args.db.is_file():
        parser.error(f"Source database does not exist: {args.db}")
    query = args.query.read_text(encoding="utf-8")
    with duckdb.connect(str(args.db), read_only=True) as con:
        result = con.execute(query).fetchdf()
    print(query)
    print(result.to_string(index=False))
    print(json.dumps(result.to_dict(orient="records"), indent=2))


if __name__ == "__main__":
    main()
