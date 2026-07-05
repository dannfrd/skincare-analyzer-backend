import argparse
import csv
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import text

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from database.db_connection import DatabaseConnection


DEFAULT_DATASET_PATH = ROOT_DIR / "data" / "dataset_scincare" / "cosmetic_ingredients.csv"


def normalize_name(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "").strip()).upper()
    cleaned = re.sub(r"[^A-Z0-9\s\-\+\./]", "", cleaned)
    return cleaned.strip()


def infer_risk_level(rating: Optional[str]) -> str:
    value = str(rating or "").strip().lower()
    if not value:
        return "unknown"
    if value in {"superstar", "goodie"}:
        return "low"
    if value in {"icky", "bad", "high"}:
        return "high"
    if value in {"moderate", "medium", "average"}:
        return "medium"
    return "unknown"


def pick_first(row: Dict[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def load_csv_rows(csv_path: Path) -> List[Dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        raw_lines = [line.rstrip("\n") for line in handle if line.strip()]

    if not raw_lines:
        return []

    sample = "\n".join(raw_lines[:5])
    has_header = csv.Sniffer().has_header(sample)

    if has_header:
        rows: List[Dict[str, str]] = []
        cleaned = []
        for line in raw_lines:
            cleaned.append(line.rstrip(";") if line.endswith(";;") else line)

        reader = csv.DictReader(cleaned)
        for row in reader:
            rows.append({str(key): str(value or "") for key, value in row.items()})
        return rows

    rows = []
    for line in raw_lines:
        cleaned_line = line.rstrip(";") if line.endswith(";;") else line
        parsed = next(csv.reader([cleaned_line]))
        if not parsed:
            continue

        rows.append(
            {
                "ingredient": parsed[0] if len(parsed) > 0 else "",
                "description": parsed[1] if len(parsed) > 1 else "",
                "rating": parsed[2] if len(parsed) > 2 else "",
                "function": parsed[3] if len(parsed) > 3 else "",
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import ingredient dataset CSV into the MySQL ingredients table."
    )
    parser.add_argument(
        "--file",
        default=str(DEFAULT_DATASET_PATH),
        help="Path to the ingredient CSV file.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and print counts without writing to the database.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional maximum number of rows to import.",
    )
    args = parser.parse_args()

    csv_path = Path(args.file).resolve()
    if not csv_path.exists():
        raise FileNotFoundError(f"Dataset file not found: {csv_path}")

    rows = load_csv_rows(csv_path)
    if args.limit > 0:
        rows = rows[: args.limit]

    db = DatabaseConnection()
    if not db.engine:
        raise RuntimeError("Database connection is unavailable.")

    inserted = 0
    updated = 0
    skipped = 0

    with db.engine.begin() as conn:
        if not db._table_exists(conn, "ingredients"):
            raise RuntimeError("The ingredients table does not exist.")

        for index, row in enumerate(rows, start=1):
            name = pick_first(row, ["ingredient", "ingredient_name", "inci_name", "name"])
            description = pick_first(row, ["description", "details", "text"])
            function_value = pick_first(row, ["functions", "function"])
            rating = pick_first(row, ["rating"])

            normalized_name = normalize_name(name)
            if not normalized_name:
                skipped += 1
                continue

            risk_level = infer_risk_level(rating)
            existing = conn.execute(
                text(
                    """
                    SELECT id, description, `function`, risk_level
                    FROM ingredients
                    WHERE name = :name
                    LIMIT 1
                    """
                ),
                {"name": normalized_name},
            ).mappings().first()

            if existing:
                updates: Dict[str, Any] = {}
                current_description = str(existing.get("description") or "").strip()
                current_function = str(existing.get("function") or "").strip()
                current_risk = str(existing.get("risk_level") or "").strip()

                if description and not current_description:
                    updates["description"] = description
                if function_value and not current_function:
                    updates["function"] = function_value
                if risk_level != "unknown" and not current_risk:
                    updates["risk_level"] = risk_level

                if updates and not args.dry_run:
                    conn.execute(
                        text(
                            """
                            UPDATE ingredients
                            SET description = COALESCE(:description, description),
                                `function` = COALESCE(:function, `function`),
                                risk_level = COALESCE(:risk_level, risk_level)
                            WHERE id = :id
                            """
                        ),
                        {
                            "id": existing.get("id"),
                            "description": updates.get("description"),
                            "function": updates.get("function"),
                            "risk_level": updates.get("risk_level"),
                        },
                    )
                    updated += 1
                else:
                    skipped += 1
                continue

            if args.dry_run:
                inserted += 1
                continue

            conn.execute(
                text(
                    """
                    INSERT INTO ingredients (name, description, `function`, risk_level, created_at)
                    VALUES (:name, :description, :function, :risk_level, NOW())
                    """
                ),
                {
                    "name": normalized_name,
                    "description": description or None,
                    "function": function_value or None,
                    "risk_level": risk_level,
                },
            )
            inserted += 1

    print(
        f"Done. parsed={len(rows)} inserted={inserted} updated={updated} skipped={skipped} dry_run={args.dry_run}"
    )


if __name__ == "__main__":
    main()