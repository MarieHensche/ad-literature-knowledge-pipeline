#!/usr/bin/env python3
"""Compatibility wrapper for rule-based scope screening."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ad_lit_pipeline.steps.screening.rule_based_scope import main


if __name__ == "__main__":
    main()
