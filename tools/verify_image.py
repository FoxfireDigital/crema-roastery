"""Inspect a built generic image offline, without starting its app or mounting data."""
from pathlib import Path
import argparse
import hashlib
import json
import secrets
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PROBE = r'''
import os,json,hashlib,importlib.util,subprocess
from pathlib import Path
def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
files={};writable=[]
for path in Path('/srv').rglob('*'):
    rel=path.relative_to('/srv').as_posix()
    if not path.is_file() or rel.startswith('staticfiles/'):continue
    files[rel]=sha(path)
    if os.access(path,os.W_OK):writable.append(rel)
root=Path('/usr/share/crema')
inventory=json.loads((root/'components.json').read_text())
notices=[]
for item in [inventory['applicationNotice'],*[entry for group in ['python','debian'] for package in inventory[group] for entry in package['notices']]]:
    p=(root/item['path']).resolve()
    assert p.is_relative_to(root) and sha(p)==item['sha256'],'Notice integrity mismatch'
    notices.append(item['path'])
assert json.loads(Path('/srv/portal/artisan_catalog.json').read_text())=={'profiles':[],'alarms':[]}
assert json.loads(Path('/srv/label_artwork/catalog.json').read_text())==[]
assert not any(Path('/var/lib/roastery-secrets').iterdir()),'Image contains instance keys'
assert importlib.util.find_spec('pip') is None,'Build-only installer and its vendored libraries remain in the runtime image'
assert not list(Path('/usr/local/lib/python3.12/ensurepip/_bundled').glob('*.whl')),'Bundled bootstrap installers remain in the runtime image'
from psycopg import pq
import psycopg_c.pq as c_pq
assert pq.__impl__=='c','Runtime must use the compiled, system-linked database driver'
assert importlib.util.find_spec('psycopg_binary') is None,'Bundled database-client wheel remains'
linkage=subprocess.check_output(['ldd',c_pq.__file__],text=True)
assert 'not found' not in linkage and 'libpq.so.5 => /' in linkage and '.libs/' not in linkage,'Database driver does not link the system client libraries'
assert not {'gcc','gcc-12','g++','g++-12','pkg-config','libpq-dev','libffi-dev','zlib1g-dev','libjpeg62-turbo-dev','libwebp-dev'} & {p['name'] for p in inventory['debian']},'Build tools remain in runtime'
assert not {'pip','setuptools','wheel','pybind11','psycopg-binary'} & {p['name'].lower().replace('_','-') for p in inventory['python']},'Build-only or bundled-driver distribution remains'
build=json.loads((root/'driver-build.json').read_text())
source=root/'sources/psycopg_c-3.3.6.tar.gz'
source_hash=sha(source)
assert source_hash=='29c568426ad61c1b702c7d73505c43ca2c9fc5d97a8431d8d9049e731e319ff8'
assert any(f['path']=='sources/'+source.name and f['sha256']==source_hash for f in build['files']),'Driver source provenance mismatch'
driver={'implementation':pq.__impl__,'libpqVersion':pq.version(),'linkage':linkage,'sourceSHA256':source_hash,'build':build}
import io,PIL,_cffi_backend
from PIL import Image,features
assert not (Path(PIL.__file__).parent.parent/'pillow.libs').exists(),'Bundled Pillow libraries remain'
for name in ['jpg','zlib','webp']:assert features.check(name),'Required image codec unavailable: '+name
for name in ['freetype2','littlecms2','libtiff','jpg_2000','avif','libimagequant','xcb']:assert not features.check(name),'Unneeded native image feature enabled: '+name
for fmt in ['PNG','JPEG','WEBP']:
    buf=io.BytesIO();Image.new('RGB',(32,32),(10,20,30)).save(buf,fmt)
    buf.seek(0)
    with Image.open(buf) as decoded:decoded.load();assert decoded.size==(32,32) and decoded.format==fmt
cffi_linkage=subprocess.check_output(['ldd',_cffi_backend.__file__],text=True)
assert 'libffi.so.8 => /' in cffi_linkage and '.libs/' not in cffi_linkage,'FFI is not system linked'
for filename,expected_hash in {'pillow-13.0.0.tar.gz':'cdcd1ba258178f7356d74170c9a81ba4eab6a5d55748bc402a5a2a6fe6be3510','cffi-2.1.1.tar.gz':'dd31f52ea1086513bb9df30f8fcee9b8918323ae067a3d5b78bc826a000712be'}.items():
    assert sha(root/'sources'/filename)==expected_hash,'Native source checksum mismatch'
native={'pillowVersion':PIL.__version__,'requiredCodecs':['PNG','JPEG','WEBP'],'pillowBundledLibraries':False,'cffiLinkage':cffi_linkage}
print(json.dumps({'uid':os.getuid(),'gid':os.getgid(),'files':files,'writableApplicationFiles':writable,'inventory':inventory,'noticeCount':len(notices),'driver':driver,'native':native}))
'''


def run(args, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, check=False, **kwargs)
    if result.returncode:
        raise SystemExit('Image inspection failed: ' + result.stderr[-2000:])
    return result.stdout


def expected_files():
    fixed = {'LICENSE', 'requirements.txt', 'manage.py', 'project_settings.py', 'project_urls.py', 'project_wsgi.py', 'bootstrap.py', 'init_instance.py', 'worker.py', 'build_notices.py', 'entrypoint.sh', 'label_artwork/catalog.json', 'portal/artisan_helper.ps1', 'portal/artisan_catalog.json'}
    result = {}
    for path in (ROOT / 'app').rglob('*'):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT / 'app').as_posix()
        included = relative in fixed or (relative.startswith('portal/') and (path.suffix == '.py' or relative.startswith('portal/templates/') and path.suffix == '.html'))
        if included and '__pycache__' not in path.parts:
            result[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def test_context(args):
    """Build a copied context with fictional unwanted files; inspect actual bytes."""
    image = 'crema-context-check:' + secrets.token_hex(8)
    with tempfile.TemporaryDirectory(prefix='crema-context-') as directory:
        context = Path(directory) / 'app'
        shutil.copytree(ROOT / 'app', context, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        canaries = ['.env', 'local-secret.txt', 'state/app.sqlite3', 'portal/.env', 'portal/backups/test.dump', 'portal/templates/export.csv', 'portal/templates/private-note.txt', 'label_artwork/unreviewed.png']
        for relative in canaries:
            path = context / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('FICTIONAL_BUILD_CONTEXT_CANARY_ONLY\n')
        try:
            run(['docker', 'build', '--build-arg', 'CREMA_VERSION=' + args.version, '--build-arg', 'CREMA_REVISION=' + args.revision, '-t', image, str(context)], timeout=600)
            probe = json.loads(run(['docker', 'run', '--rm', '-i', '--network=none', '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges:true', '--entrypoint=python', image, '-'], input=PROBE))
            expected = expected_files()
            assert probe['files'] == expected, 'Build-context mismatch: extra=%s missing=%s modified=%s' % (sorted(set(probe['files']) - set(expected)), sorted(set(expected) - set(probe['files'])), sorted(name for name in expected.keys() & probe['files'].keys() if expected[name] != probe['files'][name]))
            print('PASS: actual image excludes all %s fictional private-state canaries while retaining required sources.' % len(canaries))
        finally:
            # Only this unique disposable test image; never prune shared images.
            subprocess.run(['docker', 'image', 'rm', image], capture_output=True, text=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--test-context', action='store_true', help='Also build a disposable copy with fictional unwanted files.')
    args = parser.parse_args()
    if not args.image or args.image.startswith('-'):
        parser.error('Use an explicit image name.')
    info = json.loads(run(['docker', 'image', 'inspect', args.image]))[0]
    labels = info['Config'].get('Labels') or {}
    assert info['Config']['User'] == '10001:10001', 'Application image must run as its non-root user.'
    assert labels.get('org.opencontainers.image.version') == args.version, 'Wrong version label.'
    assert labels.get('org.opencontainers.image.revision') == args.revision, 'Wrong source revision label.'
    assert (ROOT / 'LICENSE').read_text() == (ROOT / 'app/LICENSE').read_text(), 'Application MIT notice differs from source notice.'
    # Never start the entrypoint/migrations or attach host credentials/volumes.
    data = json.loads(run(['docker', 'run', '--rm', '-i', '--network=none', '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges:true', '--entrypoint=python', args.image, '-'], input=PROBE))
    assert data['uid'] == data['gid'] == 10001, 'Unexpected runtime identity.'
    expected = expected_files()
    assert data['files'] == expected, 'Image application files differ from reviewed source (missing, modified or unexpected files).'
    assert not data['writableApplicationFiles'], 'Runtime user can modify application files.'
    assert data['inventory']['python'] and data['inventory']['debian'], 'Component inventory is incomplete.'
    apt_versions = run(['docker', 'run', '--rm', '--network=none', '--read-only', '--entrypoint=dpkg-query', args.image, '-W', '-f=${Version}\n', 'apt', 'libapt-pkg6.0']).splitlines()
    assert apt_versions == ['2.6.2', '2.6.2'], 'Application package manager fix is absent.'
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'components.json').write_text(json.dumps(data['inventory'], indent=2) + '\n')
    (args.output / 'database-driver.json').write_text(json.dumps(data['driver'], indent=2) + '\n')
    (args.output / 'native-codecs.json').write_text(json.dumps(data['native'], indent=2) + '\n')
    report = {'image': args.image, 'imageId': info['Id'], 'registryDigests': info.get('RepoDigests', []), 'version': args.version, 'revision': args.revision, 'platform': info['Os'] + '/' + info['Architecture'], 'applicationFiles': len(expected), 'uid': data['uid'], 'emptyPrivateCatalogs': True, 'emptyInstanceKeys': True, 'applicationWritable': False, 'noticeCount': data['noticeCount'], 'pythonPackages': len(data['inventory']['python']), 'debianPackages': len(data['inventory']['debian']), 'missingNoticeFiles': data['inventory']['missingNoticeFiles'], 'limitation': 'Offline application-image inspection; not an independent security audit, full license/source compliance review, registry-pull trial or proxy/database image review.'}
    report['databaseDriver'] = {key: data['driver'][key] for key in ['implementation', 'libpqVersion', 'sourceSHA256']}
    (args.output / 'image-verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    if args.test_context:
        test_context(args)


if __name__ == '__main__':
    main()
