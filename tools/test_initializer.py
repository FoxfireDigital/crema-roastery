"""Linux initializer tests; no existing volume/database is touched."""
from pathlib import Path
import os,sys,tempfile,subprocess
app=Path(os.environ.get('PORTAL_APP_ROOT',str(Path(__file__).resolve().parents[1]/'app')))
with tempfile.TemporaryDirectory(prefix='roastery-initializer-test-') as folder:
    base=Path(folder);keys=base/'keys';db=base/'db';db.mkdir()
    env={**os.environ,'PORTAL_SECRET_ROOT':str(keys),'PORTAL_DATABASE_CHECK_ROOT':str(db)}
    def run():return subprocess.run([sys.executable,str(app/'init_instance.py')],env=env,capture_output=True,text=True)
    first=run();assert first.returncode==0,first.stderr
    original={p.name:p.read_bytes() for p in [keys/'django',keys/'postgres']}
    assert original['django']!=original['postgres'] and all(len(v)>=64 for v in original.values())
    assert all(v.decode() not in first.stdout+first.stderr for v in original.values())
    (db/'PG_VERSION').write_text('16')
    again=run();assert again.returncode==0 and original=={p.name:p.read_bytes() for p in [keys/'django',keys/'postgres']}
    (keys/'django').unlink();failed=run();assert failed.returncode!=0 and not (keys/'django').exists()
    (keys/'postgres').unlink();failed=run();assert failed.returncode!=0 and not (keys/'django').exists() and not (keys/'postgres').exists()
    assert 'database is not empty' in failed.stderr.lower()
    print('PASS: unique initialization, no secret output, restart preservation, partial-key and existing-database recovery guards.')
