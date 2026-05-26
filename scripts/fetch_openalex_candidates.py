#!/usr/bin/env python3
"""Compatibility wrapper for candidate fetching.

The historical script name is OpenAlex-specific. The implementation now
dispatches through provider modules, with OpenAlex as the supported provider.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ad_lit_pipeline.steps.collection.fetch_candidates import main


if __name__ == "__main__":
    main()
