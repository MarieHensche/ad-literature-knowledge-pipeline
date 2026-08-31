from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, Mapping, TypeAlias

from ad_lit_pipeline.validity.models import (
    ClaimVerificationOutcome,
    GapStatus,
)


JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = (
    JsonScalar | tuple["JsonValue", ...] | Mapping[str, "JsonValue"]
)


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_value(item) for key, item in value.items()}
        )
    if isinstance(value, (tuple, list)):
        return tuple(_freeze_value(item) for item in value)
    if is_dataclass(value) and not isinstance(value, type):
        for field in fields(value):
            object.__setattr__(
                value,
                field.name,
                _freeze_value(getattr(value, field.name)),
            )
    return value


class RecordType(str, Enum):
    CORPUS_SNAPSHOT = "corpus_snapshot"
    SCHOLARLY_WORK = "scholarly_work"
    SOURCE_VERSION = "source_version"
    PROVIDER_RECORD = "provider_record"
    ACCESS_LOCATION = "access_location"
    DOCUMENT = "document"
    PASSAGE = "passage"
    ENTITY = "entity"
    CLAIM = "claim"
    CLAIM_EVIDENCE = "claim_evidence"
    RELATIONSHIP = "relationship"
    GAP_SIGNAL = "gap_signal"
    GAP_CANDIDATE = "gap_candidate"
    VERIFICATION_ATTEMPT = "verification_attempt"
    GAP_SCORE = "gap_score"
    EXPERT_JUDGMENT = "expert_judgment"
    OUTCOME_EVENT = "outcome_event"
    MANTIS_EXPORT_PROFILE = "mantis_export_profile"
    MANTIS_INTERPRETATION = "mantis_interpretation"
    MANTIS_PUBLICATION_RECEIPT = "mantis_publication_receipt"


class AdministrativeRecordStatus(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    INVALID = "invalid"


class ProvenanceKind(str, Enum):
    RECORD = "record"
    ARTIFACT = "artifact"
    EXTERNAL = "external"


class PartialDatePrecision(str, Enum):
    YEAR = "year"
    MONTH = "month"
    DAY = "day"
    UNKNOWN = "unknown"


class PartialDateCertainty(str, Enum):
    EXACT = "exact"
    BOUNDED = "bounded"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


class CoverageStatus(str, Enum):
    NOT_ASSESSED = "not_assessed"
    ADEQUATE_FOR_RULE = "adequate_for_rule"
    PARTIAL = "partial"
    INSUFFICIENT = "insufficient"


class SnapshotStatus(str, Enum):
    BUILDING = "building"
    FROZEN = "frozen"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class NegativeNullPolicy(str, Enum):
    TARGETED = "targeted"
    INCLUDE_WHEN_IDENTIFIED = "include_when_identified"
    NOT_TARGETED = "not_targeted"
    EXCLUDE = "exclude"


class WorkKind(str, Enum):
    RESEARCH_ARTICLE = "research_article"
    REVIEW = "review"
    PROTOCOL = "protocol"
    CLINICAL_TRIAL = "clinical_trial"
    DATASET = "dataset"
    PATENT = "patent"
    THESIS = "thesis"
    BOOK = "book"
    BOOK_CHAPTER = "book_chapter"
    CONFERENCE_OUTPUT = "conference_output"
    OTHER = "other"


class IdentityBasis(str, Enum):
    GLOBAL_IDENTIFIER = "global_identifier"
    REGISTRY_IDENTIFIER = "registry_identifier"
    METADATA_FINGERPRINT = "metadata_fingerprint"
    MANUAL_MERGE = "manual_merge"


class IdentityStatus(str, Enum):
    RESOLVED = "resolved"
    PROVISIONAL = "provisional"
    AMBIGUOUS = "ambiguous"
    NEEDS_REVIEW = "needs_review"


class SourceVersionKind(str, Enum):
    PREPRINT = "preprint"
    SUBMITTED_MANUSCRIPT = "submitted_manuscript"
    ACCEPTED_MANUSCRIPT = "accepted_manuscript"
    VERSION_OF_RECORD = "version_of_record"
    CORRECTED_VERSION = "corrected_version"
    RETRACTION_NOTICE = "retraction_notice"
    PROTOCOL_VERSION = "protocol_version"
    REGISTRY_VERSION = "registry_version"
    DATASET_RELEASE = "dataset_release"
    PATENT_PUBLICATION = "patent_publication"
    OTHER = "other"


class AvailabilityStatus(str, Enum):
    KNOWN = "known"
    BOUNDED = "bounded"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


class TemporalEligibility(str, Enum):
    ELIGIBLE = "eligible"
    AFTER_CUTOFF = "after_cutoff"
    UNKNOWN = "unknown"


class SourceLifecycleStatus(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    CORRECTED = "corrected"
    WITHDRAWN = "withdrawn"
    RETRACTED = "retracted"
    UNKNOWN = "unknown"


class ProviderRetrievalStatus(str, Enum):
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    TOMBSTONE = "tombstone"


class LocationKind(str, Enum):
    LANDING_PAGE = "landing_page"
    PDF = "pdf"
    HTML = "html"
    XML = "xml"
    API = "api"
    REPOSITORY = "repository"
    LOCAL_FILE = "local_file"
    SUPPLEMENT = "supplement"
    DATA = "data"
    OTHER = "other"


class AccessMethod(str, Enum):
    PUBLIC_HTTP = "public_http"
    PROVIDER_API = "provider_api"
    AUTHENTICATED_REFERENCE = "authenticated_reference"
    LOCAL_FILE = "local_file"


class AccessStatus(str, Enum):
    AVAILABLE = "available"
    RESTRICTED = "restricted"
    INACCESSIBLE = "inaccessible"
    NOT_FOUND = "not_found"
    ERROR = "error"
    UNKNOWN = "unknown"


class DocumentRole(str, Enum):
    MAIN = "main"
    SUPPLEMENT = "supplement"
    PROTOCOL = "protocol"
    APPENDIX = "appendix"
    DATASET_DOCUMENTATION = "dataset_documentation"
    CORRECTION = "correction"
    RETRACTION_NOTICE = "retraction_notice"
    OTHER = "other"


class DocumentStatus(str, Enum):
    STORED = "stored"
    QUARANTINED = "quarantined"
    INVALID = "invalid"
    SUPERSEDED = "superseded"


class PassageKind(str, Enum):
    TITLE = "title"
    ABSTRACT = "abstract"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    TABLE = "table"
    FIGURE_CAPTION = "figure_caption"
    FOOTNOTE = "footnote"
    REFERENCE = "reference"
    OTHER = "other"


class EntityType(str, Enum):
    TOPIC = "topic"
    CONDITION = "condition"
    POPULATION = "population"
    INTERVENTION = "intervention"
    EXPOSURE = "exposure"
    METHOD = "method"
    MEASUREMENT = "measurement"
    OUTCOME = "outcome"
    DATASET = "dataset"
    PROTOCOL = "protocol"
    STUDY_DESIGN = "study_design"
    SETTING = "setting"
    THEORY = "theory"
    POLICY = "policy"
    TECHNOLOGY = "technology"
    ORGANISM = "organism"
    MATERIAL = "material"
    OTHER = "other"


class EntityResolutionStatus(str, Enum):
    UNRESOLVED = "unresolved"
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    MERGED = "merged"
    REJECTED = "rejected"


class ClaimOrigin(str, Enum):
    SOURCE_ASSERTED = "source_asserted"
    PIPELINE_SYNTHESIS = "pipeline_synthesis"
    HUMAN_ASSERTED = "human_asserted"


class ClaimType(str, Enum):
    EMPIRICAL_FINDING = "empirical_finding"
    NULL_FINDING = "null_finding"
    METHODOLOGICAL = "methodological"
    LIMITATION = "limitation"
    FUTURE_WORK = "future_work"
    AUTHOR_GAP = "author_gap"
    BACKGROUND = "background"
    SYNTHESIS = "synthesis"
    OTHER = "other"


class ClaimPolarity(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NULL = "null"
    MIXED = "mixed"
    INCONCLUSIVE = "inconclusive"
    NOT_APPLICABLE = "not_applicable"


class ClaimDirection(str, Enum):
    INCREASES = "increases"
    DECREASES = "decreases"
    ASSOCIATED_WITH = "associated_with"
    NOT_ASSOCIATED_WITH = "not_associated_with"
    NO_EFFECT = "no_effect"
    MIXED = "mixed"
    UNCLEAR = "unclear"
    NOT_APPLICABLE = "not_applicable"


class ClaimModality(str, Enum):
    OBSERVED = "observed"
    ESTIMATED = "estimated"
    HYPOTHESIZED = "hypothesized"
    RECOMMENDED = "recommended"
    REPORTED = "reported"
    UNCLEAR = "unclear"


class ExtractionStatus(str, Enum):
    EXTRACTED = "extracted"
    NEEDS_REVIEW = "needs_review"
    REVIEWED = "reviewed"
    REJECTED = "rejected"


class EvidenceRole(str, Enum):
    PRIMARY_SUPPORT = "primary_support"
    ADDITIONAL_SUPPORT = "additional_support"
    COUNTEREVIDENCE = "counterevidence"
    QUALIFICATION = "qualification"
    CONTEXT = "context"
    METHOD = "method"


class MaterialCheckStatus(str, Enum):
    MATCHED = "matched"
    MISMATCHED = "mismatched"
    NOT_APPLICABLE = "not_applicable"
    UNCERTAIN = "uncertain"


class RelationshipStatus(str, Enum):
    ASSERTED = "asserted"
    VERIFIED = "verified"
    DISPUTED = "disputed"
    REJECTED = "rejected"


class RelationshipPredicate(str, Enum):
    IS_VERSION_OF = "is_version_of"
    SUPERSEDES = "supersedes"
    CORRECTS = "corrects"
    RETRACTS = "retracts"
    CITES = "cites"
    CONTAINS = "contains"
    MENTIONS = "mentions"
    REPORTS = "reports"
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    EXTENDS = "extends"
    USES_METHOD = "uses_method"
    STUDIES_POPULATION = "studies_population"
    USES_DATASET = "uses_dataset"
    MEASURES_OUTCOME = "measures_outcome"
    TESTS_INTERVENTION = "tests_intervention"
    HAS_STUDY_DESIGN = "has_study_design"
    ADDRESSES_GAP = "addresses_gap"
    SAME_AS = "same_as"


class GapSignalType(str, Enum):
    EXPLICIT_FUTURE_WORK_PASSAGE = "explicit_future_work_passage"
    ELIGIBLE_UNIT_COUNT_BELOW_THRESHOLD = (
        "eligible_unit_count_below_threshold"
    )
    TYPED_GRAPH_RELATION_ABSENT = "typed_graph_relation_absent"
    COMPARABLE_VERIFIED_CLAIMS_INCOMPATIBLE = (
        "comparable_verified_claims_incompatible"
    )
    POPULATION_REPRESENTATION_BELOW_THRESHOLD = (
        "population_representation_below_threshold"
    )
    SOURCE_CONTEXT_METHOD_PRESENT_TARGET_CONTEXT_ABSENT = (
        "source_context_method_present_target_context_absent"
    )
    LATEST_ELIGIBLE_EVIDENCE_OLDER_THAN_THRESHOLD = (
        "latest_eligible_evidence_older_than_threshold"
    )
    DIRECT_COMPARISON_COUNT_BELOW_THRESHOLD = (
        "direct_comparison_count_below_threshold"
    )
    GRAPH_CONNECTIVITY_BELOW_THRESHOLD = (
        "graph_connectivity_below_threshold"
    )
    EVIDENCE_QUALITY_BELOW_THRESHOLD = (
        "evidence_quality_below_threshold"
    )
    INDEPENDENT_DATASET_VALIDATION_COUNT_BELOW_THRESHOLD = (
        "independent_dataset_validation_count_below_threshold"
    )
    PROTOCOL_RESULT_LINK_ABSENT_AFTER_GRACE_PERIOD = (
        "protocol_result_link_absent_after_grace_period"
    )


class VerificationAttemptStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ABORTED = "aborted"
    ERROR = "error"


class VerificationCheckStatus(str, Enum):
    NOT_RUN = "not_run"
    PASSED = "passed"
    FAILED = "failed"
    UNCERTAIN = "uncertain"
    NOT_APPLICABLE = "not_applicable"


class ScoreCalibrationStatus(str, Enum):
    UNCALIBRATED = "uncalibrated"
    PROVISIONAL = "provisional"
    CALIBRATED = "calibrated"


class ExpertDecision(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    ALREADY_KNOWN = "already_known"
    DUPLICATE = "duplicate"
    CANNOT_ASSESS = "cannot_assess"


class BlindingState(str, Enum):
    BLINDED = "blinded"
    PARTIALLY_BLINDED = "partially_blinded"
    UNBLINDED = "unblinded"
    NOT_APPLICABLE = "not_applicable"


class OutcomeStatus(str, Enum):
    REPORTED = "reported"
    INDEPENDENTLY_VERIFIED = "independently_verified"
    DISPUTED = "disputed"
    CORRECTED = "corrected"
    WITHDRAWN = "withdrawn"


class OutcomeEventType(str, Enum):
    FUNDING_AWARDED = "funding_awarded"
    STUDY_STARTED = "study_started"
    PROTOCOL_REGISTERED = "protocol_registered"
    DATASET_RELEASED = "dataset_released"
    RESULT_PUBLISHED = "result_published"
    REPLICATED = "replicated"
    POLICY_USE = "policy_use"
    PRACTICE_USE = "practice_use"
    PROJECT_REJECTED = "project_rejected"
    PROJECT_ABANDONED = "project_abandoned"
    OTHER = "other"


class CausalAttribution(str, Enum):
    NONE = "none"
    ASSOCIATED = "associated"
    SELF_REPORTED_CONTRIBUTION = "self_reported_contribution"
    INDEPENDENTLY_ASSESSED_CONTRIBUTION = (
        "independently_assessed_contribution"
    )
    UNKNOWN = "unknown"


class MantisRecordKind(str, Enum):
    PAPER = "paper"
    VERIFIED_CLAIM = "verified_claim"
    VERIFIED_GAP = "verified_gap"


class MantisDataType(str, Enum):
    TITLE = "Title"
    SEMANTIC = "Semantic"
    CATEGORIC = "Categoric"
    NUMERIC = "Numeric"
    DATE = "Date"
    LINKS = "Links"
    CONNECTION = "Connection"


class MantisNullPolicy(str, Enum):
    EMPTY = "empty"
    OMIT = "omit"
    SENTINEL = "sentinel"
    ERROR = "error"


class MantisMultivaluePolicy(str, Enum):
    JOIN = "join"
    FIRST = "first"
    JSON = "json"
    ERROR = "error"


class InterpretationActorType(str, Enum):
    HUMAN = "human"
    MANTIS_AGENT = "mantis_agent"
    PIPELINE = "pipeline"
    LLM = "llm"


class InterpretationType(str, Enum):
    CLUSTER_SUMMARY = "cluster_summary"
    COMPARISON = "comparison"
    OUTLIER = "outlier"
    HYPOTHESIS = "hypothesis"
    GAP_HYPOTHESIS = "gap_hypothesis"
    OTHER = "other"


class InterpretationDownstreamState(str, Enum):
    PRE_CANDIDATE = "pre_candidate"
    AWAITING_INDEPENDENT_SIGNAL = "awaiting_independent_signal"
    INDEPENDENT_SIGNAL_FOUND = "independent_signal_found"
    CANDIDATE_CREATED = "candidate_created"
    DISMISSED = "dismissed"
    NEEDS_HUMAN_REVIEW = "needs_human_review"


class MantisOperation(str, Enum):
    CREATE = "create"
    REFRESH = "refresh"
    UPSERT = "upsert"
    MANUAL_IMPORT = "manual_import"


class MantisDuplicatePolicy(str, Enum):
    REJECT = "reject"
    CREATE_NEW = "create_new"
    UPSERT_BY_POINT_ID = "upsert_by_point_id"
    UNKNOWN = "unknown"


class MantisPublicationStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL = "partial"


@dataclass(frozen=True, kw_only=True)
class ProvenanceEntry:
    kind: ProvenanceKind
    relation: str
    reference: str
    sha256: str | None


@dataclass(frozen=True, kw_only=True)
class ValidationWarning:
    code: str
    message: str
    field_path: str | None


@dataclass(frozen=True, kw_only=True)
class PartialDate:
    value: str | None
    precision: PartialDatePrecision
    certainty: PartialDateCertainty


@dataclass(frozen=True, kw_only=True)
class Identifier:
    scheme: str
    value: str
    uri: str | None


@dataclass(frozen=True, kw_only=True)
class Contributor:
    name: str
    role: str
    position: int | None
    identifiers: tuple[Identifier, ...]


@dataclass(frozen=True, kw_only=True)
class CoverageAssessment:
    status: CoverageStatus
    rule_id: str
    searched_sources: tuple[str, ...]
    dimensions: Mapping[str, JsonValue]
    limitations: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class Assessment:
    dimension: str
    value: float | str | None
    scale: str
    rationale: str
    assessor_id: str


@dataclass(frozen=True, kw_only=True)
class PassageSpan:
    passage_id: str
    start_char: int
    end_char: int
    quoted_text_sha256: str


@dataclass(frozen=True, kw_only=True)
class MaterialChecks:
    population: MaterialCheckStatus
    method: MaterialCheckStatus
    outcome: MaterialCheckStatus
    direction: MaterialCheckStatus
    study_design: MaterialCheckStatus
    numeric_details: MaterialCheckStatus


@dataclass(frozen=True, kw_only=True)
class GapStateTransition:
    from_gap_status: GapStatus
    to_gap_status: GapStatus
    transitioned_at: str
    actor_id: str
    verification_attempt_id: str | None
    completed_check_ids: tuple[str, ...]
    reason: str
    new_candidate_version: bool


@dataclass(frozen=True, kw_only=True)
class VerificationCheck:
    check_id: str
    status: VerificationCheckStatus
    performed_at: str | None
    verifier_id: str | None
    evidence_ids: tuple[str, ...]
    details: str
    human_review_trigger_ids: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class ScoreDimension:
    dimension: str
    score: float
    scale_min: float
    scale_max: float
    rationale: str
    evidence_ids: tuple[str, ...]
    assessor_id: str
    uncertainty: float | None
    calibration_reference_id: str | None


@dataclass(frozen=True, kw_only=True)
class MantisFieldSpec:
    output_name: str
    source_path: str
    mantis_type: MantisDataType
    required: bool
    null_policy: MantisNullPolicy
    multivalue_policy: MantisMultivaluePolicy
    separator: str | None
    semantic_order: int | None


@dataclass(frozen=True, kw_only=True)
class PublicationError:
    code: str
    message: str
    retryable: bool


@dataclass(frozen=True, kw_only=True)
class BaseRecord:
    schema_version: str
    record_id: str
    created_at: str
    corpus_snapshot_id: str
    producing_run_id: str
    producing_step_id: str
    parent_record_ids: tuple[str, ...]
    source_record_ids: tuple[str, ...]
    provenance: tuple[ProvenanceEntry, ...]
    record_status: AdministrativeRecordStatus
    validation_warnings: tuple[ValidationWarning, ...]
    policy_versions: Mapping[str, str]
    extensions: Mapping[str, JsonValue]

    def __post_init__(self) -> None:
        """Deep-freeze nested JSON values supplied to direct constructors."""
        for field in fields(self):
            object.__setattr__(
                self,
                field.name,
                _freeze_value(getattr(self, field.name)),
            )


RecordEnvelope = BaseRecord


@dataclass(frozen=True, kw_only=True)
class CorpusSnapshot(BaseRecord):
    RECORD_TYPE: ClassVar[str] = "corpus_snapshot"

    name: str
    description: str
    snapshot_status: SnapshotStatus
    as_of: str
    availability_date_rule: str
    topic_contract_ref: Mapping[str, JsonValue]
    scope: Mapping[str, JsonValue]
    negative_null_policy: NegativeNullPolicy
    collection_plan_sha256: str
    resolved_plan_sha256: str
    retrieval_started_at: str
    retrieval_completed_at: str | None
    source_version_ids: tuple[str, ...]
    provider_record_ids: tuple[str, ...]
    coverage: CoverageAssessment
    frozen_at: str | None


@dataclass(frozen=True, kw_only=True)
class ScholarlyWork(BaseRecord):
    RECORD_TYPE: ClassVar[str] = "scholarly_work"

    preferred_title: str
    alternate_titles: tuple[str, ...]
    work_kind: WorkKind
    identifiers: tuple[Identifier, ...]
    identity_basis: IdentityBasis
    identity_key: str
    identity_status: IdentityStatus


@dataclass(frozen=True, kw_only=True)
class SourceVersion(BaseRecord):
    RECORD_TYPE: ClassVar[str] = "source_version"

    work_id: str
    version_kind: SourceVersionKind
    version_label: str | None
    version_number: str | None
    version_identifiers: tuple[Identifier, ...]
    title: str
    abstract: str | None
    contributors: tuple[Contributor, ...]
    venue: str | None
    publisher: str | None
    language: str | None
    source_type: str
    study_design_entity_ids: tuple[str, ...]
    publication_date: PartialDate | None
    availability_earliest: PartialDate | None
    availability_latest: PartialDate | None
    availability_date_rule: str
    availability_status: AvailabilityStatus
    temporal_eligibility: TemporalEligibility
    lifecycle_status: SourceLifecycleStatus
    previous_source_version_ids: tuple[str, ...]
    provider_record_ids: tuple[str, ...]
    reference_identifiers: tuple[Identifier, ...]


@dataclass(frozen=True, kw_only=True)
class ProviderRecord(BaseRecord):
    RECORD_TYPE: ClassVar[str] = "provider_record"

    provider_name: str
    provider_version: str | None
    endpoint: str
    provider_item_id: str
    provider_item_url: str | None
    query_id: str
    request_sha256: str
    redacted_request_url: str | None
    query_tier: int | None
    page_or_cursor: str | None
    provider_rank: int | None
    retrieved_at: str
    provider_updated_at: str | None
    retrieval_status: ProviderRetrievalStatus
    raw_record_media_type: str
    raw_record_sha256: str | None
    raw_record_uri: str | None
    license: str | None
    error_code: str | None
    error_message: str | None


@dataclass(frozen=True, kw_only=True)
class AccessLocation(BaseRecord):
    RECORD_TYPE: ClassVar[str] = "access_location"

    source_version_id: str
    provider_record_id: str | None
    uri: str
    uri_sha256: str
    location_kind: LocationKind
    access_method: AccessMethod
    observed_at: str
    access_status: AccessStatus
    media_type: str | None
    license: str | None
    is_open_access: bool | None
    http_status: int | None
    redirect_uri: str | None
    failure_reason: str | None


@dataclass(frozen=True, kw_only=True)
class Document(BaseRecord):
    RECORD_TYPE: ClassVar[str] = "document"

    source_version_id: str
    access_location_id: str
    document_role: DocumentRole
    media_type: str
    language: str | None
    content_sha256: str
    byte_size: int
    retrieved_at: str
    artifact_uri: str
    license: str | None
    document_status: DocumentStatus
    page_count: int | None
    encrypted: bool


@dataclass(frozen=True, kw_only=True)
class Passage(BaseRecord):
    RECORD_TYPE: ClassVar[str] = "passage"

    document_id: str
    source_version_id: str
    sequence_index: int
    passage_kind: PassageKind
    text: str
    text_sha256: str
    language: str | None
    section_path: tuple[str, ...]
    locator: Mapping[str, JsonValue]
    extractor_name: str
    extractor_version: str
    extraction_config_sha256: str
    extracted_at: str


@dataclass(frozen=True, kw_only=True)
class Entity(BaseRecord):
    RECORD_TYPE: ClassVar[str] = "entity"

    entity_type: EntityType
    canonical_name: str
    normalized_name: str
    definition: str | None
    aliases: tuple[str, ...]
    ontology_identifiers: tuple[Identifier, ...]
    resolution_status: EntityResolutionStatus
    resolution_method: str
    canonical_entity_id: str | None
    source_passage_ids: tuple[str, ...]
    topic_ids: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class Claim(BaseRecord):
    RECORD_TYPE: ClassVar[str] = "claim"

    claim_origin: ClaimOrigin
    claim_type: ClaimType
    claim_text: str
    source_version_id: str | None
    source_claim_ids: tuple[str, ...]
    topic_ids: tuple[str, ...]
    polarity: ClaimPolarity
    direction: ClaimDirection
    modality: ClaimModality
    subject_entity_ids: tuple[str, ...]
    population_entity_ids: tuple[str, ...]
    intervention_entity_ids: tuple[str, ...]
    comparator_entity_ids: tuple[str, ...]
    outcome_entity_ids: tuple[str, ...]
    measurement_entity_ids: tuple[str, ...]
    method_entity_ids: tuple[str, ...]
    dataset_entity_ids: tuple[str, ...]
    study_design_entity_ids: tuple[str, ...]
    setting_entity_ids: tuple[str, ...]
    time_horizon: str | None
    quantitative_details: tuple[Mapping[str, JsonValue], ...]
    comparability_profile: Mapping[str, JsonValue]
    extraction_status: ExtractionStatus
    extraction_assessment: Assessment | None


@dataclass(frozen=True, kw_only=True)
class ClaimEvidence(BaseRecord):
    RECORD_TYPE: ClassVar[str] = "claim_evidence"

    claim_id: str
    source_version_id: str
    evidence_role: EvidenceRole
    passage_spans: tuple[PassageSpan, ...]
    checked_passage_ids: tuple[str, ...]
    verification_outcome: ClaimVerificationOutcome
    verifier_id: str
    verification_method: str
    verified_at: str
    material_checks: MaterialChecks
    counterclaim_id: str | None
    comparability_key: str | None
    insufficiency_reasons: tuple[str, ...]
    uncertainty_reasons: tuple[str, ...]
    unresolved_checks: tuple[str, ...]
    human_review_triggers: tuple[str, ...]
    verification_assessment: Assessment | None


@dataclass(frozen=True, kw_only=True)
class Relationship(BaseRecord):
    RECORD_TYPE: ClassVar[str] = "relationship"

    subject_id: str
    subject_type: RecordType
    predicate: RelationshipPredicate
    object_id: str
    object_type: RecordType
    relationship_status: RelationshipStatus
    basis: str
    claim_evidence_ids: tuple[str, ...]
    passage_ids: tuple[str, ...]
    comparability_key: str | None
    valid_as_of: str
    asserted_at: str


@dataclass(frozen=True, kw_only=True)
class GapSignal(BaseRecord):
    RECORD_TYPE: ClassVar[str] = "gap_signal"

    signal_type: GapSignalType
    gap_type_ids: tuple[str, ...]
    rule_id: str
    rule_version: str
    statement: str
    corpus_scope: Mapping[str, JsonValue]
    as_of: str
    availability_date_rule: str
    query_or_cell: str
    rule_inputs: Mapping[str, JsonValue]
    rule_result: Mapping[str, JsonValue]
    rule_trace_sha256: str
    supporting_claim_ids: tuple[str, ...]
    supporting_passage_ids: tuple[str, ...]
    relationship_ids: tuple[str, ...]
    checked_source_version_ids: tuple[str, ...]
    retrieval_query_log_ids: tuple[str, ...]
    coverage_status: CoverageStatus
    coverage_dimensions: Mapping[str, JsonValue]
    uncertainty_reasons: tuple[str, ...]
    deterministic: bool
    source_interpretation_ids: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class GapCandidate(BaseRecord):
    RECORD_TYPE: ClassVar[str] = "gap_candidate"

    gap_lineage_id: str
    candidate_version: int
    supersedes_candidate_id: str | None
    gap_type_id: str
    gap_type_version: str
    title: str
    statement: str
    rationale: str
    research_question: str
    corpus_scope: Mapping[str, JsonValue]
    as_of: str
    availability_date_rule: str
    signal_ids: tuple[str, ...]
    supporting_claim_ids: tuple[str, ...]
    coverage_status: CoverageStatus
    coverage_dimensions: Mapping[str, JsonValue]
    uncertainty_reasons: tuple[str, ...]
    resolution_rule_id: str
    resolution_rule_version: str
    gap_status: GapStatus
    state_history: tuple[GapStateTransition, ...]
    verification_attempt_ids: tuple[str, ...]
    decisive_verification_attempt_id: str | None
    human_review_trigger_ids: tuple[str, ...]
    canonical_gap_id: str | None


@dataclass(frozen=True, kw_only=True)
class VerificationAttempt(BaseRecord):
    RECORD_TYPE: ClassVar[str] = "verification_attempt"

    gap_candidate_id: str
    attempt_number: int
    attempt_status: VerificationAttemptStatus
    from_gap_status: GapStatus
    resulting_gap_status: GapStatus | None
    protocol_id: str
    protocol_version: str
    started_at: str
    completed_at: str | None
    verifier_ids: tuple[str, ...]
    checks: tuple[VerificationCheck, ...]
    supporting_claim_evidence_ids: tuple[str, ...]
    counterclaim_evidence_ids: tuple[str, ...]
    checked_passage_ids: tuple[str, ...]
    counterretrieval_ids: tuple[str, ...]
    retrieval_query_log_ids: tuple[str, ...]
    refuting_evidence_ids: tuple[str, ...]
    resolving_evidence_ids: tuple[str, ...]
    coverage_status: CoverageStatus
    coverage_dimensions: Mapping[str, JsonValue]
    human_review_trigger_ids: tuple[str, ...]
    expert_judgment_ids: tuple[str, ...]
    uncertainty_reasons: tuple[str, ...]
    unresolved_check_ids: tuple[str, ...]
    decision_rationale: str
    resolution_rule_id: str | None
    resolution_as_of: str | None
    canonical_gap_id: str | None
    artifact_type: str | None
    artifact_basis_ids: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class GapScore(BaseRecord):
    RECORD_TYPE: ClassVar[str] = "gap_score"

    gap_candidate_id: str
    score_version: str
    protocol_id: str
    protocol_version: str
    candidate_gap_status: GapStatus
    novelty: ScoreDimension
    importance: ScoreDimension
    feasibility: ScoreDimension
    calibration_status: ScoreCalibrationStatus
    calibration_dataset_id: str | None
    expert_judgment_ids: tuple[str, ...]
    composite: ScoreDimension | None
    composite_rule_id: str | None
    composite_rule_version: str | None


@dataclass(frozen=True, kw_only=True)
class ExpertJudgment(BaseRecord):
    RECORD_TYPE: ClassVar[str] = "expert_judgment"

    protocol_id: str
    protocol_version: str
    task_id: str
    assignment_id: str
    expert_id: str
    gap_candidate_id: str
    gap_list_version_id: str
    condition_id: str
    blinding_state: BlindingState
    presented_artifact_ids: tuple[str, ...]
    mantis_profile_id: str | None
    mantis_input_sha256: str | None
    mantis_receipt_id: str | None
    decision: ExpertDecision
    decision_confidence: float | None
    confidence_scale_id: str | None
    rationale: str
    started_at: str
    submitted_at: str
    duration_seconds: float
    known_evidence_ids: tuple[str, ...]
    canonical_gap_id: str | None
    supersedes_judgment_id: str | None


@dataclass(frozen=True, kw_only=True)
class OutcomeEvent(BaseRecord):
    RECORD_TYPE: ClassVar[str] = "outcome_event"

    protocol_id: str
    protocol_version: str
    gap_candidate_id: str
    expert_judgment_ids: tuple[str, ...]
    research_project_id: str
    event_type: OutcomeEventType
    occurred_on: str
    date_precision: PartialDatePrecision
    outcome_status: OutcomeStatus
    source_reference_ids: tuple[str, ...]
    verification_method: str
    corrects_event_id: str | None
    causal_attribution: CausalAttribution
    notes: str


@dataclass(frozen=True, kw_only=True)
class MantisExportProfile(BaseRecord):
    RECORD_TYPE: ClassVar[str] = "mantis_export_profile"

    profile_version: str
    compatibility_version: str
    record_kind: MantisRecordKind
    source_contract: str
    source_schema_version: str
    eligible_statuses: tuple[str, ...]
    point_id_source_path: str
    fields: tuple[MantisFieldSpec, ...]
    semantic_text: Mapping[str, JsonValue]
    row_sort_paths: tuple[str, ...]
    csv_policy: Mapping[str, JsonValue]
    supported_tool_versions: tuple[str, ...]
    connection_compatibility_verified: bool


@dataclass(frozen=True, kw_only=True)
class MantisInterpretation(BaseRecord):
    RECORD_TYPE: ClassVar[str] = "mantis_interpretation"

    space_id: str
    map_id: str
    map_profile_version: str
    map_input_sha256: str
    selected_point_ids: tuple[str, ...]
    selected_remote_point_ids: tuple[str, ...]
    actor: str
    actor_type: InterpretationActorType
    prompt_or_action: str
    interpreted_at: str
    output_text: str
    interpretation_type: InterpretationType
    is_evidence: bool
    downstream_state: InterpretationDownstreamState
    independent_signal_ids: tuple[str, ...]
    created_candidate_ids: tuple[str, ...]
    publication_receipt_id: str


@dataclass(frozen=True, kw_only=True)
class MantisPublicationReceipt(BaseRecord):
    RECORD_TYPE: ClassVar[str] = "mantis_publication_receipt"

    export_profile_id: str
    profile_version: str
    compatibility_version: str
    source_contract: str
    source_schema_version: str
    source_artifact_reference: ProvenanceEntry
    source_sha256: str
    record_count: int
    tool_name: str
    tool_version: str
    host: str
    operation: MantisOperation
    duplicate_policy: MantisDuplicatePolicy
    attempt_number: int
    retry_of_receipt_id: str | None
    started_at: str
    completed_at: str | None
    published_at: str | None
    publication_status: MantisPublicationStatus
    space_id: str | None
    map_id: str | None
    space_uri: str | None
    map_uri: str | None
    idempotency_key: str
    error: PublicationError | None


RECORD_MODELS: Mapping[str, type[BaseRecord]] = MappingProxyType(
    {
        model.RECORD_TYPE: model
        for model in (
            CorpusSnapshot,
            ScholarlyWork,
            SourceVersion,
            ProviderRecord,
            AccessLocation,
            Document,
            Passage,
            Entity,
            Claim,
            ClaimEvidence,
            Relationship,
            GapSignal,
            GapCandidate,
            VerificationAttempt,
            GapScore,
            ExpertJudgment,
            OutcomeEvent,
            MantisExportProfile,
            MantisInterpretation,
            MantisPublicationReceipt,
        )
    }
)
