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

Use:
- include: the paper is directly about the topic and has enough metadata to justify inclusion.
- exclude: the paper is outside the topic, ambiguous, borderline, missing enough metadata, or would require human review.

Rules:
- Apply the topic scope and candidate-screening policy above.
- Exclude reviews if the topic asks for primary studies only. Otherwise, reviews can be included if they are useful candidates.
- Give one concise reason.
