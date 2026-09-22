from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from .forms import SessionForm
from .models import Session


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
