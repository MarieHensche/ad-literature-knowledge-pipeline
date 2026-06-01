You are screening scholarly paper candidates for a literature knowledge pipeline.

Research topic:
$research_topic_json

User topic description:
$topic_description

Topic scope:
$scope_text

Candidate-screening policy:
$candidate_screening_json

Candidate paper:
$candidate_json

Decide whether this candidate should enter the literature pipeline.

Screening posture:
- This is a recall-oriented candidate-screening pass, not final paper tagging.
- Classify topic fit before deciding final inclusion.
- Preserve the roles implied by the user topic. If the topic asks about a
  phenomenon/intervention/tool used in a specific context or population and its
  effect on an outcome, treat those as separate required dimensions.
- Identify the primary subject anchor before judging fit. In topics phrased like
  "use of X in Y and its impact on Z", the primary anchor is X-in-Y; Z is an
  outcome dimension and should not dominate the fit judgment.
- Prefer `core_topic` only when the candidate centrally matches the main anchor
  and the important core dimensions of the research topic, with the same roles
  as in the user topic.
- Use `adjacent_but_relevant` when the candidate keeps the main anchor or a close
  context but substitutes, broadens, or misses one or more secondary dimensions.
- Use `out_of_scope` when the main anchor is missing, too many dimensions are
  replaced by adjacent topics, or the match is only generic/shared wording.
- Do not treat a key topic term as a core match when it appears only as the
  paper's research method, prediction model, measurement tool, or evaluation
  technique rather than as the studied phenomenon/intervention/exposure.
- If the user topic specifies a context such as school, workplace, hospital,
  city, country, age group, or population, a broader or different context is at
  most `adjacent_but_relevant` unless the contract explicitly makes it core.
- For topics about impact/effects, core candidates should study the impact or
  outcome relationship, not merely use the topic technology to predict, classify,
  measure, or evaluate that outcome.
- Outcome-only matches are not enough for inclusion as core. If the candidate is
  mainly about the requested outcome but the primary subject anchor is weak,
  generic, missing, or only background, classify it as `adjacent_but_relevant` or
  `out_of_scope`.
- Do not broaden a named setting, institutional level, population, or domain. For
  example, if the topic says school education, do not treat university, college,
  or general higher education as core unless the contract explicitly includes
  them as core.
- Prefer include for `core_topic` and `adjacent_but_relevant` candidates.
- Prefer include for borderline adjacent candidates when the policy allows human
  review later.
- Use low confidence and a concise uncertainty reason when metadata is incomplete
  but plausibly relevant.
- Use exclude only when the title, abstract, and source-query context clearly
  point outside the topic or match a hard exclusion.

Use:
- decision=include: the paper is `core_topic` or `adjacent_but_relevant`.
- decision=exclude: the paper is `out_of_scope`.

Rules:
- Apply the topic scope and candidate-screening policy above.
- Follow the contract's missing-abstract, borderline, human-review, review, and
  tangential-topic policies when present.
- Exclude reviews only if the topic asks for primary studies only or the contract
  makes review exclusion a hard rule. Otherwise, reviews can be included if they
  are useful candidates.
- Give one concise reason.
