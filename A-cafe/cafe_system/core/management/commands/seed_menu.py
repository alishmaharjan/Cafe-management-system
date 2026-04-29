from django.core.management.base import BaseCommand
from core.models import Category, Product

MENU = {
    'Black Chiya': [
        ('Black Tea', 20),
        ('Masala Black Chiya', 40),
        ('Black Marich Chiya', 30),
        ('Ginger Black Tea', 30),
        ('Lemon Chiya', 30),
        ('Lemon Grass Chiya', 30),
    ],
    'Milk Chiya': [
        ('Classic Chiya', 30),
        ('Masala Chiya', 50),
        ('Ginger Milk Chiya', 40),
        ('Peach Tea', 60),
        ('Cold Peach Iced Tea', 120),
        ('Green Tea', 50),
    ],
    'Coffee': [
        ('Black Coffee', 60),
        ('Black Cold Coffee', 120),
        ('Milk Coffee', 100),
        ('Milk Cold Coffee', 150),
        ('Strong Black Coffee', 80),
    ],
    'Lemon Drinks': [
        ('Cold Lemon', 50),
        ('Cold Lemon with Ice', 80),
        ('Hot Lemon', 60),
        ('Hot Lemon with Honey', 100),
        ('Hot Lemon with H & G', 120),
        ('Lemon Sprite', 90),
        ('Lemon Soda', 90),
    ],
    'Lassi': [
        ('Plain Lassi', 120),
        ('Banana Lassi', 150),
    ],
    'Chiya ko Sathi': [
        ('Aalu Chop', 120),
        ('Pakoda', 120),
        ('Samosa (per pc)', 30),
    ],
    'Sadeko': [
        ('Wai Wai Sadeko', 120),
        ('Badam Sadeko', 150),
        ('Bhatmas Sadeko', 150),
        ('Sausage Sadeko', 180),
        ('Chicken Sadeko', 250),
        ('Sukuti Sadeko', 280),
    ],
    'Veg Fry': [
        ('French Fry', 120),
        ('Masala French Fry', 150),
        ('Slim Chips Fry', 80),
        ('Garlic (Lasun) Fry', 120),
    ],
    'Chilly': [
        ('Buff Chilly', 280),
        ('Pork Chilly', 350),
        ('Chicken Chilly', 300),
        ('Sausage Chilly', 200),
        ('French Fry Chilly', 150),
    ],
    'Meat & Fry': [
        ('Pork Fry', 320),
        ('Chicken Fry', 270),
        ('Pork Tawa', 350),
        ('Chicken Tawa', 300),
        ('Sausage Fry Buff (per pc)', 45),
        ('Sausage Fry Chicken (per pc)', 55),
        ('Chicken Drumstick (per pc)', 120),
        ('Chicken Drumstick Plate 3pc', 350),
        ('Chicken Lollipop (per pc)', 60),
        ('Chicken Lollipop Plate 6pc', 350),
    ],
    'MoMo': [
        ('Buff Steam MoMo', 120),
        ('Buff Fry MoMo', 150),
        ('Buff C.MoMo', 180),
        ('Buff Jhol MoMo', 150),
        ('Chicken Steam MoMo', 150),
        ('Chicken Fry MoMo', 180),
        ('Chicken C.MoMo', 210),
        ('Chicken Jhol MoMo', 180),
        ('Kurkure MoMo Buff', 200),
        ('Kurkure MoMo Chicken', 250),
    ],
    'Noodles': [
        ('Chowmien Veg', 100),
        ('Chowmien Egg', 140),
        ('Chowmien Buff', 150),
        ('Chowmien Chicken', 180),
        ('Chowmien Pork', 200),
        ('Chowmien Mix', 300),
        ('Thukpa Veg', 120),
        ('Thukpa Egg', 150),
        ('Thukpa Buff', 180),
        ('Thukpa Chicken', 200),
        ('Thukpa Pork', 240),
        ('Thukpa Mix', 350),
        ('Keema Noodles Veg', 140),
        ('Keema Noodles Egg', 160),
        ('Keema Noodles Buff', 180),
        ('Keema Noodles Chicken', 200),
    ],
    'Fried Rice': [
        ('Fried Rice Veg', 100),
        ('Fried Rice Egg', 150),
        ('Fried Rice Buff', 150),
        ('Fried Rice Chicken', 180),
        ('Fried Rice Pork', 220),
        ('Fried Rice Mix', 300),
    ],
    'Soft Drinks': [
        ('Coke', 70),
        ('Fanta', 70),
        ('Soda', 70),
        ('Slice', 80),
        ('Real Juice', 30),
    ],
    'Energy Drinks': [
        ('Red Bull', 140),
        ('X-Treme', 140),
    ],
}


class Command(BaseCommand):
    help = 'Seed the full Chiya Garden menu (categories + products)'

    def handle(self, *args, **options):
        cat_new = 0
        prod_new = 0
        prod_skip = 0

        for cat_name, items in MENU.items():
            cat, created = Category.objects.get_or_create(
                name=cat_name,
                defaults={'is_active': True},
            )
            if created:
                cat_new += 1
                self.stdout.write(f'  + Category: {cat_name}')

            for prod_name, price in items:
                prod, p_created = Product.objects.get_or_create(
                    name=prod_name,
                    defaults={
                        'category': cat,
                        'price': price,
                        'tax_percent': 0,
                        'is_active': True,
                    },
                )
                if p_created:
                    prod_new += 1
                else:
                    prod_skip += 1

        self.stdout.write(self.style.SUCCESS(
            f'\nDone — {cat_new} categories, {prod_new} products created, {prod_skip} already existed.'
        ))
