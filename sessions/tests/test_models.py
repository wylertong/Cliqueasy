from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from categories.models import Category
from sessions.models import Session, SessionInvite, SessionParticipant

User = get_user_model()


def make_user(name):
    return User.objects.create_user(username=name, email=f"{name}@example.com", password="testpass123")


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
        session.full_clean()  # must not raise; no SessionParticipant rows exist for this session

    def test_editing_unrelated_field_on_already_overbooked_session_succeeds(self):
        with patch.object(Session, "get_confirmed_participant_count", return_value=3):
            session = make_session(target_size=2)  # already below the (mocked) confirmed count
            session.description = "Bring extra balls"
            session.full_clean()  # must not raise; target_size itself isn't changing

    def test_further_decreasing_target_size_on_already_overbooked_session_raises(self):
        with patch.object(Session, "get_confirmed_participant_count", return_value=3):
            session = make_session(target_size=2)
            session.target_size = 1
            with self.assertRaises(ValidationError):
                session.full_clean()


class TargetSizeFloorWithRealParticipantsTests(TestCase):
    def test_decrease_below_real_confirmed_count_raises(self):
        session = make_session(target_size=5)
        for i in range(3):
            user = User.objects.create_user(username=f"realconfirmed{i}", email=f"realconfirmed{i}@example.com", password="testpass123")
            SessionParticipant.objects.create(session=session, user=user, status=SessionParticipant.Status.CONFIRMED)
        session.target_size = 2
        with self.assertRaises(ValidationError):
            session.full_clean()

    def test_decrease_to_real_confirmed_count_succeeds(self):
        session = make_session(target_size=5)
        for i in range(3):
            user = User.objects.create_user(username=f"realconfirmed_ok{i}", email=f"realconfirmed_ok{i}@example.com", password="testpass123")
            SessionParticipant.objects.create(session=session, user=user, status=SessionParticipant.Status.CONFIRMED)
        session.target_size = 3
        session.full_clean()  # must not raise


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


class SessionInviteExactlyOneTargetTests(TestCase):
    def test_invited_user_only_is_valid(self):
        session = make_session()
        invitee = User.objects.create_user(username="invitee1", email="invitee1@example.com", password="testpass123")
        SessionInvite(session=session, invited_user=invitee).full_clean()  # must not raise

    def test_invited_category_only_is_valid(self):
        session = make_session()
        category = Category.objects.create(creator=session.creator, name="Roster")
        SessionInvite(session=session, invited_category=category).full_clean()  # must not raise

    def test_both_targets_raises(self):
        session = make_session()
        invitee = User.objects.create_user(username="invitee2", email="invitee2@example.com", password="testpass123")
        category = Category.objects.create(creator=session.creator, name="Roster")
        invite = SessionInvite(session=session, invited_user=invitee, invited_category=category)
        with self.assertRaises(ValidationError):
            invite.full_clean()

    def test_neither_target_raises(self):
        session = make_session()
        with self.assertRaises(ValidationError):
            SessionInvite(session=session).full_clean()


class SessionInviteAfterCreationGuardTests(TestCase):
    def test_invite_to_open_session_succeeds(self):
        session = make_session(status=Session.Status.OPEN)
        invitee = User.objects.create_user(username="invitee3", email="invitee3@example.com", password="testpass123")
        SessionInvite(session=session, invited_user=invitee).full_clean()  # must not raise

    def test_invite_to_full_session_succeeds(self):
        session = make_session(status=Session.Status.FULL)
        invitee = User.objects.create_user(username="invitee4", email="invitee4@example.com", password="testpass123")
        SessionInvite(session=session, invited_user=invitee).full_clean()  # must not raise

    def test_invite_to_cancelled_session_raises(self):
        session = make_session(status=Session.Status.CANCELLED)
        invitee = User.objects.create_user(username="invitee5", email="invitee5@example.com", password="testpass123")
        with self.assertRaises(ValidationError):
            SessionInvite(session=session, invited_user=invitee).full_clean()

    def test_invite_to_completed_session_raises(self):
        session = make_session(status=Session.Status.COMPLETED)
        invitee = User.objects.create_user(username="invitee6", email="invitee6@example.com", password="testpass123")
        with self.assertRaises(ValidationError):
            SessionInvite(session=session, invited_user=invitee).full_clean()


class SessionInviteUniquenessTests(TestCase):
    def test_duplicate_user_invite_raises_integrity_error(self):
        session = make_session()
        invitee = User.objects.create_user(username="dupuser", email="dupuser@example.com", password="testpass123")
        SessionInvite.objects.create(session=session, invited_user=invitee)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SessionInvite.objects.create(session=session, invited_user=invitee)

    def test_duplicate_category_invite_raises_integrity_error(self):
        session = make_session()
        category = Category.objects.create(creator=session.creator, name="Roster")
        SessionInvite.objects.create(session=session, invited_category=category)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SessionInvite.objects.create(session=session, invited_category=category)

    def test_two_category_only_invites_on_same_session_coexist(self):
        session = make_session()
        category_a = Category.objects.create(creator=session.creator, name="Roster A")
        category_b = Category.objects.create(creator=session.creator, name="Roster B")
        SessionInvite.objects.create(session=session, invited_category=category_a)
        SessionInvite.objects.create(session=session, invited_category=category_b)
        self.assertEqual(session.invites.count(), 2)


class SessionInviteDefaultsTests(TestCase):
    def test_method_defaults_to_in_app_link(self):
        session = make_session()
        invitee = User.objects.create_user(username="invitee7", email="invitee7@example.com", password="testpass123")
        invite = SessionInvite.objects.create(session=session, invited_user=invitee)
        self.assertEqual(invite.method, SessionInvite.Method.IN_APP_LINK)


# ---------------------------------------------------------------------------
# SessionParticipant model tests
# ---------------------------------------------------------------------------

class SessionParticipantValidCreationTests(TestCase):
    def test_confirmed_participant_is_valid(self):
        session = make_session()
        user = make_user("p1")
        SessionParticipant(session=session, user=user, status=SessionParticipant.Status.CONFIRMED).full_clean()

    def test_waitlisted_participant_is_valid(self):
        session = make_session()
        user = make_user("p2")
        SessionParticipant(
            session=session, user=user, status=SessionParticipant.Status.WAITLISTED, position=1
        ).full_clean()


class SessionParticipantUniquenessTests(TestCase):
    def test_duplicate_participant_raises_integrity_error(self):
        session = make_session()
        user = make_user("dup")
        SessionParticipant.objects.create(session=session, user=user, status=SessionParticipant.Status.CONFIRMED)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SessionParticipant.objects.create(
                    session=session, user=user, status=SessionParticipant.Status.WAITLISTED, position=1
                )


class SessionParticipantStatusGuardTests(TestCase):
    def test_join_cancelled_session_raises(self):
        session = make_session(status=Session.Status.CANCELLED)
        user = make_user("p3")
        with self.assertRaises(ValidationError):
            SessionParticipant(session=session, user=user, status=SessionParticipant.Status.CONFIRMED).full_clean()

    def test_join_completed_session_raises(self):
        session = make_session(status=Session.Status.COMPLETED)
        user = make_user("p4")
        with self.assertRaises(ValidationError):
            SessionParticipant(session=session, user=user, status=SessionParticipant.Status.CONFIRMED).full_clean()

    def test_join_open_session_succeeds(self):
        session = make_session(status=Session.Status.OPEN)
        user = make_user("p5")
        SessionParticipant(session=session, user=user, status=SessionParticipant.Status.CONFIRMED).full_clean()


class SessionParticipantCreatorGuardTests(TestCase):
    def test_creator_cannot_join_own_session_raises(self):
        session = make_session()
        with self.assertRaises(ValidationError):
            SessionParticipant(
                session=session, user=session.creator, status=SessionParticipant.Status.CONFIRMED
            ).full_clean()


class SessionParticipantCapacityCeilingTests(TestCase):
    def test_confirmed_cannot_exceed_target_size(self):
        session = make_session(target_size=1)
        SessionParticipant.objects.create(session=session, user=make_user("filled1"), status=SessionParticipant.Status.CONFIRMED)
        with self.assertRaises(ValidationError):
            SessionParticipant(
                session=session, user=make_user("overbook1"), status=SessionParticipant.Status.CONFIRMED
            ).full_clean()

    def test_confirmed_at_exactly_target_size_is_the_last_valid_one(self):
        session = make_session(target_size=1)
        SessionParticipant(
            session=session, user=make_user("lastspot1"), status=SessionParticipant.Status.CONFIRMED
        ).full_clean()  # must not raise — this is the 1st of 1


class SessionParticipantPositionInvariantTests(TestCase):
    def test_confirmed_with_position_raises(self):
        session = make_session()
        with self.assertRaises(ValidationError):
            SessionParticipant(
                session=session, user=make_user("badpos1"), status=SessionParticipant.Status.CONFIRMED, position=1
            ).full_clean()

    def test_waitlisted_without_position_raises(self):
        session = make_session()
        with self.assertRaises(ValidationError):
            SessionParticipant(
                session=session, user=make_user("badpos2"), status=SessionParticipant.Status.WAITLISTED
            ).full_clean()

    def test_invariant_enforced_at_db_level_even_bypassing_clean(self):
        session = make_session()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SessionParticipant.objects.create(
                    session=session, user=make_user("badpos3"), status=SessionParticipant.Status.WAITLISTED, position=None
                )


class ConfirmedParticipantCountTests(TestCase):
    def test_counts_only_confirmed_rows(self):
        session = make_session()
        SessionParticipant.objects.create(session=session, user=make_user("c1"), status=SessionParticipant.Status.CONFIRMED)
        SessionParticipant.objects.create(session=session, user=make_user("c2"), status=SessionParticipant.Status.CONFIRMED)
        SessionParticipant.objects.create(session=session, user=make_user("w1"), status=SessionParticipant.Status.WAITLISTED, position=1)
        SessionParticipant.objects.create(session=session, user=make_user("l1"), status=SessionParticipant.Status.LEFT)
        self.assertEqual(session.get_confirmed_participant_count(), 2)


class SyncStatusTests(TestCase):
    def test_flips_open_to_full_at_target_size(self):
        session = make_session(target_size=1)
        SessionParticipant.objects.create(session=session, user=make_user("f1"), status=SessionParticipant.Status.CONFIRMED)
        session.sync_status()
        self.assertEqual(session.status, Session.Status.FULL)
        session.refresh_from_db()
        self.assertEqual(session.status, Session.Status.FULL)

    def test_flips_full_to_open_below_target_size(self):
        session = make_session(target_size=1, status=Session.Status.FULL)
        session.sync_status()
        self.assertEqual(session.status, Session.Status.OPEN)

    def test_noop_when_already_correct(self):
        session = make_session(target_size=2)
        session.sync_status()
        self.assertEqual(session.status, Session.Status.OPEN)

    def test_does_not_touch_cancelled(self):
        session = make_session(status=Session.Status.CANCELLED)
        session.sync_status()
        session.refresh_from_db()
        self.assertEqual(session.status, Session.Status.CANCELLED)

    def test_does_not_revert_a_concurrent_cancellation(self):
        session = make_session(target_size=1, status=Session.Status.OPEN)
        SessionParticipant.objects.create(session=session, user=make_user("racecancel1"), status=SessionParticipant.Status.CONFIRMED)
        # Simulate another request cancelling the session after this in-memory
        # `session` instance was loaded (still shows status=OPEN in memory).
        Session.objects.filter(pk=session.pk).update(status=Session.Status.CANCELLED)
        session.sync_status()
        session.refresh_from_db()
        self.assertEqual(session.status, Session.Status.CANCELLED)


class WaitlistPositionTests(TestCase):
    def test_next_waitlist_position_starts_at_one(self):
        session = make_session()
        self.assertEqual(session.next_waitlist_position(), 1)

    def test_next_waitlist_position_increments(self):
        session = make_session()
        SessionParticipant.objects.create(session=session, user=make_user("w2"), status=SessionParticipant.Status.WAITLISTED, position=1)
        SessionParticipant.objects.create(session=session, user=make_user("w3"), status=SessionParticipant.Status.WAITLISTED, position=2)
        self.assertEqual(session.next_waitlist_position(), 3)

    def test_recompact_waitlist_shifts_positions_after_removal(self):
        session = make_session()
        p1 = SessionParticipant.objects.create(session=session, user=make_user("w4"), status=SessionParticipant.Status.WAITLISTED, position=1)
        p2 = SessionParticipant.objects.create(session=session, user=make_user("w5"), status=SessionParticipant.Status.WAITLISTED, position=2)
        p3 = SessionParticipant.objects.create(session=session, user=make_user("w6"), status=SessionParticipant.Status.WAITLISTED, position=3)
        p2.status = SessionParticipant.Status.LEFT
        p2.position = None
        p2.save(update_fields=["status", "position"])
        session.recompact_waitlist(after_position=2)
        p1.refresh_from_db()
        p3.refresh_from_db()
        self.assertEqual(p1.position, 1)
        self.assertEqual(p3.position, 2)
