from pathlib import Path


def apply_sql(connection, path: Path) -> None:
    connection.execute(path.read_text(encoding="utf-8"), prepare=False)
