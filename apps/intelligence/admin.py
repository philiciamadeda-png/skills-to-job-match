from django.contrib import admin
from .models import Company, Location, Skill, Job, JobSkill


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name', 'normalised_name', 'website')
    search_fields = ('name', 'normalised_name')
    readonly_fields = ('normalised_name',)


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ('raw_text', 'country', 'city', 'is_remote')
    list_filter = ('country', 'is_remote')
    search_fields = ('raw_text', 'city', 'country')
    readonly_fields = ('normalised_country', 'normalised_city')


@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
    list_display = ('name', 'normalised_name', 'category')
    list_filter = ('category',)
    search_fields = ('name', 'normalised_name')
    readonly_fields = ('normalised_name',)


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ('title', 'company', 'location', 'source', 'published_date', 'contract_type')
    list_filter = ('source', 'contract_type', 'published_date')
    search_fields = ('title', 'source_id', 'company__name')
    readonly_fields = ('content_hash', 'source_id', 'embedding')


@admin.register(JobSkill)
class JobSkillAdmin(admin.ModelAdmin):
    list_display = ('job', 'skill', 'confidence_score', 'extraction_method')
    list_filter = ('extraction_method',)
    search_fields = ('job__title', 'skill__name')
    readonly_fields = ('extracted_at',)
