---
name: verify
description: Build/launch/drive recipe for manually verifying Cliquey (Django) changes through the real running app.
---

# Verifying Cliquey end-to-end

Cliquey has no frontend build step (server-rendered Django templates, Tailwind via CDN) — the dev server at `localhost:8000` *is* the app.

## Launch

```bash
docker compose up -d --build   # Postgres + Django dev server
```
If Docker's daemon isn't running: `open -a Docker` then poll `docker info` until it succeeds (takes ~20-30s cold).

## Seed test users

Fastest path is the Django shell, not the signup form (signup itself isn't usually what you're verifying):
```bash
docker compose exec web python manage.py shell -c "
from django.contrib.auth import get_user_model
U = get_user_model()
U.objects.create_user(username='verify_x', email='verify_x@example.com', password='verifypass123')
"
```

## Drive it via curl (no browser needed)

Django's CSRF protection means every POST needs a token scraped from a prior GET on the same cookie jar. Pattern, one cookie jar per logged-in user:

```bash
JAR=/tmp/someuser.jar
csrf=$(curl -s -c "$JAR" -b "$JAR" "http://localhost:8000/accounts/login/" \
  | grep -o 'name="csrfmiddlewaretoken" value="[^"]*"' | sed 's/.*value="//;s/"$//')
curl -s -c "$JAR" -b "$JAR" -d "csrfmiddlewaretoken=$csrf&username=verify_x&password=verifypass123" \
  -e "http://localhost:8000/accounts/login/" "http://localhost:8000/accounts/login/"
```
Then for any subsequent POST (join/leave/invite/etc.), re-scrape a fresh CSRF token from a GET on the target page (or the page that renders the form) before posting, using the same jar.

Useful checks:
- `-D -` on the POST prints response headers (watch `Location:` for redirects, status code).
- Django `messages` are one-time — they render on the *next* page load only, then vanish. Check the response body of the immediate redirect target, not a second later fetch.
- `date_time` fields need the exact format the form expects: `%Y-%m-%dT%H:%M` (e.g. `2026-12-01T10:00`).

## Gotchas specific to this app

- `sessions` app's Django `app_label` is `tennis_sessions` — `makemigrations sessions` silently no-ops; use `makemigrations tennis_sessions`.
- No JS anywhere — every mutating action is a plain `<form method="post">`, so curl-driven verification covers the real UI faithfully (no headless browser needed for logic checks). Only reach for a real browser if verifying Tailwind layout/visual details.
