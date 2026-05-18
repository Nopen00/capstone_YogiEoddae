from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('places', '0004_mediaplace_ai_reason_mediaplace_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='media',
            name='source_url',
            field=models.URLField(blank=True, default='', max_length=500),
        ),
    ]
