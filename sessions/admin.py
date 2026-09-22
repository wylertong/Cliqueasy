from django.contrib import admin

from .models import Session, SessionInvite

admin.site.register(Session)
admin.site.register(SessionInvite)
