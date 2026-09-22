from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from sessions.models import Session

User = get_user_model()


def make_session(**overrides):
    user = overrides.pop("creator", None) or User.objects.create_user(
        username="creator1", email="creator1@example.com", password="testpass123"
    )
    defaults = dict(
        creator=user,
        title="Sunday Doubles",
        session_type=Session.SessionType.DOUBLES,
        date_time=timezone.now() + timezone.timedelta(days=3),
        location_text="Sunnyvale Tennis Center",
        target_size=4,
    )
    defaults.update(overrides)
    return Session.objects.create(**defaults)


class SessionDefaultsTests(TestCase):
    def test_defaults(self):
        session = make_session()
        self.assertEqual(session.status, Session.Status.OPEN)
        self.assertEqual(session.waitlist_mode, Session.WaitlistMode.PRIORITY_CASCADE)
        self.assertEqual(session.participant_visibility, Session.ParticipantVisibility.VISIBLE)
        self.assertEqual(session.waitlist_offer_window_minutes, 30)


class TargetSizeFloorTests(TestCase):
    def test_decrease_above_confirmed_count_succeeds(self):
        session = make_session(target_size=5)
        with patch.object(Session, "get_confirmed_participant_count", return_value=3):
            session.target_size = 4
            session.full_clean()  # must not raise

    def test_decrease_to_confirmed_count_succeeds(self):
        session = make_session(target_size=5)
        with patch.object(Session, "get_confirmed_participant_count", return_value=3):
            session.target_size = 3
            session.full_clean()  # must not raise

    def test_decrease_below_confirmed_count_raises(self):
        session = make_session(target_size=5)
        with patch.object(Session, "get_confirmed_participant_count", return_value=3):
            session.target_size = 2
            with self.assertRaises(ValidationError):
                session.full_clean()

    def test_decrease_with_zero_confirmed_succeeds(self):
        session = make_session(target_size=5)
        session.target_size = 1
        session.full_clean()  # must not raise; get_confirmed_participant_count() is 0 in Phase 1


class WaitlistModeOneWaySwitchTests(TestCase):
    def test_can_create_directly_in_fcfs_blast(self):
        session = make_session(waitlist_mode=Session.WaitlistMode.FCFS_BLAST)
        session.full_clean()  # must not raise — no prior state to violate

    def test_can_switch_priority_cascade_to_fcfs_blast(self):
        session = make_session()
        session.waitlist_mode = Session.WaitlistMode.FCFS_BLAST
        session.full_clean()  # must not raise
        session.save()

    def test_cannot_switch_fcfs_blast_back_to_priority_cascade(self):
        session = make_session()
        session.waitlist_mode = Session.WaitlistMode.FCFS_BLAST
        session.save()
        session.waitlist_mode = Session.WaitlistMode.PRIORITY_CASCADE
        with self.assertRaises(ValidationError):
            session.full_clean()


class CancelledCompletedEditGuardTests(TestCase):
    def test_editing_cancelled_session_raises(self):
        session = make_session()
        Session.objects.filter(pk=session.pk).update(status=Session.Status.CANCELLED)
        session.refresh_from_db()
        session.title = "New title"
        with self.assertRaises(ValidationError):
            session.full_clean()
