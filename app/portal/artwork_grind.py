"""Map grind checkbox centers to an immutable artwork image."""
import hashlib
import json
import math

from django import forms
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import LabelArtwork

GRIND_BOXES = ('whole', 'ground')
DOT_RADIUS = 0.006


def grind_box(grind_code):
    if grind_code == 'whole':
        return 'whole'
    if grind_code in ('regular', 'fine', 'coarse', 'ground'):
        return 'ground'
    return None


def grind_box_event(artwork):
    return next((event for event in reversed(artwork.events) if event.get('action') == 'grind_boxes_mapped'), {})


def grind_boxes(artwork):
    event = grind_box_event(artwork)
    if event.get('artwork_sha256') == artwork.sha256:
        return valid_boxes(event.get('boxes'))
    return {}


def valid_boxes(boxes):
    if not isinstance(boxes, dict) or set(boxes) - set(GRIND_BOXES):
        return {}
    for point in boxes.values():
        if not isinstance(point, (tuple, list)) or len(point) != 2 or any(
            type(value) not in (int, float) or not math.isfinite(value) or not DOT_RADIUS <= value <= 1-DOT_RADIUS
            for value in point
        ):
            return {}
    if len(boxes) == 2 and math.dist(boxes['whole'], boxes['ground']) < 2*DOT_RADIUS:
        return {}
    return boxes


class GrindBoxForm(forms.Form):
    revision = forms.CharField(widget=forms.HiddenInput)
    whole_x = forms.DecimalField(label='Whole Bean · left (%)', min_value=0, max_value=100, max_digits=6, decimal_places=3, required=False)
    whole_y = forms.DecimalField(label='Whole Bean · top (%)', min_value=0, max_value=100, max_digits=6, decimal_places=3, required=False)
    ground_x = forms.DecimalField(label='Ground · left (%)', min_value=0, max_value=100, max_digits=6, decimal_places=3, required=False)
    ground_y = forms.DecimalField(label='Ground · top (%)', min_value=0, max_value=100, max_digits=6, decimal_places=3, required=False)

    def clean(self):
        data = super().clean()
        boxes = {}
        for box in GRIND_BOXES:
            point = (data.get(f'{box}_x'), data.get(f'{box}_y'))
            if point == (None, None):
                continue
            if None in point:
                raise forms.ValidationError('Enter both coordinates for each box you map.')
            boxes[box] = [float(value/100) for value in point]
        if boxes and not valid_boxes(boxes):
            raise forms.ValidationError('Place each dot inside its own checkbox, away from the artwork edge.')
        data['boxes'] = boxes
        return data


def revision(artwork):
    payload = json.dumps([artwork.sha256, grind_box_event(artwork)], sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


@staff_member_required
@require_http_methods(['GET', 'POST'])
def edit_grind_boxes(request, asset_id):
    originals = LabelArtwork.objects.defer('image_data').select_related('coffee', 'label_variant')
    artwork = get_object_or_404(originals, pk=asset_id)
    initial = {'revision': revision(artwork)}
    for box, (x, y) in grind_boxes(artwork).items():
        initial.update({f'{box}_x': round(x*100, 3), f'{box}_y': round(y*100, 3)})
    form = GrindBoxForm(request.POST if request.method == 'POST' else None, initial=initial)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            artwork = get_object_or_404(originals.select_for_update(of=('self',)), pk=asset_id)
            if form.cleaned_data['revision'] != revision(artwork):
                form.add_error(None, 'These checkbox positions changed. Reload before saving.')
            else:
                boxes = form.cleaned_data['boxes']
                if boxes != grind_boxes(artwork):
                    artwork.events.append({'action': 'grind_boxes_mapped', 'artwork_sha256': artwork.sha256,
                                           'boxes': boxes, 'actor': request.user.pk, 'at': timezone.now().isoformat()})
                    artwork.save(update_fields=['events'])
                messages.success(request, 'Grind checkbox positions saved.')
                return redirect('edit_label_grind_boxes', asset_id=asset_id)
    return render(request, 'portal/artwork_grind_boxes.html', {'artwork': artwork, 'form': form,
                  'boxes': grind_boxes(artwork)}, status=400 if form.errors else 200)
