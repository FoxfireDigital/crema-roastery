#!/bin/sh
set -eu
cd /srv
python manage.py migrate --noinput
python bootstrap.py
exec gunicorn --workers 2 --threads 2 --bind 0.0.0.0:8000 --access-logfile - --access-logformat '%(h)s %(m)s %(U)s %(s)s %(L)s' project_wsgi:application
