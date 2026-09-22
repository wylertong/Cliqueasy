from django.urls import path

from . import views

app_name = "categories"
urlpatterns = [
    path("", views.CategoryListView.as_view(), name="category_list"),
    path("new/", views.CategoryCreateView.as_view(), name="category_create"),
    path("<int:pk>/", views.CategoryDetailView.as_view(), name="category_detail"),
    path("<int:pk>/members/add/", views.AddMemberView.as_view(), name="add_member"),
    path("<int:pk>/members/<int:user_id>/remove/", views.RemoveMemberView.as_view(), name="remove_member"),
]
