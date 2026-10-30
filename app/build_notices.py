"""Capture installed component declarations and available notices at image build.

No network, application imports, database or environment dump. This inventory is
not a license compatibility opinion, source offer, vulnerability scan or SBOM
standard conformance claim. Review vendored libraries and source obligations too.
"""
from pathlib import Path
import hashlib
import importlib.metadata as metadata
import json
import re
import shutil
import subprocess

DEST = Path('/usr/share/crema')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def notice(source, relative):
    target = DEST / 'notices' / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return {'path': str(target.relative_to(DEST)), 'sha256': digest(target)}


def collect():
    DEST.mkdir(parents=True, exist_ok=True)
    own = notice(Path('/srv/LICENSE'), Path('crema/LICENSE'))
    packages = []
    for dist in sorted(metadata.distributions(), key=lambda item: item.metadata['Name'].lower()):
        name = dist.metadata['Name']
        safe = re.sub(r'[^A-Za-z0-9_.-]', '_', name)
        files = list(dist.files or [])
        notices = []
        native = []
        for entry in files:
            parts = entry.parts
            located = Path(dist.locate_file(entry))
            if not located.is_file():
                continue
            info = next((index for index, part in enumerate(parts) if part.endswith('.dist-info')), None)
            if info is not None:
                relative = Path(*parts[info + 1:])
                # License-File metadata and wheel license directories are retained
                # verbatim. Never traverse arbitrary paths from package metadata.
                wanted = relative.parts and (relative.parts[0].lower() == 'licenses' or relative.name.lower().startswith(('license', 'copying', 'notice')))
                if wanted and '..' not in relative.parts:
                    notices.append(notice(located, Path('python') / safe / relative))
            if located.suffix == '.so' or '.so.' in located.name:
                native.append({'path': str(entry), 'sha256': digest(located), 'bytes': located.stat().st_size})
        declared = dist.metadata.get('License-Expression') or dist.metadata.get('License')
        classifiers = [value for value in dist.metadata.get_all('Classifier', []) if value.startswith('License ::')]
        packages.append({'name': name, 'version': dist.version, 'declaredLicense': declared, 'licenseClassifiers': classifiers, 'notices': notices, 'nativeLibraries': native})
    query = ['dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${Architecture}\t${source:Package}\t${source:Version}\n']
    system = []
    for line in subprocess.check_output(query, text=True).splitlines():
        name, version, architecture, source, source_version = line.split('\t')
        copyright_file = Path('/usr/share/doc') / name.split(':')[0] / 'copyright'
        notices = []
        if copyright_file.is_file() and copyright_file.resolve().is_relative_to(Path('/usr/share/doc')):
            notices.append(notice(copyright_file, Path('debian') / name / 'copyright'))
        system.append({'name': name, 'version': version, 'architecture': architecture, 'sourcePackage': source, 'sourceVersion': source_version, 'notices': notices})
    missing = {'python': [p['name'] for p in packages if not p['notices']], 'debian': [p['name'] for p in system if not p['notices']]}
    report = {'format': 'crema-component-inventory-v1', 'scope': 'Application image only; proxy and database images require separate review.', 'limitation': 'Installed declarations and available notices, not legal clearance, complete vendored-source inventory, source delivery or vulnerability certification.', 'applicationNotice': own, 'python': packages, 'debian': system, 'missingNoticeFiles': missing}
    (DEST / 'components.json').write_text(json.dumps(report, indent=2) + '\n')
    (DEST / 'README.txt').write_text('Crema application code is MIT; dependencies retain their own licenses.\ncomponents.json records installed versions, declared licenses and available notices.\nReview native vendored libraries, complete license terms and applicable source obligations before distribution.\nThis inventory does not certify the database/proxy images or legal compliance.\n')
    print('Captured component declarations: %s Python / %s Debian packages; missing-notice counts %s / %s.' % (len(packages), len(system), len(missing['python']), len(missing['debian'])))


if __name__ == '__main__':
    collect()
