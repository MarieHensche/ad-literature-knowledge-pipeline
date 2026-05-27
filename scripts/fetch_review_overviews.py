#!/usr/bin/env python3
"""Compatibility wrapper for review/overview seed fetching."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ad_lit_pipeline.steps.collection.fetch_review_overviews import main


if __name__ == "__main__":
    main()
