"""Create instance keys in a dedicated volume; never print or rotate them."""
from pathlib import Path
import fcntl,os,re,secrets
root=Path(os.environ.get('PORTAL_SECRET_ROOT','/var/lib/roastery-secrets'))
database=Path(os.environ.get('PORTAL_DATABASE_CHECK_ROOT','/database-check'))
def initialize():
    root.mkdir(mode=0o755,parents=True,exist_ok=True)
    with (root/'.initialize.lock').open('a') as lock:
        os.chmod(root/'.initialize.lock',0o600);fcntl.flock(lock,fcntl.LOCK_EX)
        paths=[root/'django',root/'postgres'];present=[p.is_file() for p in paths]
        if all(present):
            for path in paths:
                if not re.fullmatch(r'[A-Za-z0-9_-]{64,128}',path.read_text(encoding='ascii')):raise SystemExit('Invalid instance key. Preserve the volumes and restore the original keys; no keys were changed.')
            print('Existing instance keys retained; no credentials changed.');return
        if any(present):raise SystemExit('Incomplete instance keys. Recover the missing key; initialization will not replace credentials.')
        try:
            if not database.is_dir() or any(database.iterdir()):raise SystemExit('The database is not empty. Restore its original instance keys; no new keys were generated.')
        except PermissionError:raise SystemExit('Cannot verify an empty database. Recover the original instance keys before starting.')
        for path in paths:
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w',encoding='ascii') as file:
                file.write(secrets.token_urlsafe(64));file.flush();os.fsync(file.fileno())
            # PostgreSQL uses another UID. Only containers explicitly granted
            # this Docker-managed volume receive these files.
            os.chmod(path,0o444)
        print('Unique instance keys created in persistent storage. No default account was created.')
if __name__=='__main__':initialize()
