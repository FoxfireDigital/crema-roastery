"""Verify and load a generic offline image bundle; never starts an installation."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess
import tarfile


def inspect(reference):
    result = subprocess.run(['docker', 'image', 'inspect', reference], capture_output=True)
    if result.returncode:
        return None
    return json.loads(result.stdout)[0]


def validate(folder):
    folder = Path(folder).resolve()
    manifest = json.loads((folder / 'release-manifest.json').read_text())
    assert manifest['format'] == 'crema-offline-release-v1'
    version, revision = manifest['version'], manifest['revision']
    assert re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[a-z0-9.-]+)?', version)
    assert re.fullmatch(r'[a-f0-9]{40}(?:-dirty)?', revision)
    assert sorted(item['role'] for item in manifest['images']) == ['application', 'database', 'proxy']
    expected_names = {'application': 'crema', 'database': 'crema-database', 'proxy': 'crema-proxy'}
    for item in manifest['images']:
        assert item['reference'] == expected_names[item['role']] + ':' + version
        path = (folder / item['file']).resolve()
        assert path.is_relative_to(folder) and path.is_file() and path.stat().st_size == item['bytes']
        with path.open('rb') as stream:
            assert hashlib.file_digest(stream, 'sha256').hexdigest() == item['sha256'], 'Artifact checksum mismatch'
        # Verify the tag list too: an otherwise valid archive must not overwrite
        # unrelated local images when Docker loads it.
        with tarfile.open(path, 'r:gz') as archive:
            members = archive.getmembers()
            assert len(members) == len({member.name for member in members})
            assert all(member.isfile() and Path(member.name).name == member.name for member in members)
            assert archive.getmember('manifest.json').size < 2_000_000
            entries = json.load(archive.extractfile('manifest.json'))
            assert len(entries) == 1 and entries[0]['RepoTags'] == [item['reference']]
            config = entries[0]['Config']
            assert Path(config).name == config
            assert archive.getmember(config).size < 2_000_000
            assert {member.name for member in members} == {'manifest.json', config, *entries[0]['Layers']}
            data = archive.extractfile(config).read()
            assert 'sha256:' + hashlib.sha256(data).hexdigest() == item['imageId']
        existing = inspect(item['reference'])
        assert existing is None or existing['Id'] == item['imageId'], 'An existing image tag identifies different content; nothing loaded'
    return manifest


def load(folder):
    folder = Path(folder).resolve()
    manifest = validate(folder)  # Check every artifact before loading any.
    titles = {'application': 'Crema', 'database': 'Crema database', 'proxy': 'Crema proxy'}
    for item in manifest['images']:
        subprocess.run(['docker', 'load', '--input', str(folder / item['file'])], capture_output=True, check=True)
        info = inspect(item['reference'])
        assert info['Id'] == item['imageId']
        labels = info['Config'].get('Labels') or {}
        assert labels.get('org.opencontainers.image.title') == titles[item['role']]
        assert labels.get('org.opencontainers.image.version') == manifest['version']
        assert labels.get('org.opencontainers.image.revision') == manifest['revision']
    print('PASS: all release artifacts verified and loaded; no containers or data volumes were started or changed.')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    if args.verify_only:
        validate(args.folder)
        print('PASS: artifact checksums, image configurations, tag lists and existing-tag guard.')
    else:
        load(args.folder)
