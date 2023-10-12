from pathlib import Path
from random import randbytes

from viper_orchestrator.config import MEDIA_ROOT, TEST, STATIC_ROOT

TEST_SECRET_KEY = "11111"
PROD_SECRET_KEY_PATH = Path(__file__).resolve().parent / "secrets/SECRET_KEY"


def read_prod_secret_key():
    with PROD_SECRET_KEY_PATH.open() as stream:
        return stream.read()


def get_prod_secret_key():
    try:
        return read_prod_secret_key()
    except FileNotFoundError:
        PROD_SECRET_KEY_PATH.parent.mkdir(exist_ok=True)
        with PROD_SECRET_KEY_PATH.open("w") as stream:
            stream.write(str(randbytes(20)))
        return read_prod_secret_key()


PROD_SECRET_KEY = get_prod_secret_key()
SECRET_KEY = TEST_SECRET_KEY if TEST is True else PROD_SECRET_KEY

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


# note that this doesn't actually matter at all because we're not using the
# django ORM or IAM or anything, it's just to keep django from whining about
# not having a db
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": Path(__file__).parent.parent / "db.sqlite3",
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

MEDIA_URL = "media/"

STATIC_URL = "assets/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
STATICFILES_DIRS = [Path(__file__).parent.parent / "static_dev"]
