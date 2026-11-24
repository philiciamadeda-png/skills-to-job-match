I am building the interface for a Django 6 job-market app: a dashboard, a job list, the CV matching flow, and auth. Show me the views, URLs and templates.

**What already exists**

Aggregation tables in `apps/analytics`, rebuilt by a Celery task after each transform and extraction run. The dashboard must read only from these, never from `Job` or `JobSkill`:

- `DailySkillCount(day, skill FK, job_count, required_count)`, unique on (day, skill)
- `DailySeniorityCount(day, seniority, job_count)`: junior, mid, senior, principal, director, unknown
- `DailyWorkModeCount(day, work_mode, job_count)`: remote, hybrid, on_site, unknown
- `DailySourceCount(day, source, job_count)`: remotive, arbeitnow
- `HeadlineTotals`: a single row with jobs_tracked, companies, distinct_skills, refreshed_at

`day` is the posting date. Duplicate jobs are excluded. `apps/analytics/selectors.py` already has `headline()`, `top_skills(days, limit)`, `skill_trend(skill_ids, days)`, `jobs_by_seniority()`, `jobs_by_work_mode()` and `new_jobs_per_day(days)`.

Raw models: `Job` (title, company FK, location FK, source, published_date, seniority, extracted_remote_status, `canonical` FK set on duplicates) with skills through `JobSkill` (is_required). CV matching exists in `apps/accounts`: `CV`, `CVProfile`, `match_profile(profile, remote_only, countries, limit)` returning `MatchResult`s with total_score, per-component scores, matched_required, missing_required, matched_nice and seniority_gap. Plain upload → matches → match-detail views exist.

**The dashboard answers four questions, one chart each, plus headline numbers:**

1. Which skills are employers asking for most? A horizontal bar chart of the top 10 skills. Axes: skill, number of jobs.
2. Is demand for those skills rising or falling? A line chart of weekly job counts for the top 5 skills over the last 12 weeks of data. Axes: week, jobs posted.
3. What level are employers hiring at? A bar chart, junior → director, then unknown. Axes: seniority, jobs.
4. How many roles can be done remotely? A bar chart: remote, hybrid, on-site, not stated. Axes: work mode, jobs.

Headline numbers: jobs tracked, companies hiring, distinct skills, and new jobs in the last 7 days. No pie charts and no fifth chart.

**Structure**
- One `templates/base.html` with the shared layout and navigation. Every page extends it.
- Tailwind v4, built with the standalone CLI (no Node), and the compiled CSS committed.
- Exactly three colours: one primary for actions, links and chart bars; a neutral slate for text, borders and backgrounds; one accent used only for gaps (missing skills, levels above the candidate). One spacing scale throughout.
- HTMX and Chart.js vendored into `static/`, no CDN.
- Partials (`_*.html`) for every fragment HTMX swaps. A view returns the partial when the request has the `HX-Request` header, and the full page otherwise, so every URL still works without JavaScript.

**Pages**
- **Dashboard (`/`, public):** the headline numbers and the four charts. Chart data goes in through `json_script`.
- **Job list (`/jobs/`, public):** search over title, company and skill. Filters for seniority, remote/hybrid/on-site, and source. 20 per page. Filtering and paging swap only the results partial and push the URL, so a filtered view can be bookmarked. Duplicates hidden. It must not run one query per job: use `select_related` for company and location and `prefetch_related` for skills.
- **Match flow (login required):** upload a CV, then the ranked results with matched skills, missing skills and seniority fit. Add a "gaps" panel listing the skills missing most often across the top matches. The remote/countries filters swap the results via HTMX. The match detail page shows the explanation and the score breakdown.
- **Auth:** sign up, log in and log out (POST), using Django's auth views. A profile page shows the person's latest CV with its top 5 matches and gaps, and their earlier CVs.

**Tests**
pytest tests for the dashboard (it never queries `Job`, and handles the state before the first refresh), the job list (each filter, search, pagination, partial vs full page, query count doesn't grow with rows), sign-up, login and the profile page.
