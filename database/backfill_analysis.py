import argparse
import sys
from pathlib import Path
from typing import List

from sqlalchemy import text

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from database.db_connection import DatabaseConnection
from modules.text_cleaning import clean_text_pipeline, extract_ingredient_text
from modules.ingredient_matching import match_tokens_to_db
from modules.expert_system import run_expert_system


def _fetch_targets(conn, limit: int) -> List[dict]:
    query = text(
        """
        SELECT
            a.id AS analysis_id,
            s.id AS scan_id,
            s.extracted_text AS extracted_text,
            COUNT(DISTINCT si.id) AS scan_ingredient_count,
            COUNT(DISTINCT ad.id) AS detail_count
        FROM analyses a
        LEFT JOIN scans s ON s.id = a.scan_id
        LEFT JOIN scan_ingredients si ON si.scan_id = s.id
        LEFT JOIN analysis_details ad ON ad.analysis_id = a.id
        WHERE s.extracted_text IS NOT NULL
          AND TRIM(s.extracted_text) != ''
        GROUP BY a.id, s.id, s.extracted_text
        HAVING scan_ingredient_count = 0 OR detail_count = 0
        ORDER BY a.id DESC
        LIMIT :limit
        """
    )

    rows = conn.execute(query, {"limit": limit}).mappings().all()
    return [dict(row) for row in rows]


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill scan_ingredients and analysis_details.")
    parser.add_argument("--limit", type=int, default=200, help="Max analyses to backfill")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    db = DatabaseConnection()
    if not db.engine:
        raise RuntimeError("Database connection unavailable.")

    with db.engine.connect() as conn:
        targets = _fetch_targets(conn, args.limit)

    if not targets:
        print("No analyses need backfill.")
        return

    ingredients = db.get_all_ingredients()
    print(f"Found {len(targets)} analyses to backfill.")

    for idx, row in enumerate(targets, start=1):
        analysis_id = row.get("analysis_id")
        scan_id = row.get("scan_id")
        raw_text = row.get("extracted_text") or ""
        scan_count = row.get("scan_ingredient_count") or 0
        detail_count = row.get("detail_count") or 0

        if not analysis_id or not scan_id or not raw_text:
            print(f"[{idx}] Skip (missing IDs/text): analysis_id={analysis_id}, scan_id={scan_id}")
            continue

        ingredient_text = extract_ingredient_text(raw_text)
        cleaned_tokens = clean_text_pipeline(ingredient_text)
        matched_ingredients = match_tokens_to_db(cleaned_tokens, ingredients)
        expert_report = run_expert_system(matched_ingredients)

        if args.dry_run:
            print(
                f"[{idx}] analysis_id={analysis_id} scan_id={scan_id} "
                f"scan_ingredients={scan_count} analysis_details={detail_count} "
                f"matched={len(matched_ingredients)}"
            )
            continue

        with db.engine.begin() as conn:
            if scan_count == 0:
                db._save_scan_ingredient_links(conn, scan_id, matched_ingredients)
            if detail_count == 0:
                db._save_analysis_details(conn, analysis_id, matched_ingredients, expert_report)

        print(
            f"[{idx}] Backfilled analysis_id={analysis_id} "
            f"scan_ingredients={scan_count == 0} details={detail_count == 0}"
        )


if __name__ == "__main__":
    main()
