# CV Extraction Prompt

You are an information extractor. Read the CV text below and return structured data about the candidate.

---

## Output schema

Return a single JSON object matching this schema exactly. Do not return anything outside the JSON object.

```json
{
  "skills": ["string"],
  "seniority": "junior | mid | senior | principal | director | not_stated",
  "years_experience": <integer> | "not_stated"
}
```

---

## Rules

**skills**
- Include every technical skill, tool, framework, language, platform, or methodology mentioned anywhere in the CV.
- Use the name exactly as written in the CV — do not normalise, expand, or abbreviate (e.g. keep "Postgres" as "Postgres", not "PostgreSQL").
- Include soft skills only if they are domain-specific (e.g. "Agile", "Scrum") — exclude generic ones ("communication", "teamwork").
- Do not invent skills not present in the text.

**seniority**
- Infer from job titles, years of experience, and scope of responsibilities.
- Use the most senior level that is clearly supported by the text.
- If the CV contains only one or two years of experience or entry-level titles, use "junior".
- If the text does not support any inference, use "not_stated".

**years_experience**
- Count total years of professional experience, not years in a single role.
- If the CV lists dates, calculate from the earliest start date to the present.
- If no dates are present but the number is stated explicitly, use that.
- If it cannot be determined, use "not_stated".
- Maximum value: 50. If your calculation exceeds this, return "not_stated".

---

## CV text

{cv_text}
