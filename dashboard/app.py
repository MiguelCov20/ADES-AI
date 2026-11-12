"""Dashboard web de control (#27) + Cache Hit-Rate Dashboard en vivo (#11).

Panel local para ver agentes, tokens/costo, hit-rate del caché, presupuesto,
proyectos y backlog, herramientas del registry, GPU y últimas ejecuciones.
Se refresca solo cada 3 s leyendo datos reales (SQLite de métricas, `.ades/`).

Uso:
    python -m dashboard.app            # http://127.0.0.1:8765
"""
import json
import os

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from core import budget, metrics_store, projects
from core.config import state_dir

app = FastAPI(title="ADES-AI Dashboard")


def _safe(fn, default=None):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        return default if default is not None else {"error": f"{type(e).__name__}: {e}"[:200]}


@app.get("/api/metrics")
def api_metrics(project: str | None = None):
    s = metrics_store.summary(project=project)
    recent = metrics_store.query(
        "SELECT ts, project, agent, provider, model, tokens_in, tokens_out, cost, cache_hit, "
        "ok, latency, fallback_from FROM calls ORDER BY id DESC LIMIT 25")
    # hit-rate por minuto (últimos 60 min) para la gráfica en vivo
    series = metrics_store.query(
        "SELECT CAST(ts/60 AS INTEGER)*60 AS minuto, COUNT(*) AS calls, SUM(cache_hit) AS hits, "
        "SUM(tokens_in+tokens_out) AS tokens, SUM(cost) AS cost FROM calls "
        "WHERE ts > strftime('%s','now') - 3600 GROUP BY minuto ORDER BY minuto")
    return {"summary": s, "recent": recent, "series": series}


@app.get("/api/projects")
def api_projects():
    from agents import backlog
    out = []
    for p in projects.list_projects():
        b = _safe(lambda: {k: len(v) for k, v in backlog.board(p["id"]).items()}, {})
        out.append({**p, "backlog": b, "budget": _safe(lambda: budget.status(p["id"]))})
    return out


@app.get("/api/agents")
def api_agents():
    from agents import roster
    return roster.get_agents()


@app.get("/api/tools")
def api_tools():
    from registry import registry
    st = registry.load_state().get("herramientas", {})
    return [{**t, "estado": st.get(t["id"], {})} for t in registry.get_tools()]


@app.get("/api/gpu")
def api_gpu():
    from core import gpu_manager
    return _safe(gpu_manager.status)


@app.get("/api/runs")
def api_runs(project: str = "ades-ai", limit: int = 10):
    d = state_dir(project) / "runs"
    if not d.exists():
        return []
    files = sorted(d.glob("*.json"), key=os.path.getmtime, reverse=True)[:limit]
    out = []
    for f in files:
        r = json.loads(f.read_text(encoding="utf-8"))
        out.append({k: r.get(k) for k in ("run_id", "requerimiento", "estado", "iteracion",
                                          "estrategias", "sandbox", "duracion_s")}
                   | {"metricas": {k: (r.get("metricas") or {}).get(k)
                                   for k in ("calls", "cost", "cache_hits")}})
    return out


PAGE = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>ADES-AI</title>
<style>
:root{--bg:#0f1115;--card:#171a21;--fg:#e6e6e6;--mut:#8a93a6;--acc:#4f9cf9;--ok:#3fb950;--bad:#f85149}
body{margin:0;font:14px system-ui,Segoe UI,sans-serif;background:var(--bg);color:var(--fg)}
header{padding:14px 20px;border-bottom:1px solid #262b36;display:flex;gap:12px;align-items:baseline}
h1{font-size:18px;margin:0}small{color:var(--mut)}
main{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px;padding:16px}
.card{background:var(--card);border:1px solid #262b36;border-radius:10px;padding:14px;overflow:auto}
.card h2{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--mut);margin:0 0 10px}
.kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
.kpi b{display:block;font-size:22px}.kpi span{color:var(--mut);font-size:12px}
table{width:100%;border-collapse:collapse;font-size:12px}td,th{padding:4px 6px;border-bottom:1px solid #222;text-align:left}
.ok{color:var(--ok)}.bad{color:var(--bad)} svg{width:100%;height:90px}
</style></head><body>
<header><h1>ADES-AI · Panel de control</h1><small id="ts"></small></header>
<main>
<section class="card"><h2>Tokens y caché (en vivo)</h2><div class="kpis" id="kpis"></div><svg id="chart"></svg></section>
<section class="card"><h2>Proyectos · backlog · presupuesto</h2><table id="projects"></table></section>
<section class="card"><h2>Agentes</h2><table id="agents"></table></section>
<section class="card"><h2>Costo por agente / modelo</h2><table id="byagent"></table></section>
<section class="card"><h2>GPU</h2><div id="gpu"></div></section>
<section class="card"><h2>Herramientas (registry)</h2><table id="tools"></table></section>
<section class="card" style="grid-column:1/-1"><h2>Últimas llamadas</h2><table id="recent"></table></section>
</main>
<script>
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
async function j(u){const r=await fetch(u);return r.json()}
function rows(el,head,data){$(el).innerHTML='<tr>'+head.map(h=>'<th>'+h+'</th>').join('')+'</tr>'+data.map(r=>'<tr>'+r.map(c=>'<td>'+c+'</td>').join('')+'</tr>').join('')}
async function tick(){
 try{
 const m=await j('/api/metrics');const s=m.summary;
 $('kpis').innerHTML=[['Llamadas',s.calls],['Hit-rate',(s.hit_rate*100).toFixed(1)+'%'],['Costo','$'+s.cost.toFixed(4)],
  ['Tokens in',s.tokens_in],['Tokens out',s.tokens_out],['Tokens locales ($0)',s.local_tokens]].map(([k,v])=>'<div class="kpi"><b>'+v+'</b><span>'+k+'</span></div>').join('');
 const se=m.series;const W=600,H=90;if(se.length){const mx=Math.max(...se.map(x=>x.calls),1);
  const bw=W/Math.max(se.length,1);$('chart').setAttribute('viewBox','0 0 '+W+' '+H);
  $('chart').innerHTML=se.map((x,i)=>{const h=x.calls/mx*(H-10),hh=(x.hits||0)/mx*(H-10);
   return '<rect x="'+(i*bw+1)+'" y="'+(H-h)+'" width="'+(bw-2)+'" height="'+h+'" fill="#2d4f7c"><title>'+x.calls+' llamadas</title></rect>'+
   '<rect x="'+(i*bw+1)+'" y="'+(H-hh)+'" width="'+(bw-2)+'" height="'+hh+'" fill="#3fb950"><title>'+(x.hits||0)+' hits</title></rect>'}).join('')}
 rows('byagent',['Agente','Modelo','Llamadas','Hits','Tokens','$'],s.by_agent.map(a=>[esc(a.agent),esc(a.model),a.calls,a.hits,a.tokens,(a.cost||0).toFixed(5)]));
 rows('recent',['Hora','Proyecto','Agente','Modelo','In','Out','$','Cache','OK','Fallback'],m.recent.map(r=>[new Date(r.ts*1000).toLocaleTimeString(),esc(r.project),esc(r.agent),esc(r.model),r.tokens_in,r.tokens_out,r.cost.toFixed(5),r.cache_hit?'✓':'',r.ok?'<span class=ok>✓</span>':'<span class=bad>✗</span>',esc(r.fallback_from)]));
 const p=await j('/api/projects');
 rows('projects',['Proyecto','todo','doing','done','failed','Presupuesto'],p.map(x=>[esc(x.id),x.backlog.todo??0,x.backlog.doing??0,x.backlog.done??0,x.backlog.failed??0,x.budget&&x.budget.used_fraction!==undefined?((x.budget.used_fraction*100).toFixed(1)+'% ('+x.budget.tier+')'):'']));
 const a=await j('/api/agents');rows('agents',['Agente','LLM'],a.map(x=>[esc(x.nombre),esc(x.llm.provider+'/'+x.llm.model)]));
 const t=await j('/api/tools');rows('tools',['Id','Tipo','Activa','Integrada'],t.map(x=>[esc(x.id),esc(x.tipo),x.estado.activa?'sí':'no',x.estado.integrada?'sí':'no']));
 const g=await j('/api/gpu');$('gpu').innerHTML=g.error?esc(g.error):('VRAM usada: '+g.used_gb+' / '+g.vram_gb+' GB<br>'+g.loaded.map(x=>esc(x.name)+' ('+x.vram_gb+' GB)').join('<br>')+(g.cpu_offload.length?'<br><span class=bad>Offload CPU: '+esc(g.cpu_offload.join(', '))+'</span>':''));
 $('ts').textContent='actualizado '+new Date().toLocaleTimeString();
 }catch(e){$('ts').textContent='error: '+e}
}
tick();setInterval(tick,3000);
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE


def main() -> int:
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("ADES_DASHBOARD_PORT", "8765")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
