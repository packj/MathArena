#!/usr/bin/env python3
"""
import_tags.py

A tool to import problem tags from a CSV file (e.g. problems.csv) into the database.
New tags are the union of the existing tags for a given problem and the tags listed in the CSV.

CSV columns expected:
    year, problem_number, tags, round, level
Tags in the CSV are delimited by semicolons (;) or commas (,).
Tags in the database are formatted as: [`Tag1`, `Tag2`, ...]
"""

import argparse
import csv
import os
import sys
from typing import Dict, List, Set, Tuple

import db_aws
from sqlalchemy import text


def parse_tags_string(tags_str: str, delimiter: str = None) -> Set[str]:
    """Parse tags from a string (handles both DB bracketed/backtick format and CSV delimiter formats)."""
    if not tags_str:
        return set()

    cleaned = tags_str.strip()
    if cleaned == "[]":
        return set()

    # If it is formatted as [`tag1`, `tag2`]
    if cleaned.startswith("[") and cleaned.endswith("]"):
        cleaned = cleaned[1:-1]

    # Remove any backticks
    cleaned = cleaned.replace("`", "")

    # If delimiter specified, split by it; otherwise check for semicolon first, then comma
    if delimiter:
        parts = cleaned.split(delimiter)
    elif ";" in cleaned:
        parts = cleaned.split(";")
    else:
        parts = cleaned.split(",")

    tags = set()
    for part in parts:
        tag = part.strip()
        if tag:
            tags.add(tag)
    return tags


def format_db_tags(tags: Set[str]) -> str:
    """Format tags set into the DB format: [`Tag 1`, `Tag 2`] sorted alphabetically."""
    if not tags:
        return "[]"
    sorted_tags = sorted(tags)
    return "[" + ", ".join(f"`{t}`" for t in sorted_tags) + "]"


def load_db_problems(conn) -> Dict[Tuple[str, str, str, int], Tuple[int, str]]:
    """
    Fetch existing problems from the DB.
    Key: (year, level, format/round, question_number) - all normalized (lowercase, stripped, int for qnum).
    Value: (problem_id, existing_tags_str)
    """
    query = text("SELECT id, year, level, format, question_number, tags FROM problems")
    rows = conn.execute(query).fetchall()

    db_map = {}
    for r in rows:
        pid, year, level, fmt, qnum, tags_str = (
            r[0],
            str(r[1]).strip(),
            str(r[2]).strip().lower(),
            str(r[3]).strip().lower(),
            int(r[4]),
            r[5],
        )
        db_map[(year, level, fmt, qnum)] = (pid, tags_str)
    return db_map


def import_tags(csv_filepath: str, dry_run: bool = False, verbose: bool = False) -> None:
    if not os.path.exists(csv_filepath):
        print(f"Error: File not found: {csv_filepath}", file=sys.stderr)
        sys.exit(1)

    print(f"Reading CSV file: {csv_filepath}...")
    with open(csv_filepath, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = [fn.strip() for fn in (reader.fieldnames or [])]
        required_cols = {"year", "problem_number", "tags", "round", "level"}
        if not required_cols.issubset(set(fieldnames)):
            print(
                f"Error: CSV missing required columns. Found: {fieldnames}, required: {sorted(list(required_cols))}",
                file=sys.stderr,
            )
            sys.exit(1)

        csv_rows = list(reader)

    print(f"Loaded {len(csv_rows)} rows from CSV.")

    print("Connecting to database...")
    with db_aws.sql_db.connect() as conn:
        db_map = load_db_problems(conn)
        print(f"Loaded {len(db_map)} existing problems from database.")

        updated_count = 0
        unchanged_count = 0
        missing_count = 0
        missing_keys = []

        updates_to_execute = []

        for row_idx, row in enumerate(csv_rows, start=1):
            year_val = row.get("year", "").strip()
            level_val = row.get("level", "").strip().lower()
            round_val = row.get("round", "").strip().lower()
            qnum_str = row.get("problem_number", "").strip()
            csv_tags_str = row.get("tags", "")

            if not (year_val and level_val and round_val and qnum_str):
                print(f"Warning: Skipping row {row_idx} due to missing identifying fields: {row}")
                continue

            try:
                qnum_val = int(qnum_str)
            except ValueError:
                print(f"Warning: Skipping row {row_idx} due to invalid question_number: '{qnum_str}'")
                continue

            key = (year_val, level_val, round_val, qnum_val)

            if key not in db_map:
                missing_count += 1
                missing_keys.append(key)
                if verbose:
                    print(f"Problem not found in DB: Year={year_val}, Level={level_val}, Round={round_val}, #{qnum_val}")
                continue

            pid, existing_tags_str = db_map[key]
            existing_tags = parse_tags_string(existing_tags_str)
            csv_tags = parse_tags_string(csv_tags_str)

            union_tags = existing_tags | csv_tags
            new_tags_str = format_db_tags(union_tags)

            # Check if there are newly added tags
            if union_tags == existing_tags:
                unchanged_count += 1
            else:
                updated_count += 1
                updates_to_execute.append((pid, new_tags_str, key, existing_tags_str, new_tags_str))
                if verbose:
                    added_tags = union_tags - existing_tags
                    print(f"[Problem {pid} ({year_val} {level_val} {round_val} #{qnum_val})] Added tags: {added_tags}")

        print(f"\n--- Summary ---")
        print(f"Total CSV records processed: {len(csv_rows)}")
        print(f"Problems to update with new tags: {updated_count}")
        print(f"Problems with no new tags to add: {unchanged_count}")
        print(f"Problems not found in database:    {missing_count}")

        if dry_run:
            print("\n[DRY RUN] No database changes made.")
            if updates_to_execute:
                print(f"First 3 changes that would be made:")
                for pid, new_tags_str, key, old_tags, _ in updates_to_execute[:3]:
                    print(f"  Problem ID {pid} {key}:")
                    print(f"    Before: {old_tags}")
                    print(f"    After:  {new_tags_str}")
            return

        if updates_to_execute:
            print(f"\nApplying {len(updates_to_execute)} updates to database...")
            update_query = text("UPDATE problems SET tags = :tags WHERE id = :id")
            for pid, new_tags_str, _, _, _ in updates_to_execute:
                conn.execute(update_query, {"tags": new_tags_str, "id": pid})
            conn.commit()
            print("Successfully updated tags in the database!")
        else:
            print("No database updates required.")


def main():
    parser = argparse.ArgumentParser(
        description="Import tags from a CSV file into the database (merging with existing tags)."
    )
    parser.add_argument(
        "csv_file",
        nargs="?",
        default="problems.csv",
        help="Path to the CSV file (default: problems.csv)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate the import and show what would be updated without writing to the database.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed output for each problem updated and missing problems.",
    )

    args = parser.parse_args()
    import_tags(csv_filepath=args.csv_file, dry_run=args.dry_run, verbose=args.verbose)


if __name__ == "__main__":
    main()
