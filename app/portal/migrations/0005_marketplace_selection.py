from django.db import migrations,models

def retain_connections(apps,schema_editor):
    alias=schema_editor.connection.alias
    Configuration=apps.get_model('portal','PortalConfiguration')
    stores=apps.get_model('portal','StoreConnection').objects.using(alias)
    chosen=set(stores.exclude(platform='csv').values_list('platform',flat=True))
    if apps.get_model('portal','ShopifyConnection').objects.using(alias).exists():chosen.add('shopify')
    if chosen:
        config,_=Configuration.objects.using(alias).get_or_create(pk=1)
        config.marketplaces=sorted(chosen);config.save(using=alias,update_fields=['marketplaces'])

class Migration(migrations.Migration):
    dependencies=[('portal','0004_store_imports')]
    operations=[migrations.AddField(model_name='portalconfiguration',name='marketplaces',field=models.JSONField(blank=True,default=None,editable=False,null=True)),migrations.RunPython(retain_connections,migrations.RunPython.noop)]
