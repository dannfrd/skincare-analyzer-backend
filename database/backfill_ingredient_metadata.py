import argparse
import sys
from pathlib import Path

from sqlalchemy import text

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from database.db_connection import DatabaseConnection
from modules.rag_context import get_ingredient_simple_description


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill empty ingredient descriptions/functions from Qdrant."
    )
    parser.add_argument("--limit", type=int, default=10000)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db = DatabaseConnection()
    if not db.engine:
        raise RuntimeError("Database connection unavailable.")

    with db.engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, name, description, `function`
                FROM ingredients
                WHERE `function` IS NULL
                   OR TRIM(`function`) = ''
                   OR LOWER(TRIM(`function`)) = 'unknown'
                   OR description IS NULL
                   OR TRIM(description) = ''
                   OR LOWER(TRIM(description)) IN (
                       'unknown',
                       'ingredient not found in database.'
                   )
                ORDER BY id
                LIMIT :limit
                """
            ),
            {"limit": max(1, args.limit)},
        ).mappings().all()

    updated = 0
    not_found = 0

    for index, row in enumerate(rows, start=1):
        metadata = get_ingredient_simple_description(str(row.get("name") or ""))
        if not metadata:
            not_found += 1
            print(f"[{index}/{len(rows)}] No exact dataset match: {row.get('name')}")
            continue

        current_description = str(row.get("description") or "").strip()
        current_function = str(row.get("function") or "").strip()
        dataset_description = str(metadata.get("simple_description") or "").strip()
        dataset_functions = str(metadata.get("functions") or "").strip()

        description = (
            dataset_description
            if dataset_description
            and (
                not current_description
                or current_description.lower()
                in {"unknown", "ingredient not found in database."}
            )
            else None
        )
        function = (
            dataset_functions
            if dataset_functions
            and (not current_function or current_function.lower() == "unknown")
            else None
        )

        if not description and not function:
            continue

        print(
            f"[{index}/{len(rows)}] {row.get('name')}: "
            f"function={function or '(unchanged)'}"
        )
        if args.dry_run:
            continue

        with db.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE ingredients
                    SET description = COALESCE(:description, description),
                        `function` = COALESCE(:function, `function`)
                    WHERE id = :id
                    """
                ),
                {
                    "id": row.get("id"),
                    "description": description,
                    "function": function,
                },
            )
        updated += 1

    print(
        f"Done. candidates={len(rows)} updated={updated} "
        f"no_exact_match={not_found} dry_run={args.dry_run}"
    )


if __name__ == "__main__":
    main()
