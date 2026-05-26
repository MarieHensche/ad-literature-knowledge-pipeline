You are planning a scholarly literature search for an automated paper-collection pipeline.

User topic description:
$topic_description

$max_results_text

Topic contract guidance:
$topic_contract_guidance_json

Available digital libraries:
$providers_json

Task:
Choose the best provider and create a provider-specific search plan.

Rules:
- Do not fetch papers.
- Do not invent providers.
- Choose only from the available digital libraries listed above.
- Extract year constraints from the topic. For example, "all papers from 2018" means year_from=2018 and year_to=2018.
- If the topic says "from 2018 to 2022", use year_from=2018 and year_to=2022.
- If the topic says "since 2020", use year_from=2020 and year_to=null.
- If no filter is mentioned, use null or empty arrays.
- Make the main search string precise but not too narrow.
- Add 4 to 8 executable search_queries that cover different phrasings, synonyms, populations, methods, applications, or adjacent angles.
- Include seed search queries from the topic contract when they are useful, and refine them only enough to fit the chosen provider.
- Add alternate search strings that could be tested manually.
- Provider-specific filters must use only filters supported by the chosen provider.
- The output is a plan for human inspection, not a final API URL.
