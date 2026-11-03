from django.db import migrations
from pgvector.django import VectorField, HnswIndex


class Migration(migrations.Migration):

    dependencies = [
        ('intelligence', '0007_job_seniority_ml_fields'),
    ]

    operations = [
        # 1. Enable the extension (idempotent)
        migrations.RunSQL(
            sql='CREATE EXTENSION IF NOT EXISTS vector;',
            reverse_sql='DROP EXTENSION IF EXISTS vector;',
        ),

        # 2. Replace the JSONField placeholder with a real vector column (1536 dims = text-embedding-3-small)
        migrations.RemoveField(model_name='job', name='embedding'),
        migrations.AddField(
            model_name='job',
            name='embedding',
            field=VectorField(dimensions=1536, null=True, blank=True),
        ),

        # 3. Store which model produced the embedding so we can filter/invalidate later
        migrations.AddField(
            model_name='job',
            name='embedding_model',
            field=__import__('django.db.models', fromlist=['CharField']).CharField(
                max_length=100, blank=True,
                help_text='Model name that produced the embedding, e.g. text-embedding-3-small',
            ),
        ),

        # 4. HNSW index — cosine distance
        migrations.AddIndex(
            model_name='job',
            index=HnswIndex(
                name='job_embedding_hnsw',
                fields=['embedding'],
                m=16,
                ef_construction=64,
                opclasses=['vector_cosine_ops'],
            ),
        ),
    ]
