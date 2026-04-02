import asyncio
import logging
import os
import threading

import discord
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from bot import create_bot, verificar_mesa
from database import Database
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise ValueError("A variável de ambiente DISCORD_TOKEN não foi definida.")

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
PORT = int(os.getenv("PORT", 8000))

# ── App ───────────────────────────────────────────────────────────────────────

db = Database()
app = FastAPI(title="Magic Tournament Bot")
bot = create_bot(db, BASE_URL)


# ── Rotas API ─────────────────────────────────────────────────────────────────

class DisponibilidadePayload(BaseModel):
    slots: list[str]  # lista de "D,S" ex: ["1,40", "1,41", "3,38"]


@app.get("/disponibilidade/{token}", response_class=HTMLResponse)
async def pagina_disponibilidade(token: str):
    import json as _json
    info = db.get_token(token)
    if not info:
        return HTMLResponse("<h2>Link inválido ou já utilizado.</h2>", status_code=404)

    rodada = db.get_rodada(info["rodada_id"])
    mesa = db.get_mesa(info["mesa_id"])

    data_ini = rodada.get("data_ini", "")
    data_fim = rodada.get("data_fim", "")

    outros_votos = db.get_outros_votos_mesa(info["mesa_id"], info["discord_id"])
    outros_votos_json = _json.dumps(outros_votos)
    total_outros = len(db.get_players_mesa(info["mesa_id"])) - 1
    outros_votaram = db.contar_outros_votos_mesa(info["mesa_id"], info["discord_id"])

    html = _render_calendar_page(
        token=token,
        rodada_nome=rodada["nome"],
        mesa_nome=mesa["nome"],
        data_ini=data_ini,
        data_fim=data_fim,
        outros_votos_json=outros_votos_json,
        total_outros=total_outros,
        outros_votaram=outros_votaram,
    )
    return HTMLResponse(html)


@app.post("/disponibilidade/{token}")
async def salvar_disponibilidade(token: str, payload: DisponibilidadePayload):
    info = db.get_token(token)
    if not info:
        raise HTTPException(404, "Link inválido ou já utilizado.")

    if not payload.slots:
        raise HTTPException(400, "Selecione pelo menos um horário.")

    db.salvar_disponibilidade(info["discord_id"], info["mesa_id"], payload.slots)
    db.marcar_token_usado(token)

    # Dispara verificação de horário em background
    if "bot_loop" in globals() and bot_loop:
        asyncio.run_coroutine_threadsafe(verificar_mesa(bot, info["mesa_id"]), bot_loop)
    else:
        asyncio.create_task(verificar_mesa(bot, info["mesa_id"]))

    return {"ok": True, "message": "Disponibilidade salva!"}


@app.get("/health")
async def health():
    return {"status": "ok", "bot": str(bot.user)}


# ── Calendar page renderer ────────────────────────────────────────────────────

def _render_calendar_page(token: str, rodada_nome: str, mesa_nome: str, data_ini: str, data_fim: str,
                          outros_votos_json: str = '{}', total_outros: int = 0, outros_votaram: int = 0) -> str:
    periodo = f"{data_ini} – {data_fim}" if data_ini and data_fim else ""
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Magic Tournament — {rodada_nome}</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f1117; color: #e8e8e8; min-height: 100vh; padding: 24px 16px; }}
  .container {{ max-width: 900px; margin: 0 auto; }}
  h1 {{ font-size: 20px; font-weight: 600; color: #fff; margin-bottom: 4px; }}
  .subtitle {{ font-size: 14px; color: #888; margin-bottom: 6px; }}
  .periodo {{ font-size: 13px; color: #5b8dee; margin-bottom: 20px; }}
  .cal-wrapper {{ overflow-x: auto; border-radius: 10px; border: 1px solid #2a2a3a; }}
  .cal {{ display: grid; grid-template-columns: 52px repeat(7, minmax(0, 1fr)); min-width: 520px; }}
  .cell-header {{ background: #1a1a2e; font-size: 11px; font-weight: 600; color: #888; text-align: center; padding: 8px 4px; border-bottom: 1px solid #2a2a3a; position: sticky; top: 0; z-index: 2; line-height: 1.4; }}
  .time-col {{ display: flex; flex-direction: column; background: #13131f; }}
  .day-col {{ display: flex; flex-direction: column; border-left: 1px solid #2a2a3a; }}
  .time-label {{ font-size: 10px; color: #555; height: 22px; display: flex; align-items: center; justify-content: flex-end; padding-right: 8px; border-bottom: 1px solid #1e1e2e; flex-shrink: 0; white-space: nowrap; }}
  .slot {{ height: 22px; border-bottom: 1px solid #1e1e2e; cursor: pointer; transition: background 0.08s; flex-shrink: 0; }}
  .slot:hover {{ background: #2a3a5a; }}
  .slot[data-heat="low"] {{ background: rgba(56, 189, 248, 0.10); }}
  .slot[data-heat="mid"] {{ background: rgba(52, 211, 153, 0.15); }}
  .slot[data-heat="high"] {{ background: rgba(52, 211, 153, 0.25); box-shadow: inset 0 0 0 1px rgba(52,211,153,0.25); }}
  .slot[data-heat="low"]:hover:not(.selected) {{ background: rgba(56, 189, 248, 0.18); }}
  .slot[data-heat="mid"]:hover:not(.selected) {{ background: rgba(52, 211, 153, 0.25); }}
  .slot[data-heat="high"]:hover:not(.selected) {{ background: rgba(52, 211, 153, 0.38); }}
  .slot.selected {{ background: #2563eb !important; }}
  .slot.selected:hover {{ background: #1d4ed8 !important; }}
  .footer {{ margin-top: 16px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }}
  .count {{ font-size: 13px; color: #888; }}
  .count strong {{ color: #5b8dee; }}
  .btn {{ background: #2563eb; color: #fff; border: none; border-radius: 8px; padding: 10px 24px; font-size: 14px; font-weight: 600; cursor: pointer; transition: background 0.15s; }}
  .btn:hover {{ background: #1d4ed8; }}
  .btn:disabled {{ background: #2a2a3a; color: #555; cursor: default; }}
  .hint {{ font-size: 12px; color: #555; margin-top: 8px; }}
  .toast {{ display: none; margin-top: 16px; padding: 14px 18px; background: #1a2e1a; border: 1px solid #2d5a2d; border-radius: 8px; font-size: 14px; color: #5cbf5c; }}
  .error {{ display: none; margin-top: 16px; padding: 14px 18px; background: #2e1a1a; border: 1px solid #5a2d2d; border-radius: 8px; font-size: 14px; color: #bf5c5c; }}
  .legend {{ display: flex; gap: 12px; align-items: center; margin-bottom: 14px; flex-wrap: wrap; }}
  .legend-item {{ display: flex; align-items: center; gap: 5px; font-size: 11px; color: #777; }}
  .legend-swatch {{ width: 16px; height: 12px; border-radius: 3px; border: 1px solid #2a2a3a; }}
  .status-bar {{ display: flex; align-items: center; gap: 8px; margin-bottom: 14px; padding: 10px 14px; background: #161625; border-radius: 8px; border: 1px solid #2a2a3a; font-size: 12px; color: #888; }}
  .status-count {{ color: #5b8dee; font-weight: 600; }}
</style>
</head>
<body>
<div class="container">
  <h1>⚔️ {rodada_nome} — {mesa_nome}</h1>
  <div class="subtitle">Marque todos os horários que você pode jogar</div>
  <div class="periodo">📅 {periodo}</div>

  <div class="status-bar" id="statusBar">
    ⏳ Votos dos adversários: <span class="status-count" id="votosCount">{outros_votaram}/{total_outros}</span>
  </div>

  <div class="legend" id="legend" style="display:none">
    <span class="legend-item"><span class="legend-swatch" style="background:#2563eb"></span> Sua seleção</span>
    <span class="legend-item"><span class="legend-swatch" style="background:rgba(56,189,248,0.2)"></span> 1 adversário</span>
    <span class="legend-item"><span class="legend-swatch" style="background:rgba(52,211,153,0.25)"></span> 2+ adversários</span>
    <span class="legend-item"><span class="legend-swatch" style="background:rgba(52,211,153,0.4);box-shadow:inset 0 0 0 1px rgba(52,211,153,0.4)"></span> Todos disponíveis</span>
  </div>

  <div class="cal-wrapper">
    <div class="cal" id="cal"></div>
  </div>

  <div class="hint">Clique ou arraste para selecionar múltiplos horários de uma vez</div>

  <div class="footer">
    <div class="count">Selecionados: <strong id="cnt">0</strong> horários (<strong id="hrs">0h</strong>)</div>
    <button class="btn" id="confirmBtn" disabled onclick="confirmar()">Confirmar disponibilidade</button>
  </div>

  <div class="toast" id="toast">✅ Disponibilidade enviada! O bot vai cruzar com os outros jogadores. 🃏</div>
  <div class="error" id="error">❌ Erro ao enviar. Tente novamente.</div>
</div>

<script>
const TOKEN = "{token}";
const DAYS = ['Dom','Seg','Ter','Qua','Qui','Sex','Sáb'];
const SLOTS = 48;
let selected = new Set();
let dragging = false, dragMode = null;

const OUTROS_VOTOS = {outros_votos_json};
const TOTAL_OUTROS = {total_outros};
const OUTROS_VOTARAM = {outros_votaram};

function slotLabel(s) {{
  const h = String(Math.floor(s/2)).padStart(2,'0');
  const m = s%2===0?'00':'30';
  return h+':'+m;
}}
function updateCount(){{
  const n=selected.size;
  document.getElementById('cnt').textContent=n;
  const m=n*30, h=Math.floor(m/60), r=m%60;
  document.getElementById('hrs').textContent=h>0&&r>0?h+'h'+r+'min':h>0?h+'h':r+'min';
  document.getElementById('confirmBtn').disabled=n===0;
}}
function setSlot(k,val){{
  const el=document.getElementById(k);
  if(!el)return;
  if(val){{selected.add(k);el.classList.add('selected');}}
  else{{selected.delete(k);el.classList.remove('selected');}}
  updateCount();
}}

function buildCal(){{
  const cal=document.getElementById('cal');
  const [dIni,mIni]='{data_ini}'.split('/').map(Number);
  const ano=new Date().getFullYear();
  let base=new Date(ano, mIni-1, dIni);
  
  let numDays = 7;
  let baseFim = null;
  if ('{data_fim}') {{
    const [dF,mF]='{data_fim}'.split('/').map(Number);
    baseFim = new Date(ano, mF-1, dF);
    if(baseFim < base) baseFim.setFullYear(ano+1);
    numDays = Math.min(Math.max(Math.ceil((baseFim - base) / 86400000) + 1, 1), 14);
  }}

  const dates=[];
  const dayNames=[];
  const realDates=[];
  for(let i=0;i<numDays;i++){{
    const d=new Date(base); d.setDate(base.getDate()+i);
    dates.push(String(d.getDate()).padStart(2,'0')+'/'+String(d.getMonth()+1).padStart(2,'0'));
    dayNames.push(DAYS[d.getDay()]);
    realDates.push(d);
  }}

  cal.style.gridTemplateColumns = `52px repeat(${{numDays}}, minmax(0, 1fr))`;
  cal.style.minWidth = `${{52 + numDays * 65}}px`;

  const tc=document.createElement('div');
  tc.className='time-col';
  tc.innerHTML='<div class="cell-header" style="min-height:48px"></div>';
  for(let s=0;s<SLOTS;s++){{
    const l=document.createElement('div');
    l.className='time-label';
    l.textContent=slotLabel(s);
    tc.appendChild(l);
  }}
  cal.appendChild(tc);

  const agora = new Date();

  for(let d=0;d<numDays;d++){{
    const col=document.createElement('div');
    col.className='day-col';
    col.innerHTML=`<div class="cell-header">${{dayNames[d]}}<br><span style="font-weight:400;font-size:10px;color:#666">${{dates[d]}}</span></div>`;
    
    // Converte a Date nativa pra chave limpa: YYYY-MM-DD
    const isoDate = realDates[d].getFullYear() + '-' + String(realDates[d].getMonth()+1).padStart(2,'0') + '-' + String(realDates[d].getDate()).padStart(2,'0');

    for(let s=0;s<SLOTS;s++){{
      const k = isoDate + ',' + s;
      const slot=document.createElement('div');
      slot.className='slot';
      slot.id=k;

      // Desativa cliques no passado
      const slotTime = new Date(realDates[d]);
      slotTime.setHours(Math.floor(s/2), (s%2)*30, 0, 0);
      
      if(slotTime < agora) {{
          slot.classList.add('past');
          slot.style.pointerEvents = 'none';
          slot.style.background = '#14141d';
          slot.style.borderBottom = '1px solid #1a1a24';
      }} else {{
          slot.addEventListener('mousedown',e=>{{
            e.preventDefault();
            dragging=true;
            dragMode=selected.has(k)?'remove':'add';
            setSlot(k, dragMode==='add');
          }});
          slot.addEventListener('mouseenter',()=>{{ if(dragging) setSlot(k, dragMode==='add'); }});
      }}
      col.appendChild(slot);
    }}
    cal.appendChild(col);
  }}
  document.addEventListener('mouseup',()=>{{dragging=false;}});
}}

async function confirmar(){{
  const btn=document.getElementById('confirmBtn');
  btn.disabled=true;
  btn.textContent='Enviando...';
  try{{
    const r=await fetch('/disponibilidade/'+TOKEN,{{
      method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{slots:[...selected]}})
    }});
    if(r.ok){{
      document.getElementById('toast').style.display='block';
      document.getElementById('error').style.display='none';
      btn.textContent='Enviado ✓';
    }}else{{
      throw new Error('server error');
    }}
  }}catch(e){{
    document.getElementById('error').style.display='block';
    btn.disabled=false;
    btn.textContent='Confirmar disponibilidade';
  }}
}}

function applyHeatmap() {{
  if (TOTAL_OUTROS === 0) return;
  document.getElementById('legend').style.display = 'flex';
  for (const [k, count] of Object.entries(OUTROS_VOTOS)) {{
    const el = document.getElementById(k);
    if (!el || el.classList.contains('past')) continue;
    const ratio = count / TOTAL_OUTROS;
    if (ratio >= 1) el.dataset.heat = 'high';
    else if (ratio >= 0.5) el.dataset.heat = 'mid';
    else el.dataset.heat = 'low';
    el.title = count + ' de ' + TOTAL_OUTROS + ' adversário(s) disponível(is) aqui';
  }}
}}

buildCal();
applyHeatmap();
</script>
</body>
</html>"""


# ── Startup: inicia bot Discord em thread separada ────────────────────────────

bot_loop = None

async def _start_bot():
    await bot.start(DISCORD_TOKEN)

def run_bot():
    global bot_loop
    bot_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(bot_loop)
    bot_loop.run_until_complete(_start_bot())


@app.on_event("startup")
async def startup():
    thread = threading.Thread(target=run_bot, daemon=True)
    thread.start()
    logger.info("Bot Discord iniciado em thread separada")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)
