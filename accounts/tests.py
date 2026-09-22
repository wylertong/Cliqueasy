from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class UserModelTests(TestCase):
    def test_create_user_with_phone(self):
        user = User.objects.create_user(
            username="jdoe", email="jdoe@example.com", password="testpass123", phone="555-0100"
        )
        self.assertEqual(user.phone, "555-0100")
        self.assertEqual(user.email, "jdoe@example.com")
        self.assertTrue(user.check_password("testpass123"))


class SignupViewTests(TestCase):
    def test_signup_creates_user_and_logs_in(self):
        response = self.client.post(reverse("accounts:signup"), {
            "username": "asmith",
            "first_name": "Alex",
            "last_name": "Smith",
            "email": "asmith@example.com",
            "phone": "555-0101",
            "password1": "cliqueyPass123",
            "password2": "cliqueyPass123",
        })
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="asmith")
        self.assertEqual(user.phone, "555-0101")
        response = self.client.get(reverse("accounts:profile"))
        self.assertEqual(response.status_code, 200)


class ProfileViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="bwong", email="bwong@example.com", password="testpass123"
        )

    def test_profile_requires_login(self):
        response = self.client.get(reverse("accounts:profile"))
        self.assertEqual(response.status_code, 302)

    def test_profile_edit_persists(self):
        self.client.login(username="bwong", password="testpass123")
        response = self.client.post(reverse("accounts:profile_edit"), {
            "first_name": "Bailey",
            "last_name": "Wong",
            "email": "bwong@example.com",
            "phone": "555-0102",
        })
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.phone, "555-0102")
