#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
============================================================================
 CADASTRO AUTOMATICO - Revista Voice (FGBMFI) no PIB-Biblio
============================================================================

 Varre a pasta da colecao, gera a capa de cada edicao e cadastra no sistema
 biblio.pibcuritiba.org.br, anexando o PDF com OCR.

 PROJETADO PARA RODAR VARIAS VEZES:
   - nunca recadastra o que ja foi cadastrado (controle por ficheiro de estado)
   - ignora PDFs que ainda nao passaram por OCR (aguarda a proxima rodada)
   - ignora arquivos que ainda estao sendo escritos em disco
   - encontra sozinho as edicoes novas que aparecerem nas pastas

 MODO PADRAO E SIMULACAO. Nada e enviado sem a flag --executar.

 USO TIPICO:
   python3 cadastrar-voice.py                    # simula e mostra relatorio
   python3 cadastrar-voice.py --testar-login     # confere credenciais
   python3 cadastrar-voice.py --executar --limite 1   # cadastra 1 (teste real)
   python3 cadastrar-voice.py --executar         # cadastra tudo que falta
   python3 cadastrar-voice.py --executar --vigiar 10  # re-varre a cada 10 min

 CREDENCIAIS - nunca escreva no arquivo. Use variaveis de ambiente:
   export BIBLIO_USER='seu.usuario'
   export BIBLIO_PASS='sua.senha'
 Se nao definir, o script pergunta no terminal (senha oculta).

 DEPENDENCIAS:
   pip3 install requests
   brew install poppler        (pdftoppm e pdftotext)
============================================================================
"""

import argparse, getpass, json, os, re, subprocess, sys, time
from datetime import datetime

try:
    import requests
except ImportError:
    sys.exit("Falta a biblioteca requests.  Rode:  pip3 install requests")

# ---------------------------------------------------------------------------
# CONFIGURACAO
# ---------------------------------------------------------------------------

PASTA = os.path.expanduser(
    "~/Library/CloudStorage/Dropbox/arquivos temporários/revista/01-EDICOES-PDF"
)

BASE_URL   = "https://biblio.pibcuritiba.org.br"
URL_LOGIN  = f"{BASE_URL}/users/login"
URL_ADD    = f"{BASE_URL}/arquivos/add"

# Nomes dos campos do formulario de login (padrao CakePHP).
# Se o login falhar, rode --testar-login que o script mostra o que encontrou.
CAMPO_USER = "data[User][usernames]"   # com S no final - confirmado na pagina de login
CAMPO_PASS = "data[User][password]"

# IDs dos autores no banco. Lidos do link de detalhe em /autores.
# Sem o ID, o vinculo autor-arquivo aparentemente nao grava.
# Para descobrir outros: buscar o nome em /autores e ler o numero que
# aparece no link "detalhesAutor/id:NNNNN".
AUTORES_ID = {
    "Nickel, Thomas R.": "11299",
    # "Becker, Raymond W.": "?",   -- existe no banco, id ainda nao lido
    # "Jensen, Jerry":     "?",    -- nao existe, precisa ser criado
    # ENTIDADE:            "?",    -- nao existe, precisa ser criada
}

LINGUA_ID       = "125"      # id de "Ingles" no banco (lido de um registro
                             # que gravou corretamente). Toda a colecao e
                             # em ingles, entao vale para as 200 edicoes.
TIPO_DOC        = "3"        # 3 = Artigo de Revista
RESTRICAO       = "0"        # 0 = Publico (padrao), 1 = Restrito ("" deixa em branco)
                             # Restrito so para documentos confidenciais que
                             # exigem uma segunda camada de protecao.
PREFIXO_TOMBO   = "VOICE"
DPI_CAPA        = 100
MIN_CHARS_OCR   = 200        # abaixo disso considera que o OCR ainda nao rodou
PAUSA_ENVIO     = 2          # segundos entre cadastros

SUBPASTA_CAPAS     = "_capas"
SUBPASTA_RESPOSTAS = "_respostas"      # HTML devolvido pelo servidor a cada envio
ARQ_ESTADO         = "_cadastro-status.json"
ARQ_LOG            = "_cadastro-log.txt"

# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# EDITORES POR PERIODO
# ---------------------------------------------------------------------------
# Levantado manualmente no expediente (masthead) das proprias edicoes.
# Vai como AUTOR SECUNDARIO (nmAutor1). O autor principal (nmAutor0) e
# sempre a entidade FGBMFI, o que garante que uma busca por autor traga a
# colecao inteira.
#
# Faixas sem editor confirmado ficam sem autor secundario - preferimos a
# lacuna ao dado errado. Para completar depois, basta acrescentar a faixa
# aqui e rodar o script de novo nas edicoes ja cadastradas.
#
#   (ano_inicial, ano_final, "Sobrenome, Nome")
EDITORES = [
    (1953, 1961, "Nickel, Thomas R."),      # "Editor and Publisher" ate jan/1961
    (1963, 1967, "Jensen, Jerry"),          # "Managing Editor" sob conselho editorial
    (1975, 1975, "Becker, Raymond W."),     # confirmado em jan, fev e mar/1975
]
# LACUNAS a confirmar: 1962, 1968-1974, 1976-1983

ENTIDADE = "Full Gospel Business Men's Fellowship International"

# Todos os campos que o formulario do navegador envia, na ordem em que
# aparecem. Capturado interceptando um submit real. O que nao usamos vai
# como string vazia - o servidor espera que a chave exista.
TODOS_OS_CAMPOS = [
    "nmTipoDoc", "isbn", "titulo",
    "tipoAssunto1", "tipoAssunto2", "tipoAssunto3", "tipoAssunto4",
    "tipoAssunto5", "tipoAssunto6", "tipoAssunto7",
    "subTitulo", "tipoAutor", "autor",
    "autor0", "autor1", "autor2",
    "nmAutor0", "nmAutor1", "nmAutor2", "nmAutor3", "nmAutor4", "nmAutor5",
    "lingua", "nmLingua", "tituloPublicacao", "volume", "numVolumes",
    "data", "nPaginas", "issn", "idioma", "numChamada", "url",
    "acervo", "repositorio", "direitos", "extra", "nota", "palavrasChave",
    "editora", "edicao", "series", "tradutor", "numSerie", "secao",
    "local", "cdd", "tipoTese", "universidade", "contribuidor",
    "tipoGravacao", "tituloSerieColecao", "estudio", "tempoExecucao",
    "dataAcesso", "dataModificacao", "abstract", "lugar", "nmRestricao",
    "dataRegistro", "caminhoImagemCapa",
]


def editor_do_ano(ano):
    """Devolve o editor da epoca, ou None se a faixa nao foi confirmada."""
    for ini, fim, nome in EDITORES:
        if ini <= ano <= fim:
            return nome
    return None


def fonte_do_ano(ano):
    """Repositorio de origem: ORU ate 1961, FGBMFI de 1962 em diante."""
    if ano <= 1961:
        return "https://digitalshowcase.oru.edu/voice/"
    return "https://www.fgbmfi.org/resources"


MESES_EN = {"january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
            "july":7,"august":8,"september":9,"october":10,"november":11,
            "december":12,"jan":1,"feb":2,"mar":3,"apr":4,"jun":6,"jul":7,
            "aug":8,"sep":9,"sept":9,"oct":10,"nov":11,"dec":12}

MESES_PT = {1:"janeiro",2:"fevereiro",3:"marco",4:"abril",5:"maio",6:"junho",
            7:"julho",8:"agosto",9:"setembro",10:"outubro",11:"novembro",
            12:"dezembro"}

MESES_EN_NOME = {1:"January",2:"February",3:"March",4:"April",5:"May",6:"June",
                 7:"July",8:"August",9:"September",10:"October",11:"November",
                 12:"December"}

V, A, R, AZ, N, F = ('\033[0;32m','\033[0;33m','\033[0;31m','\033[0;34m',
                     '\033[1m','\033[0m')

def ok(m):   print(f"{V}  ok  {F}{m}")
def warn(m): print(f"{A}  !!  {F}{m}")
def err(m):  print(f"{R}  xx  {F}{m}")
def info(m): print(f"      {m}")

def registrar_log(pasta, msg):
    with open(os.path.join(pasta, ARQ_LOG), "a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}\n")


# ===========================================================================
# 1. LEITURA DOS NOMES DE ARQUIVO
# ===========================================================================

def interpretar_nome(nome):
    """Extrai ano, meses, volume e fasciculo do nome do arquivo.

    Reconhece os tres padroes presentes na colecao:
      A) Voice - FGBMFI - 6.1 (February 1958).pdf   -> vol e n explicitos
      B) Voice-1975-07-08.pdf                       -> ano e mes(es)
      C) FGMBV-1953-02-v1-n1.pdf                    -> ano, mes, vol, n
    Devolve dict ou None se nao reconhecer.
    """
    base = os.path.splitext(nome)[0]

    # --- Padrao A: estilo ORU, com volume.fasciculo e mes por extenso ---
    m = re.search(
        r'(\d+)\.(\d+)\s*\(([A-Za-z]+)(?:\s*[-/]\s*([A-Za-z]+))?\s+(\d{4})\)', base)
    if m:
        vol, fasc, mes1, mes2, ano = m.groups()
        meses = [MESES_EN.get(mes1.lower())]
        if mes2:
            meses.append(MESES_EN.get(mes2.lower()))
        meses = [x for x in meses if x]
        if meses:
            return {"ano": int(ano), "meses": meses, "volume": int(vol),
                    "fasciculo": int(fasc), "origem": "ORU"}

    # --- Padrao C: FGMBV-1953-02-v1-n1 ---
    m = re.search(r'(\d{4})-(\d{2}).*?v(\d+).*?n(\d+)', base, re.I)
    if m:
        ano, mes, vol, fasc = m.groups()
        return {"ano": int(ano), "meses": [int(mes)], "volume": int(vol),
                "fasciculo": int(fasc), "origem": "FGBMFI"}

    # --- Padrao B: Voice-1975-07-08  ou  Voice-1975-01 ---
    m = re.search(r'(\d{4})-(\d{2})(?:-(\d{2}))?(?!\d)', base)
    if m:
        ano, m1, m2 = m.groups()
        meses = [int(m1)] + ([int(m2)] if m2 else [])
        meses = [x for x in meses if 1 <= x <= 12]
        if meses:
            return {"ano": int(ano), "meses": meses, "volume": None,
                    "fasciculo": None, "origem": "FGBMFI"}

    # --- Casos especiais sem mes ---
    m = re.search(r'(\d{4})', base)
    if m and re.search(r'global|convention|especial', base, re.I):
        return {"ano": int(m.group(1)), "meses": [], "volume": None,
                "fasciculo": None, "origem": "especial"}

    return None


def montar_metadados(dados, caminho_pdf, n_paginas):
    """Constroi o dicionario de campos do formulario."""
    ano   = dados["ano"]
    meses = dados["meses"]
    vol   = dados["volume"] or (ano - 1952)     # v.1 = 1953
    vol_estimado = dados["volume"] is None

    if meses:
        mes_en = "/".join(MESES_EN_NOME[m] for m in meses)
        mes_pt = "/".join(MESES_PT[m] for m in meses)
        codigo = f"{PREFIXO_TOMBO}-{ano}-{'-'.join(f'{m:02d}' for m in meses)}"
        data_campo = f"{meses[0]:02d}/{ano}"
        titulo = f"Voice, {mes_en} {ano}"
    else:
        mes_en = mes_pt = "edicao especial"
        codigo = f"{PREFIXO_TOMBO}-{ano}-especial"
        data_campo = str(ano)
        titulo = f"Voice, {ano} (edicao especial)"

    nota = [f"v.{vol}" + (" (estimado)" if vol_estimado else ""),
            f"{mes_pt}/{ano}"]
    if dados["fasciculo"]:
        nota.append(f"n.{dados['fasciculo']}")
    if n_paginas:
        nota.append(f"{n_paginas} p.")
    nota.append("Camada de texto adicionada por OCR (Tesseract).")

    editor = editor_do_ano(ano)
    if editor:
        nota.append(f"Editor da época: {editor.rstrip('.')}.")

    campos = {
        "data[Arquivos][nmTipoDoc]":        TIPO_DOC,
        "data[Arquivos][titulo]":           titulo,
        "data[Arquivos][subTitulo]":        "Full Gospel Business Men's Voice",
        "data[Arquivos][tituloPublicacao]": "Full Gospel Business Men's Voice",
        # APENAS UM ASSUNTO. Enviar assuntos que nao existem no vocabulario
        # do sistema causa erro interno no servidor e aborta o cadastro
        # inteiro - inclusive o upload do PDF e da capa.
        # Comprovado em 27/07/2026: 3 assuntos = falha, 1 assunto = sucesso.
        # So acrescente outro depois de cria-lo em /assuntos.
        "data[Arquivos][tipoAssunto1]":     "Pentecostalismo",
        # UM AUTOR SO, e de preferencia um que ja exista no banco.
        # Enviar autor inexistente parece quebrar o vinculo e derrubar o
        # cadastro (mesmo padrao dos assuntos inexistentes). O editor da
        # epoca tem prioridade; a entidade so entra quando nao ha editor
        # confirmado para o periodo.
        "data[Arquivos][nmAutor0]":         editor or ENTIDADE,
        # tipoAutor = "1" e o que a rotina nativa de importacao do proprio
        # sistema preenche (observado ao acionar "Busca Amazon/Google").
        # Ela deixa autor0 e autor VAZIOS - logo o ID nao e necessario,
        # mas tipoAutor sim. O script sempre mandou esse campo em branco,
        # e o vinculo do autor nunca gravava.
        "data[Arquivos][tipoAutor]":        "1",
        "data[Arquivos][autor0]":           "",
        "data[Arquivos][autor]":            "",
        # O campo visivel leva o NOME; o oculto leva o ID da lingua no banco.
        # O JavaScript da pagina preenche o ID quando o usuario seleciona no
        # autocomplete. Sem ID, o vinculo nao grava.
        # 125 = Ingles, lido de um registro que funcionou. Serve para as 200,
        # ja que a revista inteira e em ingles.
        "data[Arquivos][lingua]":           LINGUA_ID,
        "data[Arquivos][nmLingua]":         "Inglês",
        "data[Arquivos][idioma]":           "eng",
        "data[Arquivos][volume]":           str(vol),
        "data[Arquivos][data]":             data_campo,
        "data[Arquivos][nPaginas]":         str(n_paginas or ""),
        "data[Arquivos][editora]":          ENTIDADE,
        "data[Arquivos][lugar]":            "Estados Unidos",
        "data[Arquivos][url]":              fonte_do_ano(ano),
        "data[Arquivos][direitos]":         f"Copyright {ENTIDADE}",
        "data[Arquivos][extra]":            f"Tombo: {codigo}",
        "data[Arquivos][nota]":             " ".join(nota),
        "data[Arquivos][palavrasChave]":    "Pentecostalismo; Movimento carismático; "
                                            "Periódicos religiosos; FGBMFI; Demos Shakarian",
        "data[Arquivos][abstract]":         (
            f"Edição de {mes_pt} de {ano} da revista Voice, publicação oficial da "
            "Full Gospel Business Men's Fellowship International, fundada em 1952 "
            "por Demos Shakarian. Reúne testemunhos de empresários e profissionais "
            "ligados ao movimento carismático."),
    }

    # nmAutor1 fica vazio de proposito. Um segundo autor exigiria que ele
    # tambem existisse na base, e a cada nome inexistente aumenta o risco
    # de derrubar o cadastro. Fica para depois, quando o basico estiver
    # comprovado.

    if RESTRICAO != "":
        campos["data[Arquivos][nmRestricao]"] = RESTRICAO

    # ------------------------------------------------------------------
    # O navegador envia os 64 campos do formulario, inclusive os vazios.
    # O servidor le varios deles sem verificar se chegaram - se faltarem,
    # estoura erro 500 ou grava o registro sem autor/assunto/lingua.
    # Capturado interceptando o submit real em 27/07/2026.
    # ------------------------------------------------------------------
    for k in TODOS_OS_CAMPOS:
        campos.setdefault(f"data[Arquivos][{k}]", "")
    campos.setdefault("_method", "POST")

    return codigo, campos


# ===========================================================================
# 2. VERIFICACOES DE INTEGRIDADE
# ===========================================================================

def arquivo_estavel(caminho, espera=2):
    """Confere se o arquivo parou de crescer (nao esta sendo gravado)."""
    try:
        t1 = os.path.getsize(caminho)
        time.sleep(espera)
        return t1 == os.path.getsize(caminho) and t1 > 0
    except OSError:
        return False


def pdf_valido(caminho):
    try:
        with open(caminho, "rb") as f:
            if f.read(5) != b"%PDF-":
                return False
            f.seek(max(0, os.path.getsize(caminho) - 2048))
            return b"%%EOF" in f.read()
    except OSError:
        return False


def info_pdf(caminho):
    """Devolve (n_paginas, n_caracteres_de_texto)."""
    paginas = 0
    try:
        s = subprocess.run(["pdfinfo", caminho], capture_output=True,
                           text=True, timeout=30).stdout
        m = re.search(r"Pages:\s+(\d+)", s)
        if m:
            paginas = int(m.group(1))
    except Exception:
        pass

    chars = 0
    try:
        t = subprocess.run(["pdftotext", "-l", "5", caminho, "-"],
                           capture_output=True, text=True, timeout=60).stdout
        chars = len(t.strip())
    except Exception:
        pass
    return paginas, chars


def gerar_capa(caminho_pdf, pasta_capas):
    os.makedirs(pasta_capas, exist_ok=True)
    base = os.path.splitext(os.path.basename(caminho_pdf))[0]
    destino = os.path.join(pasta_capas, base)
    final = destino + ".jpg"
    if os.path.exists(final) and os.path.getsize(final) > 1000:
        return final, False
    try:
        subprocess.run(["pdftoppm", "-f", "1", "-l", "1", "-r", str(DPI_CAPA),
                        "-jpeg", "-singlefile", caminho_pdf, destino],
                       capture_output=True, timeout=120, check=True)
        return (final, True) if os.path.exists(final) else (None, False)
    except Exception:
        return None, False


# ===========================================================================
# 3. ESTADO (o que ja foi cadastrado)
# ===========================================================================

def carregar_estado(pasta):
    p = os.path.join(pasta, ARQ_ESTADO)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            warn("arquivo de estado corrompido - comecando um novo")
    return {}


def salvar_estado(pasta, estado):
    p = os.path.join(pasta, ARQ_ESTADO)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


# ===========================================================================
# 4. SESSAO NO SISTEMA
# ===========================================================================

def abrir_sessao(usuario, senha, diagnostico=False):
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})

    r = s.get(URL_LOGIN, timeout=30)
    if diagnostico:
        nomes = re.findall(r'name="([^"]+)"', r.text)
        info(f"status da pagina de login: {r.status_code}")
        info(f"campos encontrados: {', '.join(nomes[:15]) or '(nenhum)'}")

    r = s.post(URL_LOGIN, data={CAMPO_USER: usuario, CAMPO_PASS: senha},
               timeout=30, allow_redirects=True)

    # heuristica: se ainda aparece campo de senha, o login falhou
    autenticado = ('type="password"' not in r.text) or ("logout" in r.text.lower())
    return s, autenticado


def extrair_mensagens(html):
    """Pesca mensagens de retorno (flash do CakePHP, alertas, erros de campo)."""
    msgs = []

    # flash padrao do CakePHP e variantes de alerta
    for padrao in [
        r'<div[^>]*(?:class|id)="[^"]*(?:message|flash|alert)[^"]*"[^>]*>(.*?)</div>',
        r'<div[^>]*class="[^"]*error-message[^"]*"[^>]*>(.*?)</div>',
        r'<p[^>]*class="[^"]*(?:error|success)[^"]*"[^>]*>(.*?)</p>',
    ]:
        for m in re.findall(padrao, html, re.I | re.S):
            texto = re.sub(r'<[^>]+>', ' ', m)
            texto = re.sub(r'\s+', ' ', texto).strip()
            if texto and len(texto) < 300 and texto not in msgs:
                msgs.append(texto)

    # erros de validacao ligados a campos especificos
    for campo, erro in re.findall(
            r'name="data\[Arquivos\]\[(\w+)\][^"]*"[^>]*>\s*'
            r'<div[^>]*class="[^"]*error[^"]*"[^>]*>(.*?)</div>', html, re.I | re.S):
        texto = re.sub(r'<[^>]+>', ' ', erro).strip()
        if texto:
            msgs.append(f"[campo {campo}] {texto}")

    return msgs


def enviar(sessao, campos, pdf, capa, pasta=None, codigo=None):
    """Envia o registro. Devolve (sucesso, status, url_final, mensagens)."""
    arquivos = {
        "data[Arquivos][docDigital]": (os.path.basename(pdf),
                                       open(pdf, "rb"), "application/pdf"),
        "data[Arquivos][capa]":       (os.path.basename(capa),
                                       open(capa, "rb"), "image/jpeg"),
    }
    try:
        r = sessao.post(URL_ADD, data=campos, files=arquivos,
                        timeout=300, allow_redirects=True)
        html = r.text
        msgs = extrair_mensagens(html)

        # guarda a resposta crua para inspecao
        if pasta:
            d = os.path.join(pasta, SUBPASTA_RESPOSTAS)
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, f"{codigo or 'resposta'}.html"),
                      "w", encoding="utf-8") as f:
                f.write(f"<!-- POST {URL_ADD}\n"
                        f"     HTTP {r.status_code}\n"
                        f"     URL final: {r.url}\n"
                        f"     {datetime.now():%Y-%m-%d %H:%M:%S} -->\n\n")
                f.write(html)

        baixo = html.lower()

        # Deteccao ESTRITA. Ja tivemos falso positivo: o registro entrou sem
        # autor, assunto nem lingua, e foi marcado como concluido - erro que
        # so aparece muito depois. Agora exige sinal explicito de sucesso.
        tem_erro = any(p in baixo for p in [
            "internal error", "não foi possível", "nao foi possivel",
            "erro ao", "error-message", "corrija os erros", "campo obrigat"])
        tem_sucesso = any(p in baixo for p in [
            "sucesso", "cadastrado com", "salvo com", "gravado com"])

        sucesso = (r.status_code in (200, 302)
                   and tem_sucesso
                   and not tem_erro)

        return sucesso, r.status_code, r.url, msgs
    finally:
        for _, (_, fh, _) in arquivos.items():
            try: fh.close()
            except Exception: pass


# ===========================================================================
# 5. VARREDURA
# ===========================================================================

def varrer(pasta):
    """Lista todos os PDFs nas subpastas de ano, em ordem cronologica."""
    achados = []
    for raiz, dirs, arqs in os.walk(pasta):
        # ordena as pastas para a varredura seguir a cronologia (1953, 1954...)
        dirs[:] = sorted(d for d in dirs
                         if not d.startswith("_") and not d.startswith("."))
        for a in sorted(arqs):
            if a.lower().endswith(".pdf") and not a.startswith("."):
                achados.append(os.path.join(raiz, a))
    return achados


def rodada(pasta, sessao, executar, limite):
    estado = carregar_estado(pasta)
    pasta_capas = os.path.join(pasta, SUBPASTA_CAPAS)
    pdfs = varrer(pasta)

    print(f"\n{N}{AZ}  Varredura: {len(pdfs)} PDFs encontrados{F}\n")

    cont = {"cadastrados":0, "ja_feitos":0, "sem_ocr":0, "instaveis":0,
            "invalidos":0, "sem_padrao":0, "falhas":0, "capas":0}
    aguardando = []
    tentativas = 0      # envios efetivamente feitos, com ou sem sucesso

    for caminho in pdfs:
        rel = os.path.relpath(caminho, pasta)
        nome = os.path.basename(caminho)

        if estado.get(rel, {}).get("status") == "cadastrado":
            cont["ja_feitos"] += 1
            continue

        # O limite conta TENTATIVAS, nao sucessos. Se contasse sucessos,
        # uma sequencia de falhas faria o script percorrer a colecao
        # inteira sem nunca parar.
        if limite and tentativas >= limite:
            print(f"\n{A}  Limite de {limite} tentativa(s) atingido.{F}")
            break

        print(f"{N}{nome}{F}")

        dados = interpretar_nome(nome)
        if not dados:
            err("nome fora dos padroes conhecidos - pulando")
            estado[rel] = {"status": "sem_padrao", "quando": datetime.now().isoformat()}
            cont["sem_padrao"] += 1
            continue

        if not arquivo_estavel(caminho):
            warn("arquivo ainda sendo gravado - fica para a proxima rodada")
            cont["instaveis"] += 1
            aguardando.append(nome)
            continue

        if not pdf_valido(caminho):
            err("PDF incompleto ou corrompido - pulando")
            cont["invalidos"] += 1
            continue

        paginas, chars = info_pdf(caminho)

        if chars < MIN_CHARS_OCR:
            warn(f"sem camada de texto ({chars} chars) - aguardando OCR")
            cont["sem_ocr"] += 1
            aguardando.append(nome)
            continue

        capa, nova = gerar_capa(caminho, pasta_capas)
        if nova:
            cont["capas"] += 1
        if not capa:
            err("nao foi possivel gerar a capa - pulando")
            cont["falhas"] += 1
            continue

        codigo, campos = montar_metadados(dados, caminho, paginas)
        info(f"{codigo}  |  {campos['data[Arquivos][titulo]']}  |  "
             f"v.{campos['data[Arquivos][volume]']}  |  {paginas} p.  |  {chars} chars")

        if not executar:
            info(f"{A}[simulacao]{F} nada enviado")
            cont["cadastrados"] += 1
            continue

        tentativas += 1
        sucesso, status, url_final, msgs = enviar(
            sessao, campos, caminho, capa, pasta, codigo)

        for m in msgs[:3]:
            info(f"servidor: {m}")

        # "ja existe na base" nao e falha nem sucesso: e uma edicao que ja
        # esta no sistema. Marca no estado e NAO consome o --limite, senao
        # um teste de 1 se esgota numa duplicata sem testar nada.
        if any("ja existe" in mm.lower() or "já existe" in mm.lower() for mm in msgs):
            warn("ja existe no sistema - marcando e seguindo adiante")
            estado[rel] = {"status": "cadastrado", "codigo": codigo,
                           "quando": datetime.now().isoformat(),
                           "observacao": "ja existia no sistema; conferir se esta completo"}
            salvar_estado(pasta, estado)
            registrar_log(pasta, f"JA EXISTIA  {codigo}  {rel}")
            cont["ja_feitos"] += 1
            tentativas -= 1
            continue

        if sucesso:
            ok(f"cadastrado (HTTP {status})")
            estado[rel] = {"status": "cadastrado", "codigo": codigo,
                           "quando": datetime.now().isoformat()}
            salvar_estado(pasta, estado)
            registrar_log(pasta, f"CADASTRADO  {codigo}  {rel}")
            cont["cadastrados"] += 1
        else:
            err(f"falha no envio (HTTP {status})")
            info(f"resposta salva em {SUBPASTA_RESPOSTAS}/{codigo}.html")
            registrar_log(pasta, f"FALHA  {rel}  HTTP {status}  url={url_final}")
            cont["falhas"] += 1

        time.sleep(PAUSA_ENVIO)

    # So grava o estado quando houve envio real. Em simulacao nao mexemos
    # no arquivo - senao uma simulacao apagaria o historico de cadastros.
    if executar:
        salvar_estado(pasta, estado)

    print(f"\n{AZ}  {'-'*52}{F}")
    print(f"{N}  RESUMO{F}\n")
    rotulos = {"cadastrados":"Cadastrados" if executar else "Prontos (simulacao)",
               "ja_feitos":"Ja cadastrados antes", "sem_ocr":"Aguardando OCR",
               "instaveis":"Sendo gravados agora", "invalidos":"PDFs invalidos",
               "sem_padrao":"Nome nao reconhecido", "falhas":"Falhas",
               "capas":"Capas geradas"}
    for k, r in rotulos.items():
        if cont[k]:
            print(f"    {r:.<32} {cont[k]}")

    if aguardando:
        print(f"\n{A}  Ainda nao prontos ({len(aguardando)}):{F}")
        for n_ in aguardando[:10]:
            print(f"      - {n_}")
        if len(aguardando) > 10:
            print(f"      ... e mais {len(aguardando)-10}")
        print(f"\n    Rode de novo quando o OCR terminar. Nada sera duplicado.")
    print()
    return cont


# ===========================================================================
# 6. MAIN
# ===========================================================================

def main():
    ap = argparse.ArgumentParser(description="Cadastra a colecao Voice no PIB-Biblio")
    ap.add_argument("--dir", default=PASTA, help="pasta da colecao")
    ap.add_argument("--executar", action="store_true",
                    help="envia de verdade (sem isso, apenas simula)")
    ap.add_argument("--limite", type=int, default=0, help="maximo de cadastros nesta rodada")
    ap.add_argument("--vigiar", type=int, default=0,
                    help="re-varre a cada N minutos, continuamente")
    ap.add_argument("--testar-login", action="store_true", help="so testa a autenticacao")
    ap.add_argument("--so-capas", action="store_true", help="apenas gera as capas")
    args = ap.parse_args()

    pasta = os.path.expanduser(args.dir)
    if not os.path.isdir(pasta):
        sys.exit(f"Pasta nao encontrada: {pasta}")

    print(f"\n{N}{AZ}  CADASTRO VOICE -> PIB-Biblio{F}")
    print(f"{AZ}  {'-'*52}{F}")
    print(f"  Pasta: {pasta}")

    # ---- so capas ----
    if args.so_capas:
        pdfs = varrer(pasta)
        pasta_capas = os.path.join(pasta, SUBPASTA_CAPAS)
        novas = 0
        print(f"\n  Gerando capas de {len(pdfs)} PDFs...\n")
        for i, p in enumerate(pdfs, 1):
            c, nova = gerar_capa(p, pasta_capas)
            if nova:
                novas += 1
            print(f"\r  {i}/{len(pdfs)}  novas: {novas}", end="", flush=True)
        print(f"\n\n  Capas em: {pasta_capas}\n")
        return

    # ---- credenciais ----
    sessao = None
    if args.executar or args.testar_login:
        usuario = os.environ.get("BIBLIO_USER") or input("  Usuario: ").strip()
        senha   = os.environ.get("BIBLIO_PASS") or getpass.getpass("  Senha: ")
        print()
        sessao, autenticado = abrir_sessao(usuario, senha, diagnostico=args.testar_login)
        if autenticado:
            ok("autenticado")
        else:
            err("nao foi possivel autenticar")
            info("Confira usuario/senha, ou ajuste CAMPO_USER e CAMPO_PASS")
            info("no topo do script com os nomes listados acima.")
            if not args.testar_login:
                sys.exit(1)
        if args.testar_login:
            print()
            return
    else:
        print(f"  {A}MODO SIMULACAO{F} - use --executar para enviar de verdade")

    # ---- rodadas ----
    while True:
        cont = rodada(pasta, sessao, args.executar, args.limite)
        if not args.vigiar:
            break
        if cont["sem_ocr"] == 0 and cont["instaveis"] == 0:
            ok("nada mais pendente - encerrando o modo vigilancia")
            break
        print(f"  Proxima varredura em {args.vigiar} min... (Ctrl+C para sair)\n")
        try:
            time.sleep(args.vigiar * 60)
        except KeyboardInterrupt:
            print("\n  Interrompido.\n")
            break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n  Interrompido. O progresso foi salvo.\n")
