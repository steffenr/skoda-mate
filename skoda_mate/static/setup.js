// First-run setup page (/setup). A file, not an inline script: the Content-Security-Policy allows no inline code.
const $=id=>document.getElementById(id);
const post=(u,b,m='POST')=>fetch(u,{method:m,headers:{'content-type':'application/json'},body:b&&JSON.stringify(b)})
 .then(async r=>{const j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(r.status==429?'Too many attempts. Try again in a few minutes.':typeof j.detail=='string'?j.detail:'Request failed ('+r.status+')');return j});
const say=(id,t,cls)=>{const e=$(id);e.textContent=t;e.className='msg '+(cls||'')};
const days=iso=>iso?Math.floor((new Date(iso)-Date.now())/864e5):null;
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
async function refresh(){
 const s=await fetch('/api/setup/status').then(r=>{if(r.status==401){location.href='/login'}return r.json()});
 $('s2').classList.toggle('off',!s.login_set);
 for(const id of['sk','sv','ss','b2'])$(id).disabled=!s.login_set;
 // first run: the one-time code from the log; changing an existing login: the current password
 $('coderow').hidden=!s.setup_code_required;$('lc').required=!!s.setup_code_required;
 $('currow').hidden=!s.login_set;$('lo').required=!!s.login_set;
 if(s.login_set){$('h1').textContent='Signed in as '+s.login_email+'. Enter your current password and a new e-mail and password below to change the login.';
  $('b1').textContent='Change login';document.querySelector('label[for=lp]').textContent='New password'}
 if(s.vehicles.length&&!$('sv').value)$('sv').value=s.vehicles.map(v=>v.vin).join('\n');
 $('veh').innerHTML=s.vehicles.map(v=>{const d=days(v.key_expires_at);
  const exp=d==null?'':d<0?' · <b class="err">key expired</b>':d<=14?` · <b class="warn">key expires in ${d} day${d==1?'':'s'}</b>`:` · key valid ${d} days`;
  return `<li><b>${esc(v.name||v.vin)}</b> <span class="small">${esc(v.vin.slice(0,3))}…${esc(v.vin.slice(-4))}</span>${exp}${v.error?`<div class="err">${esc(v.error)}</div>`:''}</li>`}).join('');
 $('st2').className='msg '+(s.connected?'ok':'');
 $('st2').textContent=!s.key_readable?'The stored key cannot be read (secret.key is missing). Enter it again.':s.connected?'Connected.':s.skoda_set?'Saved, connecting…':'';
 $('forget').hidden=!s.skoda_set;$('go').hidden=!(s.login_set&&s.skoda_set);
}
$('f1').onsubmit=async ev=>{ev.preventDefault();say('m1','');
 if($('lp').value!==$('lq').value)return say('m1','The passwords do not match.','err');
 $('b1').disabled=true;
 try{const body={email:$('le').value,password:$('lp').value};
  if(!$('coderow').hidden)body.setup_code=$('lc').value;
  if(!$('currow').hidden)body.current_password=$('lo').value;
  await post('/api/setup/login',body);
  $('lp').value=$('lq').value=$('lo').value=$('lc').value='';say('m1','Saved. You are signed in.','ok');await refresh()}
 catch(e){say('m1',e.message,'err')}$('b1').disabled=false};
$('f2').onsubmit=async ev=>{ev.preventDefault();say('m2','Checking the key with Škoda…');
 $('b2').disabled=true;
 try{const spin=$('ss').value.trim();
  await post('/api/setup/skoda',{api_key:$('sk').value,vins:$('sv').value,spin:spin===''?null:spin});
  location.href='/'}
 catch(e){say('m2',e.message,'err');$('b2').disabled=false}};
$('forget').onclick=async()=>{if(!confirm('Disconnect from MyŠkoda? Your history stays; the API key is deleted from this app.'))return;
 try{await post('/api/setup/skoda',null,'DELETE');$('sk').value='';await refresh()}catch(e){say('m2',e.message,'err')}};
refresh();
