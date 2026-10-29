"""Parse untrusted Artisan documents as data; never execute profile content."""
import ast,base64,hashlib,json,math
from decimal import Decimal,ROUND_HALF_UP
from django.core.exceptions import ValidationError

MAX_FILE=2_000_000
MAX_SAMPLES=60000

def reject(message):raise ValidationError(message)

def decode_document(raw):
    if not raw or len(raw)>MAX_FILE:reject('Choose an .alog file no larger than 2 MB.')
    try:text=raw.decode('utf-8-sig')
    except UnicodeDecodeError:reject('Save the Artisan file as UTF-8 and upload it again.')
    def pairs(values):
        result={}
        for key,value in values:
            if key in result:reject('This file has duplicate data fields. Save a fresh copy from Artisan.')
            result[key]=value
        return result
    try:
        try:data=json.loads(text,object_pairs_hook=pairs,parse_constant=lambda value:reject('The file contains a non-finite number.'))
        except json.JSONDecodeError:
            tree=ast.parse(text,mode='eval')
            if sum(1 for _ in ast.walk(tree))>350000:reject('This profile is too complex to read.')
            for node in ast.walk(tree):
                if isinstance(node,ast.Dict):
                    keys=[ast.literal_eval(key) for key in node.keys]
                    if not all(isinstance(key,str) for key in keys) or len(keys)!=len(set(keys)):reject('The file has invalid or duplicate data fields.')
            # literal_eval never runs function calls, imports or variable lookups.
            data=ast.literal_eval(tree)
    except (ValueError,SyntaxError,TypeError,RecursionError,MemoryError):reject('This is not a readable Artisan .alog file.')
    if not isinstance(data,dict) or not all(isinstance(key,str) for key in data):reject('An Artisan profile must contain named data fields.')
    stack=[(data,0)];count=0
    while stack:
        value,depth=stack.pop();count+=1
        if depth>32 or count>350000:reject('This profile has too much nested data.')
        if isinstance(value,dict):
            if not all(isinstance(key,str) for key in value):reject('Invalid profile field names.')
            stack.extend((item,depth+1) for item in value.values())
        elif isinstance(value,(list,tuple)):stack.extend((item,depth+1) for item in value)
        elif isinstance(value,float) and not math.isfinite(value):reject('The file contains a non-finite number.')
        elif not isinstance(value,(str,int,float,bool,type(None))):reject('The file contains unsupported data types.')
    return data

def numeric(value):
    try:return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)
    except (OverflowError,ValueError):return False

def inspect(raw,filename,*,reference=False):
    data=decode_document(raw);mode=data.get('mode')
    if mode not in ['F','C']:reject('The file must identify Fahrenheit or Celsius units.')
    if reference and mode!='F':reject('Our production references use Fahrenheit. Convert the profile to Fahrenheit in Artisan before uploading.')
    times=data.get('timex');bt=data.get('temp2');indices=data.get('timeindex')
    if not isinstance(times,(list,tuple)) or not 3<=len(times)<=MAX_SAMPLES:reject('The profile needs 3–60,000 recorded samples.')
    if not isinstance(bt,(list,tuple)) or len(bt)!=len(times):reject('Bean temperatures must match the recorded time samples.')
    if any(not numeric(t) or abs(t)>10000000 for t in times) or any(b<a for a,b in zip(times,times[1:])):reject('Recorded times must be finite and in order.')
    if any(not numeric(t) or not -1000<=t<=2000 for t in bt):reject('The file contains invalid bean temperatures.')
    if not isinstance(indices,(list,tuple)) or len(indices)<7:reject('Mark Charge and Drop in Artisan before uploading this file.')
    charge,drop=indices[0],indices[6]
    if type(charge)!=int or type(drop)!=int or not 0<=charge<drop<len(times) or times[drop]<=times[charge]:reject('The file needs valid Charge and Drop markers in order.')
    if times[drop]-times[charge]>86400:reject('The recorded roast duration is longer than 24 hours. Check its markers.')
    def point(position):
        index=indices[position]
        if type(index)!=int or not charge<=index<=drop or position and index<=charge:return None
        temp=float(bt[index]);fahrenheit=temp if mode=='F' else temp*9/5+32
        return {'sample':index,'seconds':float(times[index]),'elapsed':round(float(times[index]-times[charge]),3),'bt':fahrenheit}
    ch=point(0);dr=point(6);fc=point(2);dry=point(1)
    if reference and (not 32<=ch['bt']<dr['bt']<=599.9):reject('Production references need Charge below Drop, between 32.0°F and 599.9°F.')
    if reference and Decimal(str(ch['bt'])).quantize(Decimal('.1'),rounding=ROUND_HALF_UP)>=Decimal(str(dr['bt'])).quantize(Decimal('.1'),rounding=ROUND_HALF_UP):reject('Charge and Drop must remain distinct when rounded to tenths.')
    duration=dr['elapsed'];development=round(duration-fc['elapsed'],1) if fc else None
    filename=str(filename).replace('\\','/').rsplit('/',1)[-1]
    if not filename.lower().endswith('.alog'):reject('Choose an Artisan .alog file.')
    filename=''.join(c for c in filename if c.isprintable())[:180]
    title=data.get('title') if isinstance(data.get('title'),str) else filename[:-5]
    metadata={'file':filename,'title':title[:240],'sha256':hashlib.sha256(raw).hexdigest(),'units':mode,'date':str(data.get('roastisodate',''))[:32],
              'charge':ch,'drop':dr,'firstCrack':fc,'dryEnd':dry,'durationSeconds':round(duration,1),'developmentSeconds':development,'developmentPercent':round(100*development/duration,1) if development is not None else None,
              'samples':len(times),'duplicateOf':None,'version':str(data.get('version',''))[:40]}
    return data,metadata

def source_entry(source,key):return {**source.inspection,'key':key,'source_id':str(source.pk)}

def bytes_for(entry):
    if entry.get('source_id'):
        from .models import ArtisanProfileSource
        raw=base64.b64decode(ArtisanProfileSource.objects.get(pk=entry['source_id']).original_b64,validate=True)
    else:raw=base64.b64decode(entry['original_b64'],validate=True)
    if hashlib.sha256(raw).hexdigest()!=entry['sha256']:reject('The saved source failed its integrity check.')
    return raw

def curve(raw,filename='profile.alog'):
    data,meta=inspect(raw,filename);start=meta['charge']['sample'];end=meta['drop']['sample'];indices=set(range(start,end+1,max(1,(end-start)//1100)))
    indices.update([start,end]);indices.update(p['sample'] for p in [meta['firstCrack'],meta['dryEnd']] if p)
    shift=data['timex'][start]
    points=[[round(float(data['timex'][i]-shift),3),round(float(data['temp2'][i])*(9/5 if meta['units']=='C' else 1)+(32 if meta['units']=='C' else 0),3)] for i in sorted(indices)]
    return {'metadata':meta,'points':points}

def comparison(actual,reference=None):
    series=[actual]+([reference] if reference else [])
    duration=max(row['points'][-1][0] for row in series)
    values=[p[1] for row in series for p in row['points']];low=math.floor(min(values)/25)*25;high=math.ceil(max(values)/25)*25
    if high<=low:high=low+25
    width,height,left,top=860,270,66,22
    def coordinates(row):return ' '.join(f'{left+p[0]/duration*width:.2f},{top+(high-p[1])/(high-low)*height:.2f}' for p in row['points'])
    return {'actual':actual['metadata'],'reference':reference['metadata'] if reference else None,'actual_points':coordinates(actual),'reference_points':coordinates(reference) if reference else '',
            'yticks':[{'value':round(low+(high-low)*i/4),'y':round(top+height-i*height/4,2)} for i in range(5)],
            'xticks':[{'value':round(duration*i/5/60,1),'x':round(left+width*i/5,2)} for i in range(6)]}
