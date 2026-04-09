# VoN

VoN is a Django-based B2B procurement platform built for buyers, suppliers, and administrators. The project combines a REST API, a browser-based SPA frontend, Django Admin, background task processing with Celery, and a set of operational integrations that make the diploma project look and behave closer to a commercial system than a учебный шаблон.

The system is API-first, but it also includes a ready-to-run UI at the root route `/` and a production-style admin panel for operational workflows.

## Core Functional Areas

### Authentication and Accounts

The platform supports multiple authentication flows:

- local registration with email confirmation token
- token-based login for API access
- password reset via `django-rest-passwordreset`
- social login through Google and GitHub
- DRF token bridge after successful OAuth login, so the frontend continues to work with the same token auth scheme as the REST API

New social-auth users are treated as verified users and activated on first successful OAuth callback. Existing local accounts can be associated by email through the social-auth pipeline.

### Catalog and Ordering

Buyers can:

- browse categories, shops, and product offers
- filter catalog data by shop and category
- add items to basket
- update basket quantities and remove positions
- create an order from basket with a delivery contact
- view completed orders and their statuses

Suppliers can:

- import goods from a remote YAML price list
- enable or disable order intake
- view supplier-specific orders

### Admin and Operations

The admin panel is enhanced beyond the default Django setup:

- Baton theme is enabled for improved navigation and presentation
- suppliers can import a price list through a dedicated admin page
- user avatars and product images are visible in admin previews
- search fields and list filters are tuned for day-to-day operations

Operational tooling includes:

- Swagger and OpenAPI schema generation through `drf-spectacular`
- throttling on sensitive authentication endpoints
- Sentry integration for Django and Celery, guarded by environment configuration
- a dedicated admin-only endpoint to trigger a test exception and verify error ingestion

### Background Tasks and Media

Celery and Redis are used for asynchronous processing. If the broker is unavailable, the project falls back to synchronous execution for supported tasks instead of failing hard.

Asynchronous tasks currently cover:

- email delivery
- supplier price-list import
- thumbnail generation for user avatars and product images

Media processing uses `easy-thumbnails`, and the project prepares multiple aliases for user and product images.

### Caching

The project uses two layers of caching:

- manual response caching for `/api/v1/products`
- ORM-level query caching through `django-cachalot`

If `CACHE_URL` is configured, Redis is used as the cache backend. Otherwise the project falls back to local in-memory cache for development.

## Technology Stack

- Python 3.14
- Django 5.2
- Django REST Framework
- drf-spectacular
- Celery
- Redis
- social-auth-app-django
- django-baton
- easy-thumbnails
- Pillow
- sentry-sdk
- django-cachalot
- SQLite by default

## Project Structure

```text
backend/                 domain models, API views, serializers, admin, tasks, signals, tests
backend/migrations/      database migrations
netology_pd_diplom/      Django settings, root URLs, Celery bootstrap
templates/frontend/      SPA frontend template
templates/admin/         custom admin pages
data/                    sample import files
manage.py                Django entry point
Dockerfile               container image definition
docker-compose.yml       local service composition
.env.example             required environment variables
```

## Main Routes

### Frontend and Admin

- `/` - SPA frontend
- `/admin/` - Django Admin
- `/admin/backend/shop/import/` - custom supplier import page
- `/baton/` - Baton admin routes

### API Documentation

- `/api/schema/` - OpenAPI schema
- `/api/schema/swagger-ui/` - Swagger UI
- `/api/schema/redoc/` - ReDoc

### Authentication

- `POST /api/v1/user/register`
- `POST /api/v1/user/register/confirm`
- `POST /api/v1/user/login`
- `POST /api/v1/user/password_reset`
- `POST /api/v1/user/password_reset/confirm`
- `/auth/login/google-oauth2/`
- `/auth/login/github/`
- `/auth/token-bridge/`

### Catalog and Orders

- `GET /api/v1/categories`
- `GET /api/v1/shops`
- `GET /api/v1/products`
- `GET /api/v1/basket`
- `POST /api/v1/basket`
- `PUT /api/v1/basket`
- `DELETE /api/v1/basket`
- `GET /api/v1/order`
- `POST /api/v1/order`

### Supplier API

- `POST /api/v1/partner/update`
- `GET /api/v1/partner/state`
- `POST /api/v1/partner/state`
- `GET /api/v1/partner/orders`

### Operations

- `GET /api/v1/debug/sentry`

## Environment Variables

Copy `.env.example` into your local environment configuration and set values as needed.

Required operational variables:

- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG`
- `DJANGO_ALLOWED_HOSTS`
- `FRONTEND_URL`
- `ADMIN_EMAIL`
- `EMAIL_BACKEND`
- `CELERY_BROKER_URL`
- `CELERY_RESULT_BACKEND`
- `CACHE_URL`
- `CACHALOT_TIMEOUT`
- `SENTRY_DSN`
- `SENTRY_ENVIRONMENT`
- `SENTRY_TRACES_SAMPLE_RATE`
- `SOCIAL_AUTH_GOOGLE_OAUTH2_KEY`
- `SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET`
- `SOCIAL_AUTH_GITHUB_KEY`
- `SOCIAL_AUTH_GITHUB_SECRET`

If Sentry DSN or OAuth credentials are missing, the project still starts. The related integrations simply remain inactive or incomplete until valid credentials are provided.

## Local Run

### Windows without venv activation

```powershell
cd D:\net0ology\diplom
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe manage.py migrate
.\venv\Scripts\python.exe manage.py runserver
```

### Windows with activated venv

If PowerShell blocks `Activate.ps1`, allow it for the current shell session:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

### Celery Worker

```powershell
.\venv\Scripts\python.exe -m celery -A netology_pd_diplom worker -l info
```

### Redis

Redis is required for production-style Celery and cache execution. For local development without Redis, some flows still work thanks to graceful fallbacks, but Celery queueing and Redis-backed caching will not be active.

## Docker

```powershell
docker compose up --build
```

Services:

- `web` - Django application
- `redis` - Redis broker and cache
- `celery` - background worker

Stop services:

```powershell
docker compose down
```

## Media and Thumbnails

The application stores uploaded media under `MEDIA_ROOT`. Thumbnail aliases configured in settings:

- `avatar_small`
- `avatar_medium`
- `product_small`
- `product_medium`

Thumbnails are generated asynchronously after saving user avatars and product images.

## Monitoring and Verification

If `SENTRY_DSN` is configured, Sentry is initialized for both Django and Celery. To verify the integration:

1. Log in as an admin user.
2. Open `/api/v1/debug/sentry`.
3. Confirm the forced exception appears in Sentry.

This endpoint is intentionally restricted to admins.

## Throttling

Configured throttling scopes:

- `login`: `5/minute`
- `register`: `3/minute`
- `confirm`: `5/minute`

The project includes an automated test that verifies the login endpoint returns HTTP `429` after exceeding the configured rate.

## Testing

System check:

```powershell
.\venv\Scripts\python.exe manage.py check
```

Run test suite:

```powershell
.\venv\Scripts\python.exe manage.py test backend.tests
```

Generate and validate OpenAPI schema:

```powershell
.\venv\Scripts\python.exe manage.py spectacular --file schema.yml --validate
```

## Demo Credentials

If your local database already contains demonstration records, these credentials may be available:

- admin: `admin@admin.com` / `AdminPass123!`
- supplier: `supplier@demo.local` / `DemoPass123!`
- buyer: `buyer@demo.local` / `DemoPass123!`

If the admin password is unknown:

```powershell
.\venv\Scripts\python.exe manage.py changepassword admin@admin.com
```

## Security and Reliability Notes

The project includes several defensive improvements:

- remote YAML import uses `requests.get(..., timeout=10)`
- import responses are validated with `raise_for_status()`
- YAML from external sources is parsed with `safe_load`
- Celery task dispatch falls back to synchronous execution when the broker is unavailable
- sensitive auth endpoints are throttled
- operational secrets and third-party credentials are moved to environment variables

## Change Log

### 2026-04-09

- moved runtime configuration to environment variables and added `.env.example`
- pinned project dependencies in `requirements.txt`
- connected Google and GitHub social authentication through `social-auth-app-django`
- added a local token bridge to return OAuth-authenticated users back into the SPA token flow
- enabled Baton and restyled the admin area under the VoN brand
- added media fields for user avatars and product images
- configured thumbnail aliases and asynchronous thumbnail warmup
- integrated Sentry initialization for Django and Celery
- enabled `django-cachalot` alongside existing manual product-response caching
- expanded automated tests for social auth, admin access, cache behavior, media signals, and Sentry debug endpoint

### 2026-04-03

- redesigned the frontend interface and renamed the product to VoN
- connected OpenAPI generation and Swagger UI
- added DRF throttling for authentication endpoints
- improved APIView documentation for Swagger and developer onboarding

### 2026-04-02

- hardened supplier import by adding timeout, status validation, and safe YAML loading
- improved import fallback behavior when Celery broker is unavailable
- updated admin-side supplier import workflow
