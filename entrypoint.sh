#!/bin/sh
set -e

echo "==> Waiting for PostgreSQL..."
python << 'PYEOF'
import os, sys, time
import psycopg2

for attempt in range(30):
    try:
        psycopg2.connect(
            host=os.environ.get('DB_HOST', 'db'),
            dbname=os.environ.get('DB_NAME', 'chiya_garden'),
            user=os.environ.get('DB_USER', 'chiya'),
            password=os.environ.get('DB_PASSWORD', ''),
            port=int(os.environ.get('DB_PORT', 5432)),
        ).close()
        print("  PostgreSQL is ready.")
        sys.exit(0)
    except psycopg2.OperationalError:
        print(f"  Not ready yet, retrying ({attempt + 1}/30)...")
        time.sleep(2)

print("  ERROR: PostgreSQL did not become ready in time.")
sys.exit(1)
PYEOF

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
