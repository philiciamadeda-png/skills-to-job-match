from django import forms
from django.contrib.auth.forms import UserCreationForm

from apps.accounts.extraction import MAX_FILE_SIZE, SUPPORTED_MIME_TYPES, detect_mime


class SignUpForm(UserCreationForm):
    email = forms.EmailField(required=False, help_text='Optional.')

    class Meta(UserCreationForm.Meta):
        fields = ('username', 'email')


class CVUploadForm(forms.Form):
    file = forms.FileField(
        label='CV (PDF or DOCX)',
        help_text=f'Maximum {MAX_FILE_SIZE // (1024 * 1024)} MB. PDF or DOCX only.',
        widget=forms.ClearableFileInput(attrs={'accept': '.pdf,.docx'}),
    )

    def clean_file(self):
        f = self.cleaned_data['file']

        if f.size > MAX_FILE_SIZE:
            raise forms.ValidationError(
                f'File is too large ({f.size // (1024*1024)} MB). Maximum is {MAX_FILE_SIZE // (1024*1024)} MB.'
            )

        # Validate by magic bytes — not by extension or Content-Type header
        header = f.read(8)
        f.seek(0)
        mime = detect_mime(header)
        if mime not in SUPPORTED_MIME_TYPES:
            raise forms.ValidationError('Unsupported file type. Upload a PDF or DOCX.')

        return f


class MatchFilterForm(forms.Form):
    """Hard filters for the matches page — requirements, not preferences."""
    remote_only = forms.BooleanField(
        required=False, label='Remote only',
        help_text='Exclude on-site and hybrid roles.',
    )
    countries = forms.CharField(
        required=False, max_length=100, label='Countries I can work in',
        help_text='Comma-separated ISO codes, e.g. KE,GB. Leave blank for anywhere.',
        widget=forms.TextInput(attrs={'placeholder': 'KE, GB'}),
    )

    def clean_countries(self):
        raw = self.cleaned_data['countries']
        codes = [c.strip().upper() for c in raw.split(',') if c.strip()]
        bad = [c for c in codes if len(c) != 2 or not c.isalpha()]
        if bad:
            raise forms.ValidationError(f'Use two-letter country codes (e.g. KE, GB). Not valid: {", ".join(bad)}')
        return codes


class CVUploadWithFiltersForm(CVUploadForm, MatchFilterForm):
    pass
