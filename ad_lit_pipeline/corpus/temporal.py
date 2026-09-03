from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date

from ad_lit_pipeline.records.models import (
    AvailabilityStatus,
    PartialDate,
    PartialDateCertainty,
    PartialDatePrecision,
    TemporalEligibility,
)


@dataclass(frozen=True)
class TemporalEligibilityAssessment:
    """Cutoff decision from defensible availability dates only."""

    availability_status: AvailabilityStatus
    temporal_eligibility: TemporalEligibility
    earliest_possible: str | None
    latest_possible: str | None
    review_required: bool
    reasons: tuple[str, ...]


def _date_bounds(value: PartialDate) -> tuple[date, date] | None:
    if value.value is None or value.precision is PartialDatePrecision.UNKNOWN:
        return None
    if value.precision is PartialDatePrecision.DAY:
        parsed = date.fromisoformat(value.value)
        return parsed, parsed
    if value.precision is PartialDatePrecision.MONTH:
        year_text, month_text = value.value.split("-", 1)
        year = int(year_text)
        month = int(month_text)
        last_day = calendar.monthrange(year, month)[1]
        return date(year, month, 1), date(year, month, last_day)
    if value.precision is PartialDatePrecision.YEAR:
        year = int(value.value)
        return date(year, 1, 1), date(year, 12, 31)
    return None


def assess_temporal_eligibility(
    availability_earliest: PartialDate | None,
    availability_latest: PartialDate | None,
    *,
    as_of: str,
) -> TemporalEligibilityAssessment:
    """Apply an inclusive cutoff without substituting publication date."""
    try:
        cutoff = date.fromisoformat(as_of)
    except ValueError as exc:
        raise ValueError("as_of must be a valid YYYY-MM-DD date.") from exc

    dates = tuple(
        item
        for item in (availability_earliest, availability_latest)
        if item is not None
    )
    if not dates:
        return TemporalEligibilityAssessment(
            availability_status=AvailabilityStatus.UNKNOWN,
            temporal_eligibility=TemporalEligibility.UNKNOWN,
            earliest_possible=None,
            latest_possible=None,
            review_required=True,
            reasons=("public_availability_date_missing",),
        )

    uncertain = [
        item.certainty
        for item in dates
        if item.certainty
        in {PartialDateCertainty.ESTIMATED, PartialDateCertainty.UNKNOWN}
    ]
    if uncertain:
        return TemporalEligibilityAssessment(
            availability_status=(
                AvailabilityStatus.ESTIMATED
                if PartialDateCertainty.ESTIMATED in uncertain
                else AvailabilityStatus.UNKNOWN
            ),
            temporal_eligibility=TemporalEligibility.UNKNOWN,
            earliest_possible=None,
            latest_possible=None,
            review_required=True,
            reasons=("public_availability_date_not_defensible",),
        )

    earliest_bounds = (
        _date_bounds(availability_earliest)
        if availability_earliest is not None
        else None
    )
    latest_bounds = (
        _date_bounds(availability_latest)
        if availability_latest is not None
        else None
    )
    if earliest_bounds is None and latest_bounds is None:
        return TemporalEligibilityAssessment(
            availability_status=AvailabilityStatus.UNKNOWN,
            temporal_eligibility=TemporalEligibility.UNKNOWN,
            earliest_possible=None,
            latest_possible=None,
            review_required=True,
            reasons=("public_availability_date_unparseable",),
        )

    lower = (earliest_bounds or latest_bounds)[0]
    upper = (latest_bounds or earliest_bounds)[1]
    if lower > upper:
        return TemporalEligibilityAssessment(
            availability_status=AvailabilityStatus.UNKNOWN,
            temporal_eligibility=TemporalEligibility.UNKNOWN,
            earliest_possible=lower.isoformat(),
            latest_possible=upper.isoformat(),
            review_required=True,
            reasons=("public_availability_bounds_conflict",),
        )

    bounded = lower != upper or any(
        item.precision is not PartialDatePrecision.DAY
        or item.certainty is PartialDateCertainty.BOUNDED
        for item in dates
    )
    availability_status = (
        AvailabilityStatus.BOUNDED if bounded else AvailabilityStatus.KNOWN
    )
    if upper <= cutoff:
        eligibility = TemporalEligibility.ELIGIBLE
        review_required = False
        reasons = ("latest_defensible_availability_on_or_before_cutoff",)
    elif lower > cutoff:
        eligibility = TemporalEligibility.AFTER_CUTOFF
        review_required = False
        reasons = ("earliest_defensible_availability_after_cutoff",)
    else:
        eligibility = TemporalEligibility.UNKNOWN
        review_required = True
        reasons = ("availability_bounds_cross_cutoff",)

    return TemporalEligibilityAssessment(
        availability_status=availability_status,
        temporal_eligibility=eligibility,
        earliest_possible=lower.isoformat(),
        latest_possible=upper.isoformat(),
        review_required=review_required,
        reasons=reasons,
    )
