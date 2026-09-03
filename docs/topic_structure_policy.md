# Topic-Structure Policy

Topic-contract generation and refinement use one versioned portable policy:

```text
configs/policies/topic_structure_v1.yaml
```

The policy owns research vocabulary that was previously duplicated across
Python normalization, validators, retry prompts, and prompt templates. Python
now implements generic operations; the YAML decides which concept profiles,
surface forms, exclusions, completions, anchor preferences, and fallback
secondary groups apply.

## Identity And Contract Reference

The loader in `ad_lit_pipeline/topics/policy.py` validates every policy field,
rejects unknown keys and broken group references, and calculates a deterministic
SHA-256 hash from the semantic YAML object. A generated or refined topic
contract records:

```yaml
topic_policy:
  policy_id: topic_structure
  policy_version: 1.0.0
  policy_sha256: <64-character hash>
  profile_ids:
    - alzheimer_disease
```

The step result repeats this object in metadata. Run provenance therefore
captures the policy id, version, hash, and selected profiles without requiring
the model to emit policy metadata. Loading a referenced contract fails if the
checked-in policy identity has drifted.

Existing hand-written contracts without `topic_policy` remain valid for
backward compatibility. New generated and refined contracts always receive the
reference.

## Profile Selection

When a contract already contains `topic_policy.profile_ids`, that list is an
explicit override, including an empty list. Otherwise profiles are selected
from the research question and topic-structure vocabulary. Selection is
deterministic and preserves policy order.

The initial policy contains two behavior-preserving profiles:

- `alzheimer_disease` owns disease-family names, excluded pathology/process
  terms, disease-over-method anchor precedence, and adjacent disease fallbacks.
- `computational_methods` owns method subtypes, completion terms, bare-object
  exclusions, and the adjacent experimental-method fallback.

The same selected profiles supply LLM prompt guidance and deterministic
normalization/validation. Prompt templates contain only portable structural
rules; they do not embed Alzheimer examples or vocabulary.

## Adding A Domain

Adding a concept profile does not require Python changes:

1. Add any reusable adjacent group to `secondary_groups`.
2. Add a profile with a unique id, kind, signal terms, family terms, excluded
   terms, completion terms, fallback group ids, anchor precedence, and prompt
   guidance.
3. Bump `policy_version` when semantic behavior changes.
4. Add a configuration-driven regression test representing the new domain.
5. Regenerate affected topic contracts so they record the new version/hash.

A transfer is considered unsuccessful if a new research domain requires a
named Python branch or a domain example embedded in a Markdown prompt.

## Compatibility Boundary

The migration preserves the existing Alzheimer normalization semantics:

- configured family variants remain in the parent topic;
- configured pathology/process terms are removed from disease-family terms;
- configured computational subtypes move from secondary groups into the method
  parent;
- configured fallback secondary groups are deterministic;
- the configured disease topic replaces a method anchor when required.

The policy does not claim that its vocabulary is complete, scientifically
universal, or correct for every research question. Users remain responsible for
reviewing generated contracts and can select profiles explicitly.

Focused verification:

```bash
python -m pytest -q \
  tests/test_topic_policy.py \
  tests/test_topic_contract.py \
  tests/test_llm_steps.py \
  tests/test_prompts.py \
  tests/test_non_llm_steps.py
```

The tests include a synthetic migraine profile loaded from a temporary policy.
It exercises completion, exclusion, fallback, anchor precedence, reference
hashing, and contract validation without changing pipeline Python.
