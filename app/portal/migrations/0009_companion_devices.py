import django.db.models.deletion
import django.utils.timezone
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('portal', '0008_roaster_min_green_oz'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='CompanionDevice',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=80)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('last_seen_at', models.DateTimeField(blank=True, null=True)),
                ('revoked_at', models.DateTimeField(blank=True, null=True)),
                ('access_hash', models.CharField(max_length=64, unique=True)),
                ('refresh_hash', models.CharField(max_length=64, unique=True)),
                ('access_expires_at', models.DateTimeField()),
                ('refresh_expires_at', models.DateTimeField()),
                ('auth_fingerprint', models.CharField(max_length=64)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='CompanionGrant',
            fields=[
                ('device_hash', models.CharField(max_length=64, primary_key=True, serialize=False)),
                ('code_hash', models.CharField(max_length=64, unique=True)),
                ('name', models.CharField(max_length=80)),
                ('expires_at', models.DateTimeField()),
                ('next_poll_at', models.DateTimeField()),
                ('interval', models.PositiveIntegerField(default=5)),
                ('state', models.CharField(default='pending', max_length=12)),
                ('user', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
