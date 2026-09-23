#!/usr/bin/env python3
"""Bancada local de revisão visual.

Primeira versão: funcional antes de bonita. Ela expõe, no navegador local,
o pacote de revisão gerado por ``biblioteca-local.py``: PDF ativo, capa,
metadados, conflitos, ausências explicadas, páginas internas sugeridas e
busca de ISBN. As decisões gravadas alimentam ``revisoes-manuais.json`` e
as memórias de ruído.
"""

import argparse
import importlib.util
import json
import mimetypes
import os
import pathlib
import socket
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


BASE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "biblioteca_local", BASE / "biblioteca-local.py")
local = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(local)


HTML = r"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Biblio — revisão visual</title>
  <style>
    :root { color-scheme: light dark; font-family: system-ui, -apple-system, sans-serif; }
    body { margin: 0; background: #f5f1ea; color: #2b241f; }
    header { padding: 16px 22px; background: #1f4d3a; color: white; }
    main { display: grid; grid-template-columns: 260px minmax(460px, 1.1fr) minmax(380px, .9fr); gap: 14px; padding: 14px; height: calc(100vh - 76px); box-sizing: border-box; }
    .painel { background: white; border-radius: 14px; box-shadow: 0 1px 8px #0002; overflow: hidden; }
    .visual { display: grid; grid-template-rows: auto 1fr; }
    .barra { display: flex; gap: 8px; align-items: center; padding: 10px; border-bottom: 1px solid #e7ded3; flex-wrap: wrap; }
    button { border: 0; border-radius: 10px; padding: 10px 12px; background: #1f7a56; color: white; cursor: pointer; font-weight: 650; }
    button.sec { background: #6b625a; }
    button.warn { background: #aa5a1f; }
    button.mini { padding: 5px 8px; border-radius: 7px; font-size: 12px; margin: 2px; }
    .acoes-fixas { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; padding-top: 10px; border-top: 1px solid #e7ded3; }
    .acoes-fixas button { padding: 8px 10px; }
    select, input, textarea { width: 100%; box-sizing: border-box; border: 1px solid #d8cfc3; border-radius: 8px; padding: 8px; font: inherit; }
    iframe { width: 100%; height: 100%; border: 0; background: #ddd; }
    .conclusao { display: none; height: 100%; box-sizing: border-box; padding: 36px; place-items: center; text-align: center; background: linear-gradient(135deg, #eef7f2, #f7f4ef); }
    .cartao-conclusao { max-width: 620px; background: white; border-radius: 18px; padding: 32px; box-shadow: 0 6px 24px #0002; }
    .cartao-conclusao h1 { margin: 0 0 10px; color: #1f4d3a; font-size: 30px; }
    .cartao-conclusao p { margin: 8px 0; color: #6b625a; line-height: 1.45; }
    .botoes-conclusao { display: flex; flex-wrap: wrap; gap: 10px; justify-content: center; margin-top: 22px; }
    aside { display: grid; grid-template-rows: auto minmax(0, 1fr); overflow: hidden; padding: 0; }
    .cabecalho-revisao { padding: 14px 14px 8px; border-bottom: 1px solid #e7ded3; }
    .corpo-revisao { overflow: auto; min-height: 0; padding: 0 14px 18px; }
    h2 { margin: 0 0 8px; }
    h3 { margin: 18px 0 8px; color: #1f4d3a; }
    label { display: block; margin: 8px 0; font-size: 14px; }
    .meta { color: #6b625a; font-size: 13px; }
    .tag { display: inline-block; margin: 2px 4px 2px 0; padding: 4px 7px; border-radius: 999px; background: #eee4d8; font-size: 12px; }
    .erro { color: #8a1f1f; }
    .ok { color: #1f7a56; }
    .item { border-top: 1px solid #eee4d8; padding: 8px 0; }
    .item.sel { background: #eef7f2; margin: 0 -8px; padding: 8px; border-radius: 8px; }
    .lista { overflow: auto; padding: 10px; }
    .lista button { width: 100%; text-align: left; background: transparent; color: inherit; border-radius: 8px; padding: 8px; font-weight: 500; }
    .lista button.sel { background: #eef7f2; }
    .capa { max-width: 130px; max-height: 180px; object-fit: contain; border-radius: 8px; box-shadow: 0 1px 5px #0003; background: #eee; }
    .capa-url { display: grid; grid-template-columns: 1fr auto; gap: 8px; margin-top: 10px; }
    .capa-url button { white-space: nowrap; }
    .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .fixo { position: sticky; top: 0; background: inherit; padding-bottom: 8px; z-index: 2; }
    pre { white-space: pre-wrap; background: #f7f4ef; border-radius: 8px; padding: 8px; font-size: 12px; }
    @media (max-width: 1100px) { main { grid-template-columns: 1fr; height: auto; } iframe { height: 70vh; } }
    @media (prefers-color-scheme: dark) {
      body { background: #171615; color: #f1eee9; }
      .painel { background: #24211f; }
      .barra { border-color: #3a342f; }
      .item.sel { background: #1b3328; }
      .lista button.sel { background: #1b3328; }
      .lista button { color: #f1eee9; }
      input, textarea, select { background: #1d1b19; color: #f1eee9; border-color: #5b5148; }
      .tag, pre { background: #332e29; }
      .cabecalho-revisao { border-color: #3a342f; }
      .conclusao { background: linear-gradient(135deg, #182920, #24211f); }
      .cartao-conclusao { background: #24211f; }
      .cartao-conclusao p { color: #c9c0b6; }
    }
  </style>
</head>
<body>
<header>
  <strong>Biblio — bancada de revisão visual</strong>
  <span id="estado" style="margin-left:12px;opacity:.85">carregando…</span>
</header>
<main>
  <nav class="painel lista">
    <div class="fixo">
      <button onclick="recarregar()">recarregar lista</button>
      <div class="meta" style="margin-top:8px">Itens em revisão</div>
    </div>
    <div id="listaItens"></div>
  </nav>
  <section class="painel visual">
    <div class="barra">
      <button class="sec" onclick="anterior()">← anterior</button>
      <button class="sec" onclick="proximo()">próximo sem salvar →</button>
      <button onclick="abrirPdf()">abrir PDF ativo</button>
      <button class="sec" onclick="abrirCapa()">abrir capa</button>
      <button class="warn" onclick="recarregar()">recarregar</button>
    </div>
    <iframe id="pdf"></iframe>
    <div id="conclusao" class="conclusao">
      <div class="cartao-conclusao">
        <h1>Revisão concluída</h1>
        <p>Não há mais itens pendentes nesta bancada visual.</p>
        <p>Você pode voltar ao Biblio Preparador para enviar materiais, ver o estado da biblioteca ou executar outro serviço.</p>
        <div class="botoes-conclusao">
          <button onclick="encerrarBancada()">voltar ao Biblio Preparador</button>
          <button class="sec" onclick="recarregar()">verificar novamente</button>
          <button class="sec" onclick="window.close()">fechar esta aba</button>
        </div>
        <div id="fimMsg" class="meta" style="margin-top:14px"></div>
      </div>
    </div>
  </section>
  <aside class="painel">
    <div class="cabecalho-revisao">
      <div class="grid2">
        <div>
          <h2 id="titulo">Nenhum item</h2>
          <div class="meta" id="arquivo"></div>
        </div>
        <div><img id="capa" class="capa" alt="capa"></div>
      </div>
      <div class="acoes-fixas">
        <button onclick="salvar(true, false)">salvar / validar</button>
        <button onclick="salvar(true, true)">salvar e próximo</button>
        <button class="sec" onclick="reprocessarAtual()">reprocessar este item</button>
        <button class="warn" onclick="confirmarMesmoComDivergencia()">confirmar divergência</button>
        <button class="sec" onclick="salvar(false)">salvar sem aprovar</button>
      </div>
      <div class="capa-url">
        <input id="capaUrl" placeholder="URL da capa encontrada na internet">
        <button class="sec" onclick="usarCapaInternet()">usar capa da internet</button>
      </div>
      <div class="capa-url">
        <input id="capaArquivo" type="file" accept="image/png,image/jpeg,image/webp,image/gif">
        <button class="sec" onclick="usarCapaArquivo()">usar arquivo de capa</button>
      </div>
      <div id="salvoTopo" class="meta"></div>
    </div>

    <div class="corpo-revisao">
    <h3>Campos para cadastro</h3>
    <label>Título <input id="tituloCampo"></label>
    <label>Tipo do material
      <select id="tipo_documento">
        <option>livro</option><option>opúsculo</option><option>documento</option><option>apostila</option><option>sermão</option><option>artigo</option><option>revista</option><option>periódico</option><option>boletim</option><option>jornal</option><option>tese</option><option>dissertação</option><option>trabalho acadêmico</option><option>apresentação</option><option>resumo</option><option>trecho</option>
      </select>
    </label>
    <label>Subtítulo <input id="subTitulo"></label>
    <label>Autor principal <input id="nmAutor0"></label>
    <label>Editora <input id="editora"></label>
    <label>ISBN <input id="isbn"></label>
    <button class="sec" onclick="consultarIsbn()">consultar dados por ISBN</button>
    <div id="fontesIsbn" class="meta"></div>
    <label>Edição <input id="edicao"></label>
    <label>Ano/Data <input id="data"></label>
    <label>Páginas <input id="nPaginas"></label>
    <label>Local <input id="lugar"></label>
    <label>Idioma
      <select id="nmLingua">
        <option></option><option>Português</option><option>Inglês</option><option>Espanhol</option><option>Francês</option><option>Alemão</option><option>Italiano</option>
      </select>
    </label>
    <label>CDD <input id="CDD"></label>
    <label>Assunto <input id="assunto"></label>
    <label>Palavras-chave <input id="pchave"></label>
    <label>Resumo <textarea id="abstract" rows="4"></textarea></label>

    <h3>Decisão</h3>
    <label>Ruído de título confirmado <input id="ruidoTitulo" placeholder="opcional"></label>
    <label>Ruído de autor confirmado <input id="ruidoAutor" placeholder="opcional"></label>
    <label>Fonte da revisão <input id="fonte" value="revisão visual do PDF"></label>
    <button onclick="salvar(true, false)">validar ficha</button>
    <button onclick="salvar(true, true)">validar e próximo</button>
    <button class="warn" onclick="confirmarMesmoComDivergencia()">confirmar mesmo com divergência</button>
    <button class="sec" onclick="salvar(false)">salvar sem aprovar</button>
    <div id="salvo" class="meta"></div>

    <h3>Ausências com causa</h3>
    <div id="ausencias"></div>
    <h3>Classificação do material</h3>
    <div id="classificacao"></div>
    <h3>Conflitos</h3>
    <div id="conflitos"></div>
    <h3>ISBN</h3>
    <div id="buscaIsbn"></div>
    <h3>Onde olhar dentro do material</h3>
    <div id="paginas"></div>
    <h3>Fontes rejeitadas</h3>
    <div id="rejeitadas"></div>
    </div>
  </aside>
</main>
<script>
let dados = {itens: []};
let idx = 0;
let ultimaConsultaIsbn = null;
let sujo = false;
const VOLTAR_URL = "__VOLTAR_URL__";
const campos = ["titulo","subTitulo","nmAutor0","editora","isbn","edicao","data","nPaginas","lugar","nmLingua","tipo_documento","CDD","assunto","pchave","abstract"];
const $ = id => document.getElementById(id);

function arquivoUrl(rel) {
  return rel ? "/arquivo?rel=" + encodeURIComponent(rel) : "about:blank";
}
function arquivoPaginaUrl(rel, pagina) {
  return arquivoUrl(rel) + (pagina ? "#page=" + encodeURIComponent(pagina) : "");
}
async function recarregar() {
  $("estado").textContent = "carregando…";
  const resp = await fetch("/api/pacotes");
  dados = await resp.json();
  idx = Math.min(idx, Math.max(0, dados.itens.length - 1));
  mostrar();
}
function atual() { return dados.itens[idx] || null; }
function podeSairSemSalvar() {
  return !sujo || confirm("Há alterações não salvas neste item. Deseja sair sem salvar?");
}
function anterior() { if (idx > 0 && podeSairSemSalvar()) { idx--; mostrar(); } }
function proximo() { if (idx + 1 < dados.itens.length && podeSairSemSalvar()) { idx++; mostrar(); } }
function selecionar(i) { if (i === idx || podeSairSemSalvar()) { idx = i; mostrar(); } }
function abrirPdf() {
  const item = atual();
  if (item && item.pdf_visualizacao) window.open(arquivoUrl(item.pdf_visualizacao), "_blank");
}
function abrirCapa() {
  const item = atual();
  if (item && item.capa) window.open(arquivoUrl(item.capa), "_blank");
}
async function usarCapaInternet() {
  const item = atual();
  const url = $("capaUrl").value.trim();
  if (!item || !url) {
    $("salvoTopo").innerHTML = "<span class='erro'>cole a URL da capa antes de usar</span>";
    return;
  }
  $("salvoTopo").textContent = "baixando e gravando capa…";
  $("salvo").textContent = "baixando e gravando capa…";
  try {
    const resp = await fetch("/api/capa-url", {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({arquivo: item.arquivo, url})
    });
    const out = await resp.json();
    if (!resp.ok) {
      $("salvoTopo").innerHTML = `<span class="erro">${esc(out.erro || "erro ao baixar capa")}</span>`;
      $("salvo").innerHTML = $("salvoTopo").innerHTML;
      return;
    }
    item.capa = out.capa;
    $("capa").src = arquivoUrl(out.capa) + "&v=" + Date.now();
    $("capa").style.display = "block";
    $("salvoTopo").innerHTML = `<span class="ok">capa manual gravada (${esc(out.bytes)} bytes)</span>`;
    $("salvo").innerHTML = $("salvoTopo").innerHTML;
    $("capaUrl").value = "";
  } catch (e) {
    $("salvoTopo").innerHTML = `<span class="erro">${esc(e.message || e)}</span>`;
    $("salvo").innerHTML = $("salvoTopo").innerHTML;
  }
}
function arquivoParaBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const texto = String(reader.result || "");
      resolve(texto.includes(",") ? texto.split(",").pop() : texto);
    };
    reader.onerror = () => reject(reader.error || new Error("falha ao ler arquivo"));
    reader.readAsDataURL(file);
  });
}
async function usarCapaArquivo() {
  const item = atual();
  const input = $("capaArquivo");
  const file = input.files && input.files[0];
  if (!item || !file) {
    $("salvoTopo").innerHTML = "<span class='erro'>escolha um arquivo de imagem antes de usar</span>";
    return;
  }
  $("salvoTopo").textContent = "gravando arquivo de capa…";
  $("salvo").textContent = "gravando arquivo de capa…";
  try {
    const conteudo_base64 = await arquivoParaBase64(file);
    const resp = await fetch("/api/capa-arquivo", {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({arquivo: item.arquivo, nome: file.name, conteudo_base64})
    });
    const out = await resp.json();
    if (!resp.ok) {
      $("salvoTopo").innerHTML = `<span class="erro">${esc(out.erro || "erro ao gravar capa")}</span>`;
      $("salvo").innerHTML = $("salvoTopo").innerHTML;
      return;
    }
    item.capa = out.capa;
    $("capa").src = arquivoUrl(out.capa) + "&v=" + Date.now();
    $("capa").style.display = "block";
    $("salvoTopo").innerHTML = `<span class="ok">arquivo de capa gravado (${esc(out.bytes)} bytes)</span>`;
    $("salvo").innerHTML = $("salvoTopo").innerHTML;
    input.value = "";
  } catch (e) {
    $("salvoTopo").innerHTML = `<span class="erro">${esc(e.message || e)}</span>`;
    $("salvo").innerHTML = $("salvoTopo").innerHTML;
  }
}
function irPagina(p) {
  const item = atual();
  if (item && item.pdf_visualizacao) $("pdf").src = arquivoPaginaUrl(item.pdf_visualizacao, p);
}
function usarValor(campo, valor) {
  const id = campo === "titulo" ? "tituloCampo" : campo;
  if ($(id)) { $(id).value = valor || ""; marcarSujo(); }
}
function marcarSujo() {
  sujo = true;
  $("salvo").textContent = "alterações ainda não salvas";
  $("salvoTopo").textContent = "alterações ainda não salvas";
}
function preencherCampos(camposFonte) {
  for (const [campo, valor] of Object.entries(camposFonte || {})) {
    usarValor(campo, valor);
  }
}
function cardFonteIsbn(fonte, i) {
  const c = fonte.campos || {};
  const detalhes = [
    c.titulo, c.nmAutor0, c.editora, c.data,
    c.nPaginas ? `${c.nPaginas} p.` : "", c.CDD ? `CDD ${c.CDD}` : ""
  ].filter(Boolean).map(esc).join(" · ");
  return `<div class="item"><b>${esc(fonte.fonte || "fonte")}</b> <span class="tag">pontuação ${esc(fonte.pontuacao_revisao || 0)}</span><br>${detalhes || "<span class='meta'>sem campos aproveitáveis</span>"}<br><button class="mini" onclick="usarFonteIsbn(${i})">usar esta fonte</button></div>`;
}
function usarFonteIsbn(i) {
  const fonte = ultimaConsultaIsbn && ultimaConsultaIsbn.fontes ? ultimaConsultaIsbn.fontes[i] : null;
  if (!fonte) return;
  preencherCampos(fonte.campos || {});
  $("fonte").value = `ISBN ${ultimaConsultaIsbn.isbn} — ${fonte.fonte || "fonte bibliográfica"}`;
  $("salvo").innerHTML = `<span class="ok">campos preenchidos a partir de ${esc(fonte.fonte || "fonte bibliográfica")}; confira e valide</span>`;
}
async function consultarIsbn() {
  const item = atual();
  const isbn = $("isbn").value.trim();
  if (!isbn) {
    $("fontesIsbn").innerHTML = "<span class='erro'>digite ou use um ISBN antes de consultar</span>";
    return;
  }
  $("fontesIsbn").textContent = "consultando fontes bibliográficas…";
  try {
    const resp = await fetch("/api/consultar-isbn", {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({isbn, arquivo: item ? item.arquivo : ""})
    });
    const out = await resp.json();
    ultimaConsultaIsbn = out;
    if (!resp.ok) {
      $("fontesIsbn").innerHTML = `<span class="erro">${esc(out.erro || "erro na consulta")}</span>`;
      return;
    }
    if (!out.encontrado) {
      const erros = (out.erros || []).map(e => `${e.fonte}: ${e.erro}`).join(" | ");
      const links = (out.links_busca || []).map(l => `<a class="tag" href="${esc(l.url)}" target="_blank">${esc(l.rotulo)}</a>`).join("");
      $("fontesIsbn").innerHTML = `<span class="erro">nenhuma fonte automática retornou dados para ${esc(out.isbn)}</span><br><span class="meta">${esc(erros || "as bases catalográficas consultadas não possuem este ISBN")}</span><br>${links}`;
      return;
    }
    preencherCampos(out.campos || {});
    const fonte = (out.melhor || {}).fonte || "fonte bibliográfica";
    $("fonte").value = `ISBN ${out.isbn} — ${fonte}`;
    $("fontesIsbn").innerHTML = `<div class="ok">dados preenchidos pela melhor fonte: ${esc(fonte)}</div>` + (out.fontes || []).map(cardFonteIsbn).join("");
  } catch (e) {
    $("fontesIsbn").innerHTML = `<span class="erro">${esc(e.message || e)}</span>`;
  }
}
function lista(id, itens, vazio) {
  $(id).innerHTML = itens && itens.length ? itens.map(x => `<div class="item">${x}</div>`).join("") : `<span class="meta">${vazio}</span>`;
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function removerItemAtualDaRevisao() {
  const pos = idx;
  dados.itens.splice(idx, 1);
  idx = Math.min(pos, Math.max(0, dados.itens.length - 1));
  mostrar();
}
function mostrarConclusao() {
  $("pdf").src = "about:blank";
  $("pdf").style.display = "none";
  $("conclusao").style.display = "grid";
  $("titulo").textContent = "Revisão concluída";
  $("arquivo").textContent = "Todos os itens da bancada foram tratados.";
  $("capa").style.display = "none";
  $("salvoTopo").innerHTML = "<span class='ok'>não há mais itens para corrigir</span>";
  $("salvo").innerHTML = "<span class='ok'>revisão concluída</span>";
  $("conflitos").innerHTML = "<span class='meta'>sem item ativo</span>";
  $("ausencias").innerHTML = "<span class='meta'>sem item ativo</span>";
  $("classificacao").innerHTML = "<span class='meta'>sem item ativo</span>";
  $("buscaIsbn").innerHTML = "<span class='meta'>sem item ativo</span>";
  $("paginas").innerHTML = "<span class='meta'>sem item ativo</span>";
  $("rejeitadas").innerHTML = "<span class='meta'>sem item ativo</span>";
  sujo = false;
}
async function encerrarBancada() {
  $("fimMsg").innerHTML = "<span class='ok'>voltando ao Biblio Preparador…</span>";
  if (VOLTAR_URL) {
    // Não aguardamos a resposta de /api/encerrar: ao desligar o servidor da
    // bancada, alguns navegadores cancelam o redirecionamento e o botão fica
    // parecendo quebrado. Primeiro devolvemos o operador ao Preparador; o
    // fechamento da bancada fica em segundo plano.
    try {
      navigator.sendBeacon("/api/encerrar", new Blob(["{}"], {type:"application/json"}));
    } catch (e) {
      fetch("/api/encerrar", {method:"POST", keepalive:true}).catch(() => {});
    }
    setTimeout(() => { window.location.assign(VOLTAR_URL); }, 80);
  } else {
    try {
      navigator.sendBeacon("/api/encerrar", new Blob(["{}"], {type:"application/json"}));
    } catch (e) {
      fetch("/api/encerrar", {method:"POST", keepalive:true}).catch(() => {});
    }
    setTimeout(() => { try { window.close(); } catch(e) {} }, 700);
  }
}
function mostrar() {
  const item = atual();
  $("estado").textContent = `${dados.itens.length} item(ns) de revisão`;
  $("listaItens").innerHTML = (dados.itens || []).map((x, i) => `<button class="${i===idx?'sel':''}" onclick="selecionar(${i})"><b>${esc(x.campos.titulo || x.arquivo)}</b><br><span class="meta">${esc(x.estado || "")} · ${esc((x.classificacao_material||{}).tipo_atual || "")}</span></button>`).join("");
  if (!item) {
    mostrarConclusao();
    return;
  }
  $("pdf").style.display = "block";
  $("conclusao").style.display = "none";
  $("titulo").textContent = item.campos.titulo || item.arquivo;
  $("arquivo").textContent = `${idx + 1}/${dados.itens.length} — ${item.arquivo} — ${item.estado}`;
  $("pdf").src = "about:blank";
  setTimeout(() => { $("pdf").src = arquivoUrl(item.pdf_visualizacao); }, 30);
  $("capa").src = item.capa ? arquivoUrl(item.capa) : "";
  $("capa").style.display = item.capa ? "block" : "none";
  $("capaUrl").value = "";
  $("capaArquivo").value = "";
  document.querySelector(".corpo-revisao").scrollTop = 0;
  for (const c of campos) $(c === "titulo" ? "tituloCampo" : c).value = item.campos[c] || "";
  ultimaConsultaIsbn = null;
  $("fontesIsbn").textContent = "";
  lista("conflitos", item.conflitos.map(esc), "sem conflito registrado");
  lista("ausencias", item.ausencias.map(a => `<b>${esc(a.rotulo)}</b><br>${esc((a.causas||[]).join(" | "))}<br><span class="meta">${esc(a.sugestao)}</span>`), "sem ausência obrigatória");
  const cm = item.classificacao_material || {};
  const sinais = (cm.sinais || []).map(s => `<span class="tag">${esc(s.tipo)}: ${esc(s.sinal)}</span>`).join("");
  const contras = (cm.contradicoes || []).map(c => `<div class="erro">${esc(c)}</div>`).join("");
  $("classificacao").innerHTML = `<div><b>${esc(cm.tipo_atual || "")}</b> → ${esc(cm.fila_provavel || "")}</div><div class="meta">${esc(cm.orientacao || "")}</div>${sinais}${contras}`;
  const bi = item.busca_isbn || {};
  const validos = (bi.validos || []).map(x => `<span class="tag">p.${x.pagina || "?"}: ${esc(x.isbn)} <button class="mini" onclick="usarValor('isbn','${esc(x.isbn)}')">usar</button> <button class="mini sec" onclick="irPagina(${Number(x.pagina)||1})">abrir p.</button></span>`);
  const suspeitos = (bi.suspeitos || []).map(x => `<div class="item erro">p.${x.pagina}: ${esc(x.valor)} <button class="mini sec" onclick="irPagina(${Number(x.pagina)||1})">abrir página</button><br><span class="meta">correções possíveis: ${esc((x.correcoes_um_digito||[]).map(c=>c.isbn).join(", ") || "nenhuma")}</span></div>`);
  $("buscaIsbn").innerHTML = `<div class="meta">${esc(bi.motivo || "")}</div>${validos.join("")}${suspeitos.join("")}`;
  lista("paginas", item.paginas_sugeridas.map(p => `<b>p.${p.pagina} — ${esc(p.motivo)}</b> <button class="mini sec" onclick="irPagina(${Number(p.pagina)||1})">abrir página</button><pre>${esc(p.trecho)}</pre>`), "sem página sugerida");
  lista("rejeitadas", item.fontes_rejeitadas.map(r => `<b>${esc(r.fonte)}</b>: ${esc(r.motivo || r.razao || "")}`), "sem rejeição registrada");
  $("salvo").textContent = "";
  $("salvoTopo").textContent = "";
  sujo = false;
}
async function salvar(aprovado, avancar=false) {
  const item = atual();
  const payload = {arquivo: item.arquivo, aprovado, campos: {}, fonte: $("fonte").value, ruido_titulo: [], ruido_autor: [], confirmacao_soberana: false, motivo_confirmacao: ""};
  for (const c of campos) payload.campos[c] = $(c === "titulo" ? "tituloCampo" : c).value;
  if ($("ruidoTitulo").value.trim()) payload.ruido_titulo.push($("ruidoTitulo").value.trim());
  if ($("ruidoAutor").value.trim()) payload.ruido_autor.push($("ruidoAutor").value.trim());
  $("salvo").textContent = "gravando…";
  $("salvoTopo").textContent = "gravando…";
  const resp = await fetch("/api/gravar", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)});
  const out = await resp.json();
  $("salvo").innerHTML = resp.ok ? `<span class="ok">gravado em ${esc(out.revisao)}</span>` : `<span class="erro">${esc(out.erro || "erro")}</span>`;
  $("salvoTopo").innerHTML = $("salvo").innerHTML;
  if (resp.ok) sujo = false;
  if (resp.ok && aprovado) removerItemAtualDaRevisao();
  else if (resp.ok && avancar) proximo();
}
async function confirmarMesmoComDivergencia() {
  const motivo = prompt("Explique rapidamente por que sua decisão deve prevalecer sobre as divergências:", "operador conferiu visualmente o PDF e confirmou esta edição");
  if (motivo === null) return;
  const item = atual();
  const payload = {arquivo: item.arquivo, aprovado: true, campos: {}, fonte: `decisão soberana do operador — ${motivo || "conferência visual"}`, ruido_titulo: [], ruido_autor: [], confirmacao_soberana: true, motivo_confirmacao: motivo || "conferência visual"};
  for (const c of campos) payload.campos[c] = $(c === "titulo" ? "tituloCampo" : c).value;
  if ($("ruidoTitulo").value.trim()) payload.ruido_titulo.push($("ruidoTitulo").value.trim());
  if ($("ruidoAutor").value.trim()) payload.ruido_autor.push($("ruidoAutor").value.trim());
  $("salvo").textContent = "gravando confirmação soberana…";
  $("salvoTopo").textContent = "gravando confirmação soberana…";
  const resp = await fetch("/api/gravar", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)});
  const out = await resp.json();
  $("salvo").innerHTML = resp.ok ? `<span class="ok">decisão soberana registrada em ${esc(out.revisao)}</span>` : `<span class="erro">${esc(out.erro || "erro")}</span>`;
  $("salvoTopo").innerHTML = $("salvo").innerHTML;
  if (resp.ok) {
    sujo = false;
    removerItemAtualDaRevisao();
  }
}
async function reprocessarAtual() {
  const item = atual();
  if (!item) return;
  if (sujo && !confirm("Há alterações não salvas nesta ficha. Reprocessar agora pode substituir os campos visíveis. Continuar?")) {
    return;
  }
  $("salvo").textContent = "reprocessando este item…";
  $("salvoTopo").textContent = "reprocessando este item…";
  const resp = await fetch("/api/reprocessar", {
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({arquivo:item.arquivo})
  });
  const out = await resp.json();
  if (!resp.ok) {
    $("salvo").innerHTML = `<span class="erro">${esc(out.erro || "erro ao reprocessar")}</span>`;
    $("salvoTopo").innerHTML = $("salvo").innerHTML;
    return;
  }
  const resumo = out.resumo || {};
  $("salvo").innerHTML = `<span class="ok">reprocessado: prontos=${esc(resumo.prontos || 0)}, revisão=${esc(resumo.revisao || 0)}, documentos=${esc(resumo.documentos || 0)}, acadêmicos=${esc(resumo.academicos || 0)}</span>`;
  $("salvoTopo").innerHTML = $("salvo").innerHTML;
  sujo = false;
  await recarregar();
}
window.addEventListener("load", () => {
  for (const c of campos) {
    const el = $(c === "titulo" ? "tituloCampo" : c);
    if (el) el.addEventListener("input", marcarSujo);
  }
});
recarregar();
</script>
</body>
</html>
"""


class ServidorRevisao(BaseHTTPRequestHandler):
    raiz = pathlib.Path(".")
    limite = 0
    voltar_url = ""

    def _json(self, dados, status=200):
        bruto = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(bruto)))
        self.end_headers()
        self.wfile.write(bruto)

    def _html(self):
        html = HTML.replace("__VOLTAR_URL__", self.voltar_url)
        bruto = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(bruto)))
        self.end_headers()
        self.wfile.write(bruto)

    def _arquivo(self):
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        rel = qs.get("rel", [""])[0]
        alvo = (self.raiz / rel).resolve()
        raiz = self.raiz.resolve()
        if alvo != raiz and raiz not in alvo.parents:
            self.send_error(403)
            return
        if not alvo.is_file():
            self.send_error(404)
            return
        tipo = mimetypes.guess_type(str(alvo))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(alvo.stat().st_size))
        self.end_headers()
        with alvo.open("rb") as f:
            while True:
                bloco = f.read(1024 * 1024)
                if not bloco:
                    break
                self.wfile.write(bloco)

    def do_GET(self):
        caminho = urllib.parse.urlparse(self.path).path
        if caminho == "/":
            self._html()
        elif caminho == "/api/pacotes":
            self._json(local.pacotes_revisao(
                self.raiz, limite=self.limite, imprimir=False))
        elif caminho == "/arquivo":
            self._arquivo()
        else:
            self.send_error(404)

    def do_POST(self):
        caminho = urllib.parse.urlparse(self.path).path
        if caminho not in {
                "/api/gravar", "/api/consultar-isbn", "/api/capa-url",
                "/api/capa-arquivo", "/api/reprocessar", "/api/encerrar"}:
            self.send_error(404)
            return
        try:
            if caminho == "/api/encerrar":
                self._json({"ok": True, "mensagem": "bancada encerrada"})
                threading.Thread(
                    target=self.server.shutdown, daemon=True).start()
                return
            tamanho = int(self.headers.get("Content-Length", "0"))
            dados = json.loads(self.rfile.read(tamanho).decode("utf-8"))
            if caminho == "/api/consultar-isbn":
                resultado = local.consultar_metadados_isbn_revisao(
                    self.raiz,
                    dados.get("isbn", ""),
                    arquivo=dados.get("arquivo", ""),
                    imprimir=False,
                )
            elif caminho == "/api/capa-url":
                resultado = local.substituir_capa_revisao(
                    self.raiz,
                    dados.get("arquivo", ""),
                    dados.get("url", ""),
                    imprimir=False,
                )
            elif caminho == "/api/capa-arquivo":
                resultado = local.substituir_capa_arquivo_revisao(
                    self.raiz,
                    dados.get("arquivo", ""),
                    dados.get("nome", ""),
                    dados.get("conteudo_base64", ""),
                    imprimir=False,
                )
            elif caminho == "/api/reprocessar":
                arquivo = dados.get("arquivo", "")
                if not arquivo:
                    raise RuntimeError("nenhum item ativo para reprocessar")
                resultado = {
                    "ok": True,
                    "resumo": local.reprocessar_revisao(
                        self.raiz, usar_api=True, arquivos=[arquivo]),
                }
            else:
                resultado = local.gravar_decisao_revisao(
                    self.raiz,
                    dados.get("arquivo", ""),
                    campos=dados.get("campos", {}),
                    aprovado=bool(dados.get("aprovado")),
                    fontes=[dados.get("fonte") or "revisão visual"],
                    ruidos_titulo=dados.get("ruido_titulo", []),
                    ruidos_autor=dados.get("ruido_autor", []),
                    confirmacao_soberana=bool(
                        dados.get("confirmacao_soberana")),
                    motivo_confirmacao=dados.get("motivo_confirmacao", ""),
                    imprimir=False,
                )
            self._json(resultado)
        except Exception as exc:
            self._json({"erro": str(exc)}, status=400)

    def log_message(self, formato, *args):
        return


def porta_livre(preferida):
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", preferida))
            return s.getsockname()[1]
        except OSError:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


def main():
    ap = argparse.ArgumentParser(description="Bancada local de revisão visual")
    ap.add_argument("--raiz", required=True)
    ap.add_argument("--porta", type=int, default=8765)
    ap.add_argument("--limite", type=int, default=0,
                    help="quantidade máxima de itens; 0 mostra todos")
    ap.add_argument("--voltar-url", default="",
                    help="URL do Biblio Preparador para retorno ao concluir")
    ap.add_argument("--abrir", action="store_true",
                    help="abre a bancada no navegador padrão")
    args = ap.parse_args()
    ServidorRevisao.raiz = pathlib.Path(args.raiz).expanduser().resolve()
    ServidorRevisao.limite = args.limite
    ServidorRevisao.voltar_url = args.voltar_url
    porta = porta_livre(args.porta)
    servidor = ThreadingHTTPServer(("127.0.0.1", porta), ServidorRevisao)
    url = f"http://127.0.0.1:{porta}/"
    print(f"Bancada de revisão aberta em: {url}", flush=True)
    if args.abrir:
        webbrowser.open(url)
    print("Use Ctrl+C para encerrar.", flush=True)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nBancada encerrada.")
        return 0
    finally:
        servidor.server_close()
    print("Bancada encerrada. Voltando ao menu principal.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
