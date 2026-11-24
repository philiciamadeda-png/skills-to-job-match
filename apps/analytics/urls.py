from django.urls import path

from apps.analytics import views

app_name = 'analytics'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
]
