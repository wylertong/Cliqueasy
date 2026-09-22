from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Category, CategoryMember

User = get_user_model()


class CategoryScopingTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner", email="owner@example.com", password="testpass123")
        self.other = User.objects.create_user(username="other", email="other@example.com", password="testpass123")
        self.category = Category.objects.create(creator=self.owner, name="USTA Roster")

    def test_create_associates_creator(self):
        self.client.login(username="owner", password="testpass123")
        response = self.client.post(reverse("categories:category_create"), {"name": "Class of '24 parents"})
        self.assertEqual(response.status_code, 302)
        category = Category.objects.get(name="Class of '24 parents")
        self.assertEqual(category.creator, self.owner)

    def test_non_creator_gets_404_on_detail(self):
        self.client.login(username="other", password="testpass123")
        response = self.client.get(reverse("categories:category_detail", args=[self.category.pk]))
        self.assertEqual(response.status_code, 404)

    def test_add_and_remove_member(self):
        self.client.login(username="owner", password="testpass123")
        add_url = reverse("categories:add_member", args=[self.category.pk])
        response = self.client.post(add_url, {"user": self.other.pk})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(CategoryMember.objects.filter(category=self.category, user=self.other).exists())

        remove_url = reverse("categories:remove_member", args=[self.category.pk, self.other.pk])
        response = self.client.post(remove_url)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(CategoryMember.objects.filter(category=self.category, user=self.other).exists())
