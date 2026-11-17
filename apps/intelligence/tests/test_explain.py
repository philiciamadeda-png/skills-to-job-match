"""
Tests for the match explanation service.

The LLM is always faked — no network calls.
"""
from types import SimpleNamespace

import pytest

from apps.intelligence.explain import (
    build_facts, cache_key, explain_match, explain_match_with_source, fallback_explanation,
    render_prompt, validate_explanation,
)
from apps.intelligence.llm.client import LLMClient, LLMResponse
from apps.intelligence.matching import MatchResult


def _result(**kw):
    job = SimpleNamespace(pk=1, title=kw.pop('title', 'Backend Engineer'),
                          seniority=kw.pop('job_seniority', 'senior'),
                          description='SECRET JOB DESCRIPTION')
    defaults = dict(
        job=job, total_score=0.7, required_skill_score=0.75, semantic_score=0.6,
        seniority_score=1.0, nice_to_have_score=0.0, recency_score=0.5,
        matched_required=['Django', 'PostgreSQL', 'Python'], missing_required=['Kubernetes'],
        matched_nice=[], seniority_gap=0, profile_seniority='senior',
    )
    defaults.update(kw)
    return MatchResult(**defaults)


def _client(content=None, exc=None):
    captured = {}

    def call(model, messages, timeout):
        captured['prompt'] = messages[0]['content']
        if exc:
            raise exc
        return LLMResponse(content=content, tokens_in=0, tokens_out=0, cost_usd=0.0, model='test')

    return LLMClient(_call_fn=call), captured


GOOD = ('You have three of the four required skills for this Backend Engineer role, including '
        'Python and Django, and the level matches yours. The gap is Kubernetes, which is required.')


# ── Facts ─────────────────────────────────────────────────────────────────

def test_candidate_seniority_comes_from_profile_not_job():
    facts = build_facts(_result(profile_seniority='junior', job_seniority='principal', seniority_gap=-3))
    assert facts['candidate_seniority'] == 'junior'
    assert facts['job_seniority'] == 'principal'
    assert facts['seniority_note'] == 'the role is 3 levels above your level'


@pytest.mark.parametrize('cand,job,gap,note', [
    ('senior', 'senior', 0, 'same level'),
    ('senior', 'mid', 1, 'the role is 1 level below your level'),
    ('mid', 'senior', -1, 'the role is 1 level above your level'),
    ('', 'senior', 0, 'unknown'),
    ('not_stated', 'senior', 0, 'unknown'),
])
def test_seniority_note(cand, job, gap, note):
    assert build_facts(_result(profile_seniority=cand, job_seniority=job, seniority_gap=gap))['seniority_note'] == note


def test_prompt_contains_facts_but_no_raw_text():
    r = _result(missing_required=['Kubernetes', 'Terraform', 'Go', 'Rust', 'AWS'])
    prompt = render_prompt(build_facts(r))
    assert 'Kubernetes' in prompt
    assert '(+2 more)' in prompt                  # capped at 3 names, total still reported
    assert '(5 of 8)' in prompt
    assert 'SECRET JOB DESCRIPTION' not in prompt


# ── Validation ────────────────────────────────────────────────────────────

def test_valid_output_returned():
    client, _ = _client(GOOD)
    assert explain_match(_result(), client=client) == GOOD


@pytest.mark.parametrize('bad', [
    'One sentence only, mentioning Kubernetes.',
    'Here is the explanation: You have most skills. Kubernetes is missing.',
    'You have most of the skills. The level matches. You are a strong candidate. Apply today.',
    'You have most of the required skills. The level matches yours.',           # silent about Kubernetes
    ' '.join(['word'] * 80) + '. Kubernetes is missing.',
    'This is a strong match for you. Only Kubernetes is missing.',              # flattery
    'Your score is 0.70 for this role. Only Kubernetes is missing.',            # quotes the score
    'You have Python and Xero. The one gap is Kubernetes.',                    # copied from prompt examples
    'Start with the skills you have. You have Python. Kubernetes is missing.', # echoes the instructions
    'You have Python and another skill that is not listed. Kubernetes is missing.',  # invents a skill
    'You are a good match for this role. Only Kubernetes is missing.',         # flattery
])
def test_invalid_output_falls_back(bad):
    client, _ = _client(bad)
    out = explain_match(_result(), client=client)
    assert out == fallback_explanation(build_facts(_result()))


def test_output_silent_about_level_gap_falls_back():
    r = _result(profile_seniority='senior', job_seniority='junior', seniority_gap=2, missing_required=[])
    client, _ = _client('You have all three required skills. Django and Python are both covered.')
    assert explain_match(r, client=client) == fallback_explanation(build_facts(r))


def test_level_gap_stated_backwards_falls_back():
    r = _result(profile_seniority='junior', job_seniority='principal', seniority_gap=-3,
                matched_required=['SQL'], missing_required=['Spark'])
    facts = build_facts(r)
    assert validate_explanation('You are three levels above this role. You lack Spark.', facts) is None
    ok = 'This role is three levels above your level. You have SQL but lack Spark.'
    assert validate_explanation(ok, facts) == ok


@pytest.mark.parametrize('kw,lead', [
    ({}, 'the skills you have'),
    ({'matched_required': ['SQL'], 'missing_required': ['Spark', 'Airflow']}, 'the missing skills'),
    ({'profile_seniority': 'junior', 'job_seniority': 'principal', 'seniority_gap': -3}, 'the level difference'),
])
def test_lead(kw, lead):
    assert build_facts(_result(**kw))['lead'] == lead


def test_nothing_missing_framed_as_gap_falls_back():
    r = _result(missing_required=[])
    assert 'every required skill' in render_prompt(build_facts(r))
    bad = 'You have all four required skills. Unfortunately, you are missing none of them.'
    assert validate_explanation(bad, build_facts(r)) is None
    bad2 = 'You have every required skill for this role. The only required skill you are missing is none.'
    assert validate_explanation(bad2, build_facts(r)) is None


def test_llm_error_falls_back_or_empty():
    client, _ = _client(exc=RuntimeError('ollama down'))
    assert 'Kubernetes' in explain_match(_result(), client=client)
    client, _ = _client(exc=RuntimeError('ollama down'))
    assert explain_match(_result(), client=client, fallback=False) == ''


def test_source_reported():
    from django.core.cache import cache

    client, _ = _client(GOOD)
    assert explain_match_with_source(_result(), client)[1] == 'llm'
    cache.clear()
    client, _ = _client('One sentence, Kubernetes.')
    assert explain_match_with_source(_result(), client)[1] == 'template:rejected'
    cache.clear()
    client, _ = _client(exc=RuntimeError('down'))
    assert explain_match_with_source(_result(), client)[1] == 'template:error'


def test_quotes_and_whitespace_stripped():
    assert validate_explanation(f'  "{GOOD}"\n', build_facts(_result())) == GOOD


# ── Fallback ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize('kw', [
    {},
    {'missing_required': []},
    {'matched_required': [], 'missing_required': ['Go', 'Rust']},
    {'matched_required': [], 'missing_required': [], 'profile_seniority': ''},
    {'profile_seniority': 'junior', 'job_seniority': 'principal', 'seniority_gap': -3},
])
def test_fallback_is_two_or_three_sentences_and_names_gaps(kw):
    facts = build_facts(_result(**kw))
    text = fallback_explanation(facts)
    assert validate_explanation(text, facts) == text


# ── Cache ─────────────────────────────────────────────────────────────────

def _counting_client(content=None, exc=None):
    calls = []

    def call(model, messages, timeout):
        calls.append(messages[0]['content'])
        if exc:
            raise exc
        return LLMResponse(content=content, tokens_in=0, tokens_out=0, cost_usd=0.0, model='test')

    return LLMClient(_call_fn=call), calls


def test_reopening_a_match_does_not_call_the_model_again():
    client, calls = _counting_client(GOOD)
    first = explain_match_with_source(_result(), client=client)
    second = explain_match_with_source(_result(), client=client)
    assert first == second == (GOOD, 'llm')
    assert len(calls) == 1


def test_changed_facts_generate_a_new_explanation():
    client, calls = _counting_client(GOOD)
    explain_match_with_source(_result(), client=client)
    explain_match_with_source(_result(missing_required=['Kubernetes', 'Terraform']), client=client)
    assert len(calls) == 2


def test_scores_alone_do_not_invalidate_the_cache():
    # The explanation never quotes scores, so a score change must not cost a new call
    client, calls = _counting_client(GOOD)
    explain_match_with_source(_result(total_score=0.7), client=client)
    explain_match_with_source(_result(total_score=0.65, semantic_score=0.5), client=client)
    assert len(calls) == 1


def test_rejected_output_cached_as_template():
    client, calls = _counting_client('One sentence only, mentioning Kubernetes.')
    expected = (fallback_explanation(build_facts(_result())), 'template:rejected')
    assert explain_match_with_source(_result(), client=client) == expected
    assert explain_match_with_source(_result(), client=client) == expected
    assert len(calls) == 1


def test_llm_error_not_cached_so_next_view_retries():
    failing, _ = _counting_client(exc=RuntimeError('ollama down'))
    assert explain_match_with_source(_result(), client=failing)[1] == 'template:error'
    working, calls = _counting_client(GOOD)
    assert explain_match_with_source(_result(), client=working) == (GOOD, 'llm')
    assert len(calls) == 1


def test_cache_key_depends_on_model_and_prompt():
    prompt = render_prompt(build_facts(_result()))
    assert cache_key('llama3.2', prompt) == cache_key('llama3.2', prompt)
    assert cache_key('llama3.2', prompt) != cache_key('qwen2.5', prompt)
    assert cache_key('llama3.2', prompt) != cache_key('llama3.2', prompt + ' ')


def test_cache_outage_still_returns_an_explanation(monkeypatch):
    from django.core.cache import cache

    def down(*a, **kw):
        raise ConnectionError('redis down')

    monkeypatch.setattr(cache, 'get', down)
    monkeypatch.setattr(cache, 'set', down)
    client, calls = _counting_client(GOOD)
    assert explain_match_with_source(_result(), client=client) == (GOOD, 'llm')
    assert len(calls) == 1
