from django.contrib import admin

from .models import (
    HeadlineTotals,
    DailySeniorityCount,
    DailySkillCount,
    DailySourceCount,
    DailyWorkModeCount,
)


class ReadOnlyAdmin(admin.ModelAdmin):
    """Rows are rebuilt by refresh_aggregates — edits would be overwritten."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DailySkillCount)
class DailySkillCountAdmin(ReadOnlyAdmin):
    list_display = ('day', 'skill', 'job_count', 'required_count')
    list_select_related = ('skill',)
    date_hierarchy = 'day'
    search_fields = ('skill__name',)


@admin.register(DailySeniorityCount)
class DailySeniorityCountAdmin(ReadOnlyAdmin):
    list_display = ('day', 'seniority', 'job_count')
    list_filter = ('seniority',)
    date_hierarchy = 'day'


@admin.register(DailyWorkModeCount)
class DailyWorkModeCountAdmin(ReadOnlyAdmin):
    list_display = ('day', 'work_mode', 'job_count')
    list_filter = ('work_mode',)
    date_hierarchy = 'day'


@admin.register(DailySourceCount)
class DailySourceCountAdmin(ReadOnlyAdmin):
    list_display = ('day', 'source', 'job_count')
    list_filter = ('source',)
    date_hierarchy = 'day'


@admin.register(HeadlineTotals)
class HeadlineTotalsAdmin(ReadOnlyAdmin):
    list_display = ('jobs_tracked', 'companies', 'distinct_skills', 'refreshed_at')
