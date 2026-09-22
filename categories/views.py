from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, DetailView, ListView

from .forms import AddMemberForm, CategoryForm
from .models import Category, CategoryMember


class CategoryListView(LoginRequiredMixin, ListView):
    template_name = "categories/category_list.html"
    context_object_name = "categories"

    def get_queryset(self):
        return Category.objects.filter(creator=self.request.user)


class CategoryDetailView(LoginRequiredMixin, DetailView):
    template_name = "categories/category_detail.html"
    context_object_name = "category"

    def get_queryset(self):
        return Category.objects.filter(creator=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["add_member_form"] = AddMemberForm(category=self.object)
        return context


class CategoryCreateView(LoginRequiredMixin, CreateView):
    model = Category
    form_class = CategoryForm
    template_name = "categories/category_form.html"
    success_url = reverse_lazy("categories:category_list")

    def form_valid(self, form):
        form.instance.creator = self.request.user
        return super().form_valid(form)


class AddMemberView(LoginRequiredMixin, View):
    def post(self, request, pk):
        category = get_object_or_404(Category, pk=pk, creator=request.user)
        form = AddMemberForm(request.POST, category=category)
        if form.is_valid():
            CategoryMember.objects.create(category=category, user=form.cleaned_data["user"])
        return redirect("categories:category_detail", pk=category.pk)


class RemoveMemberView(LoginRequiredMixin, View):
    def post(self, request, pk, user_id):
        category = get_object_or_404(Category, pk=pk, creator=request.user)
        CategoryMember.objects.filter(category=category, user_id=user_id).delete()
        return redirect("categories:category_detail", pk=category.pk)
