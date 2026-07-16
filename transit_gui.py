#!/usr/bin/env python3
"""Convenience wrapper: run the transit viewer without -m.

    python transit_gui.py
    python transit_gui.py results.json
    python transit_gui.py --config other-site.json

Equivalent to `python -m sattransit.gui ...`. On Windows, launch with
pythonw.exe (instead of python.exe) to avoid an extra console window.
"""

import sys

from sattransit.gui import main

if __name__ == "__main__":
    sys.exit(main())
