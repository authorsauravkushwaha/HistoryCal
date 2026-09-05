#!/usr/bin/env python3
"""Runs every test module in tests/ and exits non-zero on any failure.

    python run_tests.py
"""
import runpy
import sys
import os

TEST_FILES = [
    "tests/test_calendar_math.py",
    "tests/test_storage.py",
    "tests/test_theme.py",
    "tests/test_history_api.py",
]


def main():
    root = os.path.dirname(os.path.abspath(__file__))
    failed = []
    for rel_path in TEST_FILES:
        path = os.path.join(root, rel_path)
        print(f"\n----- {rel_path} -----")
        try:
            runpy.run_path(path, run_name="__main__")
        except AssertionError as exc:
            print(f"FAILED: {exc}")
            failed.append(rel_path)
        except Exception as exc:  # noqa: BLE001 - test runner, want to catch everything
            print(f"ERROR: {exc}")
            failed.append(rel_path)

    print("\n" + "=" * 50)
    if failed:
        print(f"{len(failed)} test file(s) failed: {failed}")
        sys.exit(1)
    print("All test suites passed.")


if __name__ == "__main__":
    main()
