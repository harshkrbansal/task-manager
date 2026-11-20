(()=>{
const $=s=>document.querySelector(s);
document.head.insertAdjacentHTML('beforeend','<style>.voice{border:1px dashed var(--line);border-radius:8px;padding:10px;margin:8px 0 4px}.voice .vrow{display:flex;gap:6px;flex-wrap:wrap;align-items:center}.voice textarea{width:100%;margin-top:8px;padding:7px 9px;border:1px solid var(--line);border-radius:6px;background:var(--bg)}.voice .vrec{color:var(--high);font-weight:600}.voice [hidden]{display:none}</style>');

const NUM={ek:1,one:1,do:2,two:2,teen:3,three:3,char:4,chaar:4,four:4,paanch:5,panch:5,five:5,chhe:6,che:6,six:6,saat:7,seven:7,aath:8,eight:8,nau:9,nine:9,das:10,ten:10,gyarah:11,eleven:11,barah:12,twelve:12};
const MON={jan:0,january:0,feb:1,february:1,mar:2,march:2,apr:3,april:3,may:4,jun:5,june:5,jul:6,july:6,aug:7,august:7,sep:8,sept:8,september:8,oct:9,october:9,nov:10,november:10,dec:11,december:11};
const WD={sunday:0,sun:0,ravivar:0,monday:1,mon:1,somvar:1,tuesday:2,tue:2,mangalvar:2,wednesday:3,wed:3,budhvar:3,thursday:4,thu:4,guruvar:4,thursdays:4,friday:5,fri:5,shukravar:5,saturday:6,sat:6,shanivar:6};
const DV={'नाम':'naam','क्लाइंट':'client','क्लायंट':'client','डेडलाइन':'deadline','नोट्स':'notes','नोट':'note','प्रायोरिटी':'priority','प्रोजेक्ट':'project','टास्क':'task','सीनियर':'senior','एनालिस्ट':'analyst','रिमाइंडर':'reminder','कैटेगरी':'category','कल':'kal','आज':'aaj','परसों':'parso','बजे':'baje','शाम':'shaam','सुबह':'subah','दोपहर':'dopahar','रात':'raat','हाई':'high','मीडियम':'medium','सोमवार':'monday','मंगलवार':'tuesday','बुधवार':'wednesday','गुरुवार':'thursday','शुक्रवार':'friday','शनिवार':'saturday','रविवार':'sunday'};
const norm=s=>{let t=' '+s+' ';for(const [k,v] of Object.entries(DV))t=t.replace(new RegExp('(?<![\\p{L}\\p{M}])'+k+'(?![\\p{L}\\p{M}])','gu'),' '+v+' ');return t.replace(/\s+/g,' ').trim()};

const K={
 task:[['title','task name|task title|task|title|kaam|naam|name'],['due','due date|due on|due|deadline|last date'],['pri','priority|importance'],['cat','category'],['proj','project name|project'],['rep','repeat'],['rem','reminder|remind me|remind|alert'],['notes','notes|note|remarks|remark|details|detail']],
 project:[['name','project name|project|naam|name'],['client','client|customer'],['start','start date|starting|start|shuru'],['due','due date|due on|due|deadline|last date'],['senior','senior analyst|senior|reviewer'],['analyst','analyst|mentee'],['extra','extra details|extra|additional'],['notes','notes|note|remarks|remark']]
};
const clean=v=>v.replace(/^[\s,.:;\-]+|[\s,.:;\-]+$/g,'');
function split(text,kind){
  const t=norm(text),map={},alts=[];
  K[kind].forEach(([f,w])=>w.split('|').forEach(x=>{map[x]=f;alts.push(x)}));
  alts.sort((a,b)=>b.length-a.length);
  const re=new RegExp('(?<![a-z0-9])('+alts.map(a=>a.replace(/ /g,'\\s+')).join('|')+')(?![a-z0-9])','gi');
  const hits=[];let m;
  while((m=re.exec(t))){const f=map[m[1].toLowerCase().replace(/\s+/g,' ')];hits.push({f,s:m.index,e:m.index+m[0].length});if(f==='notes'||f==='extra')break}
  const out={},rest=[],pre=clean(hits.length?t.slice(0,hits[0].s):t);
  if(pre)rest.push(pre);
  hits.forEach((h,i)=>{const v=clean(t.slice(h.e,i+1<hits.length?hits[i+1].s:t.length));if(!v)return;
    if(h.f==='notes'||h.f==='extra')(out[h.f]=out[h.f]||[]).push(v);else out[h.f]=v});
  return {out,rest};
}
const pad=n=>String(n).padStart(2,'0');
const ymd=x=>x.getFullYear()+'-'+pad(x.getMonth()+1)+'-'+pad(x.getDate());
const hm=x=>pad(x.getHours())+':'+pad(x.getMinutes());
const pri=v=>/\b(high|urgent|critical|jaldi|zaroori|zaruri|important)\b/i.test(v)?'High':/\b(low|kam|chhota)\b/i.test(v)?'Low':/\b(medium|normal|madhyam)\b/i.test(v)?'Medium':null;
function rem(v){
  const s=v.toLowerCase().replace(/\b[a-z]+\b/g,w=>NUM[w]||w),o=new Set();
  if(/(due time|time pe|time par|on time|at due)/.test(s))o.add(0);
  for(const m of s.matchAll(/(\d+)\s*(min\w*|ghant\w*|hour\w*|hr\w*|din|day\w*)/g)){
    const n=+m[1],u=m[2],mins=/^min/.test(u)?n:/^(ghant|hour|hr)/.test(u)?n*60:n*1440;
    if(OFFS.some(x=>x[0]===mins))o.add(mins)}
  return [...o];
}
const MN=Object.keys(MON).sort((a,b)=>b.length-a.length).join('|');
function when(v){
  const s=' '+norm(v).toLowerCase().replace(/,/g,' ').replace(/\.(?!\d)/g,' ').replace(/\b[a-z]+\b/g,w=>NUM[w]||w).replace(/\s+/g,' ')+' ';
  const b=new Date();b.setHours(0,0,0,0);
  const day=n=>{const x=new Date(b);x.setDate(x.getDate()+n);return x};
  const mk=(dd,mm,yy)=>{if(mm<0||mm>11||dd<1||dd>31)return null;const y=yy?(yy<100?2000+yy:yy):b.getFullYear();let x=new Date(y,mm,dd);if(!yy&&x<b)x=new Date(y+1,mm,dd);return x};
  let d=null,m;
  if(/ (parso|parson|day after tomorrow) /.test(s))d=day(2);
  else if(/ narso /.test(s))d=day(3);
  else if(/ (kal|tomorrow) /.test(s))d=day(1);
  else if(/ (aaj|today) /.test(s))d=day(0);
  else if((m=s.match(/ (\d+) (din|days?) (baad|later) /)||s.match(/ in (\d+) days? /)))d=day(+m[1]);
  else if(/ (agle|agla|next) (hafte|hafta|week) /.test(s))d=day(7);
  else if((m=s.match(new RegExp(' (?:(?:agle|agla|next|is|this) )?('+Object.keys(WD).join('|')+') ')))){let diff=(WD[m[1]]-b.getDay()+7)%7;if(diff===0)diff=7;d=day(diff)}
  else if((m=s.match(/ (\d{1,2})[\/-](\d{1,2})(?:[\/-](\d{2,4}))? /)))d=mk(+m[1],+m[2]-1,m[3]?+m[3]:0);
  else if((m=s.match(new RegExp(' (\\d{1,2})(?:st|nd|rd|th)? (?:of )?('+MN+') '))))d=mk(+m[1],MON[m[2]],0);
  else if((m=s.match(new RegExp(' ('+MN+') (\\d{1,2})(?:st|nd|rd|th)? '))))d=mk(+m[2],MON[m[1]],0);
  const per=(s.match(/ (subah|morning|dopahar|afternoon|shaam|evening|raat|night) /)||[])[1];
  const adj=(h,ap)=>{
    if(ap==='pm')return h<12?h+12:h;if(ap==='am')return h===12?0:h;
    if(per){if(/^(dopahar|afternoon|shaam|evening)$/.test(per))return h<12?h+12:h;
      if(/^(raat|night)$/.test(per))return h===12?0:(h>=6&&h<12?h+12:h);return h}
    return h>=1&&h<=7?h+12:h};
  let t=null;
  if((m=s.match(/ (\d{1,2}):(\d{2}) ?(am|pm)? /)))t=[adj(+m[1],m[3]),+m[2]];
  else if((m=s.match(/ (\d{1,2}) ?(am|pm) /)))t=[adj(+m[1],m[2]),0];
  else if((m=s.match(/ (\d{1,2}) (?:baje|bje|oclock|o'clock)/)))t=[adj(+m[1]),0];
  else if((m=s.match(/ (?:subah|morning|dopahar|afternoon|shaam|evening|raat|night) (\d{1,2}) /)))t=[adj(+m[1]),0];
  if(!d&&!t)return null;
  if(!d){d=day(0);const x=new Date(d);x.setHours(t[0],t[1]);if(x<new Date())d=day(1)}
  const x=new Date(d);x.setHours(t?t[0]:9,t?t[1]:0,0,0);
  return {d:x,hasT:!!t};
}
function addNotes(sel,arr,repl){
  if(!arr.length)return;const el=$(sel),add=arr.join('\n');
  el.value=(repl||!el.value)?add:el.value+'\n'+add;
}
function fillTask(r,repl){
  const ok=[],miss=[],notes=[...r.rest],o=r.out,put=(sel,v,n)=>{$(sel).value=v;ok.push(n)};
  if(o.title)put('#f-title',o.title,'Title');
  if(o.due){const w=when(o.due);if(w)put('#f-due',ymd(w.d)+'T'+hm(w.d),'Due');else miss.push('Due: '+o.due)}
  if(o.pri){const v=pri(o.pri);if(v)put('#f-pri',v,'Priority');else miss.push('Priority: '+o.pri)}
  if(o.cat)put('#f-cat',o.cat,'Category');
  if(o.proj){const l=o.proj.toLowerCase(),p=projects.find(x=>x.status!=='Completed'&&(x.name.toLowerCase().includes(l)||l.includes(x.name.toLowerCase())));
    if(p){$('#f-proj').value=p.id;ok.push('Project')}else miss.push('Project nahi mila: '+o.proj)}
  if(o.rep){const l=o.rep.toLowerCase();
    if(/daily|roz|har din|every day/.test(l))put('#f-rep','daily','Repeat');
    else if(/weekly|hafte|week/.test(l))put('#f-rep','weekly','Repeat');
    else if(/never|nahi|band|no/.test(l))put('#f-rep','','Repeat');else miss.push('Repeat: '+o.rep)}
  if(o.rem){const a=rem(o.rem);if(a.length){document.querySelectorAll('#chips input').forEach(i=>i.checked=a.includes(+i.value));ok.push('Reminder')}else miss.push('Reminder: '+o.rem)}
  addNotes('#f-notes',[...notes,...(o.notes||[]),...miss],repl);
  return {ok,miss};
}
function fillProject(r,repl){
  const ok=[],miss=[],notes=[...r.rest],o=r.out,put=(sel,v,n)=>{$(sel).value=v;ok.push(n)};
  if(o.name)put('#p-name',o.name,'Name');
  if(o.client)put('#p-client',o.client,'Client');
  if(o.start){const w=when(o.start);if(w)put('#p-start',ymd(w.d),'Start');else miss.push('Start: '+o.start)}
  if(o.due){const w=when(o.due);if(w)put('#p-due',ymd(w.d),'Due');else miss.push('Due: '+o.due)}
  if(o.senior)put('#p-senior',o.senior,'Senior analyst');
  if(o.analyst)put('#p-analyst',o.analyst,'Analyst');
  if(o.extra)addNotes('#p-extra',o.extra,repl),ok.push('Extra details');
  addNotes('#p-notes',[...notes,...(o.notes||[]),...miss],repl);
  return {ok,miss};
}
function fill(kind,text,repl){
  const r=split(text,kind);return kind==='task'?fillTask(r,repl):fillProject(r,repl);
}

const S={task:{st:'idle',chunks:[]},project:{st:'idle',chunks:[]}};
const EX={task:'Jaise: task prior art search, due kal shaam 5 baje, priority high, reminder 1 hour, notes client ne scope badla',project:'Jaise: project name Alpha, client XYZ, due 25 november, senior Rahul, notes pehle call ke baad scope final'};
function build(kind){
  const p=document.querySelector('.voice[data-kind="'+kind+'"]');if(!p)return;
  p.innerHTML='<div class="vrow"><button type="button" data-vact="rec">Record</button><button type="button" data-vact="pause" hidden>Pause</button><button type="button" class="primary" data-vact="send" hidden>Send</button><button type="button" class="ghost" data-vact="clear">Clear</button><span class="hint vstat"></span></div><div class="hint" style="margin-top:6px">'+EX[kind]+'</div><textarea class="vtxt" rows="3" placeholder="Bola hua text yahan judta jayega. Galti ho to edit karo, phir Fill fields dabao."></textarea><div class="vrow" style="margin-top:6px"><button type="button" data-vact="apply">Fill fields from text</button><button type="button" data-vact="dl" hidden>Download voice model (one time, ~480 MB)</button></div><div class="hint vmsg" style="margin-top:6px"></div>';
}
const msg=(p,t)=>{p.querySelector('.vmsg').textContent=t};
const status=async()=>(await fetch('/api/voice/status')).json();
function ui(p,s){
  const q=n=>p.querySelector('[data-vact='+n+']'),live=s.st==='rec'||s.st==='pause';
  q('rec').hidden=s.st!=='idle';q('pause').hidden=!live;q('send').hidden=!live;
  q('pause').textContent=s.st==='pause'?'Resume':'Pause';
  const v=p.querySelector('.vstat');v.className='hint vstat'+(s.st==='rec'?' vrec':'');
  v.textContent={idle:'',rec:'Recording... ruk ruk ke bol sakte ho',pause:'Paused',busy:'Text ban raha hai...'}[s.st];
}
function stop(k){
  const s=S[k],p=document.querySelector('.voice[data-kind="'+k+'"]');
  if(s.rec&&s.rec.state!=='inactive'){s.rec.onstop=null;try{s.rec.stop()}catch(e){}}
  if(s.stream)s.stream.getTracks().forEach(t=>t.stop());
  s.rec=s.stream=null;s.chunks=[];s.st='idle';
  if(p){ui(p,s);p.querySelector('.vtxt').value='';msg(p,'');p.querySelector('[data-vact=dl]').hidden=true}
}
async function poll(p){
  for(;;){const st=await status();
    if(st.ready){msg(p,'Voice model ready. Ab Record dabao.');p.querySelector('[data-vact=dl]').hidden=true;return}
    if(st.error){msg(p,'Download fail hua: '+st.error);p.querySelector('[data-vact=dl]').hidden=false;return}
    if(!st.downloading)return;
    msg(p,'Model download ho raha hai (~480 MB), kuch minute lag sakte hain...');
    await new Promise(r=>setTimeout(r,3000))}
}
function report(p,r){
  msg(p,(r.ok.length?'Bhara gaya: '+r.ok.join(', ')+'. ':'Koi field match nahi hui (text Notes mein gaya). ')+(r.miss.length?'Samajh nahi aaya, Notes mein daal diya: '+r.miss.join(' | '):''));
}
 async function toPCM(blob){
  const buf=await blob.arrayBuffer();
  const ac=new (window.AudioContext||window.webkitAudioContext)();
  const dec=await ac.decodeAudioData(buf);
  ac.close();
  const off=new OfflineAudioContext(1,Math.max(1,Math.ceil(dec.duration*16000)),16000);
  const src=off.createBufferSource();
  src.buffer=dec;src.connect(off.destination);src.start();
  return (await off.startRendering()).getChannelData(0);
}
async function act(k,a,p){
  const s=S[k],ta=p.querySelector('.vtxt');
  if(a==='rec'){
    const st=await status();
    if(!st.ready){p.querySelector('[data-vact=dl]').hidden=false;msg(p,st.downloading?'Model download ho raha hai...':'Voice model abhi download nahi hua. Neeche button dabao (internet chahiye, sirf ek baar).');if(st.downloading)poll(p);return}
    try{s.stream=await navigator.mediaDevices.getUserMedia({audio:true})}catch(e){msg(p,'Microphone access nahi mila. Browser mein 127.0.0.1 ke liye microphone allow karo.');return}
    const mt=['audio/webm;codecs=opus','audio/webm','audio/ogg;codecs=opus'].find(t=>MediaRecorder.isTypeSupported(t));
    s.chunks=[];s.rec=new MediaRecorder(s.stream,mt?{mimeType:mt}:{});
    s.rec.ondataavailable=e=>{if(e.data.size)s.chunks.push(e.data)};
    s.rec.start(1000);s.st='rec';ui(p,s);msg(p,'');
  }else if(a==='pause'){
    if(s.rec.state==='recording'){s.rec.pause();s.st='pause'}else{s.rec.resume();s.st='rec'}ui(p,s);
  }else if(a==='send'){
    const blob=await new Promise(res=>{s.rec.onstop=()=>res(new Blob(s.chunks,{type:s.rec.mimeType||'audio/webm'}));s.rec.stop()});
    s.stream.getTracks().forEach(t=>t.stop());s.rec=s.stream=null;s.chunks=[];s.st='busy';ui(p,s);
    msg(p,'Pehli baar model load hone mein zyada time lag sakta hai.');
    try{
      const pcm=await toPCM(blob);
      const r=await fetch('/api/voice',{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:pcm}),j=await r.json();
      if(!r.ok){msg(p,r.status===409?'Voice model nahi mila. Download button dabao.':(typeof j.detail==='string'?j.detail:'Voice error.'));if(r.status===409)p.querySelector('[data-vact=dl]').hidden=false}
      else if(!j.text){msg(p,'Kuch sunai nahi diya. Dobara bolo.')}
      else{ta.value=(ta.value?ta.value+'\n':'')+j.text;report(p,fill(k,j.text,false))}
    }catch(e){msg(p,'Voice request fail hua: '+e)}
    s.st='idle';ui(p,s);
  }else if(a==='clear'){stop(k)}
  else if(a==='apply'){if(ta.value.trim())report(p,fill(k,ta.value,true));else msg(p,'Pehle kuch bolo ya text likho.')}
  else if(a==='dl'){await fetch('/api/voice/download',{method:'POST'});poll(p)}
}
document.addEventListener('click',e=>{
  const b=e.target.closest('[data-vact]');if(!b)return;
  const p=b.closest('.voice');act(p.dataset.kind,b.dataset.vact,p);
});
build('task');build('project');
$('#dlg').addEventListener('close',()=>stop('task'));
$('#pdlg').addEventListener('close',()=>stop('project'));
})();
