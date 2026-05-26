#!/usr/bin/env python3
"""Compatibility wrapper for tagging config normalization."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ad_lit_pipeline.steps.tagging.normalize_config import main


if __name__ == "__main__":
    main()
