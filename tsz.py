#!/usr/bin/env python
"""Compatibility wrapper for the renamed ORZIP utility."""
from __future__ import annotations

from orzip import *  # noqa: F401,F403 - preserve old import surface during rename
from orzip import main

if __name__ == "__main__":
    raise SystemExit(main())
