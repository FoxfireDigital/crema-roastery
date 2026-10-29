from datetime import timedelta
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from django.utils import timezone
from .models import SubscriptionContract,Batch,Coffee
from .artwork_library import coverage,coverage_sections,frac_coverage


@staff_member_required
def information_review(request):
    rows,unmatched=coverage();missing=[]
    for row in rows:
        gaps=[cell for cell in row['cells'] if cell['issue']]
        if gaps:missing.append({**row,'cells':gaps})
    contracts=[]
    for contract in SubscriptionContract.objects.filter(status='ACTIVE',next_billing_at__gte=timezone.now(),next_billing_at__lte=timezone.now()+timedelta(days=14)):
        choices=[item for item in contract.lines if item.get('needs_cycle_assignment') or item.get('cycle_choice')]
        if choices or not contract.customer:contracts.append({'contract':contract,'choices':choices})
    outliers=[]
    for batch in Batch.objects.exclude(roasted_oz=None).select_related('coffee'):
        if batch.green_oz:
            loss=(1-batch.roasted_oz/batch.green_oz)*100
            if loss<5 or loss>30:outliers.append({'batch':batch,'loss':loss})
    from .artwork_decisions import review_rows
    from .shopify import connection_status
    pending,resolved,checked_at=review_rows()
    return render(request,'portal/information_review.html',{'missing':missing,'coverage_sections':coverage_sections(),'fracs':frac_coverage(),'unmatched':unmatched,'contracts':contracts,'outliers':outliers,'label_reviews':pending,'label_resolved':resolved,'coffees':Coffee.objects.filter(active=True),'catalog_checked_at':checked_at,'shopify_status':connection_status()})
