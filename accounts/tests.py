from django.contrib.auth import get_user_model
from django.test import TestCase

User = get_user_model()


class UserModelTests(TestCase):
    def test_create_user_with_phone(self):
        user = User.objects.create_user(
            username="jdoe", email="jdoe@example.com", password="testpass123", phone="555-0100"
        )
        self.assertEqual(user.phone, "555-0100")
        self.assertEqual(user.email, "jdoe@example.com")
        self.assertTrue(user.check_password("testpass123"))
