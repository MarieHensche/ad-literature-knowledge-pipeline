"""Validated, versioned projections and optional publication for Mantis."""

from ad_lit_pipeline.mantis.profiles import (
    DEFAULT_PROFILE_DIRECTORY,
    ProfileContext,
    compile_profile,
    load_profile_template,
)
from ad_lit_pipeline.mantis.projection import (
    ProjectionResult,
    export_mantis_views,
    project_records,
)

__all__ = [
    "DEFAULT_PROFILE_DIRECTORY",
    "ProfileContext",
    "ProjectionResult",
    "compile_profile",
    "export_mantis_views",
    "load_profile_template",
    "project_records",
]
