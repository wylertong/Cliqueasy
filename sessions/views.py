from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView

from .forms import InviteCategoryForm, InviteUsersForm, SessionForm
from .models import Session, SessionInvite


class HomeView(LoginRequiredMixin, TemplateView):
    template_name = "sessions/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # "My Sessions" (joined/waitlisted) needs SessionParticipant, which doesn't exist
        # until Phase 3 — the template renders a static placeholder for that section.
        context["open_to_join_sessions"] = (
            Session.objects.filter(
                Q(invites__invited_user=self.request.user)
                | Q(invites__invited_category__members__user=self.request.user)
            )
            .exclude(status=Session.Status.CANCELLED)
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
    # Phase 1 shows all fields plainly to any logged-in user — the spec's per-viewer
    # visibility rules (see "Implementation note: participant visibility") don't apply
    # until SessionParticipant exists and there's an actual roster to gate.

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.object.creator == self.request.user:
            context["invite_category_form"] = InviteCategoryForm(session=self.object)
            context["invite_users_form"] = InviteUsersForm(session=self.object)
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
