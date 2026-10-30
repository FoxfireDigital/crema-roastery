from django.db import migrations,models

class Migration(migrations.Migration):
    dependencies=[('portal','0005_marketplace_selection')]
    operations=[
        migrations.AddField(model_name='greenbeandetails',name='roast_levels',field=models.JSONField(blank=True,default=list)),
        migrations.AddField(model_name='greenbeandetails',name='flavor_tags',field=models.CharField(blank=True,max_length=300,help_text='Optional comma-separated flavor notes, for example cocoa, nuts, citrus. Used for substitution suggestions only.')),
        migrations.AddField(model_name='greenbeandetails',name='caffeine',field=models.CharField(blank=True,max_length=12,choices=[('','Not recorded'),('regular','Caffeinated'),('decaf','Decaf')])),
    ]
