"""Inspect generic service images without starting a database or mounting keys."""
from pathlib import Path
import argparse
import hashlib
import io
import json
import subprocess
import tarfile


def run(args):
    result = subprocess.run(args, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError('Service inspection failed: ' + result.stderr.decode(errors='replace')[-1500:])
    return result.stdout


def inspect_image(image, title, version, revision):
    if not image or image.startswith('-'):
        raise ValueError('Use an explicit generic service image.')
    info = json.loads(run(['docker', 'image', 'inspect', image]))[0]
    labels = info['Config'].get('Labels') or {}
    assert labels.get('org.opencontainers.image.title') == title
    assert labels.get('org.opencontainers.image.version') == version
    assert labels.get('org.opencontainers.image.revision') == revision
    return info


def filesystem(image):
    # The created container is never started. Its anonymous upstream database
    # volume is removed with this exact container; no existing volume is used.
    cid = run(['docker', 'create', '--entrypoint', '/bin/true', image]).decode().strip()
    try:
        raw = run(['docker', 'export', cid])
    finally:
        run(['docker', 'rm', '-v', cid])
    return tarfile.open(fileobj=io.BytesIO(raw), mode='r:')


def read(archive, name):
    member = archive.getmember(name)
    assert member.isfile() and member.size < 100_000_000
    return archive.extractfile(member).read()


def metadata(archive, prefix, binary):
    data = json.loads(read(archive, prefix + '/components.json'))
    assert data['goVersion'] == 'go1.27.3'
    assert hashlib.sha256(read(archive, binary)).hexdigest() == data['binarySHA256']
    count = 0
    for component in data['components']:
        assert component['notices'], 'Missing compiled component notice: ' + component['name']
        for item in component['notices']:
            assert '..' not in Path(item['path']).parts and not item['path'].startswith('/')
            assert hashlib.sha256(read(archive, prefix + '/' + item['path'])).hexdigest() == item['sha256']
            count += 1
    return data, count


def verify(proxy_image, database_image, version, revision, output):
    proxy_info = inspect_image(proxy_image, 'Crema proxy', version, revision)
    db_info = inspect_image(database_image, 'Crema database', version, revision)
    with filesystem(proxy_image) as archive:
        names = archive.getnames()
        proxy, proxy_notices = metadata(archive, 'usr/share/crema-proxy', 'usr/bin/caddy')
        assert 'bin/sh' not in names and 'usr/bin/curl' not in names
        assert not any(name.startswith(('data/', 'config/')) for name in names), 'Instance certificate/config data in proxy image'
        assert not any('libbrotli' in name for name in names)
        trust = json.loads(read(archive, 'usr/share/crema-proxy/trust.json'))
        assert hashlib.sha256(read(archive, 'etc/ssl/certs/ca-certificates.crt')).hexdigest() == trust['bundleSHA256']
        read(archive, 'usr/share/crema-proxy/notices/ca-certificates/copyright')
        # The package-level OpenPGP warning requires separate source-graph
        # evidence too. Absence of its path here is an additional binary check.
        assert b'golang.org/x/crypto/openpgp' not in read(archive, 'usr/bin/caddy')
    with filesystem(database_image) as archive:
        db, db_notices = metadata(archive, 'usr/share/crema-database', 'usr/local/bin/gosu')
        source = read(archive, 'usr/share/crema-database/sources/gosu-1.20.tar.gz')
        assert hashlib.sha256(source).hexdigest() == '207a2045e890d3ca3326027c5f585733085960b401a49dbc00e3bb628c054cf8'
        assert not any(name.startswith('var/lib/postgresql/data/') and name.endswith('PG_VERSION') for name in archive.getnames())
    proxy_version = run(['docker', 'run', '--rm', '--network=none', '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges:true', proxy_image, 'version']).decode().strip()
    assert proxy_version.startswith('v2.11.7')
    gosu_version = run(['docker', 'run', '--rm', '--network=none', '--read-only', '--entrypoint', 'gosu', database_image, '--version']).decode().strip()
    assert gosu_version.startswith('1.20 ') and 'go1.27.3' in gosu_version
    uid = run(['docker', 'run', '--rm', '--network=none', '--read-only', '--entrypoint', 'gosu', database_image, 'postgres', 'id', '-u']).decode().strip()
    assert uid.isdigit() and uid != '0', 'Database helper did not drop root identity'
    report = {'version': version, 'revision': revision, 'proxy': {'image': proxy_image, 'id': proxy_info['Id'], 'version': proxy_version, 'goComponents': proxy, 'noticeCount': proxy_notices, 'trust': trust, 'shellOrCurl': False, 'instanceData': False, 'openPGPPackagePathInBinary': False}, 'database': {'image': database_image, 'id': db_info['Id'], 'gosuVersion': gosu_version, 'postgresUID': uid, 'goComponents': db, 'noticeCount': db_notices}, 'limitation': 'Maintainer image/provenance/identity checks, not independent vulnerability or legal clearance.'}
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'service-verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print('PASS: exact service identities, compiled notices, source hashes, minimal proxy contents and database privilege drop.')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proxy-image', required=True)
    parser.add_argument('--database-image', required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    verify(args.proxy_image, args.database_image, args.version, args.revision, args.output)
