You are screening a scholarly paper candidate by field-aware topic fit.

Research topic:
$research_topic_json

Topic structure:
$topic_structure_json

Configured secondary replacement groups:
$secondary_topic_groups_json

Candidate:
$candidate_json

Task:
Classify whether the candidate fits the structured topic using only the fields
allowed by each topic component.

Rules:
- Use the candidate title only for topic components whose `field` is `title`.
- Use the candidate abstract only for topic components whose `field` is
  `abstract`.
- Use either the candidate title or abstract for topic components whose `field`
  is `title_or_abstract`.
- The anchor topic is mandatory. If the allowed field for the anchor topic does
  not contain the anchor topic, return decision `exclude`.
- Broad main-topic terms count as the same topic component, including synonyms,
  abbreviations, subtypes, concrete tools/platforms, and narrower indicators
  listed in `main_topics[].terms`.
- Secondary-topic groups can replace only the non-anchor main topic named by
  that group's parent `main_topic_id`.
- When returning a secondary replacement, use only a configured
  `secondary_topic_id` from "Configured secondary replacement groups".
- The returned secondary terms must come from that configured secondary group.
- Do not let secondary-topic terms replace the anchor topic.
- Do not mix secondary groups across parents. A secondary configured for one
  main-topic component cannot replace a different component.
- Tier 0 means the allowed fields contain the anchor and all main topics.
- Tier 1 means the allowed fields contain the anchor, all but one main topic,
  and a secondary replacement for the missing non-anchor main topic.
- Tier 2 means the allowed fields contain the anchor, all but two main topics,
  and secondary replacements for the missing non-anchor main topics.
- Continue this tier logic generically for more missing main topics.
- Return `include` only when the anchor is present and every missing non-anchor
  main topic has a matched secondary replacement.
- Return `exclude` when the anchor is missing or when a missing non-anchor main
  topic has no secondary replacement.
- Give one concise reason.
