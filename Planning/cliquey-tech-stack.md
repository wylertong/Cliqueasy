# Cliquey — Tech Stack

Companion to the MVP Spec — that document covers *what* the app does; this one covers *how* it's built and deployed.

## Language & Framework
- **Django** (Python), chosen over Next.js/React and Rails — best fit given prior experience in Java, C++, and some Python/R, and Django's built-in auth, ORM, admin panel, and scheduled-task patterns line up well with the MVP's needs (background jobs, email, no heavy frontend interactivity required)

## Local Development
- **Docker + Docker Compose** for a consistent local environment
- Two services: `web` (Django) and `db` (local Postgres container) — local dev talks to the Docker Postgres, **not** Supabase
- Known gotcha from prior Docker/Mac experience: bind-mount permission issues on the `.:/app` volume. Fix: `docker compose exec web chown -R $(id -u):$(id -g) .`

**Dockerfile:**
```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
```

**docker-compose.yml:**
```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: cliquey
      POSTGRES_USER: cliquey
      POSTGRES_PASSWORD: cliquey
    volumes:
      - pgdata:/var/lib/postgresql/data

  web:
    build: .
    command: python manage.py runserver 0.0.0.0:8000
    volumes:
      - .:/app
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      - db

volumes:
  pgdata:
```

## Project Directory Structure
One Django app per domain concept, mapping onto the MVP spec's entity groupings:
```
cliquey/
├── .env.example
├── .gitignore
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── manage.py
├── config/              # settings, urls, wsgi (renamed from Django's default project name)
├── accounts/            # User, auth, signup/login
├── sessions/            # Session, SessionParticipant, SessionInvite
├── categories/          # Category, CategoryMember
├── waitlist/            # WaitlistCascade, WaitlistOffer, cascade scheduler logic
├── notifications/       # Notification model + email-sending logic
├── templates/
└── static/
```

## Database
- **Supabase** (Postgres) for the deployed environment — permanent free tier, unlike Render's own free Postgres (which expires 30 days after creation)
- Use the **Session pooler** connection string from Supabase's Connect panel (not Transaction pooler — that's for serverless/short-lived connections — and not the direct connection, which can hit IPv6 connectivity issues on hosts without IPv6 support)
- `DATABASE_URL` env var: local dev points at the Docker `db` service; the deployed environment (Render) points at Supabase's pooler URL

## Hosting / Deployment
- **Render**, free web service tier
- Known limits: spins down after 15 minutes of inactivity (cold start ~1 min on next request); 750 free instance-hours per workspace per month
- Free-tier terms across all hosting providers change often — worth a quick check of Render's and Supabase's current pricing pages right before actually signing up, rather than trusting this doc blindly months later

## Scheduled Jobs (Waitlist Cascade + Underfilled Checks)
- Render's own cron jobs are **not** part of the free tier
- Workaround: expose a protected endpoint (e.g. `/internal/run-scheduled-checks/`, guarded by a secret token) that runs the cascade-expansion and 24h/3h underfilled-session checks when hit
- Use **cron-job.org** (free, unlimited jobs under fair use, 60-second minimum interval) to ping that endpoint every minute
- Side benefit: the same ping keeps the Render free web service from spinning down, since pings arrive well within the 15-minute inactivity window

## Email
- Free-tier transactional email provider — **Resend** (3,000/month), **Brevo** (300/day), or **SendGrid** (100/day); any comfortably covers MVP volume
- **django-anymail** for Django integration
- Every notification type in the spec is emailed — no in-app-only tier, no SMS in v1 (SMS via Twilio deferred to Phase 2+)

## Frontend / Styling
- **Django templates** rendering server-side, no separate frontend framework
- **HTMX** for the interactive bits (join button, waitlist updates) without needing to learn React
- **Tailwind CSS via CDN script tag** (`<script src="https://cdn.tailwindcss.com"></script>`) rather than the full `django-tailwind` + npm build pipeline — zero build step, appropriate given limited Tailwind experience and no other JS tooling needs. Trade-off: ships the full unminified compiler and logs a "not for production" console warning; fine at MVP scale, and migrating to a real build pipeline later doesn't require changing any class names or templates

## Static Files
- **WhiteNoise** — serves CSS/JS directly from the Django app on Render, no separate CDN or S3 bucket needed

## Auth
- Django's built-in auth system — no third-party auth provider (e.g. Auth0) needed for this scope

## Testing
- Django's built-in test framework
- Worth prioritizing tests for the waitlist cascade logic specifically (mode switching, superseded offers, target-size validation) — that's the most intricate business logic in the spec, and the easiest to accidentally break with an unrelated change

## Version Control
- GitHub. GitHub Actions is a natural (optional) next step for CI once there's something worth automating, but not essential to set up before the MVP works

## Dependency Philosophy
Start minimal and add packages only when the feature that needs them is actually being built, rather than pre-installing everything up front:
```
Django>=5.0,<6.0
psycopg2-binary
django-environ
```
Then add `django-anymail` when building the notifications app, and nothing else until a specific need comes up.
