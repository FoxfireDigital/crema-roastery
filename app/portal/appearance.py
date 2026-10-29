"""Account-owned, fixed palettes. Previewing never writes a preference."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods
from .models import UserAppearance


# These tokens cover shared controls as well as older page-specific styles.
# Status colors describe meaning consistently across the account palettes.
LIGHT_STATUS = dict(
    warning='#775510', warning_bg='#fff5db', warning_line='#ac872f',
    red='#a52e27', error_bg='#fff0ec', error_line='#bb6b5f',
    good='#23603a', success_bg='#e8f3e9', success_line='#568565',
    shadow='#10291d20', on_header='#ffffff', on_primary='#ffffff',
)
DARK_STATUS = dict(
    warning='#f3d483', warning_bg='#392e16', warning_line='#ad8a3e',
    red='#ffb4ab', error_bg='#402521', error_line='#c57a71',
    good='#a1d9ad', success_bg='#20392b', success_line='#699b77',
    shadow='#00000040', on_header='#f5f7fb', on_primary='#ffffff',
)


def palette(key, name, description, dark=False, **colors):
    return dict(id=key, name=name, description=description, dark=dark,
                tokens={**(DARK_STATUS if dark else LIGHT_STATUS), **colors})


PALETTES = (
    palette('forest', 'Forest', 'The familiar forest greens and clean, pale surfaces.',
        forest='#24513c', forest_dark='#173b2b', header='#203b30', header_hover='#375548',
        ink='#20362b', heading='#203b30', muted='#52675b', surface='#f4f7f4', panel='#ffffff',
        soft='#edf3ee', soft_hover='#dcebe1', selected='#d6eadf', selected_ink='#173c2a',
        line='#a5b9ac', input_line='#7c9585', focus='#087fa7'),
    palette('espresso', 'Espresso', 'Warm cream, rich coffee brown and soft caramel.',
        forest='#70452e', forest_dark='#50301f', header='#3f2b21', header_hover='#604535',
        ink='#382c26', heading='#4c3022', muted='#6e5c50', surface='#f7f2ea', panel='#fffcf7',
        soft='#eee3d5', soft_hover='#e5d5c0', selected='#e4cfb6', selected_ink='#4c3022',
        line='#b8a38c', input_line='#a48d73', focus='#966023'),
    palette('ocean', 'Ocean', 'Deep blue with cool, airy backgrounds.',
        forest='#245d83', forest_dark='#163e5a', header='#18394e', header_hover='#2e526c',
        ink='#203444', heading='#18394e', muted='#526878', surface='#f0f5f9', panel='#ffffff',
        soft='#e5eef5', soft_hover='#d6e5f0', selected='#cbdfee', selected_ink='#163e5a',
        line='#9fb7c8', input_line='#7592a7', focus='#156e9e'),
    palette('plum', 'Plum', 'Soft lavender with a deep plum accent.',
        forest='#754366', forest_dark='#542e49', header='#422c3e', header_hover='#63485d',
        ink='#392e3b', heading='#542e49', muted='#6d5c70', surface='#f7f2f7', panel='#fffaff',
        soft='#eee4ef', soft_hover='#e4d6e6', selected='#dfcbe0', selected_ink='#542e49',
        line='#bba3bb', input_line='#a589a6', focus='#8a4884'),
    palette('slate', 'Slate dusk', 'A gentle dark slate palette with soft blue accents.', True,
        forest='#28658c', forest_dark='#3478a1', header='#1a2632', header_hover='#334758',
        ink='#e3eaf0', heading='#f0f5fa', muted='#b2c0ce', surface='#18212b', panel='#24313e',
        soft='#304252', soft_hover='#3a5164', selected='#345b77', selected_ink='#f1f7fc',
        line='#71899c', input_line='#829aaf', focus='#8ed1ff'),
    palette('midnight', 'Midnight forest', 'A dark woodland palette with calm green accents.', True,
        forest='#30734e', forest_dark='#3a845b', header='#14241c', header_hover='#304d3c',
        ink='#e4ede5', heading='#f0f6ef', muted='#b3c6b7', surface='#15221b', panel='#21352a',
        soft='#2d4737', soft_hover='#385742', selected='#3a6049', selected_ink='#f0f8ef',
        line='#738f7b', input_line='#83a18a', focus='#a6dfac'),
    palette('crimson', 'Crimson', 'Deep red and black, with warm cream surfaces.',
        forest='#901b1d', forest_dark='#701315', header='#191716', header_hover='#49302f',
        ink='#302522', heading='#741719', muted='#6b5550', surface='#f8f3ed', panel='#fffdf8',
        soft='#f0e5dd', soft_hover='#e9d8ce', selected='#ead3cc', selected_ink='#651315',
        line='#bda69b', input_line='#9a7c70', focus='#981f25'),
    palette('gold', 'Black & Gold', 'Black and gold with warm dark surfaces.', True,
        forest='#e4bd56', forest_dark='#f1d17d', on_primary='#181715',
        header='#131313', header_hover='#363027', on_header='#f4d679',
        ink='#f1ebdc', heading='#f4d679', muted='#c9bda3', surface='#181715', panel='#25231f',
        soft='#38332a', soft_hover='#484030', selected='#554625', selected_ink='#fff0bc',
        line='#8f8062', input_line='#aa9870', focus='#f4d679'),
)
PALETTE_IDS = tuple(p['id'] for p in PALETTES)


def appearance_context(request):
    saved = None
    if request.user.is_authenticated:
        saved = UserAppearance.objects.filter(user=request.user).values_list('palette', flat=True).first()
    return {'appearance_palette': saved if saved in PALETTE_IDS else 'forest',
            'appearance_palettes': PALETTES}


@login_required
@require_http_methods(['GET', 'POST'])
def appearance_page(request):
    error = ''
    if request.method == 'POST':
        chosen = request.POST.get('palette', '')
        if chosen not in PALETTE_IDS:
            error = 'Choose one of the available palettes, then save.'
        else:
            # Never take a user ID from the form: each account owns its choice.
            UserAppearance.objects.update_or_create(user=request.user, defaults={'palette': chosen})
            messages.success(request, 'Your appearance settings have been saved.')
            return redirect('appearance')
    return render(request, 'portal/appearance.html', {'appearance_error': error}, status=400 if error else 200)
