"""Fail closed on private assets/state in this source release."""
from pathlib import Path
import re,json,sys,zipfile,hashlib
ROOT=Path(__file__).resolve().parents[1]
# Known markers are represented in pieces so the scanner has no private data.
markers=['fox'+'fire.digital','chan'+'tal','xhn'+'x4x','fl'+'oyd','trail'+'blazer','sunrise '+'warrior','voya'+'ger','C:'+ '/'+'Users/','C:'+chr(92)+'Users'+chr(92)]
forbidden={'.env','.git','state','backups','__pycache__'}
binary_suffixes={'.sqlite3','.db','.dump','.png','.jpg','.jpeg','.webp','.zip','.xlsx','.csv','.alog','.alrm','.xml','.pfx','.pem','.key','.dpapi'}
# Reviewed transformation of existing platform choices only; no catalog/customer seeds.
# Exact bytes are allowlisted so changing this migration requires a fresh privacy review.
reviewed_migrations={'app/portal/migrations/0005_marketplace_selection.py':'8b9ec808c90c8dbc5dc33d8dc3bbbcaa8172c6fad026748ebfdc051d10a79df5'}
def check_items(items):
    checked=0;fail=[]
    for name,raw in items:
        parts=Path(name).parts
        if '.git' in parts or '__pycache__' in parts:continue
        if any(part in forbidden for part in parts) or Path(name).suffix.lower() in binary_suffixes:fail.append(name+': private-state or binary file');continue
        try:text=raw.decode('utf-8-sig')
        except UnicodeDecodeError:fail.append(name+': unexpected binary data');continue
        low=text.casefold()
        if any(marker.casefold() in low for marker in markers):fail.append(name+': private installation marker')
        if re.search(r'(?<![A-Za-z0-9])(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|shpat_[a-f0-9]{20,}|-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----)',text):fail.append(name+': credential pattern')
        if re.search(r'\b(?:10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+)\b',text):fail.append(name+': private LAN address')
        if name.endswith('artisan_catalog.json') and json.loads(text)!={'profiles':[],'alarms':[]}:fail.append(name+': nonempty profile catalog')
        if name.endswith('label_artwork/catalog.json') and json.loads(text)!=[]:fail.append(name+': nonempty label catalog')
        if '/migrations/' in name and re.search(r'RunPython|RunSQL',text):
            approved=next((sha for path,sha in reviewed_migrations.items() if name==path or name.endswith('/'+path)),None)
            if hashlib.sha256(raw.replace(b'\r\n',b'\n')).hexdigest()!=approved:fail.append(name+': unexpected seeded or unreviewed data migration')
        checked+=1
    if fail:raise SystemExit('Release privacy check failed:\n'+'\n'.join(fail))
    print('PASS: source-only privacy checks ('+str(checked)+' files).')
if __name__=='__main__':
    if len(sys.argv)>1:
        with zipfile.ZipFile(sys.argv[1]) as archive:check_items((i.filename,archive.read(i)) for i in archive.infolist() if not i.is_dir())
    else:check_items((p.relative_to(ROOT).as_posix(),p.read_bytes()) for p in ROOT.rglob('*') if p.is_file())
