from django.urls import path

from . import views

app_name = "sessions"
urlpatterns = [
    path("", views.SessionListView.as_view(), name="session_list"),
    path("new/", views.SessionCreateView.as_view(), name="session_create"),
    path("<int:pk>/", views.SessionDetailView.as_view(), name="session_detail"),
    path("<int:pk>/edit/", views.SessionUpdateView.as_view(), name="session_edit"),
]
