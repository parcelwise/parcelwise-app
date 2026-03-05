"""Apply migrations/*.sql in order. Each file runs once; applied names are kept in schema_migrations."""

from pathlib import Path

from app.core.db import transaction

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def main():
    with transaction() as cur:
        cur.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY)")
        cur.execute("SELECT name FROM schema_migrations")
        done = {row[0] for row in cur.fetchall()}
        for path in sorted(MIGRATIONS.glob("*.sql")):
            if path.name not in done:
                cur.execute(path.read_text())
                cur.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
                print("applied", path.name)


if __name__ == "__main__":
    main()
