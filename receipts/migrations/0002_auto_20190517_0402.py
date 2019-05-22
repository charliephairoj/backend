# -*- coding: utf-8 -*-
# Generated by Django 1.11.12 on 2019-05-16 21:02
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('invoices', '__first__'),
        ('receipts', '0001_initial'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='item',
            options={},
        ),
        migrations.RemoveField(
            model_name='item',
            name='acknowledgement_item',
        ),
        migrations.RemoveField(
            model_name='item',
            name='image',
        ),
        migrations.RemoveField(
            model_name='item',
            name='product',
        ),
        migrations.AddField(
            model_name='item',
            name='invoice_item',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='receipt_items', to='invoices.Item'),
        ),
        migrations.AlterField(
            model_name='item',
            name='status',
            field=models.CharField(db_column=b'status', default=b'paid', max_length=50),
        ),
    ]
