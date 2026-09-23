#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Interface visual local do Biblio Preparador."""

from __future__ import annotations

import argparse
import cgi
import json
import mimetypes
import os
import pathlib
import shutil
import socket
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import biblio_app_service as svc

PORTA_PADRAO = 65087
APP_ID = "biblio-preparador-visual"


HTML = r"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Biblio Preparador</title>
  <style>
    :root {
      color-scheme: light;
      --bg:#f5efe3; --card:#fffaf1; --card2:#eadcc8; --line:#decbb2;
      --green:#1f4d3a; --green2:#25845f; --gold:#bc7429;
      --text:#2b241f; --muted:#76695b; --red:#8a1f1f;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    body { margin:0; background:var(--bg); color:var(--text); }
    .app { min-height:100vh; display:grid; grid-template-rows:auto 1fr; }
    header { background:var(--green); color:white; padding:16px 24px; display:flex; align-items:center; justify-content:space-between; gap:18px; }
    header h1 { margin:0; font-size:22px; }
    header small { opacity:.8; display:block; margin-top:2px; }
    .flow { display:grid; grid-template-columns:repeat(5, 1fr); border-bottom:1px solid var(--line); background:#fff7ea; }
    .tab { border:0; background:transparent; padding:12px 10px; color:var(--text); border-right:1px solid var(--line); cursor:pointer; }
    .tab strong { display:block; font-size:16px; }
    .tab span { color:var(--muted); font-size:12px; }
    .tab.active { background:var(--card2); box-shadow: inset 0 -4px 0 var(--green2); }
    main { padding:18px; max-width:1280px; width:100%; margin:0 auto; }
    .screen { display:none; }
    .screen.active { display:block; }
    .two { display:grid; grid-template-columns:minmax(320px,.85fr) minmax(460px,1.15fr); gap:16px; align-items:start; }
    .panel { background:var(--card); border:1px solid var(--line); border-radius:22px; padding:18px; box-shadow:0 10px 30px #0001; }
    h2 { margin:0 0 8px; font-size:28px; }
    h3 { margin:18px 0 10px; color:var(--green); }
    p { color:var(--muted); line-height:1.45; }
    .actions { display:flex; flex-wrap:wrap; gap:10px; margin-top:14px; }
    button, .fake-button { border:0; border-radius:999px; padding:11px 16px; font-weight:800; cursor:pointer; background:var(--green2); color:white; text-decoration:none; display:inline-flex; align-items:center; gap:8px; }
    button.secondary { background:#756a5f; }
    button.warn { background:var(--gold); }
    button.danger { background:var(--red); }
    button:disabled { opacity:.55; cursor:not-allowed; }
    input[type=file] { display:block; width:100%; border:1px dashed var(--line); border-radius:18px; padding:18px; background:#fffdf8; }
    .stats { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin:16px 0; }
    .stat { background:#fffdf8; border:1px solid var(--line); border-radius:16px; padding:12px; }
    .stat b { display:block; color:var(--green); font-size:26px; }
    .stat span { color:var(--muted); font-size:12px; }
    .progress-card { background:#fffdf8; border:1px solid var(--line); border-radius:18px; padding:14px; }
    .bar { height:10px; background:#eadcc8; border-radius:99px; overflow:hidden; margin:10px 0; }
    .bar > div { height:100%; width:30%; background:linear-gradient(90deg,var(--green2),#70b38a); border-radius:99px; animation:pulse 2s ease-in-out infinite; }
    @keyframes pulse { 0%{width:20%} 50%{width:78%} 100%{width:35%} }
    .log { height:360px; overflow:auto; white-space:pre-wrap; font-family:ui-monospace, SFMono-Regular, Menlo, monospace; font-size:12px; line-height:1.35; background:#211c18; color:#f9ead6; border-radius:16px; padding:14px; }
    .muted { color:var(--muted); }
    .list { display:grid; gap:10px; }
    .row { display:grid; grid-template-columns:40px 1fr auto; gap:10px; align-items:center; background:#fffdf8; border:1px solid var(--line); border-radius:16px; padding:12px; }
    .icon { width:40px; height:40px; display:grid; place-items:center; border-radius:13px; background:#e1efe7; color:var(--green); font-weight:900; }
    .badge { padding:5px 9px; border-radius:999px; background:#eee4d8; color:var(--muted); font-size:12px; font-weight:800; }
    iframe.review { display:block; width:max(100%,1280px); height:min(82vh,870px); min-height:740px; border:0; background:#f5efe3; }
    .review-shell { overflow-x:auto; border:1px solid var(--line); border-radius:22px; background:#f5efe3; }
    .review-note { display:flex; justify-content:space-between; align-items:center; gap:12px; padding:12px 16px; background:#fff7ea; border-bottom:1px solid var(--line); }
    pre.status { white-space:pre-wrap; background:#fffdf8; border:1px solid var(--line); border-radius:16px; padding:14px; max-height:440px; overflow:auto; }
    .modal-backdrop { position:fixed; inset:0; background:#0008; display:none; align-items:center; justify-content:center; padding:22px; z-index:50; }
    .modal-backdrop.active { display:flex; }
    .modal { width:min(520px, 100%); background:var(--card); border:1px solid var(--line); border-radius:24px; padding:22px; box-shadow:0 30px 80px #0005; }
    .modal h2 { font-size:24px; }
    .modal p { margin:8px 0; }
    .modal .danger-text { color:var(--red); font-weight:800; }
    .modal-actions { display:flex; justify-content:flex-end; gap:10px; margin-top:18px; flex-wrap:wrap; }
    @media (max-width:900px) {
      .two { grid-template-columns:1fr; }
      .stats { grid-template-columns:repeat(2,1fr); }
      .flow { grid-template-columns:1fr; }
    }
  </style>
</head>
<body>
<div class="app">
  <header>
    <div><h1>Biblio Preparador</h1><small id="biblioteca">carregando biblioteca…</small></div>
    <button class="secondary" onclick="carregarStatus()">atualizar estado</button>
  </header>
  <nav class="flow">
    <button class="tab active" data-screen="entrada"><strong>1 Importar</strong><span>arquivos ou pasta</span></button>
    <button class="tab" data-screen="preparar"><strong>2 Preparar</strong><span>acompanhar lote</span></button>
    <button class="tab" data-screen="enviar"><strong>3 Enviar</strong><span>subir e limpar</span></button>
    <button class="tab" data-screen="revisar"><strong>4 Revisar</strong><span>bancada visual</span></button>
    <button class="tab" data-screen="concluir"><strong>5 Concluir</strong><span>resumo final</span></button>
  </nav>
  <main>
    <section class="screen active" id="entrada">
      <div class="two">
        <div class="panel">
          <h2>Importar materiais</h2>
          <p>Escolha arquivos, selecione uma pasta ou abra a pasta de entrada. O preparo real só começa quando você clicar em “Iniciar preparação”.</p>
          <form id="uploadForm">
            <input name="files" type="file" multiple webkitdirectory directory>
            <div class="actions">
              <button type="submit">importar selecionados</button>
              <button type="button" class="secondary" onclick="acao('abrir_entrada')">abrir pasta de entrada</button>
            </div>
          </form>
          <p class="muted" id="uploadMsg"></p>
        </div>
        <div class="panel">
          <h2>Estado da biblioteca</h2>
          <div class="stats" id="stats"></div>
          <div class="actions">
            <button class="secondary" onclick="iniciarJob('reprocessar_pendentes')">reprocessar pendentes</button>
          </div>
          <pre class="status" id="statusTexto">carregando…</pre>
        </div>
      </div>
    </section>

    <section class="screen" id="preparar">
      <div class="two">
        <div class="panel">
          <h2>Preparar lote</h2>
          <p>Este botão executa o equivalente ao ciclo completo do menu antigo, com OCR, preparo, conciliação, filas e resumo.</p>
          <div class="actions">
            <button onclick="iniciarJob('preparar')">iniciar preparação</button>
            <button class="secondary" onclick="iniciarJob('preparar_sem_internet')">preparar sem internet</button>
            <button class="secondary" onclick="iniciarJob('reprocessar_pendentes')">reprocessar pendentes com melhorias novas</button>
            <button class="secondary" onclick="mostrar('enviar')">ir para envio</button>
          </div>
        </div>
        <div class="panel">
          <h2>Centro de progresso</h2>
          <div class="progress-card">
            <b id="jobNome">Nenhum processo em execução</b>
            <div class="muted" id="jobEtapa">Aguardando ação do operador.</div>
            <div class="bar" id="jobBar" style="display:none"><div></div></div>
          </div>
          <h3>Atividade em tempo real</h3>
          <div class="log" id="jobLog">Quando iniciar uma tarefa, o andamento aparecerá aqui.</div>
        </div>
      </div>
    </section>

    <section class="screen" id="enviar">
      <div class="two">
        <div class="panel">
          <h2>Enviar para o Biblio</h2>
          <p>Primeiro simule ou veja a fila. O envio real pede confirmação.</p>
          <div class="list">
            <div class="row"><div class="icon">✓</div><div><b>Simular envio unificado</b><br><span class="muted">Mostra a fila realmente selecionável para envio, sem cadastrar.</span></div><button onclick="iniciarJob('simular_envio')">simular</button></div>
            <div class="row"><div class="icon">↑</div><div><b>Enviar fila pronta</b><br><span class="muted">Envia somente o que está pendente na fila: livros, documentos, acadêmicos e revistas.</span></div><button class="warn" onclick="confirmarEnviar()">enviar agora</button></div>
            <div class="row"><div class="icon">🧹</div><div><b>Liberar espaço</b><br><span class="muted">Simula ou move cadastrados/duplicados/descartes para a Lixeira.</span></div><button class="secondary" onclick="iniciarJob('simular_limpeza')">simular</button></div>
            <div class="row"><div class="icon">🗑</div><div><b>Executar limpeza</b><br><span class="muted">Pede confirmação antes de mover arquivos.</span></div><button class="danger" onclick="confirmarLimpeza()">liberar</button></div>
          </div>
        </div>
        <div class="panel">
          <h2>Progresso do envio</h2>
          <div class="progress-card">
            <b id="jobNomeEnvio">Aguardando</b>
            <div class="muted" id="jobEtapaEnvio">Use uma das ações ao lado.</div>
            <div class="bar" id="jobBarEnvio" style="display:none"><div></div></div>
          </div>
          <h3>Atividade</h3>
          <div class="log" id="jobLogEnvio">Sem atividade ainda.</div>
        </div>
      </div>
    </section>

    <section class="screen" id="revisar">
      <div class="review-shell">
        <div class="review-note">
          <div><b>4 Revisar pendentes</b><br><span class="muted">Abre a bancada visual aprovada em uma aba/janela local.</span></div>
          <div class="actions">
            <button onclick="iniciarJob('abrir_revisao')">abrir bancada</button>
            <button class="secondary" onclick="iniciarJob('reprocessar_pendentes')">reprocessar todos em revisão</button>
            <button class="secondary" onclick="mostrar('enviar')">← Enviar</button>
            <button onclick="mostrar('concluir')">Concluir</button>
          </div>
        </div>
        <div class="panel" style="margin:18px">
          <h2>Bancada aprovada</h2>
          <p>A revisão real continua usando a bancada já testada: lista à esquerda, PDF no centro e metadados à direita.</p>
          <div class="log" id="jobLogRevisao">Clique em “abrir bancada”.</div>
        </div>
      </div>
    </section>

    <section class="screen" id="concluir">
      <div class="two">
        <div class="panel">
          <h2>Conclusão do lote</h2>
          <p>Use esta tela para conferir o estado final antes de encerrar.</p>
          <div class="actions">
            <button onclick="carregarStatus()">atualizar resumo</button>
            <button class="secondary" onclick="mostrar('entrada')">novo lote</button>
          </div>
        </div>
        <div class="panel">
          <h2>Resumo</h2>
          <div class="stats" id="statsFinal"></div>
          <pre class="status" id="statusFinal">carregando…</pre>
        </div>
      </div>
    </section>
  </main>
  <div class="modal-backdrop" id="confirmModal" role="dialog" aria-modal="true" aria-labelledby="modalTitulo">
    <div class="modal">
      <h2 id="modalTitulo">Confirmar ação</h2>
      <p id="modalTexto"></p>
      <p class="danger-text" id="modalAlerta"></p>
      <div class="modal-actions">
        <button class="secondary" onclick="fecharModal()">Cancelar</button>
        <button id="modalConfirmar" class="warn">Confirmar</button>
      </div>
    </div>
  </div>
</div>

<script>
let jobAtual = null;
let telaAtual = 'entrada';
const telasJob = {preparar:['jobNome','jobEtapa','jobLog','jobBar'], enviar:['jobNomeEnvio','jobEtapaEnvio','jobLogEnvio','jobBarEnvio'], revisar:['jobNome','jobEtapa','jobLogRevisao','jobBar']};

document.querySelectorAll('.tab').forEach(btn => btn.addEventListener('click', () => mostrar(btn.dataset.screen)));
function $(id){ return document.getElementById(id); }
function mostrar(id){
  telaAtual = id;
  document.querySelectorAll('.screen').forEach(s => s.classList.toggle('active', s.id === id));
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.screen === id));
  if(location.hash !== '#' + id) history.replaceState(null, '', '#' + id);
  if(id === 'concluir') carregarStatus();
  if(id === 'revisar') carregarStatus();
}
async function api(path, body){
  const opt = body ? {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)} : {};
  const r = await fetch(path, opt);
  if(!r.ok) throw new Error(await r.text());
  return await r.json();
}
function renderStats(data, alvo){
  const nomes = {entrada:'Entrada', revisao:'Revisão', prontos:'Prontos', documentos:'Docs', academicos:'Acadêmicos', revistas:'Revistas', descarte:'Descarte'};
  alvo.innerHTML = Object.entries(nomes).map(([k,n]) => `<div class="stat"><b>${data[k] ?? 0}</b><span>${n}</span></div>`).join('');
}
async function carregarStatus(){
  const data = await api('/api/status');
  $('biblioteca').textContent = data.raiz;
  renderStats(data.contagens, $('stats'));
  renderStats(data.contagens, $('statsFinal'));
  $('statusTexto').textContent = data.status;
  $('statusFinal').textContent = data.status;
}
async function acao(nome){
  const data = await api('/api/action', {action:nome});
  if(data.message) alert(data.message);
  await carregarStatus();
}
async function iniciarJob(action){
  if(action.includes('envio') || action.includes('limpeza')) mostrar('enviar');
  if(action.includes('preparar') || action.includes('reprocessar')) mostrar('preparar');
  if(action.includes('abrir_revisao')) mostrar('revisar');
  const data = await api('/api/action', {action});
  jobAtual = data.job_id;
  atualizarJob();
}
function abrirModal({titulo, texto, alerta, classe='warn', confirmarTexto='Confirmar', acao}) {
  $('modalTitulo').textContent = titulo;
  $('modalTexto').textContent = texto;
  $('modalAlerta').textContent = alerta || '';
  const botao = $('modalConfirmar');
  botao.textContent = confirmarTexto;
  botao.className = classe;
  botao.onclick = () => { fecharModal(); acao(); };
  $('confirmModal').classList.add('active');
}
function fecharModal(){ $('confirmModal').classList.remove('active'); }
function confirmarEnviar(){
  abrirModal({
    titulo: 'Enviar materiais para o Biblio?',
    texto: 'A fila pronta será cadastrada no servidor do Biblio como material público.',
    alerta: 'Antes do envio, o motor consulta duplicidade e evita reenviar o que já existir, mas esta é uma ação real.',
    confirmarTexto: 'Sim, enviar agora',
    classe: 'warn',
    acao: () => iniciarJob('enviar_tudo')
  });
}
function confirmarLimpeza(){
  abrirModal({
    titulo: 'Liberar espaço local?',
    texto: 'Arquivos cadastrados, duplicados confirmados e descartes serão movidos para a Lixeira do macOS.',
    alerta: 'Metadados, IDs, hashes e histórico serão preservados.',
    confirmarTexto: 'Sim, liberar espaço',
    classe: 'danger',
    acao: () => iniciarJob('executar_limpeza')
  });
}
async function atualizarJob(){
  if(!jobAtual) return;
  const data = await api('/api/job?id=' + encodeURIComponent(jobAtual));
  const map = telaAtual === 'enviar' ? telasJob.enviar : telaAtual === 'revisar' ? telasJob.revisar : telasJob.preparar;
  $(map[0]).textContent = data.nome + ' — ' + data.estado;
  $(map[1]).textContent = data.etapa_atual || 'aguardando…';
  $(map[2]).textContent = (data.linhas || []).join('\n');
  $(map[2]).scrollTop = $(map[2]).scrollHeight;
  $(map[3]).style.display = data.estado === 'rodando' ? 'block' : 'none';
  if(data.estado === 'concluido' || data.estado === 'erro') carregarStatus();
  if(data.estado === 'rodando') setTimeout(atualizarJob, 1200);
}
$('uploadForm').addEventListener('submit', async ev => {
  ev.preventDefault();
  const form = new FormData(ev.target);
  $('uploadMsg').textContent = 'importando…';
  const r = await fetch('/api/upload', {method:'POST', body:form});
  const data = await r.json();
  $('uploadMsg').textContent = data.message;
  await carregarStatus();
});
const telaInicial = (location.hash || '#entrada').slice(1);
mostrar(['entrada','preparar','enviar','revisar','concluir'].includes(telaInicial) ? telaInicial : 'entrada');
carregarStatus();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    raiz: pathlib.Path = svc.biblioteca_padrao()

    def log_message(self, fmt, *args):  # noqa: D401
        sys.stderr.write("BiblioApp: " + (fmt % args) + "\n")

    def _json(self, dados, status=200):
        bruto = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(bruto)))
        self.end_headers()
        self.wfile.write(bruto)

    def _html(self):
        bruto = HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(bruto)))
        self.end_headers()
        self.wfile.write(bruto)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path == "/":
            self._html()
            return
        if url.path == "/api/health":
            self._json({
                "ok": True,
                "app": APP_ID,
                "raiz": str(self.raiz),
            })
            return
        if url.path == "/api/status":
            try:
                self._json({
                    "raiz": str(self.raiz),
                    "contagens": svc.contagens_basicas(self.raiz),
                    "status": svc.status_texto(self.raiz),
                })
            except Exception as exc:
                self._json({"erro": str(exc)}, 500)
            return
        if url.path == "/api/job":
            job_id = urllib.parse.parse_qs(url.query).get("id", [""])[0]
            job = svc.JOBS.obter(job_id)
            if not job:
                self._json({"erro": "processo não encontrado"}, 404)
            else:
                self._json(job.como_dict())
            return
        self.send_error(404)

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        if url.path == "/api/action":
            tamanho = int(self.headers.get("Content-Length", "0"))
            dados = json.loads(self.rfile.read(tamanho) or b"{}")
            self._action(dados.get("action", ""))
            return
        if url.path == "/api/upload":
            self._upload()
            return
        self.send_error(404)

    def _action(self, action: str):
        try:
            if action == "abrir_entrada":
                svc.abrir_entrada(self.raiz)
                self._json({"ok": True, "message": "Pasta de entrada aberta."})
            elif action == "preparar":
                job = svc.JOBS.iniciar("Preparação completa", svc.etapas_preparar(self.raiz, True))
                self._json({"ok": True, "job_id": job.id})
            elif action == "preparar_sem_internet":
                job = svc.JOBS.iniciar("Preparação sem internet", svc.etapas_preparar(self.raiz, False))
                self._json({"ok": True, "job_id": job.id})
            elif action == "reprocessar_pendentes":
                job = svc.JOBS.iniciar("Reprocessamento dos pendentes", svc.etapas_reprocessar_pendentes(self.raiz))
                self._json({"ok": True, "job_id": job.id})
            elif action == "simular_envio":
                job = svc.JOBS.iniciar("Simulação de envio", svc.etapas_enviar_tudo(self.raiz, False, 0))
                self._json({"ok": True, "job_id": job.id})
            elif action == "enviar_tudo":
                job = svc.JOBS.iniciar("Envio real", svc.etapas_enviar_tudo(self.raiz, True, 0))
                self._json({"ok": True, "job_id": job.id})
            elif action == "simular_limpeza":
                job = svc.JOBS.iniciar("Simulação de limpeza", svc.etapas_liberar_espaco(self.raiz, False))
                self._json({"ok": True, "job_id": job.id})
            elif action == "executar_limpeza":
                job = svc.JOBS.iniciar("Liberação de espaço", svc.etapas_liberar_espaco(self.raiz, True))
                self._json({"ok": True, "job_id": job.id})
            elif action == "abrir_revisao":
                host = self.headers.get("Host", "")
                voltar_url = f"http://{host}/#revisar" if host else ""
                job = svc.abrir_revisao(self.raiz, voltar_url=voltar_url)
                self._json({"ok": True, "job_id": job.id})
            else:
                self._json({"erro": "ação desconhecida"}, 400)
        except Exception as exc:
            self._json({"erro": str(exc)}, 500)

    def _upload(self):
        try:
            svc.inicializar_biblioteca(self.raiz)
            entrada = self.raiz / "00-ENTRADA"
            form = cgi.FieldStorage(fp=self.rfile, headers=self.headers,
                                    environ={"REQUEST_METHOD": "POST"})
            campos = form["files"] if "files" in form else []
            if not isinstance(campos, list):
                campos = [campos]
            copiados = 0
            for item in campos:
                if not getattr(item, "filename", ""):
                    continue
                nome = pathlib.Path(item.filename).name
                destino = entrada / nome
                if destino.exists():
                    destino = entrada / f"{destino.stem}-{copiados + 1}{destino.suffix}"
                with destino.open("wb") as f:
                    shutil.copyfileobj(item.file, f)
                copiados += 1
            self._json({"ok": True, "message": f"{copiados} arquivo(s) importado(s)."})
        except Exception as exc:
            self._json({"erro": str(exc)}, 500)


def porta_ocupada_por_biblio(porta: int) -> bool:
    for caminho in ("/api/health", "/api/status"):
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{porta}{caminho}",
                    timeout=(0.8 if caminho == "/api/health" else 4.0)) as resp:
                dados = json.loads(resp.read().decode("utf-8"))
        except Exception:
            continue
        if dados.get("app") == APP_ID:
            return True
        # Compatibilidade com uma instância antiga do mesmo Preparador,
        # anterior ao endpoint /api/health.
        if caminho == "/api/status" and "contagens" in dados and "raiz" in dados:
            return True
    return False


def porta_disponivel(porta: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", porta))
            return True
        except OSError:
            return False


def resolver_porta(inicial: int, abrir: bool) -> tuple[int, bool]:
    """Retorna (porta, reutilizada). Porta 0 continua útil para testes."""
    if inicial == 0:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return int(s.getsockname()[1]), False
    if porta_ocupada_por_biblio(inicial):
        url = f"http://127.0.0.1:{inicial}/"
        print(f"Biblio Preparador já está aberto em: {url}", flush=True)
        if abrir:
            webbrowser.open(url)
        return inicial, True
    if porta_disponivel(inicial):
        return inicial, False
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        alternativa = int(s.getsockname()[1])
    print(
        f"Porta fixa {inicial} ocupada; usando porta livre {alternativa}.",
        flush=True)
    return alternativa, False


def main():
    ap = argparse.ArgumentParser(description="Interface visual local do Biblio Preparador")
    ap.add_argument("--raiz", default=str(svc.biblioteca_padrao()))
    ap.add_argument("--porta", type=int, default=PORTA_PADRAO)
    ap.add_argument("--abrir", action="store_true")
    args = ap.parse_args()
    Handler.raiz = pathlib.Path(args.raiz).expanduser().resolve()
    svc.inicializar_biblioteca(Handler.raiz)
    porta, reutilizada = resolver_porta(args.porta, args.abrir)
    if reutilizada:
        return 0
    servidor = ThreadingHTTPServer(("127.0.0.1", porta), Handler)
    url = f"http://127.0.0.1:{porta}/"
    print(f"Biblio Preparador visual aberto em: {url}", flush=True)
    if args.abrir:
        webbrowser.open(url)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nBiblio Preparador encerrado.")
    finally:
        servidor.server_close()


if __name__ == "__main__":
    main()
