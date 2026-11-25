"""Build docs/index.html: a static, interactive dashboard for GitHub Pages.

The data (synthetic plods + real WA hole collars they are attached to) is embedded as JSON, so the page
needs no server. Filters, KPIs, charts, map and tables are all recomputed in the browser.
Usage: python -m plodtrack.build_site
"""
import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd

PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PlodTrack - live drilling analysis</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#1c2330;--mut:#667085;--line:#e4e7ec;--acc:#1f5fbf;--bad:#c2410c}
*{box-sizing:border-box}body{margin:0;font-family:system-ui,sans-serif;background:var(--bg);color:var(--ink)}
header{padding:20px 28px;background:#14213d;color:#fff}header h1{margin:0;font-size:1.4em}
header p{margin:4px 0 0;color:#c9d3e6;font-size:.9em}
main{max-width:1150px;margin:0 auto;padding:20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:16px}
.filters{display:flex;gap:16px;flex-wrap:wrap;align-items:end}
label{display:block;font-size:.78em;color:var(--mut);margin-bottom:4px}
select,input[type=date]{padding:6px 8px;border:1px solid var(--line);border-radius:6px;font:inherit}
button{padding:7px 12px;border:1px solid var(--line);background:#fff;border-radius:6px;cursor:pointer;font:inherit}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 16px}
.kpi span{font-size:.78em;color:var(--mut)}.kpi b{display:block;font-size:1.6em;margin-top:2px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media(max-width:800px){.grid{grid-template-columns:1fr}}
h2{font-size:1em;margin:0 0 10px}#map{height:340px;border-radius:8px}
table{border-collapse:collapse;width:100%;font-size:.85em}th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left}
th{color:var(--mut);font-weight:600;cursor:default}.num{text-align:right}tr.flag td{background:#fff4ed}
.tag{display:inline-block;padding:1px 7px;border-radius:99px;background:#fde7d9;color:var(--bad);font-size:.8em}
.scroll{max-height:340px;overflow:auto}footer{color:var(--mut);font-size:.8em;padding:0 20px 30px;max-width:1150px;margin:auto}
</style></head><body>
<header><h1>PlodTrack - live drilling analysis</h1>
<p>Interactive view of the pipeline output. Plods are <b>synthetic</b>; hole locations are real WA open-file collars.</p></header>
<main>
<div class="card filters">
 <div><label>From</label><input type="date" id="from"></div>
 <div><label>To</label><input type="date" id="to"></div>
 <div><label>Contractor</label><select id="contractor"></select></div>
 <div><label>Drill type</label><select id="dtype"></select></div>
 <div><label>Shift</label><select id="shift"></select></div>
 <div><label><input type="checkbox" id="onlyflag"> only flagged</label></div>
 <button id="reset">Reset</button>
</div>
<div class="kpis" id="kpis"></div>
<div class="grid" style="margin-top:16px">
 <div class="card"><h2>Metres per day</h2><canvas id="cm" height="170"></canvas></div>
 <div class="card"><h2>Cost per metre by day (AUD)</h2><canvas id="cc" height="170"></canvas></div>
 <div class="card"><h2>Metres per hour vs physical limit</h2><canvas id="cs" height="170"></canvas></div>
 <div class="card"><h2>Metres by contractor and drill type</h2><canvas id="cd" height="170"></canvas></div>
</div>
<div class="card"><h2>Hole locations (real WA collars, Kalgoorlie area) - red = has a flagged plod</h2><div id="map"></div></div>
<div class="card"><h2>Contractor summary</h2><div id="ctab"></div></div>
<div class="card"><h2>Flagged entries <span id="nflag"></span></h2><div class="scroll" id="ftab"></div></div>
<div class="card"><h2>Plods (filtered)</h2><div class="scroll" id="ptab"></div></div>
</main>
<footer>Rules: metres/hour above a physical limit per drill type, metres beyond registered hole depth, standby &gt; hours, and cost-per-metre outliers (robust MAD z-score). Rebuild with <code>python -m plodtrack.build_site</code>.</footer>
<script>
const D=__DATA__;
const LIMIT=D.limits, P=D.plods, F={};
D.flags.forEach(f=>{(F[f.plod_id]??=[]).push(f)});
const $=id=>document.getElementById(id);
const fmt=(n,d=0)=>n.toLocaleString('en-AU',{maximumFractionDigits:d});
const uniq=k=>[...new Set(P.map(p=>p[k]))].sort();
function fill(id,vals){$(id).innerHTML='<option value="">All</option>'+vals.map(v=>`<option>${v}</option>`).join('')}
fill('contractor',uniq('contractor'));fill('dtype',uniq('drill_type'));fill('shift',uniq('shift'));
const dates=uniq('plod_date');
function reset(){$('from').value=dates[0];$('to').value=dates.at(-1);['contractor','dtype','shift'].forEach(i=>$(i).value='');$('onlyflag').checked=false;render()}
function rows(){const f=$('from').value,t=$('to').value,c=$('contractor').value,d=$('dtype').value,s=$('shift').value,o=$('onlyflag').checked;
 return P.filter(p=>p.plod_date>=f&&p.plod_date<=t&&(!c||p.contractor===c)&&(!d||p.drill_type===d)&&(!s||p.shift===s)&&(!o||F[p.plod_id]))}
const charts={};
function chart(id,cfg){charts[id]?.destroy();charts[id]=new Chart($(id),cfg)}
const COL=['#1f5fbf','#e07a1f','#2a9d8f','#8d5fd3'];
function table(el,cols,data,cls){ $(el).innerHTML='<table><thead><tr>'+cols.map(c=>`<th class="${c.n?'num':''}">${c.h}</th>`).join('')+'</tr></thead><tbody>'+
 data.map(r=>`<tr class="${cls?cls(r):''}">`+cols.map(c=>`<td class="${c.n?'num':''}">${c.f?c.f(r):r[c.k]}</td>`).join('')+'</tr>').join('')+'</tbody></table>'}
let map,layer;
function render(){
 const R=rows(), m=R.reduce((a,p)=>a+p.metres_drilled,0), c=R.reduce((a,p)=>a+p.cost_aud,0);
 const h=R.reduce((a,p)=>a+p.hours_worked,0), sb=R.reduce((a,p)=>a+p.standby_hours,0), nf=R.filter(p=>F[p.plod_id]).length;
 $('kpis').innerHTML=[['Plods',fmt(R.length)],['Total metres',fmt(m)],['Total cost','$'+fmt(c)],['Avg $/m','$'+fmt(m?c/m:0,2)],
  ['Metres / hour',fmt(h?m/h:0,1)],['Standby %',fmt(h?100*sb/h:0,1)+'%'],['Flagged plods',nf]].map(([l,v])=>`<div class="kpi"><span>${l}</span><b>${v}</b></div>`).join('');
 const days=[...new Set(R.map(p=>p.plod_date))].sort(), by=d=>R.filter(p=>p.plod_date===d);
 chart('cm',{type:'bar',data:{labels:days,datasets:[{label:'Metres',data:days.map(d=>by(d).reduce((a,p)=>a+p.metres_drilled,0)),backgroundColor:COL[0]}]},options:{plugins:{legend:{display:false}}}});
 chart('cc',{type:'line',data:{labels:days,datasets:[{label:'$/m',data:days.map(d=>{const x=by(d),mm=x.reduce((a,p)=>a+p.metres_drilled,0);return mm?x.reduce((a,p)=>a+p.cost_aud,0)/mm:null}),borderColor:COL[1],tension:.25}]},options:{plugins:{legend:{display:false}}}});
 const types=Object.keys(LIMIT);
 chart('cs',{type:'scatter',data:{datasets:[
  {label:'Plod',data:R.map(p=>({x:p.hours_worked-p.standby_hours,y:p.metres_drilled,p})),backgroundColor:R.map(p=>F[p.plod_id]?'#c2410c':'rgba(31,95,191,.5)'),pointRadius:R.map(p=>F[p.plod_id]?6:3)}]},
  options:{plugins:{legend:{display:false},tooltip:{callbacks:{label:t=>{const p=t.raw.p;return `${p.hole_id} ${p.drill_type}: ${p.metres_drilled} m in ${(p.hours_worked-p.standby_hours).toFixed(1)} h`}}}},
   scales:{x:{title:{display:true,text:'productive hours'}},y:{title:{display:true,text:'metres'}}}}});
 const cons=uniq('contractor');
 chart('cd',{type:'bar',data:{labels:cons,datasets:types.map((t,i)=>({label:t,backgroundColor:COL[i],data:cons.map(k=>R.filter(p=>p.contractor===k&&p.drill_type===t).reduce((a,p)=>a+p.metres_drilled,0))}))},options:{scales:{x:{stacked:true},y:{stacked:true}}}});
 table('ctab',[{h:'Contractor',k:'c'},{h:'Plods',k:'n',n:1},{h:'Metres',n:1,f:r=>fmt(r.m)},{h:'Cost (AUD)',n:1,f:r=>'$'+fmt(r.cost)},{h:'$/m',n:1,f:r=>'$'+fmt(r.cost/r.m,2)},{h:'m/h',n:1,f:r=>fmt(r.m/r.h,1)},{h:'Standby %',n:1,f:r=>fmt(100*r.sb/r.h,1)+'%'}],
  cons.map(c=>{const x=R.filter(p=>p.contractor===c);return{c,n:x.length,m:x.reduce((a,p)=>a+p.metres_drilled,0)||0,cost:x.reduce((a,p)=>a+p.cost_aud,0),h:x.reduce((a,p)=>a+p.hours_worked,0)||1,sb:x.reduce((a,p)=>a+p.standby_hours,0)}}).filter(r=>r.n));
 const fl=R.filter(p=>F[p.plod_id]).flatMap(p=>F[p.plod_id].map(f=>({...p,...f})));
 $('nflag').textContent='('+fl.length+')';
 table('ftab',[{h:'Date',k:'plod_date'},{h:'Contractor',k:'contractor'},{h:'Rig',k:'rig_id'},{h:'Hole',k:'hole_id'},{h:'Rule',f:r=>`<span class="tag">${r.rule}</span>`},{h:'Detail',k:'detail'}],fl);
 table('ptab',[{h:'Date',k:'plod_date'},{h:'Contractor',k:'contractor'},{h:'Shift',k:'shift'},{h:'Rig',k:'rig_id'},{h:'Hole',k:'hole_id'},{h:'Type',k:'drill_type'},
  {h:'Metres',n:1,k:'metres_drilled'},{h:'Hours',n:1,k:'hours_worked'},{h:'Standby',n:1,k:'standby_hours'},{h:'Cost',n:1,f:r=>'$'+fmt(r.cost_aud,2)},{h:'$/m',n:1,f:r=>r.metres_drilled?'$'+fmt(r.cost_aud/r.metres_drilled,2):'-'}],R,r=>F[r.plod_id]?'flag':'');
 layer.clearLayers();const seen={};
 R.forEach(p=>{if(p.lat==null)return;const k=p.hole_id;seen[k]=seen[k]||{p,flag:false};if(F[p.plod_id])seen[k].flag=true});
 Object.values(seen).forEach(({p,flag})=>L.circleMarker([p.lat,p.lon],{radius:flag?7:4,color:flag?'#c2410c':'#1f5fbf',weight:1,fillOpacity:.6})
  .bindPopup(`<b>${p.hole_id}</b><br>${p.operator||''} - ${p.project||''}<br>registered depth ${p.max_depth_m} m`).addTo(layer));
}
map=L.map('map').setView([-30.8,121.4],9);L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'&copy; OpenStreetMap'}).addTo(map);
layer=L.layerGroup().addTo(map);
['from','to','contractor','dtype','shift','onlyflag'].forEach(i=>$(i).addEventListener('change',render));$('reset').onclick=reset;reset();
</script></body></html>"""


def main(db_path="data/processed/plods.db", out="docs/index.html"):
    from plodtrack.anomalies import MAX_MPH
    conn = sqlite3.connect(db_path)
    plods = pd.read_sql("""SELECT p.plod_id, p.plod_date, p.contractor, p.shift, p.rig_id, p.hole_id, p.drill_type,
                                  p.metres_drilled, p.hours_worked, p.standby_hours, p.cost_aud,
                                  h.latitude AS lat, h.longitude AS lon, h.operator, h.project, h.max_depth_m
                           FROM drill_plods p LEFT JOIN holes h ON h.hole_id = p.hole_id
                           ORDER BY p.plod_date""", conn)
    flags = pd.read_sql("SELECT plod_id, rule, detail FROM anomalies", conn)
    data = {"plods": plods.astype(object).where(plods.notna(), None).to_dict("records"),
            "flags": flags.to_dict("records"), "limits": MAX_MPH}
    Path(out).parent.mkdir(exist_ok=True)
    Path(out).write_text(PAGE.replace("__DATA__", json.dumps(data)))
    Path(out).with_name(".nojekyll").touch()
    print(f"Wrote {out} ({len(plods)} plods, {len(flags)} flags)")


if __name__ == "__main__":
    main(*sys.argv[1:])
