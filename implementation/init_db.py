from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

try:
    from .db import DEFAULT_DB_PATH, SQLiteAdapter
except ImportError:
    from db import DEFAULT_DB_PATH, SQLiteAdapter


SCHEMA_SQL = """
CREATE TABLE students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    cohort TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    gpa REAL NOT NULL CHECK (gpa >= 0 AND gpa <= 4),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    credits INTEGER NOT NULL CHECK (credits > 0),
    department TEXT NOT NULL
);

CREATE TABLE enrollments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    course_id INTEGER NOT NULL,
    semester TEXT NOT NULL,
    score REAL NOT NULL CHECK (score >= 0 AND score <= 100),
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
    FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE,
    UNIQUE (student_id, course_id, semester)
);
"""


STUDENTS = [
    ("2A202600127", "Mai Tan Thanh", "A1", "thanh.mai@example.edu", 3.72),
    ("2A202600118", "An Nguyen", "A1", "an.nguyen@example.edu", 3.86),
    ("2A202600145", "Bao Tran", "A1", "bao.tran@example.edu", 3.42),
    ("2A202600203", "Chi Le", "A2", "chi.le@example.edu", 3.63),
    ("2A202600219", "Duc Pham", "A2", "duc.pham@example.edu", 3.18),
    ("2A202600301", "Linh Hoang", "B1", "linh.hoang@example.edu", 3.94),
]


COURSES = [
    ("AI101", "Introduction to AI", 3, "AI"),
    ("DB201", "Database Systems", 3, "CS"),
    ("MCP301", "MCP Tool Integration", 2, "AI"),
    ("STAT210", "Applied Statistics", 3, "Math"),
]


ENROLLMENTS = [
    (1, 1, "2026A", 91.5),
    (1, 2, "2026A", 87.0),
    (1, 3, "2026A", 94.0),
    (2, 1, "2026A", 95.0),
    (2, 3, "2026A", 92.5),
    (3, 2, "2026A", 79.0),
    (3, 4, "2026A", 83.5),
    (4, 1, "2026A", 88.0),
    (4, 4, "2026A", 90.0),
    (5, 2, "2026A", 76.5),
    (5, 3, "2026A", 81.0),
    (6, 1, "2026A", 97.0),
    (6, 3, "2026A", 96.0),
]


def create_database(db_path: str | Path = DEFAULT_DB_PATH, reset: bool = True) -> Path:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if reset and path.exists():
        path.unlink()

    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA_SQL)
        conn.executemany(
            """
            INSERT INTO students (student_code, name, cohort, email, gpa)
            VALUES (?, ?, ?, ?, ?)
            """,
            STUDENTS,
        )
        conn.executemany(
            """
            INSERT INTO courses (code, title, credits, department)
            VALUES (?, ?, ?, ?)
            """,
            COURSES,
        )
        conn.executemany(
            """
            INSERT INTO enrollments (student_id, course_id, semester, score)
            VALUES (?, ?, ?, ?)
            """,
            ENROLLMENTS,
        )
        conn.commit()
    return path


def ensure_database(db_path: str | Path = DEFAULT_DB_PATH) -> Path:
    path = Path(db_path)
    adapter = SQLiteAdapter(path)
    if not path.exists() or not adapter.list_tables():
        return create_database(path, reset=True)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize the SQLite lab database.")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    parser.add_argument("--reset", action="store_true", help="Recreate the database from seed data.")
    args = parser.parse_args()

    path = create_database(args.db_path, reset=True) if args.reset else ensure_database(args.db_path)
    print(f"SQLite lab database ready: {path}")


if __name__ == "__main__":
    main()
