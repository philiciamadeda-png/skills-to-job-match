from django import forms

from apps.accounts.extraction import MAX_FILE_SIZE, SUPPORTED_MIME_TYPES, detect_mime


class CVUploadForm(forms.Form):
    file = forms.FileField(
        label='CV (PDF or DOCX)',
        help_text=f'Maximum {MAX_FILE_SIZE // (1024 * 1024)} MB. PDF or DOCX only.',
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
