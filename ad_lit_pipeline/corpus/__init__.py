"""Shared corpus specification, identity, temporal, and source-type semantics."""

from ad_lit_pipeline.corpus.identity import (
    SourceVersionAssessment,
    WorkIdentityAssessment,
    assess_source_version,
    assess_work_identity,
)
from ad_lit_pipeline.corpus.source_types import (
    SourceTypeAssessment,
    classify_source_type,
)
from ad_lit_pipeline.corpus.specification import (
    CORPUS_SPECIFICATION_SCHEMA_VERSION,
    CorpusSpecification,
    corpus_specification_from_contract,
    default_corpus_specification_mapping,
    resolve_as_of,
    validate_corpus_specification,
)
from ad_lit_pipeline.corpus.temporal import (
    TemporalEligibilityAssessment,
    assess_temporal_eligibility,
)

__all__ = [
    "CORPUS_SPECIFICATION_SCHEMA_VERSION",
    "CorpusSpecification",
    "SourceTypeAssessment",
    "SourceVersionAssessment",
    "TemporalEligibilityAssessment",
    "WorkIdentityAssessment",
    "assess_source_version",
    "assess_temporal_eligibility",
    "assess_work_identity",
    "classify_source_type",
    "corpus_specification_from_contract",
    "default_corpus_specification_mapping",
    "resolve_as_of",
    "validate_corpus_specification",
]
