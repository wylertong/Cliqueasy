from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sessions.models import Session

User = get_user_model()


class SessionCreateViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="creator", email="c@example.com", password="testpass123")
        self.client.login(username="creator", password="testpass123")

    def test_create_sets_creator(self):
        response = self.client.post(reverse("sessions:session_create"), {
            "title": "Weeknight Singles",
            "description": "",
            "session_type": Session.SessionType.SINGLES,
            "date_time": (timezone.now() + timezone.timedelta(days=2)).strftime("%Y-%m-%dT%H:%M"),
            "location_text": "Fairbreigh Swim and Racket Club",
            "target_size": 2,
            "participant_visibility": Session.ParticipantVisibility.VISIBLE,
            "waitlist_mode": Session.WaitlistMode.PRIORITY_CASCADE,
            "waitlist_offer_window_minutes": 30,
        })
        self.assertEqual(response.status_code, 302)
        session = Session.objects.get(title="Weeknight Singles")
        self.assertEqual(session.creator, self.user)


class SessionUpdateViewTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner", email="owner@example.com", password="testpass123")
        self.other = User.objects.create_user(username="other", email="other@example.com", password="testpass123")
        self.session = Session.objects.create(
            creator=self.owner,
            title="Original title",
            session_type=Session.SessionType.DOUBLES,
            date_time=timezone.now() + timezone.timedelta(days=3),
            location_text="Sunnyvale Tennis Center",
            target_size=4,
        )

    def test_non_creator_cannot_edit(self):
        self.client.login(username="other", password="testpass123")
        response = self.client.get(reverse("sessions:session_edit", args=[self.session.pk]))
        self.assertIn(response.status_code, (403, 404))

    def test_creator_can_switch_to_fcfs_blast_but_not_back(self):
        self.client.login(username="owner", password="testpass123")
        edit_url = reverse("sessions:session_edit", args=[self.session.pk])
        base_data = {
            "title": self.session.title,
            "description": "",
            "session_type": self.session.session_type,
            "date_time": self.session.date_time.strftime("%Y-%m-%dT%H:%M"),
            "location_text": self.session.location_text,
            "target_size": self.session.target_size,
            "participant_visibility": Session.ParticipantVisibility.VISIBLE,
            "waitlist_offer_window_minutes": 30,
        }
        response = self.client.post(edit_url, {**base_data, "waitlist_mode": Session.WaitlistMode.FCFS_BLAST})
        self.assertEqual(response.status_code, 302)
        response = self.client.post(edit_url, {**base_data, "waitlist_mode": Session.WaitlistMode.PRIORITY_CASCADE})
        self.assertEqual(response.status_code, 200)  # re-renders form with error
        self.session.refresh_from_db()
        self.assertEqual(self.session.waitlist_mode, Session.WaitlistMode.FCFS_BLAST)
