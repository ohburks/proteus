"""Standalone seed entrypoint for `make seed` — schema, rubrics, default
accounts, and the exemplar/personalized excerpt corpora, in the order each
depends on the last. Deliberately separate from app startup (main.py only
runs init_db() there) so seeding is an explicit, one-time step: `make setup`
-> `make seed` -> `make dev`.
"""
from app.auth import seed_default_accounts
from app.db import get_connection, init_db
from app.seed import seed_rubrics
from app.seed_excerpts import seed_exemplar_excerpts, seed_personalized_excerpts


def main() -> None:
    init_db()
    seed_rubrics()
    seed_default_accounts()
    seed_exemplar_excerpts()
    seed_personalized_excerpts()

    with get_connection() as conn:
        counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("rubrics", "users", "exemplar_excerpts_src", "personalized_excerpts_src")
        }
    print("Seed complete:")
    print(f"  rubrics:                {counts['rubrics']}")
    print(f"  users:                  {counts['users']}")
    print(f"  exemplar excerpts:      {counts['exemplar_excerpts_src']}")
    print(f"  personalized excerpts:  {counts['personalized_excerpts_src']}")


if __name__ == "__main__":
    main()
