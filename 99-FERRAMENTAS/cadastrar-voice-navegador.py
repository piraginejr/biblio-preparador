#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
============================================================================
 CADASTRO DA REVISTA VOICE - VIA NAVEGADOR (Playwright)
============================================================================

 Por que esta versao existe
 --------------------------
 O envio direto por HTTP (cadastrar-voice.py) grava o registro mas nunca
 grava autor, assunto e lingua - e frequentemente devolve erro 500. Foram
 testadas e descartadas seis hipoteses para isso.

 Pelo navegador, o mesmo cadastro funciona: quatro edicoes de 1975 foram
 cadastradas assim, completas. Este script entao para de tentar adivinhar
 o servidor e repete no navegador exatamente a sequencia que da certo:

     1. abre /arquivos
     2. escolhe "Artigo de Revista"
     3. anexa o PDF e a capa
     4. preenche os campos de texto
     5. clica em Salvar
     6. confere a resposta

 E mais lento que um POST (uns 15-25 s por edicao), mas e o caminho
 comprovado. 200 edicoes levam cerca de uma hora.

 INSTALACAO (uma vez so)
 -----------------------
     pip3 install playwright
     python3 -m playwright install chromium

 USO
 ---
     python3 cadastrar-voice-navegador.py                  # simula
     python3 cadastrar-voice-navegador.py --executar --limite 1
     python3 cadastrar-voice-navegador.py --executar --limite 3
     python3 cadastrar-voice-navegador.py --executar
     python3 cadastrar-voice-navegador.py --executar --visivel   # ver acontecendo

 Compartilha o mesmo _cadastro-status.json do outro script, entao o que
 ja foi cadastrado nao e refeito.
============================================================================
"""

import argparse, getpass, json, os, re, subprocess, sys, time
from datetime import datetime

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit("Falta o Playwright.  Rode:\n"
             "   pip3 install playwright\n"
             "   python3 -m playwright install chromium")

# ---------------------------------------------------------------------------
# CONFIGURACAO
# ---------------------------------------------------------------------------

PASTA = os.path.expanduser(
    "~/Library/CloudStorage/Dropbox/arquivos temporários/revista/01-EDICOES-PDF")

BASE      = "https://biblio.pibcuritiba.org.br"
URL_LOGIN = f"{BASE}/users/login"
URL_ADD   = f"{BASE}/arquivos"

CAMPO_USER = "data[User][usernames]"
CAMPO_PASS = "data[User][password]"

TIPO_DOC   = "3"        # Artigo de Revista
RESTRICAO  = "0"        # Publico
ASSUNTO    = "Pentecostalismo"
# Entidade coletiva: SO A SIGLA. O nome por extenso estoura o campo de
# autor, e o sistema acaba truncando de forma imprevisivel - foi assim
# que surgiu o "GOSPEL, Full Business".
# O nome completo fica registrado na nota e no resumo de cada edicao.
ENTIDADE   = "FGBMFI"
DPI_CAPA   = 100
MIN_OCR    = 200
PAUSA      = 2

SUB_CAPAS  = "_capas"
ARQ_ESTADO = "_cadastro-status.json"
ARQ_LOG    = "_cadastro-log.txt"

# FORMATO DO NOME DE AUTOR - regra do proprio sistema, exibida no modal:
#   1) o sobrenome vai em MAIUSCULAS
#   2) virgula (ou ponto e virgula) separando
#   3) o primeiro nome depois
# Ex.: "JENSEN, Jerry"  -  igual ao padrao ja usado no acervo
#      (FULLER, Daniel, P. / BECKER, Gisela / JENSEN, Irving L.)
#
# Sem esse formato o botao Salvar do modal nao dispara requisicao alguma:
# a validacao barra em silencio. E um nome sem virgula e reescrito pelo
# sistema - "Full Gospel Business Men's Fellowship International" virou
# "GOSPEL, Full Business", perdendo o resto.
# Grafia EXATA como esta no banco (conferido no autocomplete). A regra do
# "sobrenome em maiusculas" vale na hora de CRIAR pelo modal; no campo da
# ficha o que importa e casar com o registro existente. As 12 primeiras
# edicoes entraram com esta grafia.
EDITORES = [
    (1953, 1961, "Nickel, Thomas R."),
    (1963, 1967, "Jensen, Jerry"),
    (1975, 1975, "Becker, Raymond W."),
]

MESES_EN = {"january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
            "july":7,"august":8,"september":9,"october":10,"november":11,
            "december":12}
MESES_PT = {1:"janeiro",2:"fevereiro",3:"março",4:"abril",5:"maio",6:"junho",
            7:"julho",8:"agosto",9:"setembro",10:"outubro",11:"novembro",
            12:"dezembro"}
MESES_EN_NOME = {1:"January",2:"February",3:"March",4:"April",5:"May",6:"June",
                 7:"July",8:"August",9:"September",10:"October",11:"November",
                 12:"December"}

V,A,R,AZ,N,F = ('\033[0;32m','\033[0;33m','\033[0;31m','\033[0;34m','\033[1m','\033[0m')
ok   = lambda m: print(f"{V}  ok  {F}{m}")
warn = lambda m: print(f"{A}  !!  {F}{m}")
err  = lambda m: print(f"{R}  xx  {F}{m}")
info = lambda m: print(f"      {m}")


def log(pasta, msg):
    with open(os.path.join(pasta, ARQ_LOG), "a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  [navegador] {msg}\n")


# ---------------------------------------------------------------------------
# METADADOS
# ---------------------------------------------------------------------------

def editor_do_ano(ano):
    for ini, fim, nome in EDITORES:
        if ini <= ano <= fim:
            return nome
    return None


def interpretar_nome(nome):
    base = os.path.splitext(nome)[0]
    m = re.search(r'(\d+)\.(\d+)\s*\(([A-Za-z]+)(?:\s*[-/]\s*([A-Za-z]+))?\s+(\d{4})\)', base)
    if m:
        vol, fasc, m1, m2, ano = m.groups()
        meses = [x for x in (MESES_EN.get(m1.lower()),
                             MESES_EN.get(m2.lower()) if m2 else None) if x]
        if meses:
            return {"ano": int(ano), "meses": meses,
                    "volume": int(vol), "fasciculo": int(fasc)}
    m = re.search(r'(\d{4})-(\d{2}).*?v(\d+).*?n(\d+)', base, re.I)
    if m:
        ano, mes, vol, fasc = m.groups()
        return {"ano": int(ano), "meses": [int(mes)],
                "volume": int(vol), "fasciculo": int(fasc)}
    m = re.search(r'(\d{4})-(\d{2})(?:-(\d{2}))?(?!\d)', base)
    if m:
        ano, m1, m2 = m.groups()
        meses = [x for x in (int(m1), int(m2) if m2 else None) if x and 1 <= x <= 12]
        if meses:
            return {"ano": int(ano), "meses": meses, "volume": None, "fasciculo": None}
    m = re.search(r'(\d{4})', base)
    if m and re.search(r'global|convention|especial', base, re.I):
        return {"ano": int(m.group(1)), "meses": [], "volume": None, "fasciculo": None}
    return None


def montar(dados, n_paginas):
    ano   = dados["ano"]
    meses = dados["meses"]
    vol   = dados["volume"] or (ano - 1952)
    estimado = dados["volume"] is None
    editor = editor_do_ano(ano)

    if meses:
        mes_en = "/".join(MESES_EN_NOME[m] for m in meses)
        mes_pt = "/".join(MESES_PT[m] for m in meses)
        codigo = f"VOICE-{ano}-" + "-".join(f"{m:02d}" for m in meses)
        data_c = f"{meses[0]:02d}/{ano}"
        titulo = f"Voice, {mes_en} {ano}"
    else:
        mes_pt = "edição especial"
        codigo = f"VOICE-{ano}-especial"
        data_c = str(ano)
        titulo = f"Voice, {ano} (edição especial)"

    nota = [f"v.{vol}" + (" (estimado)" if estimado else ""), f"{mes_pt}/{ano}"]
    if dados["fasciculo"]:
        nota.append(f"n.{dados['fasciculo']}")
    if n_paginas:
        nota.append(f"{n_paginas} p.")
    nota.append("Digitalização da FGBMFI; camada de texto adicionada por OCR (Tesseract).")
    if editor:
        nota.append(f"Editor da época: {editor}.")

    return codigo, {
        "titulo":           titulo,
        "subTitulo":        "Full Gospel Business Men's Voice",
        "tituloPublicacao": "Full Gospel Business Men's Voice",
        "tipoAssunto1":     ASSUNTO,
        "nmAutor0":         editor or ENTIDADE,
        "nmLingua":         "Inglês",
        "idioma":           "eng",
        "volume":           str(vol),
        "data":             data_c,
        "nPaginas":         str(n_paginas or ""),
        "editora":          ENTIDADE,
        "lugar":            "Estados Unidos",
        "direitos":         f"Copyright {ENTIDADE}",
        "extra":            f"Tombo: {codigo}",
        "nota":             " ".join(nota),
        "palavrasChave":    "Pentecostalismo; Movimento carismático; "
                            "Periódicos religiosos; FGBMFI; Demos Shakarian",
        "url":              ("https://digitalshowcase.oru.edu/voice/" if ano <= 1961
                             else "https://www.fgbmfi.org/resources"),
        "abstract":         (f"Edição de {mes_pt} de {ano} da revista Voice, publicação "
                             "oficial da Full Gospel Business Men's Fellowship "
                             "International, fundada em 1952 por Demos Shakarian. Reúne "
                             "testemunhos de empresários e profissionais ligados ao "
                             "movimento carismático."),
    }


# ---------------------------------------------------------------------------
# ARQUIVOS
# ---------------------------------------------------------------------------

def info_pdf(caminho):
    pg = 0
    try:
        s = subprocess.run(["pdfinfo", caminho], capture_output=True,
                           text=True, timeout=30).stdout
        m = re.search(r"Pages:\s+(\d+)", s)
        if m:
            pg = int(m.group(1))
    except Exception:
        pass
    ch = 0
    try:
        ch = len(subprocess.run(["pdftotext", "-l", "5", caminho, "-"],
                                capture_output=True, text=True,
                                timeout=60).stdout.strip())
    except Exception:
        pass
    return pg, ch


def gerar_capa(pdf, pasta_capas):
    os.makedirs(pasta_capas, exist_ok=True)
    base = os.path.splitext(os.path.basename(pdf))[0]
    final = os.path.join(pasta_capas, base + ".jpg")
    if os.path.exists(final) and os.path.getsize(final) > 1000:
        return final
    try:
        subprocess.run(["pdftoppm", "-f", "1", "-l", "1", "-r", str(DPI_CAPA),
                        "-jpeg", "-singlefile", pdf,
                        os.path.join(pasta_capas, base)],
                       capture_output=True, timeout=120, check=True)
        return final if os.path.exists(final) else None
    except Exception:
        return None


def varrer(pasta):
    achados = []
    for raiz, dirs, arqs in os.walk(pasta):
        dirs[:] = sorted(d for d in dirs
                         if not d.startswith("_") and not d.startswith("."))
        for a in sorted(arqs):
            if a.lower().endswith(".pdf") and not a.startswith("."):
                achados.append(os.path.join(raiz, a))
    return achados


def carregar_estado(pasta):
    p = os.path.join(pasta, ARQ_ESTADO)
    if os.path.exists(p):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            warn("estado corrompido - comecando novo")
    return {}


def salvar_estado(pasta, estado):
    p = os.path.join(pasta, ARQ_ESTADO)
    json.dump(estado, open(p + ".tmp", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    os.replace(p + ".tmp", p)


# ---------------------------------------------------------------------------
# NAVEGADOR  --  aqui esta a sequencia que funciona
# ---------------------------------------------------------------------------

def entrar(page, usuario, senha):
    page.goto(URL_LOGIN, wait_until="domcontentloaded")
    page.fill(f'[name="{CAMPO_USER}"]', usuario)
    page.fill(f'[name="{CAMPO_PASS}"]', senha)
    page.click('button[type=submit], input[type=submit]')
    page.wait_for_load_state("domcontentloaded")
    return "password" not in page.content().lower() or "logout" in page.content().lower()


def existe_autor(page, nome):
    """Devolve True se o autor ja esta no banco.

    IMPORTANTE: a consulta usa apenas o SOBRENOME (o trecho antes da
    virgula), nao o nome completo. O endpoint nao casa com a string
    inteira - buscar "NICKEL, Thomas R." devolve vazio, enquanto
    "NICKEL" devolve {"11299": "Nickel, Thomas R."}.
    Foi por isso que o script passou a considerar novos autores que ja
    existiam, reabrindo o modal a toa.

    A comparacao final e feita com o nome completo, ignorando maiusculas.
    """
    termo = nome.split(",")[0].strip() or nome.strip()
    if not termo:
        return False
    try:
        r = page.evaluate("""async (t) => {
            const resp = await fetch('/autores/autoCompleteAutor?term=' +
                                     encodeURIComponent(t),
                                     {credentials: 'same-origin'});
            const txt = await resp.text();
            try { return JSON.parse(txt); } catch (e) { return {}; }
        }""", termo)
        if not isinstance(r, dict):
            return False
        alvo = " ".join(nome.split()).strip().lower()
        for v in r.values():
            if " ".join(str(v).split()).strip().lower() == alvo:
                return True
        return False
    except Exception:
        return False


def criar_autor(page, nome):
    """Cria o autor pelo modal da propria pagina.

    Estrutura mapeada em 27/07/2026:
        gatilho  abreModalAutor()   ("Autor nao encontrado? clique aqui")
        modal    #modalAddAutor
        campo    #AutorNome   (data[Autor][nome])
        salvar   #idSalvarAutor
        destino  POST /Autores/add

    Necessario para catalogar em escala: com milhares de titulos nao da
    para pre-cadastrar cada autor a mao.
    """
    try:
        page.evaluate("() => { if (typeof abreModalAutor === 'function') abreModalAutor(); }")
        page.wait_for_timeout(900)

        campo = page.locator("#AutorNome")
        if not campo.count():
            return False, "modal de autor nao abriu"

        page.evaluate("""(n) => {
            const e = document.getElementById('AutorNome');
            e.value = n;
            e.dispatchEvent(new Event('input',  {bubbles: true}));
            e.dispatchEvent(new Event('change', {bubbles: true}));
        }""", nome)
        page.wait_for_timeout(300)

        # Clique real do Playwright, nao .click() por JavaScript.
        # O botao so dispara se o nome estiver no formato SOBRENOME, Nome.
        # O envio e por AJAX para /autores/addAutorCadastro - nao ha submit
        # de formulario, entao nao adianta esperar navegacao.
        page.locator("#idSalvarAutor").click(timeout=15000)
        # espera a requisicao concluir antes de tocar no modal - fechar
        # cedo demais cancelava o salvamento
        page.wait_for_timeout(4000)

        # ATENCAO - ha DOIS "Salvar" nesta tela, e eles nao se confundem:
        #
        #   Salvar do MODAL  (#idSalvarAutor)  -> grava so o AUTOR
        #   Salvar da FICHA  (#btnPesquisar)   -> grava a REVISTA, no fim
        #
        # Depois do Salvar do modal aparece um AVISO DE CONFIRMACAO. E nele
        # que se clica em OK. So entao o parentese do autor se encerra e o
        # preenchimento da ficha continua. O Salvar da ficha vem bem depois,
        # na etapa 6, com tudo ja preenchido.
        #
        # Alertas nativos sao aceitos pelo handler registrado em main();
        # aqui tratamos os avisos em HTML (SweetAlert, modal bootstrap...).
        # O aviso e um SweetAlert 1 - "div.swal-modal" com botao ".swal-button"
        # (verificado no proprio sistema em 27/07/2026). NAO e o swal2, cujo
        # seletor seria .swal2-confirm.
        #
        # O clique acontece SOMENTE dentro desse aviso. Procurar "qualquer
        # botao OK da pagina" atingia outros elementos e desmontava a ficha
        # inteira antes de completar o cadastro.
        # CLIQUE DE VERDADE, pelo Playwright. O SweetAlert ignora o .click()
        # disparado por JavaScript - verificado no proprio sistema: o aviso
        # continuava na tela depois do clique programatico. O Playwright
        # envia um evento real do navegador, que a biblioteca aceita.
        aviso = ""
        for _ in range(4):
            alerta = page.locator(".swal-modal, .sweet-alert")
            if not alerta.count() or not alerta.first.is_visible():
                break
            try:
                aviso = alerta.first.inner_text().replace("\n", " ").strip()
            except Exception:
                pass
            botao = page.locator(".swal-button--confirm, .swal-button, .sweet-alert button.confirm")
            if not botao.count():
                break
            botao.first.click(timeout=10000)
            page.wait_for_timeout(900)

        page.wait_for_timeout(600)
        if aviso:
            info(f"aviso: {aviso[:110]}")

        # Fecha a janela do autor pelo proprio botao Fechar - clique real.
        # A ficha por baixo precisa continuar preenchida, entao nada de
        # recarregar a pagina.
        # TERCEIRO clique - e obrigatorio. Observado na tela: o OK do alerta
        # dispensa apenas o aviso; a janela "Adicione um Autor" continua
        # aberta, com o campo preenchido. Sem fechar aqui, o backdrop segue
        # cobrindo a ficha e nada mais pode ser clicado.
        for tentativa in range(3):
            aberto = page.evaluate("""() => {
                const m = document.getElementById('modalAddAutor');
                return !!(m && (m.classList.contains('show') ||
                                m.style.display === 'block'));
            }""")
            if not aberto:
                break
            alvos = ["#modalAddAutor button.btn-close",
                     "#modalAddAutor [data-bs-dismiss=modal]",
                     "#modalAddAutor [data-dismiss=modal]"]
            for sel in alvos:
                loc = page.locator(sel)
                if loc.count():
                    try:
                        loc.first.click(timeout=8000)
                        break
                    except Exception:
                        continue
            page.wait_for_timeout(1000)

        # Se algo ficou para tras, limpa: o backdrop cobre a tela e impede
        # qualquer clique posterior, inclusive o Salvar da ficha.
        page.evaluate("""() => {
            const m = document.getElementById('modalAddAutor');
            if (m && (m.classList.contains('show') || m.style.display === 'block')) {
                m.classList.remove('show');
                m.style.display = 'none';
                m.setAttribute('aria-hidden', 'true');
            }
            document.querySelectorAll('.modal-backdrop').forEach(b => b.remove());
            document.body.classList.remove('modal-open');
            document.body.style.overflow = '';
            document.body.style.paddingRight = '';
        }""")
        page.wait_for_timeout(800)
        return True, "autor criado"
    except Exception as e:
        return False, f"erro ao criar autor: {str(e)[:100]}"


def garantir_autor(page, nome, verboso=False):
    """Cria o autor se ainda nao existir. Devolve (ok, mensagem)."""
    if existe_autor(page, nome):
        if verboso:
            info(f"autor ja existe: {nome}")
        return True, "ja existia"

    warn(f"autor novo: {nome} - criando")
    ok_, msg = criar_autor(page, nome)
    if not ok_:
        return False, msg

    # confere que entrou mesmo
    page.wait_for_timeout(800)
    if existe_autor(page, nome):
        ok(f"autor criado: {nome}")
        return True, "criado"
    return False, "criei o autor mas ele nao aparece na busca"


def preparar_autores(page, fila, verboso=False):
    """Garante que todos os autores da fila existem, ANTES de cadastrar nada.

    Separar as duas operacoes e essencial: criar autor abre um modal, e se
    isso acontecer no meio do preenchimento a ficha fica incompleta e a
    mensagem de sucesso da criacao do autor se confunde com a do cadastro.

    Roda uma vez por nome distinto - com milhares de titulos, isso tambem
    evita repetir a consulta a cada item.

    LIMITACAO CONHECIDA (a resolver antes de usar com livros)
    ---------------------------------------------------------
    Serve bem para a Voice, que tem 3 ou 4 autores. Nao escala para um
    acervo de livros com milhares de autores distintos:

      - a etapa vira uma varredura longa antes do primeiro cadastro
      - se um autor falhar, o lote inteiro para
      - nao ha memoria entre execucoes: reconsulta tudo a cada rodada

    Caminho para a versao de livros:
      - cache local dos autores ja verificados (arquivo proprio)
      - criar o autor sob demanda, mas em uma ABA SEPARADA, para nao
        tocar no formulario em preenchimento - foi a mistura das duas
        operacoes na mesma pagina que quebrou o fluxo em 27/07/2026
      - falha de um autor deve pular so aquele item, nao abortar o lote
    """
    nomes = []
    for _, _, _, _, campos in fila:
        a = campos.get("nmAutor0", "").strip()
        if a and a not in nomes:
            nomes.append(a)

    if not nomes:
        return True, []

    print(f"\n{N}  Conferindo {len(nomes)} autor(es) antes de comecar{F}\n")
    problemas = []
    for nome in nomes:
        page.goto(URL_ADD, wait_until="domcontentloaded")
        page.wait_for_timeout(800)
        if existe_autor(page, nome):
            ok(f"ja existe: {nome[:56]}")
            continue
        warn(f"criando: {nome[:56]}")
        criado, msg = criar_autor(page, nome)
        page.wait_for_timeout(1000)
        if criado and existe_autor(page, nome):
            ok(f"criado: {nome[:56]}")
        else:
            err(f"nao consegui criar: {nome[:50]}  ({msg})")
            problemas.append(nome)
    print()
    return len(problemas) == 0, problemas


def cadastrar(page, campos, pdf, capa, verboso=False):
    """Repete no navegador os passos do cadastro manual bem-sucedido.

    IMPORTANTE: os campos de texto sao preenchidos por JavaScript, definindo
    .value e disparando input/change - exatamente como nos testes que deram
    certo. Digitar com page.fill() aciona o autocomplete do jQuery UI, que
    pode limpar o campo ao perder o foco.
    """

    # 1. pagina de cadastro, sempre limpa
    page.goto(URL_ADD, wait_until="domcontentloaded")
    page.wait_for_timeout(1200)

    # 2. tipo de documento - revela os campos
    page.select_option("#idTipoDoc", TIPO_DOC)
    page.wait_for_timeout(1500)

    # 2b. AUTOR - apenas escrito no campo, junto com os demais.
    # NAO consultamos mais se o autor existe, e NAO abrimos o modal.
    # Os quatro autores da colecao ja estao no banco:
    #   Nickel, Thomas R. | Jensen, Jerry | Becker, Raymond W. | FGBMFI
    # O nome e simplesmente escrito no campo, junto com os demais - que e
    # exatamente como as 12 primeiras edicoes foram cadastradas.
    #
    # Para os LIVROS, onde autor novo sera a regra, o modal precisara ser
    # resolvido. Fica registrado o que se sabe dele:
    #   - a consulta /autores/autoCompleteAutor exige o cabecalho
    #     X-Requested-With: XMLHttpRequest, senao devolve HTML no lugar
    #     de JSON (foi o que quebrou a deteccao aqui)
    #   - o modal usa SweetAlert 1 e so aceita clique real, do Playwright
    #   - sao TRES cliques: Salvar do modal, OK do aviso, Fechar do modal
    #   - o que continua falhando e retomar o preenchimento depois disso

    # 3. arquivos primeiro (sao obrigatorios; sem eles a validacao do
    #    navegador barra o envio silenciosamente)
    page.set_input_files('[name="data[Arquivos][docDigital]"]', pdf)
    page.set_input_files('[name="data[Arquivos][capa]"]', capa)
    page.wait_for_timeout(600)

    # 4. campos de texto, via JS
    page.evaluate("""(dados) => {
        for (const [k, v] of Object.entries(dados)) {
            const e = document.querySelector('[name="data[Arquivos][' + k + ']"]');
            if (!e || !v) continue;
            e.value = v;
            e.dispatchEvent(new Event('input',  {bubbles: true}));
            e.dispatchEvent(new Event('change', {bubbles: true}));
        }
        const r = document.querySelector('[name="data[Arquivos][nmRestricao]"]');
        if (r) { r.value = '%s'; r.dispatchEvent(new Event('change', {bubbles: true})); }
    }""" % RESTRICAO, campos)

    page.wait_for_timeout(600)

    # 4b. FECHAR as listas de autocomplete. Varios campos (autor, lingua,
    #     local de publicacao, assunto) usam jQuery UI Autocomplete. Ao
    #     receberem valor, abrem a lista de sugestoes, que fica sobreposta
    #     ao botao Salvar e impede o clique.
    page.evaluate("""() => {
        // fecha pela API do widget, quando disponivel
        if (window.jQuery) {
            jQuery('.ui-autocomplete-input').each(function () {
                const inst = jQuery(this).data('ui-autocomplete')
                          || jQuery(this).data('autocomplete');
                if (inst && inst.close) { try { inst.close(); } catch (e) {} }
            });
            jQuery('.ui-autocomplete').hide();
        }
        // e esconde qualquer menu remanescente
        document.querySelectorAll('.ui-autocomplete, .ui-menu')
                .forEach(el => { el.style.display = 'none'; });
        // NAO chamar blur() nem Escape: a pagina reage limpando campos.
    }""")
    page.wait_for_timeout(400)

    # 4c. Reaplica os valores. Fechar os menus pode disparar handlers da
    #     pagina que limpam campos - ja aconteceu com o titulo.
    page.evaluate("""(dados) => {
        for (const [k, v] of Object.entries(dados)) {
            const e = document.querySelector('[name="data[Arquivos][' + k + ']"]');
            if (!e || !v) continue;
            if (e.value !== v) {
                e.value = v;
                e.dispatchEvent(new Event('input',  {bubbles: true}));
                e.dispatchEvent(new Event('change', {bubbles: true}));
            }
        }
    }""", campos)
    page.wait_for_timeout(300)

    # 5. confere o que ficou vazio antes de tentar salvar
    faltando = page.evaluate("""() => {
        return [...document.querySelectorAll('[required]')]
          .filter(e => e.offsetParent !== null &&
                       !e.value && !(e.files && e.files.length))
          .map(e => (e.name||'').replace('data[Arquivos][','').replace(/\\]$/,''));
    }""")
    if faltando:
        return "incompleto", "campos obrigatorios vazios: " + ", ".join(faltando)

    if verboso:
        preenchidos = page.evaluate("""() => {
            const o = [];
            document.querySelectorAll('input,select,textarea').forEach(e => {
                if (e.name && e.value && e.type !== 'hidden')
                    o.push(e.name.replace('data[Arquivos][','').replace(/\\]$/,''));
            });
            return o;
        }""")
        info(f"preenchidos: {', '.join(preenchidos)}")

    # 6. salvar
    url_antes = page.url
    botao = page.locator("#btnPesquisar")
    botao.scroll_into_view_if_needed()
    page.wait_for_timeout(300)
    try:
        botao.click(timeout=15000)
    except Exception:
        # algo continua sobreposto: aciona o clique pelo proprio elemento
        page.evaluate("() => document.getElementById('btnPesquisar').click()")
    try:
        page.wait_for_load_state("networkidle", timeout=180000)
    except Exception:
        pass
    page.wait_for_timeout(2000)

    # ATENCAO: nao dá para concluir nada comparando a URL. Apos gravar, o
    # sistema volta para /arquivos com o formulario LIMPO - mesma URL de
    # antes do clique. Checar campos obrigatorios aqui gera falso positivo,
    # porque o formulario novo esta vazio por natureza.
    # O veredito vem do texto da resposta e da conferencia no acervo.

    # Captura a mensagem do popup. Ele aparece no texto da pagina - foi
    # assim que lemos "arquivo ja existe na base de dados". Fica alguns
    # segundos na tela, entao vale insistir um pouco.
    popup = ""
    for _ in range(8):
        popup = page.evaluate("""() => {
            const txt = document.body.innerText || '';
            // a mensagem costuma vir numa linha com "Atencao" ou terminada em "x"
            const linhas = txt.split('\\n').map(s => s.trim()).filter(Boolean);
            // "Buscar nao cadastrados" e item de menu, nao popup - por isso
            // as expressoes abaixo sao ancoradas em frases, nao em palavras
            // soltas como "cadastrad".
            const alvo = linhas.find(l =>
                l.length < 200 && (
                    /aten[çc][ãa]o\\s*!/i.test(l) ||
                    /(ja|já)\\s+existe\\s+na\\s+base/i.test(l) ||
                    /com\\s+sucesso/i.test(l) ||
                    /internal error/i.test(l) ||
                    /erro\\s+(ao|interno|no)/i.test(l)
                ));
            return alvo || '';
        }""")
        if popup:
            break
        page.wait_for_timeout(500)

    if popup:
        info(f"popup: {popup[:130]}")

    baixo = (popup + " " + page.inner_text("body")).lower()

    if "ja existe" in baixo or "já existe" in baixo:
        return "duplicado", popup or baixo[:200]
    if "internal error" in baixo:
        return "erro", "erro interno do servidor"
    if any(p in baixo for p in ["sucesso", "cadastrado com", "salvo com", "gravado com"]):
        return "ok", popup or "sucesso"
    if "erro" in baixo:
        return "erro", popup or baixo[:200]
    # sem mensagem clara: quem decide e a conferencia no acervo
    return "ok", popup or "(sem mensagem; sera conferido no acervo)"


def confirmar(page, titulo):
    """Confere no acervo se o registro entrou completo."""
    from urllib.parse import quote
    page.goto(f"{BASE}/arquivos/buscaAvancada?data%5BArquivos%5D%5Btitulo%5D={quote(titulo)}",
              wait_until="domcontentloaded")
    page.wait_for_timeout(800)
    t = page.inner_text("body")
    if titulo not in t:
        return None
    bloco = t[t.find(titulo):t.find(titulo) + 700]
    return {
        "autor":   not re.search(r"Autor:\s*-", bloco),
        "assunto": not re.search(r"Assunto:\s*-", bloco),
        "lingua":  not re.search(r"Língua:\s*-", bloco),
    }


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=PASTA)
    ap.add_argument("--executar", action="store_true")
    ap.add_argument("--limite", type=int, default=0)
    ap.add_argument("--visivel", action="store_true",
                    help="mostra o navegador trabalhando")
    ap.add_argument("--apenas", default="",
                    help="so processa edicoes cujo codigo contenha este texto. "
                         "Ex: --apenas 1962   ou   --apenas 1963-01")
    args = ap.parse_args()

    pasta = os.path.expanduser(args.dir)
    if not os.path.isdir(pasta):
        sys.exit(f"Pasta nao encontrada: {pasta}")

    print(f"\n{N}{AZ}  VOICE -> PIB-Biblio  (via navegador){F}")
    print(f"{AZ}  {'-'*52}{F}")
    print(f"  Pasta: {pasta}")

    if not args.executar:
        print(f"  {A}MODO SIMULACAO{F} - use --executar para cadastrar\n")

    estado = carregar_estado(pasta)
    pasta_capas = os.path.join(pasta, SUB_CAPAS)
    pdfs = varrer(pasta)
    print(f"\n  {len(pdfs)} PDFs encontrados\n")

    # o que esta pronto para subir
    fila = []
    for caminho in pdfs:
        rel = os.path.relpath(caminho, pasta)
        if estado.get(rel, {}).get("status") == "cadastrado":
            continue
        pg, ch = info_pdf(caminho)
        if ch < MIN_OCR:
            continue
        dados = interpretar_nome(os.path.basename(caminho))
        if not dados:
            continue
        capa = gerar_capa(caminho, pasta_capas)
        if not capa:
            continue
        codigo, campos = montar(dados, pg)
        if args.apenas and args.apenas.lower() not in codigo.lower():
            continue
        fila.append((rel, caminho, capa, codigo, campos))
        if args.limite and len(fila) >= args.limite:
            break

    print(f"  {len(fila)} edicao(oes) na fila desta rodada\n")
    if not fila:
        print("  Nada a fazer.\n")
        return

    if not args.executar:
        for rel, _, _, codigo, campos in fila:
            print(f"  {codigo:<22} {campos['titulo']:<30} autor: {campos['nmAutor0']}")
        print()
        return

    usuario = os.environ.get("BIBLIO_USER") or input("  Usuario: ").strip()
    senha   = os.environ.get("BIBLIO_PASS") or getpass.getpass("  Senha: ")
    print()

    feitos = falhas = duplicados = 0

    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=not args.visivel)
        page = navegador.new_page()
        page.set_default_timeout(60000)

        # Aceita alertas nativos do navegador (alert/confirm). Sem isso o
        # Playwright os descarta e o fluxo trava esperando a pagina.
        page.on("dialog", lambda d: d.accept())

        if not entrar(page, usuario, senha):
            err("nao foi possivel autenticar")
            navegador.close()
            sys.exit(1)
        ok("autenticado")
        print()

        # O autor e criado dentro da propria ficha, quando necessario -
        # ver a etapa 2b de cadastrar(). Nao ha etapa previa: com milhares
        # de titulos, varrer todos os autores antes seria lento demais e
        # um unico nome problematico pararia o lote inteiro.
        for i, (rel, pdf, capa, codigo, campos) in enumerate(fila, 1):
            print(f"{N}[{i}/{len(fila)}] {codigo}{F}  {campos['titulo']}")
            try:
                res, trecho = cadastrar(page, campos, pdf, capa,
                                        verboso=args.visivel)
            except Exception as e:
                err(f"erro no navegador: {str(e)[:160]}")
                falhas += 1
                continue

            if res == "incompleto":
                err("o formulario nao ficou completo - nao cliquei em Salvar")
                info(trecho)
                falhas += 1
                continue

            if res == "duplicado":
                warn("ja existe no sistema")
                estado[rel] = {"status": "cadastrado", "codigo": codigo,
                               "quando": datetime.now().isoformat(),
                               "observacao": "ja existia"}
                salvar_estado(pasta, estado)
                duplicados += 1
                continue

            if res == "erro":
                err("o servidor recusou")
                info(trecho[:120])
                log(pasta, f"FALHA {codigo} {rel}")
                falhas += 1
                continue

            # confere se entrou completo
            chk = confirmar(page, campos["titulo"])
            if chk is None:
                err("nao encontrei o registro no acervo depois de salvar")
                falhas += 1
                continue

            faltando = [k for k, v in chk.items() if not v]
            if faltando:
                warn(f"gravou, mas sem: {', '.join(faltando)}")
            else:
                ok("cadastrado completo (autor, assunto e lingua)")

            estado[rel] = {"status": "cadastrado", "codigo": codigo,
                           "quando": datetime.now().isoformat(),
                           "observacao": ("incompleto: falta " + ", ".join(faltando))
                                          if faltando else "completo"}
            salvar_estado(pasta, estado)
            log(pasta, f"CADASTRADO {codigo} {rel} "
                       f"{'INCOMPLETO ' + ','.join(faltando) if faltando else 'completo'}")
            feitos += 1
            time.sleep(PAUSA)

        navegador.close()

    print(f"\n{AZ}  {'-'*52}{F}")
    print(f"{N}  RESUMO{F}\n")
    print(f"    Cadastrados ......... {feitos}")
    print(f"    Ja existiam ......... {duplicados}")
    print(f"    Falhas .............. {falhas}\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n  Interrompido. O progresso foi salvo.\n")
