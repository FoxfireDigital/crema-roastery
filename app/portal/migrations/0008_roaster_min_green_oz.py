from django.db import migrations,models


class Migration(migrations.Migration):
    dependencies=[('portal','0007_batch_cooled_at')]
    operations=[migrations.AddField(model_name='roaster',name='min_green_oz',field=models.DecimalField(decimal_places=2,default=0,help_text='Minimum green input in ounces. Use tenths; 0 leaves the minimum unset.',max_digits=7))]
