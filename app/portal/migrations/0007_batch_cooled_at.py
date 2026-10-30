from django.db import migrations,models


class Migration(migrations.Migration):
    dependencies=[('portal','0006_green_substitution_details')]
    operations=[migrations.AddField(model_name='batch',name='cooled_at',field=models.DateTimeField(blank=True,null=True))]
