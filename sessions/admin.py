from django.contrib import admin

from .models import Session, SessionInvite, SessionParticipant

admin.site.register(Session)
admin.site.register(SessionInvite)
admin.site.register(SessionParticipant)
