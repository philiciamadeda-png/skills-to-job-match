from django.contrib import admin
from .models import RawJobPayload


@admin.register(RawJobPayload)
class RawJobPayloadAdmin(admin.ModelAdmin):
    list_display = ('source', 'fetched_at', 'processed', 'content_hash')
    list_filter = ('source', 'processed')
    search_fields = ('content_hash',)
    readonly_fields = ('raw_data', 'content_hash', 'fetched_at')
