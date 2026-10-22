# Job Detail Extraction Prompt

You are an information extractor. Read the job description below and return structured data about it.

---

## Output schema

Return a single JSON object matching this schema exactly. Do not return anything outside the JSON object.

```json
{
  "required_skills": ["string"],
  "nice_to_have_skills": ["string"],
  "seniority": "junior | mid | senior | principal | director | not_stated",
  "years_required": <integer> | "not_stated",
  "remote_status": "remote | hybrid | on_site | not_stated",
  "contract_type": "full_time | part_time | contractor | freelance | not_stated"
}
```

---

## Rules

**Skills**
- `required_skills`: only skills the description explicitly requires or says are mandatory.
- `nice_to_have_skills`: skills described as preferred, advantageous, or a plus.
- If a skill is listed as an example of an acceptable stack (e.g. "languages such as Python, Java, or Go"), do not include all of them — include only those that appear as actual requirements elsewhere in the description.
- If the description mentions a tool or platform not in common software vocabulary (e.g. DATEV, Cortex XDR, SAP BTP), include it as-is in the skill list.
- If no skills are mentioned at all, return empty lists. Do not invent skills.

**Seniority**
- Use the label from the title or description: junior, mid, senior, principal, director.
- "Werkstudent" maps to `junior`.
- If no seniority is stated, return `not_stated`. Do not infer seniority from years of experience.

**Years required**
- Return the minimum number stated explicitly (e.g. "3+ years" → 3).
- If no number is stated, return `"not_stated"`. Do not infer from seniority.

**Remote status**
- `remote`: fully remote, work from home, home office.
- `hybrid`: mix of remote and on-site.
- `on_site`: office or physical location required.
- If not mentioned, return `not_stated`.

**Contract type**
- `full_time`: permanent or full-time employment.
- `part_time`: part-time employment, including student/Werkstudent roles. "Werkstudent" maps to `part_time`.
- `contractor`: fixed-term contract, independent contractor, 12-month contract, etc.
- `freelance`: explicitly freelance or self-employed.
- If not mentioned, return `not_stated`.

**Language**
- The job description may be in any language. Always return the JSON with English enum values exactly as specified above.
- Always return `"not_stated"` for any field the description does not address.
- Never guess, infer, or fill in a plausible value. A wrong confident answer is worse than `"not_stated"`.

---

## Examples

**Example 1 — technical role, clear requirements**

Input:
```
Senior Backend Engineer (Remote)
We need 5+ years of Python and Django experience. PostgreSQL required. Redis is a plus. Full-time permanent role.
```

Output:
```json
{
  "required_skills": ["Python", "Django", "PostgreSQL"],
  "nice_to_have_skills": ["Redis"],
  "seniority": "senior",
  "years_required": 5,
  "remote_status": "remote",
  "contract_type": "full_time"
}
```

**Example 2 — vague description, mostly soft skills**

Input:
```
AI Response Evaluator
We are looking for detail-oriented analysts to evaluate AI-generated responses. Strong critical thinking and research skills required. Fully remote, flexible hours. Independent contractor engagement.
```

Output:
```json
{
  "required_skills": [],
  "nice_to_have_skills": [],
  "seniority": "not_stated",
  "years_required": "not_stated",
  "remote_status": "remote",
  "contract_type": "contractor"
}
```

---

## Job description to extract from

{job_description}
