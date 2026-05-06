from pathlib import Path

BASE_DIR  = Path(__file__).parent.parent        # /home/coder/server
ROOT_DIR  = BASE_DIR.parent                     # /home/coder
DATA_DIR  = ROOT_DIR / "data"
MODEL_DIR = ROOT_DIR / "model"

SECRET_KEY = "btc-dashboard-dev-secret-key-change-in-prod"
DEBUG      = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "daphne",
    "django.contrib.staticfiles",
    "channels",
    "dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "btc_dashboard.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": [
            "django.template.context_processors.request",
        ]},
    },
]

ASGI_APPLICATION = "btc_dashboard.asgi.application"

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }
}

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

STATIC_URL  = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
