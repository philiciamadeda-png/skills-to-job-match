from django.urls import path

from apps.accounts import views

app_name = 'accounts'

urlpatterns = [
    path('', views.upload, name='upload'),
    path('cv/<int:cv_id>/', views.matches, name='matches'),
    path('cv/<int:cv_id>/job/<int:job_id>/', views.match_detail, name='match_detail'),
]
