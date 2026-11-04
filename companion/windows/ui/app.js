'use strict';
const $=id=>document.getElementById(id), send=(action,data={})=>window.chrome.webview.postMessage({action,...data});
let state={},selected=null,selectionKey='',originTouched=false;
const text=(id,value)=>{$(id).textContent=value??'';},show=(id,value)=>{$(id).hidden=!value;};
for(const action of ['refresh','disconnect','forget','manage','open','choose','copy','next','cancel','hide','view','exit'])$(action).addEventListener('click',()=>send(action));
for(const id of ['pickerOpen','emptyChoose','connectionBadge'])$(id).addEventListener('click',()=>$('roastPicker').showModal());
$('pickerClose').addEventListener('click',()=>$('roastPicker').close());
$('origin').addEventListener('input',()=>originTouched=true);
$('open').addEventListener('click',()=>$('roastPicker').close());
$('connect').addEventListener('click',()=>send('connect',{origin:$('origin').value}));
for(const field of ['ready','curve','alarms'])$(field).addEventListener('change',()=>send('check',{field,value:$(field).checked}));
$('mode').addEventListener('change',profiles);$('profile').addEventListener('change',targets);$('confirmLoad').addEventListener('change',()=>{$('prepare').disabled=state.busy||!$('confirmLoad').checked||!$('profile').value;});
$('prepare').addEventListener('click',()=>{if(selected)send('prepare',{row:selected.id,profile:Number($('profile').value),mode:$('mode').value,confirmed:$('confirmLoad').checked});});
function profiles(){
 $('profile').replaceChildren();$('confirmLoad').checked=false;
 for(const p of selected?.profiles[$('mode').value]||[]){const o=document.createElement('option');o.value=p.id;o.textContent=p.name;$('profile').append(o);}
 if(!$('profile').children.length){const o=document.createElement('option');o.value='';o.textContent='No approved profile for this session';$('profile').append(o);}
 targets();$('prepare').disabled=true;
}
function targets(){const p=selected?.profiles[$('mode').value]?.find(x=>String(x.id)===$('profile').value);text('profileTargets',p?`Charge ${Number(p.charge).toFixed(1)}°F · Drop ${Number(p.drop).toFixed(1)}°F · Off ${(Number(p.drop)+.1).toFixed(1)}°F`:'Review and approve a matching profile in Crema first.');}
const themeKeys=new Set(['forest','forest_dark','ink','heading','muted','surface','panel','soft','line','focus','on_primary','error_bg','red','selected','selected_ink']);
function theme(account){
 const tokens=account?.palette?.tokens||{};
 for(const key of themeKeys){const value=tokens[key];if(typeof value==='string'&&/^#[0-9a-f]{6}$/i.test(value))document.documentElement.style.setProperty('--'+key.replaceAll('_','-'),value);else document.documentElement.style.removeProperty('--'+key.replaceAll('_','-'));}
 document.documentElement.style.colorScheme=account?.palette?.dark?'dark':'light';
}
function render(s){
 const changedView=!!state.quickView!==!!s.quickView;state=s;theme(s.account);document.body.classList.toggle('quick',!!s.quickView);text('view',s.quickView?'Full view':'Quick view');if(changedView)document.querySelector('main').scrollTop=0;if(!originTouched&&!$('origin').value&&s.origin)$('origin').value=s.origin;text('status',s.status);$('status').classList.toggle('error',s.problem);
 text('connectionBadge',s.connected?'Connected':s.code?'Connecting':'Offline');text('roastery',s.account?.roastery||'Connect to Crema');text('identity',s.account?`${s.account.username} · ${s.account.palette.name}`:'Your roast day, ready when you are.');text('brandName',s.account?.roastery||'CREMA COMPANION');text('portalOrigin',s.origin);
 show('connectForm',!s.connected&&!s.code);show('pairing',!!s.code);text('paircode',s.code);show('connectedActions',s.connected);show('roastList',s.connected);
 text('roastCount',s.roasts?.length||0);$('roasts').replaceChildren();
 for(const row of s.roasts||[]){const b=document.createElement('button');b.className='roast-choice';b.classList.toggle('selected',row.id===selected?.id);b.disabled=s.busy;const strong=document.createElement('strong'),small=document.createElement('small');strong.textContent=row.coffee;small.textContent=`${row.roast} · ${row.roaster} · ${Number(row.green).toFixed(1)} oz\n${row.date} · Plan #${row.plan} / Load #${row.id}`;b.append(strong,small);b.addEventListener('click',()=>{selected=row;selectionKey='';$('roastPicker').close();render(state);$('selection').scrollIntoView({block:'nearest'});});$('roasts').append(b);}
 if(s.connected&&!(s.roasts||[]).length){const p=document.createElement('p');p.className='hint';p.textContent='No unroasted loads in accepted active plans.';$('roasts').append(p);}
 if(selected){const fresh=(s.roasts||[]).find(r=>r.id===selected.id);if(!fresh){selected=null;selectionKey='';}else selected=fresh;}
 const p=s.preparation,review=!!selected&&(!p||selected.id!==p.Row||s.stage==='Verified'||s.stage==='Uncertain');show('selection',review);show('empty',!p&&!review);show('prepared',!!p&&!review);show('handoff',!!p&&!review);
 if(review){text('selectionName',selected.coffee);text('selectionMeta',`${selected.roast} · ${selected.roaster} · ${Number(selected.green).toFixed(1)} oz green · Plan #${selected.plan}`);const key=selected.id+':'+selected.fingerprint;if(key!==selectionKey){selectionKey=key;profiles();}}
 text('headline',p&&!review?(s.stage==='Verified'?'Preparation verified':'Ready for your next roast'):'Ready for your next roast');text('subtitle',p&&!review?`Plan #${p.Plan} · Load #${p.Row}`:'Choose a roast, or open a preparation from Crema.');
 if(p){const roastName={Light:'City / Light','Light/Medium':'City+ / Light-Medium',Medium:'Full City / Medium','Medium/Dark':'Full City+ / Medium-Dark',Dark:'Vienna / Dark',French:'French'}[p.Roast]||p.Roast;text('coffee',p.Coffee);text('roast',p.Roaster+' \u00b7 '+roastName);if(s.quickView){text('headline','Next: '+p.Coffee);text('subtitle',`${p.Roaster} \u00b7 ${Number(p.Green).toFixed(1)} oz \u00b7 ${p.Mode==='first'?'First':'Second'} \u00b7 ${roastName}`);}text('quickTitle',p.Title);text('quickTargets',`Charge ${Number(p.Charge).toFixed(1)}\u00b0F \u00b7 Drop ${Number(p.Drop).toFixed(1)}\u00b0F \u00b7 Off ${Number(p.Off).toFixed(1)}\u00b0F`);text('weight',Number(p.Green).toFixed(1)+' oz');text('schedule',p.Mode==='first'?'First · cold machine':'Second · warm machine');text('title',p.Title);for(const field of ['charge','drop','off'])text(field,Number(p[field[0].toUpperCase()+field.slice(1)]).toFixed(1));text('artisan',s.artisan);}
 for(const field of ['ready','curve','alarms'])$(field).checked=s[field];
 show('readyRow',s.stage==='Review');show('curveRow',s.stage==='BackgroundSent');show('alarmsRow',s.stage==='AlarmsSent');
 const index={Review:0,BackgroundSent:1,AlarmsSent:2,Verified:3,Uncertain:0}[s.stage];document.querySelectorAll('.steps li').forEach((e,i)=>e.classList.toggle('active',i<=index));
 const labels={Review:'Load in open Artisan',BackgroundSent:'Load paired alarms',AlarmsSent:'Finish preparation',Verified:'Choose next roast',Uncertain:'Open a fresh preparation'};text('next',s.busy?'Working…':labels[s.stage]);
 text('result',s.busy?'Working\u2026':s.stage==='Verified'?'Preparation verified':p?'Waiting for your action':'Ready when you are');
 text('sourceNote',s.onlinePreparation?'Connected · current load checked before each handoff.':'Offline ZIP · live plan changes cannot be detected.');
 for(const button of document.querySelectorAll('button'))if(!button.classList.contains('roast-choice'))button.disabled=s.busy&&!['cancel','hide','view','pickerClose','connectionBadge'].includes(button.id);
 for(const input of document.querySelectorAll('input,select'))input.disabled=s.busy;
 $('prepare').disabled=s.busy||!$('confirmLoad').checked||!$('profile').value;
 $('next').disabled=s.busy||!p||!(s.stage==='Review'?s.ready:s.stage==='BackgroundSent'?s.ready&&s.curve:s.stage==='AlarmsSent'?s.alarms:true);
}
window.chrome.webview.addEventListener('message',e=>render(e.data));send('hello');
