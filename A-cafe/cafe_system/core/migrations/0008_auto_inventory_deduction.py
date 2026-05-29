# Generated manually for automatic inventory deduction feature

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_credit_system'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='current_qty',
            field=models.DecimalField(decimal_places=3, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name='product',
            name='min_qty_alert',
            field=models.DecimalField(decimal_places=3, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name='product',
            name='product_type',
            field=models.CharField(
                choices=[('direct_sale', 'Direct Sale'), ('recipe_based', 'Recipe Based')],
                default='recipe_based',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='order',
            name='inventory_deducted',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='inventorymovement',
            name='deduction_source',
            field=models.CharField(blank=True, default='', max_length=20),
        ),
        migrations.AddConstraint(
            model_name='product',
            constraint=models.CheckConstraint(
                condition=models.Q(('current_qty__gte', 0)),
                name='product_current_qty_gte_zero',
            ),
        ),
        migrations.AddConstraint(
            model_name='product',
            constraint=models.CheckConstraint(
                condition=models.Q(('min_qty_alert__gte', 0)),
                name='product_min_qty_gte_zero',
            ),
        ),
        migrations.CreateModel(
            name='LowStockAlert',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('item_type', models.CharField(
                    choices=[('product', 'Product'), ('ingredient', 'Ingredient')],
                    max_length=20,
                )),
                ('current_qty', models.DecimalField(decimal_places=3, max_digits=12)),
                ('min_qty_alert', models.DecimalField(decimal_places=3, max_digits=12)),
                ('message', models.CharField(max_length=255)),
                ('is_resolved', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('ingredient', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='low_stock_alerts',
                    to='core.ingredient',
                )),
                ('product', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='low_stock_alerts',
                    to='core.product',
                )),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='ProductStockMovement',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('movement_type', models.CharField(
                    choices=[
                        ('SALE', 'Sale'),
                        ('PURCHASE', 'Purchase'),
                        ('ADJUST', 'Adjust'),
                        ('RETURN', 'Return'),
                    ],
                    max_length=20,
                )),
                ('qty_change', models.DecimalField(decimal_places=3, max_digits=12)),
                ('deduction_source', models.CharField(
                    blank=True,
                    choices=[('sale', 'Sale'), ('manual', 'Manual')],
                    default='',
                    max_length=20,
                )),
                ('note', models.CharField(blank=True, max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('order', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='product_stock_movements',
                    to='core.order',
                )),
                ('product', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='stock_movements',
                    to='core.product',
                )),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='lowstockalert',
            index=models.Index(fields=['is_resolved', 'created_at'], name='core_lowsto_is_reso_idx'),
        ),
        migrations.AddIndex(
            model_name='productstockmovement',
            index=models.Index(fields=['product', 'created_at'], name='core_produc_product_idx'),
        ),
        migrations.AddIndex(
            model_name='productstockmovement',
            index=models.Index(fields=['order', 'created_at'], name='core_produc_order_i_idx'),
        ),
    ]
