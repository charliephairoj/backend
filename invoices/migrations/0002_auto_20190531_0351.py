# -*- coding: utf-8 -*-
# Generated by Django 1.11.12 on 2019-05-30 20:51
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('invoices', '0001_initial'),
    ]

    operations = [
        
        migrations.AddField(
            model_name='invoice',
            name='issue_date',
            field=models.DateField(auto_now_add=True, null=True),
        ),
        migrations.AddField(
            model_name='invoice',
            name='tax_date',
            field=models.DateField(auto_now_add=True, null=True),
        ),
       
    ]