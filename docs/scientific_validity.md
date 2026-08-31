# Scientific Validity Policy

The pipeline uses a versioned, cross-domain scientific-validity policy before
it treats any generated research-gap statement as more than a hypothesis. The
machine-readable source of truth is:

```text
configs/policies/scientific_validity_v1.yaml
```

The loader and semantic checks live in `ad_lit_pipeline/validity/`. This policy
defines vocabulary and gates; it does not yet change the legacy extraction or
Mantis CSV contracts. Durable gap and verification contracts now live in
`ad_lit_pipeline/records/`; see `docs/record_contracts_v1.md`. They are not yet
wired into production pipeline steps.

## Core Principle

A missing record, graph edge, search result, or map region is not proof that no
scientific evidence exists. Every absence statement is limited to a named
corpus snapshot, a declared scope, an inclusive `as_of` cutoff, searched
sources, and an assessed coverage status.

The preferred wording is:

> No eligible records were retrieved for the declared question within the
> named corpus snapshot and `as_of` cutoff; coverage and access limitations
> remain visible.

Unqualified phrases such as `not studied`, `never been investigated`,
`no studies have`, `no research exists`, and `no evidence exists` are rejected
by the policy. `Proven gap` and `scientifically validated gap` are always
prohibited because corpus search cannot establish either claim. Phrase checks
are a safety net, not a semantic proof: future structured gap records must carry
the required qualifiers regardless of their prose.

## Operational Terms

| Term | Meaning |
| --- | --- |
| Gap candidate | A versioned, scoped hypothesis produced from recorded deterministic signals within one corpus snapshot and `as_of` cutoff. It is not evidence of global absence. |
| Verified gap | Machine status `verified_open`: required support, counterevidence, counter-retrieval, terminology/indexing, adjacent-literature, duplicate, and coverage checks passed, and no resolving evidence was found within the qualified boundary. |
| Refuted gap | Evidence already available by the candidate's original `as_of` invalidates the operational gap or its generating signal. It does not refute the underlying scientific hypothesis. |
| Resolved gap | Later eligible evidence satisfies the declared resolution rule for a gap that was previously `verified_open`. It does not imply final scientific truth or permanent resolution. |
| Corpus-sparse | The eligible-study count or density for a declared query or graph cell is below a predeclared threshold in one snapshot. The unit, observed count, threshold, coverage, scope, and cutoff must remain visible. |
| `as_of` | The inclusive public-availability cutoff for the exact source versions considered. It is distinct from retrieval time, recording time, study completion, and run time. |
| Supported claim | Exact cited passages entail all material claim elements in their declared context. This does not establish replication or final truth. |
| Contradicted claim | Comparable verified evidence entails a materially incompatible assertion. Opposite directions in non-comparable settings are not contradictions. |
| Insufficient claim evidence | Accessible evidence establishes neither support nor contradiction. This is not proof that evidence does not exist. |
| Uncertain claim | A support decision cannot safely be reached because access, comparability, ambiguity, or verifier disagreement remains unresolved. This differs from `insufficient`, where the completed evidence check establishes neither support nor contradiction. |
| Uncertain gap | Candidate verification cannot conclude because one or more access, coverage, comparability, terminology, evidence, or automation limitations remain. The context, subject ID, reasons, and unresolved checks are required. |

## Claim Outcomes And Gap States Are Separate

Claim verification has four mutually exclusive outcomes:

- `supported`
- `contradicted`
- `insufficient`
- `uncertain`

Mandatory human review is orthogonal to those outcomes. For example, a claim
can be passage-supported and still require review because it is high stakes.

A gap candidate has its own lifecycle:

```text
proposed
  -> verification_in_progress
       -> verified_open
       -> refuted
       -> resolved
       -> uncertain
       -> terminology_artifact
       -> duplicate

uncertain / verified_open / refuted / resolved /
terminology_artifact / duplicate
  -> verification_in_progress in a new candidate version
```

All outcome states are terminal for the current candidate version. Any outcome,
including a mistaken terminology-artifact or duplicate decision, can seed a
correction or reassessment only in a new candidate version with recorded
lineage. There is no direct `proposed -> verified_open` transition. Reassessment
cannot edit a prior decision in place. Expert acceptance or rejection is a
separate human judgment record, not a gap state.

Promotion to `verified_open` requires all checks declared by the policy,
including passage-level support verification, verified counterevidence,
counter-retrieval, synonym and indexing checks, adjacent-literature and
duplicate checks, adequate-for-rule coverage, and recorded uncertainty.
`adequate_for_rule` never means that a corpus is globally complete.

## Assessment Dimensions

Every dimension has an explicit kind, and all must remain separate:

- screening confidence;
- extraction confidence;
- verification confidence;
- reporting quality;
- study quality and risk of bias;
- explained evidence-quality synthesis with its components retained;
- scientific confidence;
- corpus coverage;
- structured gap uncertainty;
- novelty, importance, and feasibility as three separate ranking dimensions.

In particular, extraction or model confidence cannot determine evidence
quality, reporting quality, study quality, scientific confidence, novelty,
importance, or feasibility. Reporting quality cannot stand in for study
quality, or vice versa. Coverage and uncertainty are not confidence scores, and
the ranking dimensions are not model confidence. The legacy
`evidence_strength` field is not scientific confidence. Mantis map proximity is
not scientific support.

## Mandatory Human Review

Human review is required for verifier disagreement, material numeric or design
mismatches, ambiguous comparability, terminology or entity ambiguity,
inaccessible central evidence, inadequate coverage when promotion is requested,
high-stakes clinical or policy claims, reopening terminal decisions, conflicting
expert judgments, and Mantis/LLM hypotheses that lack an independent signal.

Review cannot waive missing stable IDs, missing provenance, invalid schemas,
orphan references, missing snapshot/`as_of` data, or a missing independent
deterministic signal. Those are validation blockers that must be corrected.

## Mantis Boundary

Mantis is a required final exploration and interpretation workspace, but its
map geometry, clustering, and generated interpretations are not scientific
evidence. Raw Mantis output creates a `MantisInterpretation` pre-candidate, not a
gap candidate and not a lifecycle status. It must retain the source space, map,
export-profile version, immutable map-input hash, selected stable point IDs,
actor, action or prompt, timestamp, and output text. Only after an independent
deterministic signal exists may the system create a `proposed` gap candidate;
the normal counter-retrieval and verification gates must then run.

## Python API

Load the checked-in policy with:

```python
from ad_lit_pipeline.validity import load_scientific_validity_policy

policy = load_scientific_validity_policy()
```

The package also exposes lifecycle validation, absence-language validation, and
mandatory-review trigger normalization. Loading fails with a contextual
`ValidationError` when the YAML is structurally valid but violates a scientific
invariant. `scientific_validity_policy_to_dict()` produces a normalized,
parseable mapping for deterministic serialization and policy hashing; callers
should use that API instead of applying `dataclasses.asdict()` to the immutable
model.

The transition helper performs declaration-level validation: it checks that an
edge exists, all declared check IDs were supplied, and reassessment asserts a
new candidate version. The Step 1.3 record layer adds exact local schemas,
typed-reference syntax, deterministic ID recomputation, within-record
chronology, and conditional evidence/state checks. Neither layer proves that
referenced checks are truthful or that referenced records and files exist.
Cross-artifact lineage, ownership, evidence chronology, snapshot membership,
resolution cutoffs, and artifact hashes are Step 1.4 responsibilities. Passing
the helper or one record's validator alone is never scientific verification.

Policy v1 also fixes the safe rule for unknown availability: exclude that source
version from temporal conclusions and mark the result uncertain. Step 1.3
validates exact date syntax, granularity, UTC handling, and record-local temporal
ordering. Version lineage and comparisons across records, such as
`resolution_as_of > prior_as_of`, remain Step 1.4 work.
