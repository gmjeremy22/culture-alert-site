import argparse
import csv
import sqlite3
import sys
from pathlib import Path


AUTOMATION_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = AUTOMATION_DIR / "culture-alert" / "outputs"
DB_PATH = OUTPUTS_DIR / "culture-alert.sqlite"
SCHEMA_PATH = OUTPUTS_DIR / "culture-alert-schema.sql"
INSTITUTIONS_SEED = OUTPUTS_DIR / "institutions-seed.csv"
EXPANDED_INSTITUTIONS = OUTPUTS_DIR / "expanded-institution-candidates.csv"
INTERESTS_SEED = OUTPUTS_DIR / "interests-seed.csv"
OFFICIAL_DIRECTORY = OUTPUTS_DIR / "official-facility-directory.csv"

TIER_PRIORITY = {"A": 1, "B": 2, "C": 3}
RETIRED_INSTITUTIONS = {
    "예술의전당 한가람미술관/디자인미술관",
    "뮤지엄 산",
}


def read_csv(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def upsert_institution(conn, row):
    name = (row.get("institution_name") or row.get("name") or "").strip()
    if not name:
        return
    tier = (row.get("tier") or "").strip().upper()
    priority = row.get("priority") or TIER_PRIORITY.get(tier, 3)
    collection_phase = row.get("collection_phase") or (
        f"phase-{tier.lower()}" if tier else "phase3"
    )
    official_url = row.get("official_url") or ""
    exhibition_url = row.get("exhibition_url") or official_url
    program_url = row.get("program_url") or ""
    conn.execute(
        """
        INSERT INTO institutions (
          name, region, city, category, priority, collection_phase,
          exhibition_url, program_url, notes, active
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT(name) DO UPDATE SET
          region=COALESCE(NULLIF(excluded.region, ''), institutions.region),
          city=COALESCE(NULLIF(excluded.city, ''), institutions.city),
          category=COALESCE(NULLIF(excluded.category, ''), institutions.category),
          priority=MIN(institutions.priority, excluded.priority),
          collection_phase=COALESCE(NULLIF(institutions.collection_phase, ''), excluded.collection_phase),
          exhibition_url=COALESCE(NULLIF(institutions.exhibition_url, ''), excluded.exhibition_url),
          program_url=COALESCE(NULLIF(institutions.program_url, ''), excluded.program_url),
          notes=COALESCE(NULLIF(institutions.notes, ''), excluded.notes),
          active=1,
          updated_at=CURRENT_TIMESTAMP
        """,
        (
            name,
            row.get("region") or "",
            row.get("city") or "",
            row.get("category") or "박물관",
            int(priority),
            collection_phase,
            exhibition_url,
            program_url,
            row.get("notes") or "",
        ),
    )


def upsert_interest(conn, row):
    person_name = (row.get("person_name") or "").strip()
    keyword = (row.get("keyword") or "").strip()
    if not person_name or not keyword:
        return
    conn.execute(
        """
        INSERT INTO interests (person_name, keyword, weight, active)
        VALUES (?, ?, ?, 1)
        ON CONFLICT(person_name, keyword) DO UPDATE SET
          weight=excluded.weight,
          active=1
        """,
        (person_name, keyword, int(row.get("weight") or 1)),
    )


def initialize_database(reset=False):
    if reset and DB_PATH.exists():
        DB_PATH.unlink()
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"schema not found: {SCHEMA_PATH}")

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        for row in read_csv(EXPANDED_INSTITUTIONS):
            upsert_institution(conn, row)
        for row in read_csv(INSTITUTIONS_SEED):
            upsert_institution(conn, row)
        if OFFICIAL_DIRECTORY.exists():
            if str(OUTPUTS_DIR) not in sys.path:
                sys.path.insert(0, str(OUTPUTS_DIR))
            from official_facility_directory import import_directory_csv

            import_directory_csv(conn, OFFICIAL_DIRECTORY)
        for institution_name in RETIRED_INSTITUTIONS:
            conn.execute(
                "UPDATE institutions SET active=0, updated_at=CURRENT_TIMESTAMP WHERE name=?",
                (institution_name,),
            )
        for row in read_csv(INTERESTS_SEED):
            upsert_interest(conn, row)
        conn.commit()
        institutions = conn.execute("SELECT COUNT(*) FROM institutions").fetchone()[0]
        interests = conn.execute("SELECT COUNT(*) FROM interests").fetchone()[0]
    return institutions, interests


def main():
    parser = argparse.ArgumentParser(description="Initialize cloud culture-alert DB")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    institutions, interests = initialize_database(reset=args.reset)
    print(f"db={DB_PATH}")
    print(f"institutions={institutions}")
    print(f"interests={interests}")


if __name__ == "__main__":
    main()
