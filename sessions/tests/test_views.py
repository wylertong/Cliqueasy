from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from categories.models import Category, CategoryMember
from sessions.models import Session, SessionInvite

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


class InviteCategoryViewTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner2", email="owner2@example.com", password="testpass123")
        self.other = User.objects.create_user(username="other2", email="other2@example.com", password="testpass123")
        self.session = Session.objects.create(
            creator=self.owner, title="Sunday Doubles", session_type=Session.SessionType.DOUBLES,
            date_time=timezone.now() + timezone.timedelta(days=3),
            location_text="Sunnyvale Tennis Center", target_size=4,
        )
        self.category = Category.objects.create(creator=self.owner, name="Roster")

    def test_creator_can_invite_category(self):
        self.client.login(username="owner2", password="testpass123")
        response = self.client.post(reverse("sessions:invite_category", args=[self.session.pk]), {"category": self.category.pk})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(SessionInvite.objects.filter(session=self.session, invited_category=self.category).exists())

    def test_non_creator_cannot_invite_category(self):
        self.client.login(username="other2", password="testpass123")
        response = self.client.post(reverse("sessions:invite_category", args=[self.session.pk]), {"category": self.category.pk})
        self.assertEqual(response.status_code, 404)
        self.assertFalse(SessionInvite.objects.filter(session=self.session).exists())

    def test_already_invited_category_is_not_duplicated(self):
        SessionInvite.objects.create(session=self.session, invited_category=self.category)
        self.client.login(username="owner2", password="testpass123")
        response = self.client.post(reverse("sessions:invite_category", args=[self.session.pk]), {"category": self.category.pk})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(SessionInvite.objects.filter(session=self.session, invited_category=self.category).count(), 1)

    def test_cannot_invite_category_to_cancelled_session(self):
        Session.objects.filter(pk=self.session.pk).update(status=Session.Status.CANCELLED)
        self.client.login(username="owner2", password="testpass123")
        response = self.client.post(reverse("sessions:invite_category", args=[self.session.pk]), {"category": self.category.pk})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(SessionInvite.objects.filter(session=self.session).exists())


class InviteUsersViewTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner3", email="owner3@example.com", password="testpass123")
        self.other = User.objects.create_user(username="other3", email="other3@example.com", password="testpass123")
        self.invitee1 = User.objects.create_user(username="invitee_a", email="invitee_a@example.com", password="testpass123")
        self.invitee2 = User.objects.create_user(username="invitee_b", email="invitee_b@example.com", password="testpass123")
        self.session = Session.objects.create(
            creator=self.owner, title="Weeknight Singles", session_type=Session.SessionType.SINGLES,
            date_time=timezone.now() + timezone.timedelta(days=2),
            location_text="Fairbreigh Swim and Racket Club", target_size=2,
        )

    def test_creator_can_invite_multiple_users(self):
        self.client.login(username="owner3", password="testpass123")
        response = self.client.post(
            reverse("sessions:invite_users", args=[self.session.pk]),
            {"users": [self.invitee1.pk, self.invitee2.pk]},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(SessionInvite.objects.filter(session=self.session).count(), 2)

    def test_non_creator_cannot_invite_users(self):
        self.client.login(username="other3", password="testpass123")
        response = self.client.post(reverse("sessions:invite_users", args=[self.session.pk]), {"users": [self.invitee1.pk]})
        self.assertEqual(response.status_code, 404)

    def test_cannot_invite_user_to_completed_session(self):
        Session.objects.filter(pk=self.session.pk).update(status=Session.Status.COMPLETED)
        self.client.login(username="owner3", password="testpass123")
        response = self.client.post(reverse("sessions:invite_users", args=[self.session.pk]), {"users": [self.invitee1.pk]})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(SessionInvite.objects.filter(session=self.session).exists())


class HomeViewOpenToJoinTests(TestCase):
    def setUp(self):
        self.viewer = User.objects.create_user(username="viewer", email="viewer@example.com", password="testpass123")
        self.creator = User.objects.create_user(username="creator2", email="creator2@example.com", password="testpass123")

    def make_session(self, **overrides):
        defaults = dict(
            creator=self.creator, title="Session", session_type=Session.SessionType.DOUBLES,
            date_time=timezone.now() + timezone.timedelta(days=3), location_text="Court", target_size=4,
        )
        defaults.update(overrides)
        return Session.objects.create(**defaults)

    def test_direct_invite_shows_on_home(self):
        session = self.make_session(title="Direct Invite Session")
        SessionInvite.objects.create(session=session, invited_user=self.viewer)
        self.client.login(username="viewer", password="testpass123")
        response = self.client.get(reverse("sessions:home"))
        self.assertContains(response, "Direct Invite Session")

    def test_category_invite_shows_on_home(self):
        session = self.make_session(title="Category Invite Session")
        category = Category.objects.create(creator=self.creator, name="Roster")
        CategoryMember.objects.create(category=category, user=self.viewer)
        SessionInvite.objects.create(session=session, invited_category=category)
        self.client.login(username="viewer", password="testpass123")
        response = self.client.get(reverse("sessions:home"))
        self.assertContains(response, "Category Invite Session")

    def test_cancelled_session_excluded(self):
        session = self.make_session(title="Cancelled Session")
        SessionInvite.objects.create(session=session, invited_user=self.viewer)
        Session.objects.filter(pk=session.pk).update(status=Session.Status.CANCELLED)
        self.client.login(username="viewer", password="testpass123")
        response = self.client.get(reverse("sessions:home"))
        self.assertNotContains(response, "Cancelled Session")

    def test_own_created_session_excluded_even_if_self_invited_via_category(self):
        session = self.make_session(title="Own Session", creator=self.viewer)
        category = Category.objects.create(creator=self.viewer, name="Self Category")
        CategoryMember.objects.create(category=category, user=self.viewer)
        SessionInvite.objects.create(session=session, invited_category=category)
        self.client.login(username="viewer", password="testpass123")
        response = self.client.get(reverse("sessions:home"))
        self.assertNotContains(response, "Own Session")

    def test_my_sessions_placeholder_present(self):
        self.client.login(username="viewer", password="testpass123")
        response = self.client.get(reverse("sessions:home"))
        self.assertContains(response, "My Sessions")
        self.assertContains(response, "Coming soon")

    def test_completed_session_excluded(self):
        session = self.make_session(title="Completed Session")
        SessionInvite.objects.create(session=session, invited_user=self.viewer)
        Session.objects.filter(pk=session.pk).update(status=Session.Status.COMPLETED)
        self.client.login(username="viewer", password="testpass123")
        response = self.client.get(reverse("sessions:home"))
        self.assertNotContains(response, "Completed Session")

    def test_dual_path_invite_appears_once(self):
        session = self.make_session(title="Dual Path Session")
        category = Category.objects.create(creator=self.creator, name="Dual Roster")
        CategoryMember.objects.create(category=category, user=self.viewer)
        SessionInvite.objects.create(session=session, invited_user=self.viewer)
        SessionInvite.objects.create(session=session, invited_category=category)
        self.client.login(username="viewer", password="testpass123")
        response = self.client.get(reverse("sessions:home"))
        self.assertEqual(list(response.context["open_to_join_sessions"]).count(session), 1)


class LoginRedirectTests(TestCase):
    def test_login_redirects_to_home(self):
        User.objects.create_user(username="loginredir", email="loginredir@example.com", password="testpass123")
        response = self.client.post(reverse("accounts:login"), {"username": "loginredir", "password": "testpass123"})
        self.assertRedirects(response, reverse("sessions:home"))
