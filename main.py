#!/usr/bin/env python3
"""
HistoryCal - The Infinite Battle Calendar
==========================================

Run this file to start the app:

    python main.py

Requires only the Python standard library (Python 3.9+). No `pip install`
needed - Tkinter ships with almost every standard Python installation.
(If you're on Linux and get "No module named tkinter", install it with
your package manager, e.g. `sudo apt install python3-tk`.)
"""
import sys

if __name__ == "__main__":
    try:
        from historycal.ui import run
    except ImportError as exc:
        print("Could not start HistoryCal.\n")
        if "tkinter" in str(exc).lower():
            print("Tkinter is not installed. On Debian/Ubuntu, run:")
            print("    sudo apt install python3-tk")
            print("On Windows/Mac, reinstall Python from python.org and "
                  "make sure 'tcl/tk' is included (it is, by default).")
        else:
            print(f"Import error: {exc}")
        sys.exit(1)

    run()
