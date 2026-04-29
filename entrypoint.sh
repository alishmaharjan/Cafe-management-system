#!/bin/sh
set -e

echo "==> Running migrations..."
python /app/manage.py migrate --noinput

echo "==> Seeding tables and menu..."
python /app/manage.py setup_tables
python /app/manage.py seed_menu

echo "==> Collecting static files..."
python /app/manage.py collectstatic --noinput --clear

echo "==> Starting Gunicorn..."
exec gunicorn cafe_system.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 2 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
