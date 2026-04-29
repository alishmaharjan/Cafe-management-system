from django.core.management.base import BaseCommand
from core.models import Table


class Command(BaseCommand):
    help = 'Create the 17 tables for Chiya Garden'

    def handle(self, *args, **options):
        created = 0
        for i in range(1, 18):
            name = f'T{i:02d}'
            _, was_created = Table.objects.get_or_create(name=name, defaults={'capacity': 4})
            if was_created:
                created += 1
        self.stdout.write(self.style.SUCCESS(f'Done — {created} new tables created, {17 - created} already existed.'))
