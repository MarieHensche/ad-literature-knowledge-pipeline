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
- Prefer include when the paper directly studies the topic, studies a meaningful
  subtopic, or tangentially addresses one substantive aspect of the topic.
- Prefer include for borderline candidates when the policy allows human review later.
- Use low confidence and a concise uncertainty reason when metadata is incomplete
  but plausibly relevant.
- Use exclude only when the title, abstract, and source-query context clearly
  point outside the topic or match a hard exclusion.

Use:
- include: the paper is directly about the topic, adjacent to it, or useful for
  later human review.
- exclude: the paper is clearly outside the topic.

Rules:
- Apply the topic scope and candidate-screening policy above.
- Follow the contract's missing-abstract, borderline, human-review, review, and
  tangential-topic policies when present.
- Exclude reviews only if the topic asks for primary studies only or the contract
  makes review exclusion a hard rule. Otherwise, reviews can be included if they
  are useful candidates.
- Give one concise reason.
