"""Loads and renders the extraction prompt template."""
from pathlib import Path

_PROMPT_PATH = Path(__file__).parent / "extract_job_details.md"


def render_extraction_prompt(job_description: str) -> str:
    template = _PROMPT_PATH.read_text()
    return template.replace("{job_description}", job_description)
