from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView

from .forms import InviteCategoryForm, InviteUsersForm, SessionForm
from .models import Session, SessionInvite, SessionParticipant


class HomeView(LoginRequiredMixin, TemplateView):
    template_name = "sessions/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Unlike open_to_join_sessions below, intentionally NOT excluding
        # cancelled/completed — "My Sessions" is roster history, not just
        # active invites; seeing that a session you joined got cancelled is
        # still meaningful. Locked in by HomeViewMySessionsTests.
        context["my_sessions"] = Session.objects.filter(
            participants__user=self.request.user,
            participants__status__in=[SessionParticipant.Status.CONFIRMED, SessionParticipant.Status.WAITLISTED],
        ).distinct()
        context["open_to_join_sessions"] = (
            Session.objects.filter(
                Q(invites__invited_user=self.request.user)
                | Q(invites__invited_category__members__user=self.request.user)
            )
            .exclude(status__in=[Session.Status.CANCELLED, Session.Status.COMPLETED])
            .exclude(creator=self.request.user)
            .distinct()
        )
        return context


class SessionListView(LoginRequiredMixin, ListView):
    model = Session
    template_name = "sessions/session_list.html"
    context_object_name = "sessions"


class SessionDetailView(LoginRequiredMixin, DetailView):
    model = Session
    template_name = "sessions/session_detail.html"
    # The roster is shown plainly to any logged-in viewer regardless of their
    # relationship to the session — the spec's per-viewer visibility rules (see
    # "Implementation note: participant visibility") are a separate follow-up.

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.object.creator == self.request.user:
            context["invite_category_form"] = InviteCategoryForm(session=self.object)
            context["invite_users_form"] = InviteUsersForm(session=self.object)
        context["confirmed_participants"] = self.object.participants.select_related("user").filter(
            status=SessionParticipant.Status.CONFIRMED
        ).order_by("created_at")
        context["waitlisted_participants"] = self.object.participants.select_related("user").filter(
            status=SessionParticipant.Status.WAITLISTED
        ).order_by("position")
        context["confirmed_count"] = context["confirmed_participants"].count()
        context["viewer_participant"] = self.object.participants.filter(
            user=self.request.user,
            status__in=[SessionParticipant.Status.CONFIRMED, SessionParticipant.Status.WAITLISTED],
        ).first()
        context["is_full"] = not self.object.has_open_confirmed_slot()
        return context


class SessionCreateView(LoginRequiredMixin, CreateView):
    model = Session
    form_class = SessionForm
    template_name = "sessions/session_form.html"

    def form_valid(self, form):
        form.instance.creator = self.request.user
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy("sessions:session_detail", args=[self.object.pk])


class SessionUpdateView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    model = Session
    form_class = SessionForm
    template_name = "sessions/session_form.html"

    def test_func(self):
        return self.get_object().creator == self.request.user

    def get_success_url(self):
        return reverse_lazy("sessions:session_detail", args=[self.object.pk])


class InviteCategoryView(LoginRequiredMixin, View):
    def post(self, request, pk):
        session = get_object_or_404(Session, pk=pk, creator=request.user)
        form = InviteCategoryForm(request.POST, session=session)
        if form.is_valid():
            invite = SessionInvite(session=session, invited_category=form.cleaned_data["category"])
            try:
                invite.full_clean()
            except ValidationError as e:
                messages.error(request, " ".join(e.messages))
            else:
                invite.save()
        return redirect("sessions:session_detail", pk=session.pk)


class InviteUsersView(LoginRequiredMixin, View):
    def post(self, request, pk):
        session = get_object_or_404(Session, pk=pk, creator=request.user)
        form = InviteUsersForm(request.POST, session=session)
        if form.is_valid():
            for invited_user in form.cleaned_data["users"]:
                invite = SessionInvite(session=session, invited_user=invited_user)
                try:
                    invite.full_clean()
                except ValidationError as e:
                    messages.error(request, " ".join(e.messages))
                    break
                invite.save()
        return redirect("sessions:session_detail", pk=session.pk)


class SessionJoinView(LoginRequiredMixin, View):
    def post(self, request, pk):
        with transaction.atomic():
            # Locks the session row for the duration of this request, serializing
            # every join/leave/remove against it — this is what prevents
            # concurrent joins from overbooking a session, duplicate waitlist
            # positions, and the race behind double-submit crashes (see
            # Planning/session-participant-review-findings.md #1, #4, #7).
            session = get_object_or_404(Session.objects.select_for_update(), pk=pk)

            if session.is_locked:
                messages.error(request, "This session is cancelled or completed and can no longer be joined.")
                return redirect("sessions:session_detail", pk=session.pk)

            if request.user == session.creator:
                messages.error(request, "You can't join a session you created.")
                return redirect("sessions:session_detail", pk=session.pk)

            existing = SessionParticipant.objects.filter(session=session, user=request.user).first()
            if existing and existing.status in (SessionParticipant.Status.CONFIRMED, SessionParticipant.Status.WAITLISTED):
                messages.info(request, "You're already in this session.")
                return redirect("sessions:session_detail", pk=session.pk)

            has_room = session.has_open_confirmed_slot()

            if not has_room and "confirm_waitlist" not in request.POST:
                # Don't create/mutate anything yet — this is the confirmation step
                # rendered directly as the response body of this POST.
                return render(request, "sessions/session_join_confirm.html", {"session": session})

            participant = existing or SessionParticipant(session=session, user=request.user)
            if has_room:
                participant.status = SessionParticipant.Status.CONFIRMED
                participant.position = None
            else:
                participant.status = SessionParticipant.Status.WAITLISTED
                participant.position = session.next_waitlist_position()

            try:
                participant.full_clean()
            except ValidationError as e:
                messages.error(request, " ".join(e.messages))
                return redirect("sessions:session_detail", pk=session.pk)

            try:
                participant.save()
            except IntegrityError:
                # Defensive insurance alongside the row lock above — treat a
                # duplicate-row race the same as the "already in this session"
                # branch rather than surfacing a 500.
                messages.info(request, "You're already in this session.")
                return redirect("sessions:session_detail", pk=session.pk)

            session.sync_status()

            if has_room:
                messages.success(request, "You're in!")
            else:
                messages.success(request, "Session is full — you've been added to the waitlist.")
            return redirect("sessions:session_detail", pk=session.pk)


class SessionLeaveView(LoginRequiredMixin, View):
    def post(self, request, pk):
        with transaction.atomic():
            session = get_object_or_404(Session.objects.select_for_update(), pk=pk)
            participant = SessionParticipant.objects.filter(
                session=session, user=request.user,
                status__in=[SessionParticipant.Status.CONFIRMED, SessionParticipant.Status.WAITLISTED],
            ).first()
            if participant is None:
                messages.error(request, "You're not an active participant in this session.")
                return redirect("sessions:session_detail", pk=session.pk)

            participant.session = session  # reuse the already-locked instance
            participant.deactivate(SessionParticipant.Status.LEFT)

            messages.success(request, "You've left the session.")
            return redirect("sessions:session_detail", pk=session.pk)


class SessionRemoveParticipantView(LoginRequiredMixin, View):
    def post(self, request, pk, participant_pk):
        with transaction.atomic():
            session = get_object_or_404(Session.objects.select_for_update(), pk=pk, creator=request.user)
            participant = get_object_or_404(SessionParticipant, pk=participant_pk, session=session)

            if participant.status not in (SessionParticipant.Status.CONFIRMED, SessionParticipant.Status.WAITLISTED):
                messages.error(request, "This participant is no longer active in the session.")
                return redirect("sessions:session_detail", pk=session.pk)

            participant.session = session  # reuse the already-locked instance
            participant.deactivate(SessionParticipant.Status.REMOVED)

            messages.success(request, f"Removed {participant.user} from the session.")
            return redirect("sessions:session_detail", pk=session.pk)
