from django.urls import path

from apps.intelligence import views

app_name = 'jobs'

urlpatterns = [
    path('', views.job_list, name='list'),
]
