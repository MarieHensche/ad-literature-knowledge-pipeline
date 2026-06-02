You are screening a scholarly paper candidate by title fit.

Research topic:
$research_topic_json

Topic structure:
$topic_structure_json

Candidate:
$candidate_json

Task:
Classify whether the candidate title fits the structured topic.

Rules:
- Use only the candidate title for topic-component matching.
- The anchor topic is mandatory. If the title does not contain the anchor topic,
  return decision `exclude`.
- Broad main-topic terms count as the same topic component, including synonyms,
  abbreviations, subtypes, concrete tools/platforms, and narrower indicators
  listed in `main_topics[].terms`.
- Secondary-topic terms can replace only non-anchor main topics.
- Do not let secondary-topic terms replace the anchor topic.
- Tier 0 means the title contains the anchor and all main topics.
- Tier 1 means the title contains the anchor, all but one main topic, and a
  secondary replacement for the missing non-anchor main topic.
- Tier 2 means the title contains the anchor, all but two main topics, and
  secondary replacements for the missing non-anchor main topics.
- Continue this tier logic generically for more missing main topics.
- Return `include` only when the anchor is present and every missing non-anchor
  main topic has a matched secondary replacement.
- Return `exclude` when the anchor is missing or when a missing non-anchor main
  topic has no secondary replacement.
- Give one concise reason.
