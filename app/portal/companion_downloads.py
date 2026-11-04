"""Authenticated downloads of an operator-installed, checksum-verified release.

The web process only reads this directory. No browser can publish a binary,
choose a filesystem path, execute an installer or trigger a desktop update.
"""
import hashlib
import json
import os
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .companion import enabled

KINDS = {'installer': ('Windows installer', '.exe', 'application/octet-stream'),
         'portable': ('Portable ZIP', '.zip', 'application/zip'),
         'source': ('Companion source ZIP', '.zip', 'application/zip')}
MAX_BYTES = 256 * 1024 * 1024


def release():
    root = Path(os.environ.get('PORTAL_COMPANION_DOWNLOAD_ROOT', '/var/lib/crema-companion'))
    manifest = root / 'release.json'
    if manifest.is_symlink() or not manifest.is_file() or manifest.stat().st_size > 8192:
        raise ValueError('Release manifest unavailable')
    data = json.loads(manifest.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('format') != 'crema-companion-release-v1':
        raise ValueError('Unsupported release manifest')
    version = data.get('version', '')
    if not isinstance(version, str) or not re.fullmatch(r'[0-9][A-Za-z0-9.+-]{0,63}', version):
        raise ValueError('Invalid release version')
    artifacts = data.get('artifacts')
    if not isinstance(artifacts, dict) or not {'installer', 'portable'} <= artifacts.keys() or artifacts.keys() - KINDS.keys():
        raise ValueError('Invalid release artifacts')
    items = []
    for kind, item in artifacts.items():
        if not isinstance(item, dict):
            raise ValueError('Invalid release artifact')
        name, size, checksum = item.get('filename'), item.get('bytes'), item.get('sha256')
        suffix = KINDS[kind][1]
        if not isinstance(name, str) or not re.fullmatch(r'CremaCompanion-[A-Za-z0-9.+_-]{1,120}', name) or not name.endswith(suffix):
            raise ValueError('Invalid artifact filename')
        if type(size) is not int or not 0 < size <= MAX_BYTES or not isinstance(checksum, str) or not re.fullmatch(r'[a-f0-9]{64}', checksum):
            raise ValueError('Invalid artifact metadata')
        path = root / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size != size:
            raise ValueError('Release artifact unavailable')
        items.append({'kind': kind, 'label': KINDS[kind][0], 'filename': name, 'bytes': size,
                      'mb': round(size / 1024 / 1024, 1), 'sha256': checksum, 'path': path})
    return {'version': version, 'signed': data.get('signed') is True, 'artifacts': items}


def allowed(request):
    return enabled() and request.user.is_active and request.user.is_staff


@login_required
@require_GET
@never_cache
def install(request):
    if not allowed(request):
        return HttpResponse('Companion access is unavailable.', status=403)
    try:
        current = release()
    except (ValueError, OSError, UnicodeError):
        current = None
    return render(request, 'portal/companion_install.html', {'release': current, 'portal_origin': settings.PORTAL_BASE_URL})


@login_required
@require_GET
@never_cache
def download(request, kind):
    if not allowed(request):
        return HttpResponse('Companion access is unavailable.', status=403)
    handle = None
    try:
        current = release()
        item = next(x for x in current['artifacts'] if x['kind'] == kind)
        # Hash the same open file that will be streamed; do not reopen after checking.
        handle = item['path'].open('rb')
        before = os.fstat(handle.fileno())
        checksum = hashlib.file_digest(handle, 'sha256').hexdigest()
        after = os.fstat(handle.fileno())
        if checksum != item['sha256'] or before.st_size != item['bytes'] or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError('Release artifact changed')
        handle.seek(0)
        response = FileResponse(handle, as_attachment=True, filename=item['filename'], content_type=KINDS[kind][2])
        response['X-Checksum-SHA256'] = item['sha256']
        response['X-Content-Type-Options'] = 'nosniff'
        return response
    except (ValueError, OSError, UnicodeError, StopIteration):
        if handle is not None:
            handle.close()
        raise Http404('This Companion package is unavailable. Ask your administrator to check the installed release.')
