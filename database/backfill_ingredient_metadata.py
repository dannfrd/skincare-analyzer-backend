import argparse
import sys
from pathlib import Path

from sqlalchemy import text

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from database.db_connection import DatabaseConnection
from modules.rag_context import get_ingredient_simple_description


def _is_missing(value: object, placeholders: set[str]) -> bool:
    normalized = str(value or "").strip().lower()
    return not normalized or normalized in placeholders


def _load_analysis_metadata(conn) -> dict[int, dict[str, str]]:
    rows = conn.execute(
        text(
            """
            SELECT
                ad.ingredient_id,
                MAX(
                    CASE
                        WHEN ad.`function` IS NOT NULL
                         AND TRIM(ad.`function`) != ''
                         AND LOWER(TRIM(ad.`function`)) != 'unknown'
                        THEN ad.`function`
                    END
                ) AS analysis_function,
                MAX(
                    CASE
                        WHEN ad.benefit IS NOT NULL
                         AND TRIM(ad.benefit) != ''
                         AND LOWER(TRIM(ad.benefit)) NOT IN (
                             'unknown',
                             'ingredient not found in database.'
                         )
                        THEN ad.benefit
                    END
                ) AS analysis_description
            FROM analysis_details ad
            GROUP BY ad.ingredient_id
            """
        )
    ).mappings().all()
    return {
        int(row["ingredient_id"]): {
            "function": str(row.get("analysis_function") or "").strip(),
            "description": str(row.get("analysis_description") or "").strip(),
        }
        for row in rows
        if row.get("ingredient_id") is not None
    }


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
        analysis_metadata = _load_analysis_metadata(conn)

    updated = 0
    not_found = 0
    no_usable_metadata = 0
    would_update = 0

    for index, row in enumerate(rows, start=1):
        current_description = str(row.get("description") or "").strip()
        current_function = str(row.get("function") or "").strip()
        relational = analysis_metadata.get(int(row.get("id")), {})
        metadata = get_ingredient_simple_description(str(row.get("name") or ""))

        if not metadata and not relational:
            not_found += 1
            print(f"[{index}/{len(rows)}] No trusted metadata: {row.get('name')}")
            continue

        dataset_description = str(
            relational.get("description")
            or metadata.get("simple_description")
            or ""
        ).strip()
        dataset_functions = str(
            relational.get("function") or metadata.get("functions") or ""
        ).strip()

        description = (
            dataset_description
            if dataset_description
            and _is_missing(
                current_description,
                {"unknown", "ingredient not found in database."},
            )
            else None
        )
        function = (
            dataset_functions
            if dataset_functions
            and _is_missing(current_function, {"unknown"})
            else None
        )

        if not description and not function:
            no_usable_metadata += 1
            print(
                f"[{index}/{len(rows)}] Match has no missing metadata to apply: "
                f"{row.get('name')}"
            )
            continue

        source = "analysis_details" if relational else "qdrant"
        print(
            f"[{index}/{len(rows)}] {row.get('name')}: "
            f"function={function or '(unchanged)'} source={source}"
        )
        would_update += 1
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
        f"Done. candidates={len(rows)} would_update={would_update} "
        f"updated={updated} no_trusted_metadata={not_found} "
        f"no_usable_metadata={no_usable_metadata} dry_run={args.dry_run}"
    )


if __name__ == "__main__":
    main()
