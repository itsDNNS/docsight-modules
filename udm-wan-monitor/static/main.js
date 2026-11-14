/*
  UniFi WAN Monitor — dashboard tab and settings panel  v3.3.3
  Auto-loaded by DOCSight on the dashboard and the settings page, and by the
  standalone page. Each part only runs when its elements are on the page.
*/
(function () {
'use strict';

function apiUrl(p) {
  return typeof window.docsightUrl === 'function' ? window.docsightUrl(p) : location.pathname.replace(/\/[^\/]*$/, '') + p;
}

// ── Dashboard tab ────────────────────────────────────────────────────────────

function initTab() {
// All translatable strings for JS — rendered once by Jinja2 into a JSON block
const L = JSON.parse(document.getElementById('udm-wan-i18n').textContent);

const REFRESH_MS = 30_000;
let _timer = null;

const f   = (v,fb='—') => (v!==null&&v!==undefined&&v!=='') ? String(v) : fb;
const esc = s => { const d=document.createElement('div'); d.textContent=s; return d.innerHTML; };
const fe  = (v,fb='—') => esc(f(v,fb));
const el  = id => document.getElementById(id);
const txt = (id,v) => { const e=el(id); if(e) e.textContent=f(v); };

const fBytes = b => {
  if(b==null) return '—';
  const n=+b; if(isNaN(n)||n<0) return '—';
  if(n<1024)       return n+' B';
  if(n<1048576)    return (n/1024).toFixed(1)+' KB';
  if(n<1073741824) return (n/1048576).toFixed(1)+' MB';
  return (n/1073741824).toFixed(2)+' GB';
};
const fUp  = s => {
  if(!s||s<=0) return '—';
  const d=Math.floor(s/86400),h=Math.floor((s%86400)/3600),m=Math.floor((s%3600)/60);
  return [d&&d+'d',h&&h+'h',m+'min'].filter(Boolean).join(' ');
};
const fSpd  = v => { if(v==null) return '—'; const n=+v; if(isNaN(n)) return '—'; return n>=1000?(n/1000)+' Gbit/s':n+' Mbit/s'; };
const fPct  = v => v==null?'—':parseFloat(v).toFixed(1)+' %';
const fTmp  = v => v==null?'—':parseFloat(v).toFixed(1)+' °C';

function gauge(id, pct) {
  const b=el(id); if(!b) return;
  const p=Math.min(100,Math.max(0,parseFloat(pct)||0));
  b.style.width=p+'%';
  b.className='gf '+(p>=90?'gf-crit':p>=75?'gf-warn':'gf-ok');
}

function pill(pillId, txtId, isOk, labelOk, labelBad) {
  const p=el(pillId),t=el(txtId); if(!p||!t) return;
  if(isOk===null||isOk===undefined){ p.className='spill s-unk'; t.textContent='?'; return; }
  p.className='spill '+(isOk?'s-ok':'s-bad');
  t.textContent=isOk?labelOk:labelBad;
}

function setRole(px, w) {
  const rolePill=el(px+'-role'), roleTxt=el(px+'-role-txt');
  if(!rolePill||!roleTxt) return;
  const fullyHealthy = w && w.up && w.alive && w.online;
  if(!fullyHealthy || w.is_uplink===null || w.is_uplink===undefined){
    rolePill.style.display='none'; return;
  }
  rolePill.style.display='inline-flex';
  if(w.is_uplink){
    rolePill.className='spill s-active';
    rolePill.querySelector('.sdot').style.display='inline-block';
    roleTxt.textContent=L.active;
  } else {
    rolePill.className='spill s-standby';
    rolePill.querySelector('.sdot').style.display='none';
    roleTxt.textContent=L.standby;
  }
}

function fillWan(px, w) {
  if(w && !w.ifname) w=null;
  pill(px+'-link',   px+'-link-txt',   w&&w.up,     L.up,     L.down);
  pill(px+'-alive',  px+'-alive-txt',  w&&w.alive,  L.ok,     L.fail);
  pill(px+'-online', px+'-online-txt', w&&w.online, L.online, L.offline);
  setRole(px, w);
  if(!w) return;
  txt(px+'-ifname', w.ifname);
  txt(px+'-ip',    w.ip);
  const pubRow=el(px+'-ippub-row');
  if(pubRow){
    const showPub=!!w.ip_public && w.ip_public!==w.ip;
    pubRow.style.display=showPub?'':'none';
    if(showPub) txt(px+'-ippub', w.ip_public);
  }
  txt(px+'-ip6',   w.ipv6);
  txt(px+'-dns',   w.dns);
  txt(px+'-isp',   w.isp && w.city ? w.isp+' ('+w.city+')' : (w.isp||w.city||null));
  const typ = w.type ? (w.media ? w.type.toUpperCase()+' / '+w.media : w.type.toUpperCase()) : null;
  txt(px+'-type',  typ);
  txt(px+'-lat',   w.latency!=null ? w.latency+' ms' : null);
  txt(px+'-avail', w.availability!=null ? w.availability+' %' : null);
  const ab=el(px+'-avail-bar');
  if(ab) ab.style.width=(w.availability!=null?Math.min(100,w.availability):0)+'%';
  txt(px+'-rx',  w.rx_bytes_r!=null ? fBytes(w.rx_bytes_r)+'/s' : null);
  txt(px+'-tx',  w.tx_bytes_r!=null ? fBytes(w.tx_bytes_r)+'/s' : null);
  txt(px+'-spd', fSpd(w.speed));
}

function markPrimary(primary) {
  ['w1','w2'].forEach(function(px){
    const isPrimary = (px==='w1'&&primary==='wan1') || (px==='w2'&&primary==='wan2');
    const badge=el(px+'-primary'), card=el(px+'-card');
    if(badge) badge.style.display=isPrimary?'inline-flex':'none';
    if(card) card.style.order=isPrimary?'-1':'0';
  });
}

function fillDevice(dev) {
  if(!dev) return;
  txt('dev-model',  dev.model);
  txt('dev-name',   dev.name);
  txt('dev-fw',     dev.version);
  txt('dev-uptime', fUp(dev.uptime));
  txt('dev-cpu',    fPct(dev.cpu_pct));
  txt('dev-mem',    fPct(dev.mem_pct));
  txt('dev-temp',   fTmp(dev.temperature));
  txt('dev-lan',    dev.lan_clients!=null ? String(dev.lan_clients) : null);
  gauge('cpu-bar',  dev.cpu_pct);
  gauge('mem-bar',  dev.mem_pct);
  const sub=el('udm-sub');
  if(sub&&dev.model) sub.textContent=dev.name?dev.name+' ('+dev.model+')':dev.model;
}

function fillPorts(ports) {
  const tbody=el('port-tbody'); if(!tbody) return;
  if(!ports||!ports.length){
    tbody.innerHTML='<tr><td colspan="13" class="t-empty">'+esc(L.no_ports)+'</td></tr>'; return;
  }
  tbody.innerHTML=ports.map(function(p){ return '<tr>'
    +'<td><strong style="font-family:inherit;">'+fe(p.label||p.name)+'</strong></td>'
    +'<td>'+fe(p.ifname)+'</td>'
    +'<td class="'+(p.up?'t-up':'t-dn')+'">'+(p.up?'▲ '+esc(L.up):'▼ '+esc(L.down))+'</td>'
    +'<td>'+fSpd(p.speed)+'</td>'
    +'<td>'+(p.full_duplex!=null?(p.full_duplex?'Full':'Half'):'—')+'</td>'
    +'<td>'+fBytes(p.rx_bytes_r)+'/s</td>'
    +'<td>'+fBytes(p.tx_bytes_r)+'/s</td>'
    +'<td>'+fBytes(p.rx_bytes)+'</td>'
    +'<td>'+fBytes(p.tx_bytes)+'</td>'
    +'<td>'+fe(p.rx_errors,'0')+'</td>'
    +'<td>'+fe(p.tx_errors,'0')+'</td>'
    +'<td>'+fe(p.rx_dropped,'0')+'</td>'
    +'<td>'+fe(p.tx_dropped,'0')+'</td>'
    +'</tr>'; }).join('');
}

async function refreshEvents() {
  try {
    const r=await fetch(apiUrl('/api/events?event_type=udm_wan&limit=100'));
    const d=await r.json();
    const tbody=el('ev-tbody'), cnt=el('ev-count'); if(!tbody) return;
    const evs=d.events||[];
    if(!evs.length){
      tbody.innerHTML='<tr><td colspan="3" class="t-empty">'+esc(L.no_events)+'</td></tr>';
      if(cnt) cnt.textContent=''; return;
    }
    if(cnt) cnt.textContent=evs.length+' '+L.entries;
    tbody.innerHTML=evs.map(function(ev){
      var ts=esc(new Date(ev.timestamp).toLocaleString());
      var sev=ev.severity||'info';
      var cls=sev==='critical'?'ev-crit':sev==='warning'?'ev-warn':'ev-info';
      return '<tr>'
        +'<td style="white-space:nowrap;">'+ts+'</td>'
        +'<td>'+esc(ev.message||'')+'</td>'
        +'<td><span class="ev-badge '+cls+'">'+esc(sev)+'</span></td>'
        +'</tr>';
    }).join('');
  } catch(e){ console.warn('[UDM WAN] events error',e); }
}

async function udmLoad() {
  const errEl=el('udm-err'), dbg=el('udm-debug');
  try {
    const r=await fetch(apiUrl('/api/udm-wan/detail'));
    const d=await r.json();
    if(dbg&&dbg.style.display!=='none') dbg.textContent=JSON.stringify(d,null,2);
    if(!d.ok){
      if(errEl){errEl.textContent='⚠ '+d.error;errEl.style.display='';}
      return;
    }
    if(errEl) errEl.style.display='none';
    fillWan('w1', d.wan1||null);
    fillWan('w2', d.wan2||null);
    markPrimary(d.primary_wan||null);
    fillDevice(d.device||{});
    fillPorts(d.wan_ports||[]);
    const ver=el('udm-ver'); if(ver&&d.module_version) ver.textContent='v'+d.module_version;
    const ts=el('udm-last-ts');
    if(ts) ts.textContent=new Date(d.timestamp).toLocaleTimeString();
  } catch(e){
    if(errEl){errEl.textContent='⚠ '+e;errEl.style.display='';}
    console.warn('[UDM WAN] detail error',e);
  }
}

function udmToggleDebug(){
  const dbg=el('udm-debug'); if(!dbg) return;
  // The panel starts hidden by its CSS class, so the inline style begins empty.
  const show=dbg.style.display!=='block';
  dbg.style.display=show?'block':'none';
  if(show) udmLoad();
}

async function udmRefreshAll(){ await Promise.all([udmLoad(),refreshEvents()]); }

el('udm-debug-btn').addEventListener('click', udmToggleDebug);
el('udm-refresh-btn').addEventListener('click', udmLoad);

function startPolling(){
  udmRefreshAll();
  if(_timer) clearInterval(_timer);
  _timer=setInterval(udmRefreshAll,REFRESH_MS);
}

const viewEl=document.getElementById('view-mod-community-udm_wan_monitor');
if(viewEl){
  new MutationObserver(()=>{
    if(viewEl.classList.contains('active')) startPolling();
    else { clearInterval(_timer);_timer=null; }
  }).observe(viewEl,{attributes:true,attributeFilter:['class']});
  if(viewEl.classList.contains('active')) startPolling();
} else { startPolling(); }

if(typeof lucide!=='undefined') lucide.createIcons();
}

// ── Settings: connection test ────────────────────────────────────────────────

function initConnectionTest() {
  var btn = document.getElementById('udm-test-btn');
  var res = document.getElementById('udm-test-result');

  async function udmWanTest() {
    btn.disabled = true;
    res.className = 'test-result';
    res.style.display = 'none';

    try {
      var r = await fetch(apiUrl('/api/udm-wan/test'), { method: 'POST' });
      var d = await r.json();
      if (d.ok) {
        res.textContent = '';
        var icon = document.createElement('i');
        icon.setAttribute('data-lucide', 'check-circle');
        icon.style.cssText = 'width:16px;height:16px;flex-shrink:0;';
        res.appendChild(icon);
        var span = document.createElement('span');
        span.textContent = 'Connected';
        res.appendChild(span);
        res.className = 'test-result test-ok';
      } else {
        res.textContent = '';
        var icon = document.createElement('i');
        icon.setAttribute('data-lucide', 'alert-circle');
        icon.style.cssText = 'width:16px;height:16px;flex-shrink:0;';
        res.appendChild(icon);
        var span = document.createElement('span');
        span.textContent = d.error || 'Unknown error';
        res.appendChild(span);
        res.className = 'test-result test-fail';
      }
      res.style.display = 'flex';
      if (typeof lucide !== 'undefined') lucide.createIcons();
    } catch (e) {
      res.textContent = '';
      var span = document.createElement('span');
      span.textContent = 'Request failed';
      res.appendChild(span);
      res.className = 'test-result test-fail';
      res.style.display = 'flex';
    } finally {
      btn.disabled = false;
    }
  }

  btn.addEventListener('click', udmWanTest);
}

// ── Settings: manual WAN ports ───────────────────────────────────────────────

function initPorts() {
  var MAX_PORTS = 8;
  var IFNAME_RE = /^[A-Za-z0-9_.:-]{1,32}$/;
  var section = document.getElementById('udm-ports-section');
  var hidden = document.getElementById('udm_wan_extra_ports');
  var list = document.getElementById('udm-ports-list');
  var addBtn = document.getElementById('udm-port-add');
  var dlg = document.getElementById('udm-port-dialog');
  if (!section || !hidden || !list || !addBtn || !dlg) return;

  document.body.appendChild(dlg);

  var ifnameInput = dlg.querySelector('#udm-port-ifname');
  var aliasInput = dlg.querySelector('#udm-port-alias');
  var errBox = dlg.querySelector('#udm-port-error');

  function load() {
    var raw = (hidden.value || '').trim();
    var src = raw || hidden.dataset.legacy || '[]';
    try {
      var v = JSON.parse(src);
      return Array.isArray(v) ? v.filter(function (p) { return p && IFNAME_RE.test(String(p.ifname || '')); }) : [];
    } catch (e) { return []; }
  }
  var ports = load();

  function commit() {
    hidden.value = JSON.stringify(ports);
    hidden.dispatchEvent(new Event('input', { bubbles: true }));
  }

  function render() {
    list.textContent = '';
    if (!ports.length) {
      var empty = document.createElement('p');
      empty.style.cssText = 'font-size:.8rem;color:var(--text-muted);margin:0;';
      empty.textContent = section.dataset.msgEmpty;
      list.appendChild(empty);
    }
    ports.forEach(function (p, i) {
      var row = document.createElement('div');
      row.style.cssText = 'display:flex;align-items:center;gap:var(--space-sm);padding:.35rem 0;';
      var name = document.createElement('strong');
      name.textContent = p.alias || p.ifname;
      var code = document.createElement('code');
      code.style.cssText = 'color:var(--text-muted);font-size:.78rem;';
      code.textContent = p.ifname;
      var rm = document.createElement('button');
      rm.type = 'button';
      rm.className = 'btn btn-ghost btn-sm';
      rm.style.marginLeft = 'auto';
      rm.setAttribute('aria-label', section.dataset.msgRemove + ': ' + p.ifname);
      rm.title = section.dataset.msgRemove;
      var icon = document.createElement('i');
      icon.setAttribute('data-lucide', 'x');
      icon.style.cssText = 'width:14px;height:14px;';
      rm.appendChild(icon);
      rm.addEventListener('click', function () { ports.splice(i, 1); commit(); render(); });
      row.appendChild(name); row.appendChild(code); row.appendChild(rm);
      list.appendChild(row);
    });
    addBtn.style.display = ports.length >= MAX_PORTS ? 'none' : '';
    if (typeof lucide !== 'undefined') lucide.createIcons({ nodes: [list] });
  }

  function showError(msg) { errBox.textContent = msg; errBox.style.display = 'flex'; }

  function openDialog() {
    ifnameInput.value = ''; aliasInput.value = ''; errBox.style.display = 'none';
    dlg.showModal();
    ifnameInput.focus();
  }

  function confirmAdd() {
    var ifname = ifnameInput.value.trim().toLowerCase();
    var alias = aliasInput.value.trim();
    if (!IFNAME_RE.test(ifname)) { showError(section.dataset.msgInvalid); return; }
    if (ports.some(function (p) { return String(p.ifname).toLowerCase() === ifname; })) {
      showError(section.dataset.msgDuplicate); return;
    }
    if (ports.length >= MAX_PORTS) { showError(section.dataset.msgMax); return; }
    ports.push({ ifname: ifname, alias: alias || ifname });
    commit(); render(); dlg.close();
  }

  addBtn.addEventListener('click', openDialog);
  dlg.querySelector('#udm-port-confirm').addEventListener('click', confirmAdd);
  dlg.querySelector('#udm-port-cancel').addEventListener('click', function () { dlg.close(); });
  dlg.querySelector('#udm-port-close').addEventListener('click', function () { dlg.close(); });
  dlg.addEventListener('click', function (e) { if (e.target === dlg) dlg.close(); });
  [ifnameInput, aliasInput].forEach(function (el) {
    el.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); confirmAdd(); } });
  });
  render();
}

if (document.getElementById('udm-wan-view')) initTab();
if (document.getElementById('udm-test-btn')) initConnectionTest();
initPorts();
})();
