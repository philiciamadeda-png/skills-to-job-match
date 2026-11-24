import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.accounts.models import CV, CVProfile
from apps.intelligence.models import Job, JobSkill, Skill

pytestmark = pytest.mark.django_db

User = get_user_model()
VECTOR = [0.1] * 768
PASSWORD = 'a-long-Passw0rd!'


@pytest.fixture
def user():
    return User.objects.create_user(username='alice', password=PASSWORD)


def _skill(name):
    return Skill.objects.get_or_create(normalised_name=name.lower(), defaults={'name': name})[0]


def _job(job_factory, title, skills):
    job = job_factory(title=title, extraction_status=Job.ExtractionStatus.SUCCESS, seniority='senior',
                      embedding=VECTOR, extracted_remote_status='remote')
    for name in skills:
        JobSkill.objects.create(job=job, skill=_skill(name))
    return job


def _cv_with_profile(owner, name='alice_cv.docx', skills=('Python', 'Django', 'PostgreSQL')):
    cv = CV.objects.create(owner=owner, original_filename=name, status=CV.Status.READY, extracted_text='x')
    profile = CVProfile.objects.create(cv=cv, seniority='senior', embedding=VECTOR)
    profile.skills.set([_skill(s) for s in skills])
    return cv


# ── Sign up, log in, log out ──────────────────────────────────────────────

def test_signup_creates_user_logs_in_and_goes_to_upload(client):
    resp = client.post(reverse('accounts:signup'), {
        'username': 'newbie', 'email': '', 'password1': PASSWORD, 'password2': PASSWORD,
    })
    assert resp.status_code == 302
    assert resp['Location'] == reverse('accounts:upload')
    assert User.objects.filter(username='newbie').exists()
    assert client.get(reverse('accounts:profile')).status_code == 200      # signed in


def test_signup_errors_are_shown(client):
    resp = client.post(reverse('accounts:signup'), {
        'username': 'newbie', 'password1': PASSWORD, 'password2': 'different',
    })
    assert resp.status_code == 200
    assert 'didn’t match' in resp.content.decode() or "didn't match" in resp.content.decode()
    assert not User.objects.filter(username='newbie').exists()


def test_login_then_profile(client, user):
    resp = client.post(reverse('login'), {'username': 'alice', 'password': PASSWORD})
    assert resp.status_code == 302
    assert resp['Location'] == reverse('accounts:profile')


def test_wrong_password_message(client, user):
    resp = client.post(reverse('login'), {'username': 'alice', 'password': 'nope'})
    assert 'don’t match' in resp.content.decode()


def test_logout_is_a_post_and_returns_to_dashboard(client, user):
    client.force_login(user)
    resp = client.post(reverse('logout'))
    assert resp['Location'] == reverse('analytics:dashboard')
    assert client.get(reverse('accounts:profile')).status_code == 302      # signed out


def test_nav_reflects_sign_in_state(client, user):
    page = client.get(reverse('analytics:dashboard')).content.decode()
    assert 'Log in' in page and 'Sign up' in page
    client.force_login(user)
    page = client.get(reverse('analytics:dashboard')).content.decode()
    assert 'My profile' in page and 'Log out' in page and 'Sign up' not in page


# ── Profile ───────────────────────────────────────────────────────────────

def test_profile_requires_login(client):
    resp = client.get(reverse('accounts:profile'))
    assert resp['Location'].startswith(reverse('login'))


def test_profile_without_cv_prompts_upload(client, user):
    client.force_login(user)
    page = client.get(reverse('accounts:profile')).content.decode()
    assert 'No CV yet' in page


def test_profile_shows_latest_cv_top_matches_and_gaps(client, user, job_factory):
    for i in range(7):
        _job(job_factory, f'Backend Role {i}', ['Python', 'Django', 'PostgreSQL', 'Kubernetes'])
    _cv_with_profile(user, name='old_cv.docx', skills=('Excel',))
    _cv_with_profile(user, name='new_cv.docx')
    client.force_login(user)

    resp = client.get(reverse('accounts:profile'))
    page = resp.content.decode()
    assert resp.context['latest'].original_filename == 'new_cv.docx'
    assert len(resp.context['results']) == 5                              # top 5 shown
    assert resp.context['match_count'] == 7
    assert resp.context['gaps'] == [('Kubernetes', 7)]                    # counted over all 7
    assert 'Your biggest gaps' in page and 'Kubernetes' in page
    assert 'old_cv.docx' in page                                          # listed under earlier CVs


def test_profile_never_shows_another_users_cv(client, user):
    other = User.objects.create_user(username='bob', password=PASSWORD)
    _cv_with_profile(other, name='bob_cv.docx')
    client.force_login(user)
    page = client.get(reverse('accounts:profile')).content.decode()
    assert 'bob_cv.docx' not in page
    assert 'No CV yet' in page


# ── Matches page: HTMX filters and gaps ───────────────────────────────────

def test_matches_filters_swap_only_the_results(client, user, job_factory):
    _job(job_factory, 'Backend Role', ['Python', 'Django', 'PostgreSQL', 'Kubernetes'])
    cv = _cv_with_profile(user)
    client.force_login(user)

    resp = client.get(reverse('accounts:matches', args=[cv.pk]), {'remote_only': 'on'}, HTTP_HX_REQUEST='true')
    page = resp.content.decode()
    assert '<html' not in page
    assert 'Backend Role' in page
    assert 'Your biggest gaps' in page and 'Kubernetes' in page
