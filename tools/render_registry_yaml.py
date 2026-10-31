"""Render a deployment YAML using explicitly supplied immutable image references."""
from pathlib import Path
import argparse
import json
import re

ROOT = Path(__file__).resolve().parents[1]


def render(images, destination):
    assert set(images) == {'application', 'database', 'proxy'}
    for reference in images.values():
        assert isinstance(reference, str) and re.fullmatch(r'[a-z0-9][a-z0-9./:_-]*@sha256:[a-f0-9]{64}', reference), 'Supply complete immutable image references without credentials'
    source = ROOT / 'compose.yaml'
    destination = Path(destination).resolve()
    assert destination != source.resolve(), 'Do not overwrite the source installation YAML'
    text = source.read_text()
    text, app_count = re.subn(r'^(x-portal-image: &portal-image) crema:[a-z0-9.-]+$', lambda m: m[1] + ' ' + images['application'], text, flags=re.M)
    text, db_count = re.subn(r'^    image: crema-database:[a-z0-9.-]+$', '    image: ' + images['database'], text, flags=re.M)
    text, proxy_count = re.subn(r'^    image: crema-proxy:[a-z0-9.-]+$', '    image: ' + images['proxy'], text, flags=re.M)
    assert app_count == db_count == proxy_count == 1
    text = text.replace('pull_policy: never', 'pull_policy: if_not_present')
    text = '# Generated from explicit image digests; edit domain/origin/timezone before installing.\n' + text
    destination.write_text(text)
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image_map', type=Path, help='JSON object: application, database and proxy immutable references')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    render(json.loads(args.image_map.read_text()), args.output)
    print('Rendered deployment YAML. No images were pushed, pulled or made public.')
