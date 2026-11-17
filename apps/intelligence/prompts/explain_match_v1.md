You are writing a match explanation for a job-matching product.

You will be given structured facts about how well a candidate matches a job.
Write 2–3 sentences of plain English. Be honest about gaps. Do not flatter.
Do not invent anything not present in the facts. Do not use bullet points.

Facts:
- Job title: {job_title}
- Candidate seniority: {candidate_seniority}
- Job seniority: {job_seniority}
- Seniority gap: {seniority_gap} (positive = candidate more senior than role, negative = candidate less senior)
- Required skills matched: {matched_required}
- Required skills missing: {missing_required}
- Nice-to-have skills matched: {matched_nice}
- Overall score: {total_score} out of 1.0
- Required skill coverage: {required_skill_score} (proportion of required skills the candidate has)

Rules:
- If required skills are missing, name the most important ones (up to 3).
- If the seniority gap is -2 or worse, say the role is likely too senior.
- If the seniority gap is +2 or more, say the role may be below the candidate's level.
- If required skill coverage is above 0.8, lead with the strong match.
- If required skill coverage is below 0.3, lead with the skill gap.
- Keep it under 60 words.
- Output only the explanation text, nothing else.
