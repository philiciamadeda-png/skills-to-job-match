from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('intelligence', '0009_embedding_run_and_hash'),
    ]

    operations = [
        migrations.AddField(
            model_name='jobskill',
            name='is_required',
            field=models.BooleanField(default=True),
        ),
    ]
