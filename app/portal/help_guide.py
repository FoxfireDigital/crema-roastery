from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from .models import Coffee
from .plan_actions import ROAST_NAMES


@login_required
def help_guide(request):
    coffees=list(Coffee.objects.filter(active=True).select_related('roast_base'))
    for coffee in coffees:coffee.guide_roast='Experimental — choose each batch’s roast and record its origin' if coffee.experimental else ROAST_NAMES.get(coffee.standard_roast,coffee.standard_roast or 'Needs confirmation')
    return render(request,'portal/help.html',{'guide_coffees':coffees})
