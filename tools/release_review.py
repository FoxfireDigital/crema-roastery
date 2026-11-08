"""Bounded, repeatable privacy/history/archive evidence; never publishes anything."""
import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import zipfile
from privacy_check import check_items

ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])


def review(archive):
    if git('status', '--porcelain').strip():
        raise ValueError('Commit the exact reviewed candidate first; working tree is not clean.')
    commit = git('rev-parse', 'HEAD').decode().strip()
    names = [n for n in git('ls-files', '-z').decode().split('\0') if n]
    source = {n: (ROOT / n).read_bytes() for n in names}
    if any((ROOT / n).is_symlink() for n in names):
        raise ValueError('Release source must not contain symlinks.')
    with contextlib.redirect_stdout(io.StringIO()): check_items(source.items())
    manifest = json.loads(source['MANIFEST.json'])
    entries = manifest['files']
    if len({e['path'] for e in entries}) != len(entries): raise ValueError('Duplicate source manifest entries.')
    expected = {e['path']: e for e in entries}
    if set(expected) != set(source) - {'MANIFEST.json'}: raise ValueError('Manifest/source file set mismatch.')
    for name, item in expected.items():
        if len(source[name]) != item['bytes'] or hashlib.sha256(source[name]).hexdigest() != item['sha256']:
            raise ValueError('Manifest/source bytes differ: ' + name)
    with zipfile.ZipFile(archive) as bundle:
        infos = bundle.infolist()
        if len({i.filename for i in infos}) != len(infos): raise ValueError('Duplicate archive names.')
        files = {i.filename: bundle.read(i) for i in infos if not i.is_dir()}
    if set(files) != {'crema/' + n for n in source}: raise ValueError('Archive/source file set mismatch.')
    if any(files['crema/' + n] != raw for n, raw in source.items()): raise ValueError('Archive/source bytes differ.')
    # Only HEAD ancestry is proposed for publication. Other refs/logs/assets
    # need their own explicit review before any repository visibility change.
    revisions = git('rev-list', 'HEAD').decode().splitlines()
    if len(revisions) > 1000: raise ValueError('History exceeds bounded review; split the assessment deliberately.')
    blobs = {}
    for revision in revisions:
        metadata = git('show', '-s', '--format=%ae%n%ce%n%B', revision).decode()
        emails = metadata.splitlines()[:2]
        if any(not email.endswith('@users.noreply.github.com') for email in emails):
            raise ValueError('Commit identity requires privacy review: ' + revision)
        with contextlib.redirect_stdout(io.StringIO()): check_items([('commit-message.txt', metadata.encode())])
        for entry in git('ls-tree', '-r', '-z', revision).split(b'\0'):
            if not entry: continue
            mode_type_id, path = entry.split(b'\t', 1)
            mode, kind, object_id = mode_type_id.decode().split()
            name = path.decode()
            if kind != 'blob' or mode not in ['100644', '100755']: raise ValueError('Unexpected tree entry: ' + name)
            blobs.setdefault((object_id, name), None)
    if len(blobs) > 30000: raise ValueError('History exceeds bounded blob review.')
    for object_id, name in blobs:
        with contextlib.redirect_stdout(io.StringIO()): check_items([(name, git('cat-file', 'blob', object_id))])
    return {'commit': commit, 'version': manifest['version'], 'sourceFiles': len(source),
            'sourceManifestMatches': True, 'archiveMatchesSource': True,
            'archiveSHA256': hashlib.sha256(Path(archive).read_bytes()).hexdigest(),
            'headAncestryCommitsReviewed': len(revisions), 'historicalBlobPathsReviewed': len(blobs),
            'privacyPatternsPassed': True, 'publicReleaseApproved': False,
            'reviewLimits': ['Pattern checks are not a complete privacy or security assessment.',
                            'Only HEAD ancestry is covered; other refs, Actions logs and release assets require review.',
                            'Dependency advisories, licenses, external pilot and publication approval are separate gates.']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.is_relative_to(ROOT): raise SystemExit('Save private review evidence outside the product source tree.')
    report = review(args.archive)
    output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))
