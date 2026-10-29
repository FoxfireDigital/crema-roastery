"""Check pip's resolved report against OSV without importing the application."""
from pathlib import Path
import json,sys,urllib.request

report=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
packages=[{'package':{'name':item['metadata']['name'],'ecosystem':'PyPI'},'version':item['metadata']['version']} for item in report['install']]
if not packages or len(packages)>200:raise SystemExit('Unexpected dependency report; audit did not run.')
request=urllib.request.Request('https://api.osv.dev/v1/querybatch',json.dumps({'queries':packages}).encode(),{'Content-Type':'application/json','User-Agent':'Crema-dependency-audit'})
with urllib.request.urlopen(request,timeout=45) as response:data=json.load(response)
if len(data.get('results',[]))!=len(packages):raise SystemExit('Incomplete advisory response; audit did not pass.')
findings=[]
for package,result in zip(packages,data['results']):
    findings.extend(package['package']['name']+' '+package['version']+': '+v['id'] for v in result.get('vulns',[]))
if findings:raise SystemExit('Dependency advisories require review:\n'+'\n'.join(findings))
print('PASS: no known advisories returned for '+str(len(packages))+' resolved packages. This is not a full security audit.')
