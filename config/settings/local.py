from .base import *
import environ

env = environ.Env()

DEBUG = True

DATABASES = {
    'default': env.db('DATABASE_URL')
}
