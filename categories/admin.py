from django.contrib import admin

from .models import Category, CategoryMember

admin.site.register(Category)
admin.site.register(CategoryMember)
