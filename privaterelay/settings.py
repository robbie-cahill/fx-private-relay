"""
Django settings for privaterelay project.

Generated by 'django-admin startproject' using Django 2.2.2.

For more information on this file, see
https://docs.djangoproject.com/en/2.2/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/2.2/ref/settings/
"""

import os

from decouple import config

import django_heroku

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/2.2/howto/deployment/checklist/

# defaulting to blank to be production-broken by default
SECRET_KEY = config('SECRET_KEY', None)

DEBUG = config('DEBUG', False)

# Honor the 'X-Forwarded-Proto' header for request.is_secure()
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_HOST = config('DJANGO_SECURE_SSL_HOST', None)
SECURE_SSL_REDIRECT = config('DJANGO_SECURE_SSL_REDIRECT', False)
SECURE_HSTS_SECONDS = config('DJANGO_SECURE_HSTS_SECONDS', None)
SECURE_CONTENT_TYPE_NOSNIFF = config('DJANGO_SECURE_CONTENT_TYPE_NOSNIFF',
                                     True)
SECURE_BROWSER_XSS_FILTER = config('DJANGO_SECURE_BROWSER_XSS_FILTER', True)
CSP_DEFAULT_SRC = ("'none'",)
CSP_SCRIPT_SRC = ("'self'", "https://unpkg.com")
CSP_STYLE_SRC = ("'self'", "https://unpkg.com")
CSP_IMG_SRC = ("'self'", config('FXA_PROFILE_ENDPOINT', 'https://profile.accounts.firefox.com/v1'), "https://unpkg.com", "https://placehold.it")
REFERRER_POLICY = 'strict-origin-when-cross-origin'

ALLOWED_HOSTS = []


# Get our backing resource configs to check if we should install the app
ADMIN_ENABLED = config('ADMIN_ENABLED', None)
SOCKETLABS_SERVER_ID = config('SOCKETLABS_SERVER_ID', None, cast=int)
SOCKETLABS_API_KEY = config('SOCKETLABS_API_KEY', None)
TWILIO_ACCOUNT_SID = config('TWILIO_ACCOUNT_SID', None)
TWILIO_AUTH_TOKEN = config('TWILIO_AUTH_TOKEN', None)

# Application definition

INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.sites',
    'django.contrib.staticfiles',

    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.fxa',
]

if ADMIN_ENABLED:
    INSTALLED_APPS += [
        'django.contrib.admin',
    ]

if SOCKETLABS_API_KEY:
    INSTALLED_APPS += [
        'emails.apps.EmailsConfig',
    ]

if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
    INSTALLED_APPS += [
        'phones.apps.PhonesConfig',
    ]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',

    'csp.middleware.CSPMiddleware',
    'django_referrer_policy.middleware.ReferrerPolicyMiddleware',
]

ROOT_URLCONF = 'privaterelay.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            os.path.join(BASE_DIR, 'privaterelay', 'templates'),
        ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'privaterelay.wsgi.application'


# Database
# https://docs.djangoproject.com/en/2.2/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
    }
}


# Password validation
# https://docs.djangoproject.com/en/2.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/2.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_L10N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/2.2/howto/static-files/

STATIC_URL = '/static/'

STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),
]

SITE_ID = 1

AUTHENTICATION_BACKENDS = (
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
)

SOCIALACCOUNT_PROVIDERS = {
    'fxa': {
        # Note: to request "profile" scope, must be a trusted Mozilla client
        'SCOPE': ['profile'],
        'OAUTH_ENDPOINT': config('FXA_OAUTH_ENDPOINT', 'https://oauth.accounts.firefox.com/v1'),
        'PROFILE_ENDPOINT': config('FXA_PROFILE_ENDPOINT', 'https://profile.accounts.firefox.com/v1'),
    }
}

SOCIALACCOUNT_EMAIL_VERIFICATION = 'none'

django_heroku.settings(locals())
