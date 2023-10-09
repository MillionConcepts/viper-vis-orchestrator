from pathlib import Path

from viper_orchestrator.config import MEDIA_ROOT

BASE_DIR = Path(__file__).resolve().parent.parent

# TODO: unsuitable for production
SECRET_KEY = "11111"

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

# TODO: will be modified depending on specific architecture
ALLOWED_HOSTS = []

# Application definition

INSTALLED_APPS = [
    # "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "viper_orchestrator.visintent.tracking"
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "viper_orchestrator.visintent.visintent.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "visintent.wsgi.application"


# TODO: will use postgres later in dev
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True

# TODO: unknown where we're actually writing these.
# TODO, maybe: put this behind gunicorn/nginx. note that the canonical
#  external-server methods are strictly not available to us, malicious actions
#  by internal users are not considered a major source of risk, and this
#  application will never face the Internet. It is a question of efficiency
#  only.
# TODO, alternatively: we may need to interact with a preexisting Apache server
#  or something in some way, so don't make this decision as of yet.
MEDIA_URL = "media/"
STATICFILES_DIRS = [Path(BASE_DIR) / "static_dev"]
STATIC_ROOT = Path(BASE_DIR) / "static_pro"
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

