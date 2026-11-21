#!/bin/sh
set -e

# In a multi-instance deployment (ECS/EKS/ASG) run migrations as a one-off job
# and set RUN_MIGRATIONS=0 on the web containers.
if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  python manage.py migrate --noinput
fi

exec gunicorn banking_project.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers "${WEB_CONCURRENCY:-3}" \
  --timeout 30 \
  --access-logfile - \
  --error-logfile -
