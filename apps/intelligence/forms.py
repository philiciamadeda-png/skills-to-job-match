from django import forms

from apps.intelligence.queries import LEVELS, SENIORITY_LABELS, UNKNOWN, WORK_MODE_LABELS, WORK_MODES

SOURCES = [('remotive', 'Remotive'), ('arbeitnow', 'Arbeitnow')]


class JobFilterForm(forms.Form):
    q = forms.CharField(
        required=False, max_length=100, label='Search',
        widget=forms.SearchInput(attrs={'placeholder': 'Title, company or skill'}),
    )
    seniority = forms.ChoiceField(
        required=False, label='Level',
        choices=[('', 'Any level')] + [(k, SENIORITY_LABELS[k]) for k in LEVELS + [UNKNOWN]],
    )
    work_mode = forms.ChoiceField(
        required=False, label='Work mode',
        choices=[('', 'Any')] + [(k, WORK_MODE_LABELS[k]) for k in WORK_MODES],
    )
    source = forms.ChoiceField(required=False, label='Source', choices=[('', 'All sources')] + SOURCES)
