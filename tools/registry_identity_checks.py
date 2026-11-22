"""Hardware-free checks for Docker archive identity verification."""
import hashlib
import io
import json
import tarfile
from pathlib import Path
from load_release import archive_config_id, image_config_id


def run_registry_identity_checks(folder):
    raw = b'{"os":"linux","architecture":"amd64","rootfs":{"diff_ids":["sha256:layer"]}}'
    expected = {'Os': 'linux', 'Architecture': 'amd64', 'RootFS': {'Layers': ['sha256:layer']}}
    config_id = 'sha256:' + hashlib.sha256(raw).hexdigest()
    for name in ('config.json', 'blobs/sha256/' + config_id.removeprefix('sha256:')):
        path = Path(folder) / 'identity.tar'
        with tarfile.open(path, 'w') as archive:
            for entry, data in [('manifest.json', json.dumps([{'Config': name}]).encode()), (name, raw)]:
                item = tarfile.TarInfo(entry)
                item.size = len(data)
                archive.addfile(item, io.BytesIO(data))
        assert archive_config_id(path, expected) == config_id
        for wrong in ({**expected, 'Architecture': 'arm64'}, {**expected, 'RootFS': {'Layers': ['sha256:other']}}):
            try:
                archive_config_id(path, wrong)
            except AssertionError:
                pass
            else:
                raise AssertionError('Wrong platform or layer identity accepted')
    assert image_config_id('never-contacted', {'Id': config_id}) == config_id
    print('PASS: classic/OCI saved configuration identities, platform/layer mismatch rejection and legacy IDs.')
