"""Rehearse complete anonymous image downloads via a loopback-only registry."""
from pathlib import Path
import argparse
import copy
import gzip
import hashlib
import io
import json
import secrets
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.request
from load_release import load, validate, inspect, image_config_id
from render_registry_yaml import render

ROOT = Path(__file__).resolve().parents[1]
LOCAL_HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def run(args, **kwargs):
    value = subprocess.run(args, capture_output=True, check=False, **kwargs)
    if value.returncode:
        raise RuntimeError('Registry trial command failed: ' + value.stderr.decode(errors='replace')[-1600:])
    return value.stdout


def download(url, destination):
    # Our own loopback registry uses local storage, never a redirecting backend.
    with LOCAL_HTTP.open(url, timeout=120) as response:
        assert response.geturl() == url, 'Unexpected registry redirect'
        with destination.open('wb') as target:
            shutil.copyfileobj(response, target, 1024 * 1024)
    with destination.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def add_bytes(archive, name, raw):
    item = tarfile.TarInfo(name)
    item.size = len(raw)
    item.mode = 0o644
    archive.addfile(item, io.BytesIO(raw))


def fetch_image(origin, repository, tag, expected, reference, output, work):
    accept = 'application/vnd.oci.image.index.v1+json,application/vnd.oci.image.manifest.v1+json,application/vnd.docker.distribution.manifest.list.v2+json,application/vnd.docker.distribution.manifest.v2+json'
    def manifest_at(identity):
        request = urllib.request.Request(origin + '/v2/' + repository + '/manifests/' + identity, headers={'Accept': accept})
        with LOCAL_HTTP.open(request, timeout=30) as response:
            raw = response.read(2_000_000)
            digest = 'sha256:' + hashlib.sha256(raw).hexdigest()
            assert response.headers.get('Docker-Content-Digest') == digest
        return json.loads(raw), digest
    manifest, digest = manifest_at(tag)
    index_digest = digest
    if 'manifests' in manifest:
        candidates = [entry for entry in manifest['manifests'] if entry.get('platform', {}).get('os') == expected['Os'] and entry.get('platform', {}).get('architecture') == expected['Architecture']]
        assert len(candidates) == 1
        manifest, digest = manifest_at(candidates[0]['digest'])
    config_id = image_config_id(reference, expected)
    assert manifest['config']['digest'] == config_id
    config_file = work / 'config.json'
    assert 'sha256:' + download(origin + '/v2/' + repository + '/blobs/' + config_id, config_file) == config_id
    config = json.loads(config_file.read_text())
    assert len(config['rootfs']['diff_ids']) == len(manifest['layers'])
    layers, blob_bytes = [], 0
    for index, (layer, diff_id) in enumerate(zip(manifest['layers'], config['rootfs']['diff_ids'])):
        compressed = work / ('blob-' + str(index))
        assert 0 < layer['size'] < 2_000_000_000
        assert 'sha256:' + download(origin + '/v2/' + repository + '/blobs/' + layer['digest'], compressed) == layer['digest']
        blob_bytes += compressed.stat().st_size
        target = work / ('layer-' + str(index) + '.tar')
        with compressed.open('rb') as source:
            magic = source.read(2)
            source.seek(0)
            decoded = gzip.GzipFile(fileobj=source) if magic == b'\x1f\x8b' else source
            with target.open('wb') as stream:
                shutil.copyfileobj(decoded, stream, 1024 * 1024)
        with target.open('rb') as stream:
            assert 'sha256:' + hashlib.file_digest(stream, 'sha256').hexdigest() == diff_id
        layers.append(target)
        compressed.unlink()
    filename = reference.replace(':', '-') + '-linux-' + expected['Architecture'] + '.tar.gz'
    artifact = output / filename
    config_name = config_id.split(':')[1] + '.json'
    with tarfile.open(artifact, 'w:gz', compresslevel=1) as archive:
        add_bytes(archive, config_name, config_file.read_bytes())
        add_bytes(archive, 'manifest.json', json.dumps([{'Config': config_name, 'RepoTags': [reference], 'Layers': [p.name for p in layers]}]).encode())
        for path in layers:
            archive.add(path, arcname=path.name, recursive=False)
    with artifact.open('rb') as stream:
        checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'reference': reference, 'file': filename, 'bytes': artifact.stat().st_size, 'sha256': checksum, 'imageId': config_id, 'registryIndexDigest': index_digest, 'registryManifestDigest': digest, 'downloadedBlobBytes': blob_bytes, 'layersDownloaded': len(layers)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--proxy-image', required=True)
    parser.add_argument('--database-image', required=True)
    parser.add_argument('--registry-image', required=True, help='Pinned official registry image, used only for local QA')
    parser.add_argument('--revision', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    assert '@sha256:' in args.registry_image
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    assert not (output / 'release-manifest.json').exists(), 'Inspect existing artifacts before repeating a trial'
    token = secrets.token_hex(6)
    name, volume = 'crema_registry_' + token, 'crema_registry_store_' + token
    work = Path(tempfile.mkdtemp(prefix='crema-registry-trial-', dir='/tmp')).resolve()
    config_dir = work / 'docker-config'
    config_dir.mkdir()
    (config_dir / 'config.json').write_text('{}')
    pushed, pulled, added_tags, records = [], [], [], []
    started = False
    report = {'result': 'not completed', 'sourceRevision': args.revision, 'productionChanged': False, 'publicRegistryUsed': False, 'anonymousTransport': True, 'engineCacheErased': False}
    version = json.loads(run(['docker', 'image', 'inspect', args.image]))[0]['Config']['Labels']['org.opencontainers.image.version']
    sources = {'application': args.image, 'proxy': args.proxy_image, 'database': args.database_image}
    refs = {'application': 'crema:' + version, 'proxy': 'crema-proxy:' + version, 'database': 'crema-database:' + version}
    try:
        # Fail before copying any input that might be a private installation.
        run(['python3', str(ROOT / 'tools/verify_image.py'), '--image', args.image, '--version', version, '--revision', args.revision, '--output', str(output / 'image-review')])
        run(['python3', str(ROOT / 'tools/verify_services.py'), '--proxy-image', args.proxy_image, '--database-image', args.database_image, '--version', version, '--revision', args.revision, '--output', str(output / 'service-review')])
        run(['docker', 'volume', 'create', '--label', 'org.crema.qa-token=' + token, volume])
        run(['docker', 'run', '-d', '--name', name, '--label', 'org.crema.qa-token=' + token, '--cpus=1', '--memory=384m', '-p', '127.0.0.1::5000', '-e', 'OTEL_TRACES_EXPORTER=none', '-v', volume + ':/var/lib/registry', args.registry_image])
        started = True
        info = json.loads(run(['docker', 'inspect', name]))[0]
        binding = info['NetworkSettings']['Ports']['5000/tcp'][0]
        assert binding['HostIp'] == '127.0.0.1'
        registry = '127.0.0.1:' + binding['HostPort']
        origin = 'http://' + registry
        for _ in range(30):
            try:
                with LOCAL_HTTP.open(origin + '/v2/', timeout=2) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(1)
        else:
            raise RuntimeError('Local test registry did not become ready')
        for role, image in sources.items():
            expected = inspect(image)
            existing = inspect(refs[role])
            assert existing is None or existing['Id'] == expected['Id'], 'Canonical release tag already identifies different content'
            if existing is None:
                added_tags.append(refs[role])
            target = registry + '/crema-' + role + ':' + version
            run(['docker', 'tag', image, target])
            pushed.append(target)
            run(['docker', '--config', str(config_dir), 'push', target])
            folder = work / role
            folder.mkdir()
            record = fetch_image(origin, 'crema-' + role, version, expected, refs[role], output, folder)
            records.append({'role': role, **record})
            shutil.rmtree(folder)
        manifest = {'format': 'crema-offline-release-v1', 'version': version, 'revision': args.revision, 'images': records, 'limitation': 'Unsigned local-registry rehearsal; not evidence of Internet registry availability, public DNS/CA issuance or independent review.'}
        manifest_path = output / 'release-manifest.json'
        manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
        registry_images = {}
        for item in records:
            reference = registry + '/crema-' + item['role'] + '@' + item['registryManifestDigest']
            run(['docker', '--config', str(config_dir), 'pull', '--platform', 'linux/amd64', reference])
            pulled.append(reference)
            assert image_config_id(reference) == item['imageId']
            registry_images[item['role']] = reference
        (output / 'registry-image-map.json').write_text(json.dumps(registry_images, indent=2) + '\n')
        registry_yaml = render(registry_images, output / 'registry-install-rehearsal.yaml')
        # Negative checks must reject tampered hashes and escaping paths before
        # Docker sees an artifact. Restore the exact manifest after each check.
        for key, bad_value in [('sha256', '0' * 64), ('file', '../outside-release.tar.gz')]:
            bad = copy.deepcopy(manifest)
            bad['images'][0][key] = bad_value
            manifest_path.write_text(json.dumps(bad))
            try:
                validate(output)
            except (AssertionError, FileNotFoundError):
                pass
            else:
                raise AssertionError('Invalid release manifest was accepted')
            finally:
                manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
        load(output)
        run(['python3', str(ROOT / 'tools/test_compose.py'), '--image', registry_images['application'], '--proxy-image', registry_images['proxy'], '--database-image', registry_images['database'], '--compose-yaml', str(registry_yaml), '--revision', args.revision, '--output', str(output / 'deployment-review')])
        report.update(result='passed', images=records, completeBlobDownloads=True, hashAndDiffIdVerified=True, anonymousDigestPull=True, registryYAML=True, freshKeysAndYAMLInstall=True, tamperedManifestRejected=True, isolatedRecovery=True)
    finally:
        if started:
            info = json.loads(run(['docker', 'inspect', name]))[0]
            assert info['Config']['Labels']['org.crema.qa-token'] == token
            run(['docker', 'rm', '-f', '-v', name])
        state = subprocess.run(['docker', 'volume', 'inspect', volume], capture_output=True)
        if state.returncode == 0:
            assert json.loads(state.stdout)[0]['Labels']['org.crema.qa-token'] == token
            run(['docker', 'volume', 'rm', volume])
        for tag in pushed + pulled + added_tags:
            subprocess.run(['docker', 'image', 'rm', tag], capture_output=True)
        report['temporaryImageTagsRemoved'] = all(inspect(tag) is None for tag in pushed + pulled + added_tags)
        assert report['temporaryImageTagsRemoved']
        assert work.parent == Path('/tmp') and work.name.startswith('crema-registry-trial-')
        shutil.rmtree(work)
        report['temporaryRegistryAndVolumeRemoved'] = True
        (output / 'registry-install-verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print('PASS: complete anonymous downloads, verified offline artifacts, YAML installation and isolated recovery; test registry removed.')


if __name__ == '__main__':
    main()
