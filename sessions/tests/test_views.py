import threading

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from categories.models import Category, CategoryMember
from sessions.models import Session, SessionInvite, SessionParticipant

User = get_user_model()


def make_user(name):
    return User.objects.create_user(username=name, email=f"{name}@example.com", password="testpass123")


def make_session(**overrides):
    creator = overrides.pop("creator", None) or User.objects.create_user(
        username=f"creator-{User.objects.count()}", email=f"creator{User.objects.count()}@example.com",
        password="testpass123",
    )
    defaults = dict(
        creator=creator,
        title="Sunday Doubles",
        session_type=Session.SessionType.DOUBLES,
        date_time=timezone.now() + timezone.timedelta(days=3),
        location_text="Sunnyvale Tennis Center",
        target_size=2,
    )
    defaults.update(overrides)
    return Session.objects.create(**defaults)


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


# ---------------------------------------------------------------------------
# SessionParticipant view tests
# ---------------------------------------------------------------------------

class SessionJoinViewTests(TestCase):
    def setUp(self):
        self.creator = make_user("join_creator")
        self.session = make_session(creator=self.creator, target_size=1)

    def test_join_with_room_confirms_immediately(self):
        joiner = make_user("joiner1")
        self.client.login(username="joiner1", password="testpass123")
        response = self.client.post(reverse("sessions:session_join", args=[self.session.pk]))
        self.assertEqual(response.status_code, 302)
        participant = SessionParticipant.objects.get(session=self.session, user=joiner)
        self.assertEqual(participant.status, SessionParticipant.Status.CONFIRMED)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, Session.Status.FULL)

    def test_join_when_full_shows_confirmation_without_creating_row(self):
        SessionParticipant.objects.create(session=self.session, user=make_user("filler"), status=SessionParticipant.Status.CONFIRMED)
        self.session.sync_status()
        joiner = make_user("joiner2")
        self.client.login(username="joiner2", password="testpass123")
        response = self.client.post(reverse("sessions:session_join", args=[self.session.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "waitlist")
        self.assertFalse(SessionParticipant.objects.filter(session=self.session, user=joiner).exists())

    def test_post_confirm_waitlist_when_full_creates_waitlisted_row(self):
        SessionParticipant.objects.create(session=self.session, user=make_user("filler2"), status=SessionParticipant.Status.CONFIRMED)
        self.session.sync_status()
        joiner = make_user("joiner3")
        self.client.login(username="joiner3", password="testpass123")
        response = self.client.post(reverse("sessions:session_join", args=[self.session.pk]), {"confirm_waitlist": "1"})
        self.assertEqual(response.status_code, 302)
        participant = SessionParticipant.objects.get(session=self.session, user=joiner)
        self.assertEqual(participant.status, SessionParticipant.Status.WAITLISTED)
        self.assertEqual(participant.position, 1)

    def test_join_cancelled_session_rejected(self):
        Session.objects.filter(pk=self.session.pk).update(status=Session.Status.CANCELLED)
        joiner = make_user("joiner4")
        self.client.login(username="joiner4", password="testpass123")
        response = self.client.post(reverse("sessions:session_join", args=[self.session.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(SessionParticipant.objects.filter(session=self.session, user=joiner).exists())

    def test_duplicate_join_is_noop(self):
        joiner = make_user("joiner5")
        self.client.login(username="joiner5", password="testpass123")
        self.client.post(reverse("sessions:session_join", args=[self.session.pk]))
        self.client.post(reverse("sessions:session_join", args=[self.session.pk]))
        self.assertEqual(SessionParticipant.objects.filter(session=self.session, user=joiner).count(), 1)

    def test_creator_cannot_join_own_session(self):
        self.client.login(username="join_creator", password="testpass123")
        response = self.client.post(reverse("sessions:session_join", args=[self.session.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(SessionParticipant.objects.filter(session=self.session, user=self.creator).exists())

    def test_new_joiner_cannot_skip_existing_waitlist(self):
        # target_size=1: A confirmed, B waitlisted. A leaves -> a slot opens up,
        # but B is still waiting. A brand-new joiner C must not skip ahead of B.
        a = make_user("queue_a")
        b = make_user("queue_b")
        c = make_user("queue_c")
        SessionParticipant.objects.create(session=self.session, user=a, status=SessionParticipant.Status.CONFIRMED)
        SessionParticipant.objects.create(session=self.session, user=b, status=SessionParticipant.Status.WAITLISTED, position=1)
        self.session.sync_status()

        self.client.login(username="queue_a", password="testpass123")
        self.client.post(reverse("sessions:session_leave", args=[self.session.pk]))

        self.client.login(username="queue_c", password="testpass123")
        response = self.client.post(reverse("sessions:session_join", args=[self.session.pk]), {"confirm_waitlist": "1"})
        self.assertEqual(response.status_code, 302)
        c_participant = SessionParticipant.objects.get(session=self.session, user=c)
        self.assertEqual(c_participant.status, SessionParticipant.Status.WAITLISTED)
        self.assertEqual(c_participant.position, 2)


class ConcurrentJoinTests(TransactionTestCase):
    def test_concurrent_joins_serialize_correctly(self):
        session = make_session(target_size=1)
        users = [make_user(f"racer{i}") for i in range(5)]
        status_codes = []
        lock = threading.Lock()

        def attempt_join(username):
            try:
                client = Client()
                client.login(username=username, password="testpass123")
                response = client.post(reverse("sessions:session_join", args=[session.pk]))
                if response.status_code == 200:
                    # Session was full by the time this request got the lock —
                    # follow the real two-step flow and confirm the waitlist.
                    response = client.post(
                        reverse("sessions:session_join", args=[session.pk]), {"confirm_waitlist": "1"}
                    )
                with lock:
                    status_codes.append(response.status_code)
            finally:
                connection.close()

        threads = [threading.Thread(target=attempt_join, args=(u.username,)) for u in users]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertTrue(all(code == 302 for code in status_codes), status_codes)
        confirmed = SessionParticipant.objects.filter(session=session, status=SessionParticipant.Status.CONFIRMED)
        waitlisted = SessionParticipant.objects.filter(
            session=session, status=SessionParticipant.Status.WAITLISTED
        ).order_by("position")
        self.assertEqual(confirmed.count(), 1)
        self.assertEqual(list(waitlisted.values_list("position", flat=True)), [1, 2, 3, 4])


class SessionLeaveViewTests(TestCase):
    def setUp(self):
        self.creator = make_user("leave_creator")
        self.session = make_session(creator=self.creator, target_size=1)

    def test_confirmed_leave_frees_spot_and_flips_full_to_open(self):
        joiner = make_user("leaver1")
        SessionParticipant.objects.create(session=self.session, user=joiner, status=SessionParticipant.Status.CONFIRMED)
        self.session.sync_status()
        self.assertEqual(self.session.status, Session.Status.FULL)
        self.client.login(username="leaver1", password="testpass123")
        response = self.client.post(reverse("sessions:session_leave", args=[self.session.pk]))
        self.assertEqual(response.status_code, 302)
        participant = SessionParticipant.objects.get(session=self.session, user=joiner)
        self.assertEqual(participant.status, SessionParticipant.Status.LEFT)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, Session.Status.OPEN)

    def test_waitlisted_leave_recompacts_positions(self):
        w1 = make_user("wleaver1")
        w2 = make_user("wleaver2")
        SessionParticipant.objects.create(session=self.session, user=w1, status=SessionParticipant.Status.WAITLISTED, position=1)
        p2 = SessionParticipant.objects.create(session=self.session, user=w2, status=SessionParticipant.Status.WAITLISTED, position=2)
        self.client.login(username="wleaver1", password="testpass123")
        self.client.post(reverse("sessions:session_leave", args=[self.session.pk]))
        p2.refresh_from_db()
        self.assertEqual(p2.position, 1)

    def test_non_participant_leave_is_noop(self):
        stranger = make_user("stranger1")
        self.client.login(username="stranger1", password="testpass123")
        response = self.client.post(reverse("sessions:session_leave", args=[self.session.pk]))
        self.assertEqual(response.status_code, 302)


class SessionRemoveParticipantViewTests(TestCase):
    def setUp(self):
        self.creator = make_user("remove_creator")
        self.other = make_user("remove_other")
        self.session = make_session(creator=self.creator, target_size=1)
        self.participant = SessionParticipant.objects.create(
            session=self.session, user=make_user("removee"), status=SessionParticipant.Status.CONFIRMED
        )
        self.session.sync_status()

    def test_creator_can_remove_confirmed_participant(self):
        self.client.login(username="remove_creator", password="testpass123")
        response = self.client.post(
            reverse("sessions:session_remove_participant", args=[self.session.pk, self.participant.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.participant.refresh_from_db()
        self.assertEqual(self.participant.status, SessionParticipant.Status.REMOVED)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, Session.Status.OPEN)

    def test_non_creator_cannot_remove_participant(self):
        self.client.login(username="remove_other", password="testpass123")
        response = self.client.post(
            reverse("sessions:session_remove_participant", args=[self.session.pk, self.participant.pk])
        )
        self.assertEqual(response.status_code, 404)
        self.participant.refresh_from_db()
        self.assertEqual(self.participant.status, SessionParticipant.Status.CONFIRMED)

    def test_double_remove_is_graceful_not_404(self):
        self.client.login(username="remove_creator", password="testpass123")
        remove_url = reverse("sessions:session_remove_participant", args=[self.session.pk, self.participant.pk])
        self.client.post(remove_url)
        response = self.client.post(remove_url)
        self.assertEqual(response.status_code, 302)


class HomeViewMySessionsTests(TestCase):
    def setUp(self):
        self.viewer = make_user("my_sessions_viewer")
        self.creator = make_user("my_sessions_creator")

    def test_confirmed_session_shows_in_my_sessions(self):
        session = make_session(creator=self.creator, title="My Confirmed Session")
        SessionParticipant.objects.create(session=session, user=self.viewer, status=SessionParticipant.Status.CONFIRMED)
        self.client.login(username="my_sessions_viewer", password="testpass123")
        response = self.client.get(reverse("sessions:home"))
        self.assertContains(response, "My Confirmed Session")

    def test_waitlisted_session_shows_in_my_sessions(self):
        session = make_session(creator=self.creator, title="My Waitlisted Session")
        SessionParticipant.objects.create(session=session, user=self.viewer, status=SessionParticipant.Status.WAITLISTED, position=1)
        self.client.login(username="my_sessions_viewer", password="testpass123")
        response = self.client.get(reverse("sessions:home"))
        self.assertContains(response, "My Waitlisted Session")

    def test_left_session_does_not_show_in_my_sessions(self):
        session = make_session(creator=self.creator, title="My Left Session")
        SessionParticipant.objects.create(session=session, user=self.viewer, status=SessionParticipant.Status.LEFT)
        self.client.login(username="my_sessions_viewer", password="testpass123")
        response = self.client.get(reverse("sessions:home"))
        self.assertNotContains(response, "My Left Session")

    def test_creator_own_session_not_in_my_sessions(self):
        make_session(creator=self.creator, title="Created Not Joined Session")
        self.client.login(username="my_sessions_creator", password="testpass123")
        response = self.client.get(reverse("sessions:home"))
        self.assertNotContains(response, "Created Not Joined Session")

    def test_cancelled_session_still_shown_in_my_sessions(self):
        # Intentional, unlike Open to Join: My Sessions is roster history, not
        # just active invites — a session you joined that got cancelled is
        # still meaningful to see.
        session = make_session(creator=self.creator, title="My Cancelled Session")
        SessionParticipant.objects.create(session=session, user=self.viewer, status=SessionParticipant.Status.CONFIRMED)
        Session.objects.filter(pk=session.pk).update(status=Session.Status.CANCELLED)
        self.client.login(username="my_sessions_viewer", password="testpass123")
        response = self.client.get(reverse("sessions:home"))
        self.assertContains(response, "My Cancelled Session")
