"""Initialize the database."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.models import init_database
from config.settings import DATABASE_PATH


def main():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    engine = init_database(str(DATABASE_PATH))
    print(f"Database initialized at {DATABASE_PATH}")
    print("Tables created:")
    from database.models import Base
    for table_name in Base.metadata.tables:
        print(f"  - {table_name}")


if __name__ == "__main__":
    main()
