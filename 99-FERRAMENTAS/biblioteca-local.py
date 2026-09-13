#!/usr/bin/env python3
"""Fluxo incremental local para preparar livros e documentos sem duplicação.

PDFs são movidos entre estados; DOC/DOCX e EPUB geram uma cópia PDF pesquisável
e preservam o original. A liberação de espaço é separada, simulada por padrão e
só leva arquivos à Lixeira depois da confirmação do cadastro.
"""

import argparse
import csv
import difflib
import errno
import fcntl
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import base64
from contextlib import contextmanager
from datetime import datetime


sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import converter_html          # HTML -> PDF pesquisavel (Chromium)

BASE_SCRIPT = pathlib.Path(__file__).with_name("preparar-livros.py")
SPEC = importlib.util.spec_from_file_location("preparar_livros", BASE_SCRIPT)
prep = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prep)

API_SCRIPT = pathlib.Path(__file__).with_name("enviar-livro-api.py")
SPEC_API = importlib.util.spec_from_file_location("enviar_livro_api", API_SCRIPT)
api_envio = importlib.util.module_from_spec(SPEC_API)
SPEC_API.loader.exec_module(api_envio)

PASTAS = {
    "entrada": "00-ENTRADA",
    "revisao": "10-REVISAO",
    "academicos": "15-TESES-DISSERTACOES-E-TRABALHOS",
    "documentos": "16-ARTIGOS-E-DOCUMENTOS",
    "revistas": "17-REVISTAS-E-PERIODICOS",
    "excecoes_tamanho": "18-EXCECOES-DE-TAMANHO",
    "descarte": "19-DESCARTE",
    "pronto": "20-PRONTOS",
    "arquivado": "30-ARQUIVADOS",
    "controle": "_controle",
    "capas": "_capas",
    "metadados": "_metadados",
    "preparados": "_preparados-envio",
}
VERSAO_CATALOGO = 1
# A partir de 50 MB sempre tentamos reduzir o arquivo. Esse valor nao e mais
# impedimento de envio: o limite efetivo informado para o PHP em producao e
# 500M. A aplicacao do servidor aceita ate 50G, mas o menor teto da cadeia e
# o que governa a transferencia HTTP.
LIMITE_OTIMIZACAO_BYTES = 50_000_000
LIMITE_ENVIO_BYTES = 500_000_000
# Três passes são suficientes para decidir se a API de 50 MB pode receber o
# arquivo. PDFs extensos tornavam cinco regravações integrais muito caras.
# A resolução monocromática permanece no dobro da resolução de cor para
# preservar letras e traços finos enquanto imagens são reduzidas com vigor.
TENTATIVAS_COMPACTACAO = ((120, 240), (105, 210), (96, 200))
GANHO_MINIMO_COMPACTACAO = 0.03
# Acima de 75 MB, o PDF precisa perder pelo menos um terço para caber no
# servidor. A experiência mostrou que passes conservadores só consomem tempo.
LIMITE_COMPACTACAO_DIRETA_96 = 75_000_000
LIMITE_PROJECAO_EXCECAO = 55_000_000
PAGINAS_AMOSTRA_COMPACTACAO = 140
ESTADO_EXCECAO_TAMANHO = "aguardando exceção de tamanho"
ESTADO_DESCARTE = "descartado - não é livro"
ESTADO_DUPLICADO_CONTEUDO = "duplicado confirmado por conteúdo"
# A comparação integral de uma Bíblia levou mais de 14 minutos e pareceu
# congelar o aplicativo. O SHA-256 já elimina cópias byte a byte; para cópias
# recompostas, 30 mil palavras distribuídas entre começo, meio e fim dão uma
# amostra ampla sem permitir que o custo cresça indefinidamente.
MAX_PALAVRAS_DUPLICIDADE = 30_000
TIPOS_ACADEMICOS = {"tese", "dissertação", "trabalho acadêmico"}
TIPOS_DOCUMENTOS = {"artigo", "documento", "apostila", "sermão", "trecho",
                    "resumo", "apresentação"}
TIPOS_REVISTAS = {"revista", "periódico", "boletim", "jornal"}
ESTADOS_REVISAO_VISUAL = {
    "analisado", "conflito", "precisa OCR",
    "duplicado textual - revisar",
    "já existente na API - conferir vínculo",
    "duplicado informado pela API - revisar",
}
ESTADOS_TERMINAIS_REVISAO_VISUAL = {
    "pronto para cadastro",
    "pronto para cadastro específico",
    "cadastrado",
    "cadastrado - arquivos locais liberados",
    "duplicado na API - arquivos locais liberados",
    "duplicado confirmado por ISBN",
    "duplicado confirmado por título",
    "duplicado confirmado por título e autor",
    "duplicado confirmado por conteúdo",
    "descartado - arquivos locais liberados",
    ESTADO_DESCARTE,
}
LIMITE_CAPA_MANUAL_BYTES = 8 * 1024 * 1024
CAMPOS_REVISAO_POR_TIPO = {
    "livro": ("titulo", "nmAutor0", "editora", "data", "nmLingua"),
    "documento": ("titulo",),
    "apostila": ("titulo",),
    "sermão": ("titulo",),
    "trecho": ("titulo",),
    "resumo": ("titulo",),
    "apresentação": ("titulo",),
    "artigo": ("titulo",),
    "revista": ("titulo", "data"),
    "periódico": ("titulo", "data"),
    "boletim": ("titulo", "data"),
    "jornal": ("titulo", "data"),
    "tese": ("titulo", "nmAutor0", "data"),
    "dissertação": ("titulo", "nmAutor0", "data"),
    "trabalho acadêmico": ("titulo", "nmAutor0", "data"),
}
EBOOK_CONVERT = pathlib.Path("/Applications/calibre.app/Contents/MacOS/ebook-convert")
EXTENSOES_WORD = {".doc", ".docx"}
# PowerPoint e congêneres. Sete apresentações ficaram paradas em
# 00-ENTRADA/apresentações porque a esteira só convertia Word, EPUB e HTML.
# O Biblio só aceita PDF: sem conversão, elas nunca subiriam.
EXTENSOES_APRESENTACAO = {".ppt", ".pptx", ".pps", ".ppsx", ".odp"}
SOFFICE_APLICATIVOS = (
    pathlib.Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"),
    pathlib.Path("/Applications/LibreOfficeDev.app/Contents/MacOS/soffice"),
)
MICROSOFT_WORD = pathlib.Path("/Applications/Microsoft Word.app")
ARQUIVOS_SISTEMA_IGNORADOS = {
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
}


def agora():
    return datetime.now().isoformat(timespec="seconds")


def arquivo_de_sistema_ignorado(caminho):
    """Arquivos auxiliares do sistema/Finder não são material bibliográfico."""
    nome = pathlib.Path(caminho).name
    return (
        nome in ARQUIVOS_SISTEMA_IGNORADOS
        or nome.startswith("._")
        or nome.startswith("~$")
    )


def caminhos(raiz):
    raiz = pathlib.Path(raiz).expanduser().resolve()
    return {k: raiz / v for k, v in PASTAS.items()} | {"raiz": raiz}


def inicializar(raiz):
    c = caminhos(raiz)
    c["raiz"].mkdir(parents=True, exist_ok=True)
    for k in PASTAS:
        c[k].mkdir(parents=True, exist_ok=True)
    catalogo = c["controle"] / "catalogo-local.json"
    if not catalogo.exists():
        salvar_json(catalogo, {
            "versao": VERSAO_CATALOGO,
            "criado_em": agora(),
            "atualizado_em": agora(),
            "livros": {},
        })
    return c


def salvar_json(destino, dados):
    destino = pathlib.Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_name(destino.name + ".tmp")
    with temporario.open("w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    os.replace(temporario, destino)


def atualizar_processamento_ativo(c, **campos):
    arquivo = c["controle"] / "processamento-ativo.json"
    atual = {}
    try:
        atual = json.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    # Marcador de OUTRO processo (morto sem limpar) nao pode contaminar este:
    # os campos sao mesclados, e "pagina: 180/279" do processo anterior
    # apareceria como se fosse o progresso do atual.
    if atual.get("pid") not in (None, os.getpid()):
        atual = {}
    atual.update({"pid": os.getpid(), "atualizado_em": agora(), **campos})
    salvar_json(arquivo, atual)


def limpar_processamento_ativo(c):
    arquivo = c["controle"] / "processamento-ativo.json"
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        dados = {}
    if dados.get("pid") in (None, os.getpid()) and arquivo.is_file():
        arquivo.unlink()


@contextmanager
def trava_execucao(raiz, operacao):
    c = inicializar(raiz)
    arquivo = c["controle"] / "processamento.lock"
    with arquivo.open("a+", encoding="utf-8") as trava:
        try:
            fcntl.flock(trava.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            trava.seek(0)
            responsavel = trava.read().strip() or "outro processo"
            raise RuntimeError(
                f"já existe um processamento ativo ({responsavel})") from exc
        trava.seek(0)
        trava.truncate()
        trava.write(f"pid={os.getpid()} operação={operacao} iniciado={agora()}\n")
        trava.flush()
        atualizar_processamento_ativo(
            c, operacao=operacao, etapa="iniciando", arquivo="",
            pagina=0, paginas=0, percentual=0, eta_segundos=None)
        try:
            yield c
        finally:
            limpar_processamento_ativo(c)
            trava.seek(0)
            trava.truncate()
            trava.flush()
            fcntl.flock(trava.fileno(), fcntl.LOCK_UN)


def carregar_catalogo(c):
    p = c["controle"] / "catalogo-local.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        d = {"versao": VERSAO_CATALOGO, "criado_em": agora(), "livros": {}}
    d.setdefault("livros", {})
    return d


def salvar_catalogo(c, catalogo):
    catalogo["versao"] = VERSAO_CATALOGO
    catalogo["atualizado_em"] = agora()
    salvar_json(c["controle"] / "catalogo-local.json", catalogo)


def sha256(arquivo, bloco=1024 * 1024):
    h = hashlib.sha256()
    with open(arquivo, "rb") as f:
        while True:
            b = f.read(bloco)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def texto_normalizado_para_duplicidade(paginas, limite=MAX_PALAVRAS_DUPLICIDADE):
    texto = prep.identificar.normalizar(" ".join(paginas or []))
    palavras = re.findall(r"[a-z0-9]+", texto)
    if limite and len(palavras) > limite:
        trecho = limite // 3
        meio = len(palavras) // 2
        palavras = (palavras[:trecho]
                    + palavras[meio - trecho // 2:meio + trecho // 2]
                    + palavras[-trecho:])
    return " ".join(palavras)


def assinatura_textual(paginas):
    """Cria uma assinatura pequena para localizar cópias quase idênticas."""
    texto = texto_normalizado_para_duplicidade(paginas)
    palavras = texto.split()
    if len(palavras) < 120:
        return {"simhash": "", "palavras": len(palavras),
                "hash_texto": hashlib.sha256(texto.encode()).hexdigest()}
    janelas = [" ".join(palavras[i:i + 5])
               for i in range(max(1, len(palavras) - 4))]
    acumulado = [0] * 64
    for janela in janelas:
        valor = int.from_bytes(
            hashlib.blake2b(janela.encode(), digest_size=8).digest(), "big")
        for bit in range(64):
            acumulado[bit] += 1 if valor & (1 << bit) else -1
    simhash = sum((1 << bit) for bit, peso in enumerate(acumulado) if peso >= 0)
    return {
        "simhash": f"{simhash:016x}", "palavras": len(palavras),
        "hash_texto": hashlib.sha256(texto.encode()).hexdigest(),
    }


def distancia_simhash(a, b):
    try:
        return (int(a, 16) ^ int(b, 16)).bit_count()
    except (TypeError, ValueError, AttributeError):
        # Python 3.9 deste Mac ainda não possui int.bit_count().
        try:
            return bin(int(a, 16) ^ int(b, 16)).count("1")
        except (TypeError, ValueError):
            return 65


def _arquivo_do_registro(c, registro):
    caminho = c["raiz"] / registro.get("caminho", "")
    if caminho.is_file():
        return caminho
    nome = registro.get("arquivo", "")
    candidatos = [pasta / nome for chave, pasta in c.items()
                  if chave not in {"raiz", "controle", "metadados"}
                  and isinstance(pasta, pathlib.Path) and (pasta / nome).is_file()]
    return candidatos[0] if len(candidatos) == 1 else None


def localizar_duplicado_textual(c, catalogo, paginas, excluir_digest=""):
    """Confirma por texto integral uma coincidência indicada pelo SimHash."""
    atual = assinatura_textual(paginas)
    if not atual["simhash"]:
        return atual, {}
    texto_atual = texto_normalizado_para_duplicidade(paginas)
    melhor = {}
    for digest, registro in catalogo.get("livros", {}).items():
        if digest == excluir_digest or str(digest).startswith("duplicado:"):
            continue
        simhash = registro.get("simhash_texto", "")
        palavras = int(registro.get("palavras_texto", 0) or 0)
        if (not simhash or not palavras
                or min(palavras, atual["palavras"]) /
                max(palavras, atual["palavras"]) < 0.82
                or distancia_simhash(simhash, atual["simhash"]) > 10):
            continue
        candidato = _arquivo_do_registro(c, registro)
        if not candidato:
            continue
        paginas_candidato = prep.paginas_pdftotext(str(candidato))
        texto_candidato = texto_normalizado_para_duplicidade(paginas_candidato)
        # Comparar caracteres com autojunk desligado é patológico em obras
        # longas e repetitivas. Palavras amostradas mantêm a confirmação
        # bibliográfica e deixam o algoritmo ignorar repetições excessivas.
        similaridade = difflib.SequenceMatcher(
            None, texto_atual.split(), texto_candidato.split()).ratio()
        if similaridade >= 0.94 and similaridade > melhor.get("similaridade", 0):
            melhor = {
                "hash_sha256": digest, "arquivo": registro.get("arquivo", ""),
                "caminho": registro.get("caminho", ""),
                "similaridade": similaridade,
                "estado": registro.get("estado", ""),
                "id_remoto": registro.get("id_remoto"),
            }
    return atual, melhor


def registrar_duplicado_textual(c, catalogo, digest, origem,
                                assinatura, duplicado):
    """Estaciona a cópia sem repetir OCR e confirma casos inequívocos."""
    registro = catalogo.get("livros", {}).get(digest, {})
    ficha_path = c["raiz"] / registro.get("metadados", "")
    try:
        ficha = json.loads(ficha_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        ficha = {}
    destino = mover_sem_substituir(
        origem, c["revisao"] / "DUPLICADOS-TEXTO", digest)
    confirmado = bool(
        duplicado.get("similaridade", 0) >= 0.99
        and duplicado.get("id_remoto")
        and duplicado.get("estado") in {
            "cadastrado", "cadastrado - arquivos locais liberados"})
    estado = (ESTADO_DUPLICADO_CONTEUDO if confirmado
              else "duplicado textual - revisar")
    ficha.update({
        "arquivo": destino.name, "pdf_original": relativo(c, destino),
        "situacao": estado, "situacao_metadados": estado,
        "duplicado_textual_de": duplicado.get("arquivo", ""),
        "duplicado_textual_caminho": duplicado.get("caminho", ""),
        "similaridade_textual": round(duplicado.get("similaridade", 0), 4),
        "simhash_texto": assinatura.get("simhash", ""),
        "palavras_texto": assinatura.get("palavras", 0),
        "hash_texto": assinatura.get("hash_texto", ""),
        "conflitos": ("" if confirmado else
                      f"conteúdo {duplicado.get('similaridade', 0):.1%} "
                      f"semelhante a {duplicado.get('arquivo', '')}"),
        "pendencias": ("" if confirmado else
                       "confirmar qual cópia deve ser preservada"),
        "id_remoto_duplicado": duplicado.get("id_remoto"),
        "hash_sha256": digest, "gerado_em": agora(),
    })
    if not ficha_path.name or ficha_path == c["raiz"]:
        ficha_path = c["metadados"] / f"{destino.stem}-{digest[:8]}.json"
    salvar_json(ficha_path, ficha)
    catalogo["livros"][digest] = {
        **registro, "hash_sha256": digest, "arquivo": destino.name,
        "caminho": relativo(c, destino), "tamanho_bytes": destino.stat().st_size,
        "estado": estado, "processado_em": agora(),
        "metadados": relativo(c, ficha_path), "duplicado_de": duplicado.get("caminho", ""),
        "id_remoto": duplicado.get("id_remoto") if confirmado else "",
        "simhash_texto": assinatura.get("simhash", ""),
        "palavras_texto": assinatura.get("palavras", 0),
        "hash_texto": assinatura.get("hash_texto", ""),
    }
    salvar_catalogo(c, catalogo)
    return destino


def relativo(c, arquivo):
    try:
        return str(pathlib.Path(arquivo).resolve().relative_to(c["raiz"]))
    except ValueError:
        return str(pathlib.Path(arquivo).resolve())


def destino_unico(pasta, nome, digest, aceitar_igual=False):
    destino = pasta / nome
    if not destino.exists():
        return destino
    try:
        if aceitar_igual and sha256(destino) == digest:
            return destino
    except OSError:
        pass
    base, ext = os.path.splitext(nome)
    destino = pasta / f"{base}-{digest[:8]}{ext}"
    contador = 2
    while destino.exists():
        destino = pasta / f"{base}-{digest[:8]}-{contador}{ext}"
        contador += 1
    return destino


def mover_sem_substituir(origem, pasta, digest):
    pasta.mkdir(parents=True, exist_ok=True)
    destino = destino_unico(pasta, origem.name, digest)
    if origem.resolve() == destino.resolve():
        return destino
    if destino.exists():
        raise FileExistsError(f"destino ja contem o mesmo PDF: {destino}")
    return pathlib.Path(shutil.move(str(origem), str(destino)))


def medir_compactacao(tamanho_fonte, tamanho_saida):
    """Quantifica ganho e distância do limite para decidir o próximo passe."""
    reducao = ((tamanho_fonte - tamanho_saida) / tamanho_fonte
               if tamanho_fonte else 0.0)
    return {
        "tamanho_bytes": tamanho_saida,
        "tamanho_mb": round(tamanho_saida / 1_000_000, 2),
        "reducao_percentual": round(reducao * 100, 2),
        "excesso_bytes": max(0, tamanho_saida - LIMITE_OTIMIZACAO_BYTES),
        "excesso_mb": round(max(0, tamanho_saida - LIMITE_OTIMIZACAO_BYTES)
                           / 1_000_000, 2),
        "contraproducente": reducao <= 0,
        "ganho_relevante": reducao >= GANHO_MINIMO_COMPACTACAO,
    }


def selecionar_tentativas_compactacao(tamanho_fonte):
    if tamanho_fonte >= LIMITE_COMPACTACAO_DIRETA_96:
        return (TENTATIVAS_COMPACTACAO[-1],)
    return TENTATIVAS_COMPACTACAO


def diagnosticar_estrutura_pdf(fonte, texto=""):
    """Distingue peso de imagens, fontes repetidas e alfabetos complexos."""
    complexo = bool(
        re.search(r"[\u0370-\u03ff\u0590-\u05ff\u0600-\u06ff]", texto or "")
        or re.search(r"(?i)\b(?:hebraic[oa]|hebrew|greg[oa]|greek|"
                     r"[áa]rabe|arabic|aramaic[oa])\b", texto or ""))
    resultado = {
        "disponivel": False, "imagens": 0, "imagens_jbig2": 0,
        "fontes": 0, "alfabeto_complexo": complexo,
    }
    try:
        imagens = subprocess.run(
            ["pdfimages", "-list", str(fonte)], capture_output=True,
            text=True, timeout=120, check=True).stdout.splitlines()
        linhas_imagem = [l.split() for l in imagens
                         if re.match(r"^\s*\d+\s+\d+\s+", l)]
        resultado["imagens"] = len(linhas_imagem)
        resultado["imagens_jbig2"] = sum(
            1 for colunas in linhas_imagem if "jbig2" in colunas)
        fontes = subprocess.run(
            ["pdffonts", str(fonte)], capture_output=True,
            text=True, timeout=120, check=True).stdout.splitlines()
        resultado["fontes"] = sum(
            1 for linha in fontes[2:] if linha.strip())
        resultado["proporcao_jbig2"] = round(
            resultado["imagens_jbig2"] / max(1, resultado["imagens"]), 4)
        resultado["disponivel"] = True
    except (OSError, subprocess.SubprocessError):
        resultado["motivo"] = "ferramentas de diagnóstico indisponíveis"
    return resultado


def otimizar_pdf_sem_perdas(fonte, destino, progresso=None):
    """Tenta compactação estrutural com qpdf, sem reduzir imagens ou OCR."""
    qpdf = shutil.which("qpdf")
    if not qpdf:
        return False, {"disponivel": False, "motivo": "qpdf indisponível"}
    fonte = pathlib.Path(fonte)
    destino = pathlib.Path(destino)
    try:
        with tempfile.TemporaryDirectory(prefix="biblio-sem-perdas-") as td:
            saida = pathlib.Path(td) / "compacto.pdf"
            comando = [
                qpdf, "--object-streams=generate", "--compress-streams=y",
                "--recompress-flate", "--compression-level=9",
            ]
            if progresso:
                comando.append("--progress")
            comando += [str(fonte), str(saida)]
            if progresso:
                processo = subprocess.Popen(
                    comando, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True, bufsize=1)
                inicio = time.monotonic()
                fluxo = processo.stdout
                try:
                    for linha in fluxo or ():
                        percentual = re.search(r"(\d{1,3})%", linha)
                        if percentual:
                            tamanho = (saida.stat().st_size
                                       if saida.is_file() else 0)
                            progresso(min(100, int(percentual.group(1))),
                                      tamanho)
                        if time.monotonic() - inicio > 600:
                            processo.kill(); processo.wait()
                            raise subprocess.TimeoutExpired(comando, 600)
                finally:
                    if fluxo:
                        fluxo.close()
                retorno = processo.wait()
                if retorno:
                    raise subprocess.CalledProcessError(retorno, comando)
            else:
                subprocess.run(comando, check=True, timeout=600,
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
            if (not saida.is_file()
                    or prep.n_paginas(str(saida)) != prep.n_paginas(str(fonte))):
                return False, {"disponivel": False,
                               "motivo": "validação da cópia falhou"}
            medida = medir_compactacao(fonte.stat().st_size,
                                       saida.stat().st_size)
            medida.update({"disponivel": True, "metodo": "qpdf sem perdas"})
            # So promovemos uma copia que de fato economize espaco. Acima de
            # 50 MB ela ainda e valida para envio, desde que caiba nos 500 MB.
            if (medida["contraproducente"]
                    or saida.stat().st_size > LIMITE_ENVIO_BYTES):
                medida["resultado"] = ("contraproducente" if
                                       medida["contraproducente"] else
                                       "acima do limite real")
                return False, medida
            destino.parent.mkdir(parents=True, exist_ok=True)
            lateral = destino.with_name(f".{destino.name}.{os.getpid()}.sem-perdas")
            try:
                shutil.copy2(saida, lateral)
                os.replace(lateral, destino)
            finally:
                if lateral.is_file():
                    lateral.unlink()
            medida["resultado"] = "aceito"
            return True, medida
    except (OSError, subprocess.SubprocessError) as exc:
        return False, {"disponivel": False,
                       "motivo": f"limpeza sem perdas falhou: {type(exc).__name__}"}


def estimar_compactacao_96(fonte, paginas_total):
    """Projeta o PDF integral por páginas distribuídas, sem alterar a fonte."""
    qpdf = shutil.which("qpdf")
    if not qpdf or paginas_total < 200:
        return {"disponivel": False, "motivo": "amostragem indisponível"}
    bloco = max(10, min(20, PAGINAS_AMOSTRA_COMPACTACAO // 7))
    max_inicio = max(1, paginas_total - bloco + 1)
    inicios = sorted({1 + round(i * (max_inicio - 1) / 6) for i in range(7)})
    faixas = [(inicio, min(paginas_total, inicio + bloco - 1))
              for inicio in inicios]
    paginas_amostra = sum(fim - inicio + 1 for inicio, fim in faixas)
    try:
        with tempfile.TemporaryDirectory(prefix="biblio-amostra-") as td:
            amostra = pathlib.Path(td) / "amostra.pdf"
            compacta = pathlib.Path(td) / "amostra-96.pdf"
            comando = [qpdf, "--empty", "--pages"]
            for inicio, fim in faixas:
                comando.extend([str(fonte), f"{inicio}-{fim}"])
            comando.extend(["--", str(amostra)])
            subprocess.run(comando, check=True, timeout=300,
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
            if not prep.otimizar_pdf_envio(
                    str(amostra), str(compacta), dpi_cor=96, dpi_mono=200):
                return {"disponivel": False,
                        "motivo": "falha ao compactar amostra"}
            tamanho_amostra = compacta.stat().st_size
            projecao = round(tamanho_amostra / paginas_amostra * paginas_total)
            return {
                "disponivel": True,
                "paginas_amostra": paginas_amostra,
                "paginas_total": paginas_total,
                "tamanho_amostra_bytes": tamanho_amostra,
                "projecao_bytes": projecao,
                "projecao_mb": round(projecao / 1_000_000, 2),
                "margem_decisao_mb": LIMITE_PROJECAO_EXCECAO / 1_000_000,
                "decisao": ("exceção projetada" if
                            projecao > LIMITE_PROJECAO_EXCECAO
                            else "prosseguir"),
                "faixas": [f"{inicio}-{fim}" for inicio, fim in faixas],
            }
    except (OSError, subprocess.SubprocessError) as exc:
        return {"disponivel": False,
                "motivo": f"amostragem falhou: {type(exc).__name__}"}


def monitor_progresso_compactacao(c, arquivo, paginas_total, dpi):
    inicio = time.monotonic()
    ultimo_percentual = -5
    ultima_atualizacao = 0.0

    def progresso(pagina):
        nonlocal ultimo_percentual, ultima_atualizacao
        agora_mono = time.monotonic()
        percentual = min(100, round(pagina / max(1, paginas_total) * 100))
        if (pagina not in (1, paginas_total)
                and percentual < ultimo_percentual + 5
                and agora_mono - ultima_atualizacao < 30):
            return
        decorrido = max(0.1, agora_mono - inicio)
        eta = round(decorrido / pagina * (paginas_total - pagina)) if pagina else None
        ultimo_percentual = percentual
        ultima_atualizacao = agora_mono
        atualizar_processamento_ativo(
            c, etapa="compactando", arquivo=pathlib.Path(arquivo).name,
            dpi=dpi, pagina=pagina, paginas=paginas_total,
            percentual=percentual, decorrido_segundos=round(decorrido),
            eta_segundos=eta)
        eta_texto = f"; faltam ~{max(0, eta) // 60} min" if eta is not None else ""
        print(f"    página {pagina}/{paginas_total} ({percentual}%){eta_texto}",
              flush=True)

    return progresso


def monitor_progresso_ocr(c, arquivo, paginas_total, bytes_origem):
    inicio = time.monotonic()
    ultimo_percentual = -5
    ultima_atualizacao = 0.0

    def progresso(concluidas, bytes_temporarios):
        nonlocal ultimo_percentual, ultima_atualizacao
        agora_mono = time.monotonic()
        percentual = min(100, round(
            concluidas / max(1, paginas_total) * 100))
        if (concluidas not in (1, paginas_total)
                and percentual < ultimo_percentual + 5
                and agora_mono - ultima_atualizacao < 30):
            return
        decorrido = max(0.1, agora_mono - inicio)
        eta = (round(decorrido / concluidas * (paginas_total - concluidas))
               if concluidas else None)
        bytes_percorridos = round(
            bytes_origem * concluidas / max(1, paginas_total))
        ultimo_percentual = percentual
        ultima_atualizacao = agora_mono
        atualizar_processamento_ativo(
            c, etapa="OCR com Apple Vision", arquivo=pathlib.Path(arquivo).name,
            pagina=concluidas, paginas=paginas_total,
            percentual=percentual, bytes_origem=bytes_origem,
            bytes_percorridos=bytes_percorridos,
            bytes_temporarios_processados=bytes_temporarios,
            decorrido_segundos=round(decorrido), eta_segundos=eta)
        eta_texto = f"; faltam ~{max(0, eta) // 60} min" if eta is not None else ""
        print(
            f"    OCR: {concluidas}/{paginas_total} ({percentual}%); "
            f"{bytes_percorridos/1_000_000:.1f}/{bytes_origem/1_000_000:.1f} MB"
            f"{eta_texto}", flush=True)

    return progresso


def monitor_progresso_limpeza(c, arquivo, bytes_origem):
    inicio = time.monotonic()
    ultimo_percentual = -10

    def progresso(percentual, bytes_saida):
        nonlocal ultimo_percentual
        if percentual < ultimo_percentual + 10 and percentual not in (0, 100):
            return
        ultimo_percentual = percentual
        decorrido = max(0.1, time.monotonic() - inicio)
        eta = (round(decorrido / percentual * (100 - percentual))
               if percentual else None)
        atualizar_processamento_ativo(
            c, etapa="limpeza sem perdas", arquivo=pathlib.Path(arquivo).name,
            percentual=percentual, bytes_origem=bytes_origem,
            bytes_saida_temporaria=bytes_saida,
            decorrido_segundos=round(decorrido), eta_segundos=eta)
        eta_texto = f"; faltam ~{max(0, eta) // 60} min" if eta is not None else ""
        print(f"    limpeza: {percentual}%; saída temporária "
              f"{bytes_saida/1_000_000:.1f} MB{eta_texto}", flush=True)

    return progresso


def anunciar_fase_arquivo(c, arquivo, item, itens_total,
                          fase, fases_total, descricao):
    """Mostra e registra a atividade atual; silencio nao parece travamento."""
    texto = f"fase {fase}/{fases_total} - {descricao}"
    print(f"  {texto}", flush=True)
    atualizar_processamento_ativo(
        c, etapa=texto, arquivo=pathlib.Path(arquivo).name,
        item=item, itens_total=itens_total, pagina=0, paginas=0,
        percentual=round((fase - 1) * 100 / max(1, fases_total)),
        eta_segundos=None)


def monitor_progresso_diagnostico(c, arquivo):
    """Expõe o avanço do diagnóstico textual e das páginas sem texto."""
    inicio = time.monotonic()
    ultimo = {}

    def progresso(fase, concluidas, total, pagina=None):
        percentual = min(100, round(concluidas / max(1, total) * 100))
        anterior = ultimo.get(fase, -10)
        if (concluidas not in (1, total)
                and percentual < anterior + 10):
            return
        ultimo[fase] = percentual
        decorrido = max(0.1, time.monotonic() - inicio)
        eta = (round(decorrido / concluidas * (total - concluidas))
               if concluidas else None)
        atualizar_processamento_ativo(
            c, etapa=f"diagnóstico de OCR: {fase}",
            arquivo=pathlib.Path(arquivo).name,
            pagina=pagina or concluidas, paginas=total,
            percentual=percentual, decorrido_segundos=round(decorrido),
            eta_segundos=eta)
        pagina_texto = (f"; página PDF {pagina}" if pagina is not None
                        and fase == "verificando páginas sem texto" else "")
        eta_texto = (f"; faltam ~{max(0, eta)} s"
                     if eta is not None and eta >= 2 else "")
        print(f"    OCR: {fase} {concluidas}/{total} ({percentual}%)"
              f"{pagina_texto}{eta_texto}", flush=True)

    return progresso


def preparar_pdf_automaticamente(c, origem, digest, paginas=None,
                                 fonte_preparada=None,
                                 progresso_diagnostico=None):
    """Corrige OCR e tamanho antes da catalogacao; nunca altera o original."""
    origem = pathlib.Path(origem).resolve()
    fonte_preparada = (pathlib.Path(fonte_preparada).resolve()
                       if fonte_preparada else None)
    if fonte_preparada and not fonte_preparada.is_file():
        fonte_preparada = None
    fonte = fonte_preparada or origem
    paginas = (paginas if paginas is not None
               else prep.paginas_pdftotext(str(fonte)))
    paginas_originais = prep.n_paginas(str(origem))
    diagnostico = prep.diagnosticar_ocr(
        str(fonte), paginas, progresso=progresso_diagnostico)
    preparado = fonte_preparada
    acoes = []
    erros = []
    tentativas_compactacao = []
    preflight_compactacao = {}
    diagnostico_estrutura = {}
    otimizacao_sem_perdas = {}

    if diagnostico["status"] != "OCR aprovado":
        preparado = c["preparados"] / f"{origem.stem}-{digest[:8]}.pdf"
        texto_idioma = "\n".join(paginas[:30]) or prep.texto_inicio(str(origem))
        idioma = prep.IDIOMA_OCR.get(prep.idioma_do_texto(texto_idioma),
                                     "por+eng+spa")
        print(f"  preparando OCR automaticamente com Apple Vision ({idioma})",
              flush=True)
        refazer = bool(diagnostico.get("paginas_pesquisaveis"))
        if prep.rodar_ocr(str(origem), str(preparado), idioma=idioma,
                          refazer=refazer, otimizar=3,
                          progresso=monitor_progresso_ocr(
                              c, origem.name, paginas_originais,
                              origem.stat().st_size)):
            fonte = preparado
            paginas = prep.paginas_pdftotext(str(fonte))
            diagnostico = prep.diagnosticar_ocr(
                str(fonte), paginas, progresso=progresso_diagnostico)
            acoes.append("OCR criado" if not refazer else "OCR refeito")
            if diagnostico["status"] != "OCR aprovado":
                erros.append("a copia ainda nao passou no diagnostico de OCR")
        else:
            preparado = None
            detalhe = prep.MOTOR.get("erro_ocr", "").strip()
            erros.append("falha ao criar OCR" + (f": {detalhe}" if detalhe else ""))

    if fonte.stat().st_size > LIMITE_OTIMIZACAO_BYTES:
        destino = (preparado or
                   c["preparados"] / f"{origem.stem}-{digest[:8]}.pdf")
        print(f"  otimizando copia para envio ({fonte.stat().st_size/1024/1024:.1f} MB)",
              flush=True)
        diagnostico_estrutura = diagnosticar_estrutura_pdf(
            fonte, origem.name + "\n" + "\n".join(paginas[:30]))
        if diagnostico_estrutura.get("disponivel"):
            print(
                f"    estrutura: {diagnostico_estrutura['imagens']} imagens, "
                f"{diagnostico_estrutura['fontes']} fontes; "
                f"JBIG2 {diagnostico_estrutura['proporcao_jbig2'] * 100:.0f}%",
                flush=True)
        atualizar_processamento_ativo(
            c, etapa="limpeza sem perdas", arquivo=origem.name,
            pagina=0, paginas=paginas_originais, percentual=0,
            eta_segundos=None)
        aceito_sem_perdas, otimizacao_sem_perdas = otimizar_pdf_sem_perdas(
            fonte, destino, progresso=monitor_progresso_limpeza(
                c, origem.name, fonte.stat().st_size))
        if otimizacao_sem_perdas.get("disponivel"):
            tentativa_sem_perdas = dict(otimizacao_sem_perdas)
            tentativa_sem_perdas.setdefault(
                "resultado", "acima do limite" if
                tentativa_sem_perdas.get("excesso_bytes") else "aceito")
            tentativas_compactacao.append(tentativa_sem_perdas)
            print(
                f"    limpeza sem perdas: "
                f"{otimizacao_sem_perdas['tamanho_mb']:.2f} MB; "
                f"redução {otimizacao_sem_perdas['reducao_percentual']:.2f}%",
                flush=True)
        if aceito_sem_perdas:
            fonte = destino
            preparado = destino
            paginas = prep.paginas_pdftotext(str(fonte))
            diagnostico = prep.diagnosticar_ocr(
                str(fonte), paginas, progresso=progresso_diagnostico)
            acoes.append("PDF otimizado sem perdas")
            return {
                "fonte": fonte, "preparado": preparado, "paginas": paginas,
                "diagnostico": diagnostico, "acoes": acoes, "erros": [],
                "hash_pdf_preparado": sha256(fonte),
                "tamanho_original": origem.stat().st_size,
                "tamanho_envio": fonte.stat().st_size,
                "paginas_originais": paginas_originais,
                "tentativas_compactacao": tentativas_compactacao,
                "preflight_compactacao": preflight_compactacao,
                "diagnostico_estrutura": diagnostico_estrutura,
                "otimizacao_sem_perdas": otimizacao_sem_perdas,
            }
        estrutura_sensivel = (
            diagnostico_estrutura.get("alfabeto_complexo")
            and diagnostico_estrutura.get("proporcao_jbig2", 0) >= 0.70
            and diagnostico_estrutura.get("fontes", 0)
                > max(100, paginas_originais * 5)
            and otimizacao_sem_perdas.get("disponivel"))
        if estrutura_sensivel:
            mensagem = (
                f"limpeza sem perdas resultou em "
                f"{otimizacao_sem_perdas['tamanho_mb']:.2f} MB; "
                "alfabeto complexo e imagens JBIG2 já otimizadas")
            print(f"    {mensagem}; preservando qualidade", flush=True)
            acoes.append("redução de resolução evitada para preservar escrita complexa")
            if diagnostico["status"] != "OCR aprovado":
                erros.append("OCR nao aprovado apos a preparacao")
            if fonte.stat().st_size > LIMITE_ENVIO_BYTES:
                erros.append(
                    f"arquivo preparado excede o limite real de "
                    f"{LIMITE_ENVIO_BYTES/1_000_000:.0f} MB")
            return {
                "fonte": fonte, "preparado": preparado, "paginas": paginas,
                "diagnostico": diagnostico, "acoes": acoes,
                "erros": list(dict.fromkeys(erros)),
                "hash_pdf_preparado": (sha256(fonte)
                                        if preparado and fonte.is_file() else ""),
                "tamanho_original": origem.stat().st_size,
                "tamanho_envio": fonte.stat().st_size,
                "paginas_originais": paginas_originais,
                "tentativas_compactacao": tentativas_compactacao,
                "preflight_compactacao": preflight_compactacao,
                "diagnostico_estrutura": diagnostico_estrutura,
                "otimizacao_sem_perdas": otimizacao_sem_perdas,
            }
        atualizar_processamento_ativo(
            c, etapa="estimando compactação", arquivo=origem.name,
            pagina=0, paginas=paginas_originais, percentual=0,
            eta_segundos=None)
        preflight_compactacao = estimar_compactacao_96(
            fonte, paginas_originais)
        if preflight_compactacao.get("disponivel"):
            print(
                f"    amostra de {preflight_compactacao['paginas_amostra']} páginas: "
                f"projeção {preflight_compactacao['projecao_mb']:.2f} MB",
                flush=True)
        if preflight_compactacao.get("decisao") == "exceção projetada":
            mensagem = (
                f"projeção de {preflight_compactacao['projecao_mb']:.2f} MB "
                f"em 96 dpi; encaminhar para exceção de tamanho")
            print(f"    {mensagem}; compactação integral evitada", flush=True)
            acoes.append("compactação integral evitada por amostragem")
            # A amostra serve para evitar uma regravação integral sem ganho;
            # nao bloqueia mais um arquivo que o novo servidor consegue receber.
            if diagnostico["status"] != "OCR aprovado":
                erros.append("OCR nao aprovado apos a preparacao")
            if fonte.stat().st_size > LIMITE_ENVIO_BYTES:
                erros.append(
                    f"arquivo preparado excede o limite real de "
                    f"{LIMITE_ENVIO_BYTES/1_000_000:.0f} MB")
            return {
                "fonte": fonte, "preparado": preparado, "paginas": paginas,
                "diagnostico": diagnostico, "acoes": acoes,
                "erros": list(dict.fromkeys(erros)),
                "hash_pdf_preparado": (sha256(fonte)
                                        if preparado and fonte.is_file() else ""),
                "tamanho_original": origem.stat().st_size,
                "tamanho_envio": fonte.stat().st_size,
                "paginas_originais": paginas_originais,
                "tentativas_compactacao": tentativas_compactacao,
                "preflight_compactacao": preflight_compactacao,
                "diagnostico_estrutura": diagnostico_estrutura,
                "otimizacao_sem_perdas": otimizacao_sem_perdas,
            }
        otimizou = False
        compactacao_contraproducente = False
        # O temporario fica fora do Dropbox. O sincronizador so conhece o
        # arquivo depois de completo, validado e promovido atomicamente.
        with tempfile.TemporaryDirectory(prefix="biblio-compactar-") as td:
            intermediario = pathlib.Path(td) / "compacto.pdf"
            residuo_ghostscript = pathlib.Path(str(intermediario) + ".tmp.pdf")
            # Cada tentativa parte da mesma fonte, sem repetir OCR. Começamos
            # em 120 dpi porque a experiência com volumes de centenas de
            # páginas mostrou que 150/135 dpi consumiam vários minutos e
            # frequentemente continuavam acima do limite da API.
            tentativas = selecionar_tentativas_compactacao(
                fonte.stat().st_size)
            if len(tentativas) == 1:
                print(
                    f"    arquivo com {fonte.stat().st_size / 1_000_000:.2f} MB; "
                    f"indo diretamente para {tentativas[0][0]} dpi",
                    flush=True)
                acoes.append("compactação direta em 96 dpi por tamanho elevado")
            indice = 0
            while indice < len(tentativas):
                dpi_cor, dpi_mono = tentativas[indice]
                if intermediario.is_file():
                    intermediario.unlink()
                otimizou = prep.otimizar_pdf_envio(
                    str(fonte), str(intermediario), dpi_cor=dpi_cor,
                    dpi_mono=dpi_mono,
                    progresso=monitor_progresso_compactacao(
                        c, origem.name, paginas_originais, dpi_cor))
                if residuo_ghostscript.is_file():
                    residuo_ghostscript.unlink()
                if otimizou and intermediario.is_file():
                    medida = medir_compactacao(
                        fonte.stat().st_size, intermediario.stat().st_size)
                    medida.update({"dpi_cor": dpi_cor, "dpi_mono": dpi_mono})
                    medida["resultado"] = (
                        "meta de 50 MB atingida" if medida["excesso_bytes"] == 0
                        else "reduzido, acima da meta de 50 MB")
                    tentativas_compactacao.append(medida)
                    print(
                        f"    {dpi_cor} dpi: {medida['tamanho_mb']:.2f} MB; "
                        f"redução {medida['reducao_percentual']:.2f}%; "
                        + ("dentro do limite" if not medida["excesso_bytes"]
                           else f"{medida['excesso_mb']:.2f} MB acima do limite"),
                        flush=True)
                else:
                    tentativas_compactacao.append({
                        "dpi_cor": dpi_cor, "dpi_mono": dpi_mono,
                        "resultado": "falha técnica"})
                    print(f"    {dpi_cor} dpi: falha técnica", flush=True)

                if (otimizou and intermediario.is_file()
                        and not tentativas_compactacao[-1].get("contraproducente")
                        and intermediario.stat().st_size <= LIMITE_ENVIO_BYTES):
                    acoes.append(f"PDF otimizado para envio ({dpi_cor} dpi)")
                    break
                otimizou = False
                # Se a própria regravação não reduziu o arquivo, resoluções
                # menores repetiriam um trabalho caro sobre um PDF cuja
                # estrutura não responde bem ao Ghostscript. Encaminhamos
                # imediatamente para a exceção de tamanho.
                if (indice == 0 and tentativas_compactacao[-1].get(
                        "contraproducente") is True):
                    tentativas_compactacao[-1]["resultado"] = "contraproducente"
                    print(
                        "    compactação aumentou ou não reduziu o arquivo; "
                        "interrompendo novas passagens",
                        flush=True)
                    acoes.append(
                        "compactação interrompida: primeira passagem não reduziu o arquivo")
                    compactacao_contraproducente = True
                    break
                # Se o primeiro passe quase não alterou o tamanho, o nível
                # intermediário tende a custar outra leitura integral sem
                # resolver. Saltamos diretamente para o último nível.
                if (indice == 0 and tentativas_compactacao[-1].get(
                        "ganho_relevante") is False):
                    if len(tentativas) == 1:
                        indice += 1
                        continue
                    print(
                        f"    ganho inferior a "
                        f"{GANHO_MINIMO_COMPACTACAO * 100:.0f}%; "
                        f"pulando {tentativas[1][0]} dpi e "
                        f"indo para {tentativas[-1][0]} dpi",
                        flush=True)
                    acoes.append("compactação intermediária ignorada por ganho ínfimo")
                    indice = len(tentativas) - 1
                else:
                    indice += 1
            if otimizou:
                try:
                    os.replace(intermediario, destino)
                except OSError as exc:
                    if exc.errno != errno.EXDEV:
                        raise
                    lateral = destino.with_name(
                        f".{destino.name}.{os.getpid()}.pronto")
                    try:
                        shutil.copy2(intermediario, lateral)
                        os.replace(lateral, destino)
                    finally:
                        if lateral.is_file():
                            lateral.unlink()
                fonte = destino
                preparado = destino
                paginas = prep.paginas_pdftotext(str(fonte))
                diagnostico = prep.diagnosticar_ocr(
                    str(fonte), paginas, progresso=progresso_diagnostico)
            else:
                # A tentativa foi registrada, mas o original pesquisavel e a
                # melhor copia segura. Ele segue normalmente se couber em 500 MB.
                acoes.append(
                    "original preservado após compactação contraproducente"
                    if compactacao_contraproducente else
                    "original preservado após falha de compactação")
                if fonte.stat().st_size > LIMITE_ENVIO_BYTES:
                    erros.append("falha ao reduzir o PDF abaixo do limite real")

    paginas_finais = prep.n_paginas(str(fonte))
    if paginas_originais and paginas_finais != paginas_originais:
        erros.append("a copia preparada alterou a quantidade de paginas")
    if diagnostico["status"] != "OCR aprovado":
        erros.append("OCR nao aprovado apos a preparacao")
    if fonte.stat().st_size > LIMITE_ENVIO_BYTES:
        erros.append(
            f"arquivo preparado excede o limite real de "
            f"{LIMITE_ENVIO_BYTES/1_000_000:.0f} MB")

    return {
        "fonte": fonte, "preparado": preparado, "paginas": paginas,
        "diagnostico": diagnostico, "acoes": acoes,
        "erros": list(dict.fromkeys(erros)),
        "hash_pdf_preparado": (sha256(fonte)
                                if preparado and fonte.is_file() else ""),
        "tamanho_original": origem.stat().st_size,
        "tamanho_envio": fonte.stat().st_size,
        "paginas_originais": paginas_originais,
        "tentativas_compactacao": tentativas_compactacao,
        "preflight_compactacao": preflight_compactacao,
        "diagnostico_estrutura": diagnostico_estrutura,
        "otimizacao_sem_perdas": otimizacao_sem_perdas,
    }


def limpar_residuos_temporarios(c):
    """Remove apenas temporarios internos, nunca originais ou copias finais."""
    removidos = 0
    bytes_removidos = 0
    for padrao in (".*-compacto.pdf.tmp.pdf", ".*-compacto.pdf"):
        for arquivo in c["preparados"].glob(padrao):
            if not arquivo.is_file() or arquivo.is_symlink():
                continue
            bytes_removidos += arquivo.stat().st_size
            arquivo.unlink()
            removidos += 1
    return removidos, bytes_removidos


def preparo_envio_pendente(registro, origem, ficha, raiz):
    """Detecta copia ausente ou grande demais antes de formar a fila da API."""
    if registro.get("estado") != "pronto para cadastro" or not origem.is_file():
        return False
    preparado_rel = ficha.get("pdf_preparado", "")
    candidato = raiz / preparado_rel if preparado_rel else origem
    if preparado_rel and not candidato.is_file():
        return True
    return candidato.is_file() and candidato.stat().st_size > LIMITE_ENVIO_BYTES


def excedeu_tamanho_apos_preparo(preparo):
    """Distingue excecao real de tamanho de uma pendencia bibliografica."""
    return (preparo.get("tamanho_envio", 0) > LIMITE_ENVIO_BYTES and
            any("otimizar" in erro or "excede" in erro
                for erro in preparo.get("erros", [])))


def ficha_existente(c, nome):
    p = c["metadados"] / (pathlib.Path(nome).stem + ".json")
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def registrar_existentes(raiz):
    c = inicializar(raiz)
    catalogo = carregar_catalogo(c)
    reservadas = {p.name for k, p in c.items() if k not in ("raiz",)}
    pdfs = [p for p in c["raiz"].iterdir()
            if p.is_file() and p.suffix.lower() == ".pdf"
            and p.parent.name not in reservadas]
    novos = repetidos = 0
    for p in sorted(pdfs):
        digest = sha256(p)
        if digest in catalogo["livros"]:
            ficha = ficha_existente(c, p.name)
            if ficha:
                registro = catalogo["livros"][digest]
                # O estado remoto e definitivo. Reindexar arquivos locais nunca
                # pode recolocar na fila um item que a API ja cadastrou.
                estado = registro.get("estado")
                if estado != "cadastrado":
                    estado = ficha.get("situacao", estado)
                registro.update({
                    "estado": estado,
                    "processado_em": ficha.get("gerado_em", ""),
                    "metadados": relativo(c, c["metadados"] / (p.stem + ".json")),
                    "capa": ficha.get("capa", ""),
                })
            repetidos += 1
            continue
        ficha = ficha_existente(c, p.name)
        estado = ficha.get("situacao", "legado registrado")
        catalogo["livros"][digest] = {
            "hash_sha256": digest,
            "arquivo": p.name,
            "caminho": relativo(c, p),
            "tamanho_bytes": p.stat().st_size,
            "estado": estado,
            "origem": "lote existente",
            "registrado_em": agora(),
            "processado_em": ficha.get("gerado_em", ""),
            "metadados": relativo(c, c["metadados"] / (p.stem + ".json")),
            "capa": ficha.get("capa", ""),
        }
        novos += 1
    salvar_catalogo(c, catalogo)
    consolidar(c, catalogo)
    print(f"Registrados: {novos}; ja conhecidos: {repetidos}; PDFs mantidos no lugar.")
    return novos


def gravar_ficha(c, digest, linha):
    nome = pathlib.Path(linha["arquivo"]).stem
    destino = c["metadados"] / f"{nome}-{digest[:8]}.json"
    ficha = {k: v for k, v in linha.items() if not k.startswith("_")}
    ficha["diagnostico_ocr"] = linha["_diagnostico_ocr"]
    ficha["evidencias"] = linha["_evidencias"]
    ficha["hash_sha256"] = digest
    ficha["gerado_em"] = agora()
    salvar_json(destino, ficha)
    return destino


def pistas_consulta_previa(origem):
    """Extrai pistas baratas: nunca cria OCR, capa ou copia compactada."""
    origem = pathlib.Path(origem)
    paginas = prep.paginas_pdftotext(str(origem), ate=30)
    revisao = prep.revisao_manual(str(origem))
    campos_revisao = revisao.get("campos", {}) if isinstance(revisao, dict) else {}
    documento = prep.metadados_pdf(str(origem))
    titulo_nome, autor_nome = prep.do_nome(origem.name)
    titulo_bruto = (campos_revisao.get("titulo") or documento.get("titulo")
                    or titulo_nome)
    autor_bruto = (campos_revisao.get("nmAutor0") or campos_revisao.get("autor")
                   or documento.get("autor") or autor_nome)
    titulo = (titulo_bruto if prep.titulo_bibliograficamente_plausivel(
        titulo_bruto) else "")
    autor = (autor_bruto if prep.autor_bibliograficamente_plausivel(
        autor_bruto) else "")
    autores = []
    for item in campos_revisao.get("autores", []) or []:
        nome = item.get("nome", "") if isinstance(item, dict) else str(item)
        if nome and prep.autor_bibliograficamente_plausivel(nome):
            autores.append(nome)
    if not autores and autor:
        autores = [autor]
    candidatos = prep.candidatos_isbn_paginas(paginas)
    candidatos += prep.candidatos_isbn(origem.name)
    isbn_revisado = prep.isbn_valido(campos_revisao.get("isbn", ""))
    if isbn_revisado:
        candidatos.append({
            "isbn": isbn_revisado, "rotulo": "revisão manual",
            "ctx": "", "linha": "", "formato": "impresso",
            "volume": "", "origem": "revisão manual",
        })
    isbn, origem_isbn = prep.escolher_isbn(candidatos, origem.name, None)
    return {"isbn": isbn, "origem_isbn": origem_isbn,
            "titulo": titulo, "autores": autores,
            "titulo_bruto": titulo_bruto, "autor_bruto": autor_bruto}


def consultar_duplicidade_antes_do_preparo(origem, sessao, chave):
    pistas = pistas_consulta_previa(origem)
    if not pistas["isbn"] and not (pistas["titulo"] and pistas["autores"]):
        return {}, pistas
    resposta = api_envio.consultar_livro(
        sessao, chave, isbn=pistas["isbn"], titulo=pistas["titulo"],
        autores=pistas["autores"], exato=False)
    return resposta, pistas


def autores_da_ficha(linha):
    """Normaliza os autores finais para a consulta de duplicidade no Biblio."""
    autores = []
    for item in linha.get("autores", []) or []:
        nome = item.get("nome", "") if isinstance(item, dict) else str(item)
        nome = str(nome).strip()
        if nome and nome not in autores:
            autores.append(nome)
    autor_principal = str(linha.get("nmAutor0", "")).strip()
    if not autores and autor_principal:
        autores.append(autor_principal)
    return autores


def consultar_duplicidade_apos_preparo(linha, sessao, chave):
    """Repete a consulta com a identidade definitiva descoberta no preparo."""
    isbn = str(linha.get("isbn", "")).strip()
    titulo = str(linha.get("titulo", "")).strip()
    autores = autores_da_ficha(linha)
    if not isbn and not (titulo and autores):
        return {}
    return api_envio.consultar_livro(
        sessao, chave, isbn=isbn, titulo=titulo, autores=autores, exato=False)


def _partes_pipe(valor):
    if isinstance(valor, list):
        return [str(v).strip() for v in valor if str(v).strip()]
    return [p.strip() for p in str(valor or "").split("|") if p.strip()]


def _campo_vazio(valor):
    if isinstance(valor, list):
        return not any(not _campo_vazio(v) for v in valor)
    if isinstance(valor, dict):
        return not any(not _campo_vazio(v) for v in valor.values())
    return not str(valor or "").strip()


def _campos_obrigatorios_revisao(ficha):
    tipo = str(ficha.get("tipo_documento", "livro") or "livro").strip().lower()
    return CAMPOS_REVISAO_POR_TIPO.get(tipo, CAMPOS_REVISAO_POR_TIPO["livro"])


def _aliases_campo_revisao(campo):
    return {
        "titulo": ("titulo", "título", "title"),
        "nmAutor0": ("nmAutor0", "autor", "autoria", "author"),
        "editora": ("editora", "editor", "publisher", "publicador"),
        "data": ("data", "ano", "publicacao", "publicação", "copyright"),
        "nmLingua": ("idioma", "lingua", "língua", "language"),
    }.get(campo, (campo,))


def diagnosticar_ausencias_revisao(ficha):
    """Transforma campo vazio em causa verificável para a revisão visual."""
    pendencias = _partes_pipe(ficha.get("pendencias", ""))
    rejeicoes = ficha.get("fontes_rejeitadas", []) or []
    evidencias = ficha.get("evidencias", []) or []
    resultado = []
    for campo in _campos_obrigatorios_revisao(ficha):
        if not _campo_vazio(ficha.get(campo, "")):
            continue
        aliases = _aliases_campo_revisao(campo)
        causas = [p for p in pendencias
                  if any(alias.casefold() in p.casefold()
                         for alias in aliases)]
        fontes_sem_resposta = []
        for rejeicao in rejeicoes:
            motivo = str(rejeicao.get("motivo", "")).strip()
            fonte = str(rejeicao.get("fonte", "")).strip()
            if fonte and motivo:
                fontes_sem_resposta.append(f"{fonte}: {motivo}")
        sugestao = _sugestao_campo_revisao(campo, ficha, evidencias)
        if not causas and fontes_sem_resposta:
            causas = fontes_sem_resposta[:5]
        if not causas:
            causas = ["campo ausente sem causa registrada - revisar fonte visual"]
        resultado.append({
            "campo": campo,
            "rotulo": _rotulo_campo_revisao(campo),
            "causas": causas,
            "sugestao": sugestao,
        })
    return resultado


def _rotulo_campo_revisao(campo):
    return {
        "titulo": "título",
        "nmAutor0": "autor principal",
        "editora": "editora",
        "data": "ano/data",
        "nmLingua": "idioma",
    }.get(campo, campo)


def _sugestao_campo_revisao(campo, ficha, evidencias):
    if campo == "titulo":
        return "ver capa, folha de rosto e bloco CIP; descarte frases promocionais"
    if campo == "nmAutor0":
        return "ver folha de rosto, página de créditos e CIP"
    if campo == "editora":
        return "ver página de créditos, CIP e rodapé editorial"
    if campo == "data":
        return "ver copyright, edição, ficha catalográfica e expediente"
    if campo == "nmLingua":
        return "inferir pela língua predominante do texto, não pelo nome do arquivo"
    return "conferir visualmente no PDF e nas evidências coletadas"


def _ler_ficha_registro(c, registro):
    ficha_path = c["raiz"] / registro.get("metadados", "")
    if not ficha_path.is_file():
        return ficha_path, {}
    try:
        ficha = json.loads(ficha_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return ficha_path, {}
    # A bancada visual grava decisões humanas em revisoes-manuais.json.
    # Antes desta mesclagem, reabrir a bancada mostrava a ficha automática
    # antiga, dando a impressão de que o trabalho manual havia sido perdido.
    # A revisão só é aplicada quando o hash do PDF confere, via
    # prep.revisao_manual, para não contaminar outro arquivo com mesmo nome.
    pdf = _arquivo_do_registro(c, registro)
    revisao = prep.revisao_manual(str(pdf)) if pdf else {}
    campos_revisados = revisao.get("campos", {}) if isinstance(revisao, dict) else {}
    if campos_revisados:
        ficha.update({k: v for k, v in campos_revisados.items()
                      if not k.startswith("_")})
        ficha["revisao_manual_aplicada"] = True
        ficha["revisao_manual_aprovada"] = bool(revisao.get("aprovado"))
        ficha["revisao_manual_atualizada_em"] = revisao.get("atualizado_em", "")
    return ficha_path, ficha


def _localizar_registro(c, catalogo, arquivo):
    alvo = str(arquivo or "").strip()
    if not alvo:
        return None, None
    alvo_path = pathlib.Path(alvo)
    for digest, registro in catalogo.get("livros", {}).items():
        caminhos_possiveis = {
            registro.get("arquivo", ""),
            registro.get("caminho", ""),
            pathlib.Path(registro.get("caminho", "")).name,
        }
        if alvo in caminhos_possiveis or alvo_path.name in caminhos_possiveis:
            return digest, registro
    return None, None


def _caminho_visualizacao(c, ficha, registro):
    for chave in ("pdf_preparado", "pdf_original"):
        rel = ficha.get(chave, "")
        if rel and (c["raiz"] / rel).is_file():
            return relativo(c, c["raiz"] / rel)
    arquivo = _arquivo_do_registro(c, registro)
    return relativo(c, arquivo) if arquivo else ""


def paginas_sugeridas_revisao(c, ficha, registro, limite_paginas=40):
    """Indica páginas internas úteis, não apenas a capa.

    A revisão visual precisa olhar o material: folha de rosto, CIP,
    créditos, sumário e páginas onde apareceram ISBN/editora/autor. O pacote
    guarda pequenos trechos para guiar a tela futura sem abrir o PDF inteiro.
    """
    rel = _caminho_visualizacao(c, ficha, registro)
    pdf = c["raiz"] / rel if rel else None
    if not pdf or not pdf.is_file() or pdf.suffix.lower() != ".pdf":
        return []
    try:
        paginas = prep.paginas_pdftotext(str(pdf), ate=limite_paginas)
    except Exception:
        paginas = []
    marcadores = (
        ("ficha catalográfica/CIP", re.compile(
            r"(?i)\b(?:ficha catalogr[aá]fica|dados internacionais de "
            r"cataloga[çc][aã]o|cataloging[ -]in[ -]publication|CDD|CDU)\b")),
        ("ISBN/código editorial", re.compile(r"(?i)\b(?:ISBN|EAN)\b")),
        ("créditos/copyright", re.compile(
            r"(?i)\b(?:copyright|direitos reservados|publicado por|"
            r"published by|editora|publisher|imprensa|press)\b|[©℗]")),
        ("sumário/expediente", re.compile(
            r"(?i)\b(?:sum[aá]rio|[ií]ndice|contents|expediente)\b")),
        ("resumo/abstract", re.compile(r"(?i)\b(?:resumo|abstract)\b")),
        ("capa/folha de rosto", re.compile(
            r"(?i)\b(?:autor|organizad[oa]r|editor(?:a|ial)?|t[ií]tulo)\b")),
    )
    vistos = set()
    sugestoes = []

    def adicionar(numero, motivo, texto):
        if numero in vistos:
            for item in sugestoes:
                if item["pagina"] == numero and motivo not in item["motivo"]:
                    item["motivo"] = f"{item['motivo']} / {motivo}"
            return
        vistos.add(numero)
        linhas = [x.strip() for x in str(texto or "").splitlines() if x.strip()]
        trecho = " ".join(linhas[:8])[:900]
        sugestoes.append({
            "pagina": numero,
            "motivo": motivo,
            "trecho": trecho,
        })

    for numero in (1, 2, 3):
        if numero <= len(paginas):
            adicionar(numero, "começo do material", paginas[numero - 1])
    for numero, texto in enumerate(paginas, 1):
        for motivo, padrao in marcadores:
            if padrao.search(texto or ""):
                adicionar(numero, motivo, texto)
                break
        if len(sugestoes) >= 10:
            break
    return sugestoes


def buscar_isbn_para_revisao(c, ficha, registro, limite_paginas=40):
    """Lista ISBNs válidos e suspeitos para conferência humana."""
    rel = _caminho_visualizacao(c, ficha, registro)
    pdf = c["raiz"] / rel if rel else None
    if not pdf or not pdf.is_file() or pdf.suffix.lower() != ".pdf":
        return {"validos": [], "suspeitos": [], "motivo": "PDF não disponível"}
    try:
        paginas = prep.paginas_pdftotext(str(pdf), ate=limite_paginas)
    except Exception:
        paginas = []
    validos = []
    suspeitos = []
    for numero, texto in enumerate(paginas, 1):
        for candidato in prep.candidatos_isbn(texto or ""):
            item = dict(candidato)
            item["pagina"] = numero
            if not any(x["isbn"] == item["isbn"] for x in validos):
                validos.append(item)
        if prep.conferir_identidade:
            for suspeito in prep.conferir_identidade.isbns_suspeitos_no_texto(
                    texto or ""):
                correcoes = prep.conferir_identidade.candidatos_um_digito(
                    suspeito)
                trecho = ""
                achado = re.search(
                    r"(?i)ISBN.{0,80}" + re.escape(suspeito[:4]), texto or "")
                if achado:
                    inicio = max(0, achado.start() - 80)
                    fim = min(len(texto), achado.end() + 160)
                    trecho = " ".join((texto or "")[inicio:fim].split())
                if not any(x["valor"] == suspeito for x in suspeitos):
                    suspeitos.append({
                        "valor": suspeito,
                        "pagina": numero,
                        "correcoes_um_digito": correcoes,
                        "trecho": trecho[:500],
                    })
    motivo = ("ISBN válido localizado" if validos else
              "ISBN suspeito localizado; exige conferência visual"
              if suspeitos else
              "nenhum ISBN localizado nas páginas lidas")
    return {"validos": validos, "suspeitos": suspeitos, "motivo": motivo}


def _campos_revisao_de_fonte(fonte, isbn):
    """Traduz uma resposta bibliográfica externa para campos da nossa ficha."""
    autores = str(fonte.get("autores") or fonte.get("autor") or "").strip()
    autor_principal = autores.split(";")[0].strip() if autores else ""
    assuntos = str(fonte.get("assuntos") or fonte.get("assunto") or "").strip()
    campos = {
        "titulo": str(fonte.get("titulo") or "").strip(),
        "subTitulo": str(fonte.get("subtitulo") or fonte.get("subTitulo")
                         or fonte.get("titulo_publicacao") or "").strip(),
        "nmAutor0": autor_principal,
        "autores_texto": autores,
        "editora": str(fonte.get("editora") or "").strip(),
        "isbn": prep.isbn_valido(fonte.get("isbn", "")) or isbn,
        "data": str(fonte.get("ano") or fonte.get("data") or "").strip(),
        "nPaginas": str(fonte.get("paginas") or fonte.get("nPaginas")
                        or "").strip(),
        "lugar": str(fonte.get("lugar_fonte") or fonte.get("lugar")
                     or "").strip(),
        "CDD": str(fonte.get("cdd") or fonte.get("CDD") or "").strip(),
        "assunto": assuntos,
        "pchave": assuntos,
    }
    return {k: v for k, v in campos.items() if str(v or "").strip()}


def _pontuar_fonte_isbn(fonte):
    pontos = 0
    for campo, peso in (
            ("titulo", 5), ("autores", 4), ("editora", 3), ("ano", 2),
            ("paginas", 2), ("assuntos", 1), ("cdd", 1), ("lugar_fonte", 1)):
        if fonte.get(campo):
            pontos += peso
    nome = str(fonte.get("fonte") or "")
    if "CBL" in nome:
        pontos += 3
    elif "Library of Congress" in nome:
        pontos += 2
    elif "Google" in nome or "OpenLibrary" in nome or "Open Library" in nome:
        pontos += 1
    return pontos


def links_busca_isbn_revisao(isbn):
    numero = prep.isbn_valido(isbn) or re.sub(r"[^0-9Xx]", "", str(isbn or ""))
    if not numero:
        return []
    from urllib.parse import quote_plus
    consultas = [
        ("Google — ISBN exato", f'"{numero}" livro'),
        ("Google — Touché Livros", f'site:touchelivros.com.br "{numero}"'),
        ("Google — Estante Virtual", f'site:estantevirtual.com.br "{numero}"'),
        ("Google — Amazon Brasil", f'site:amazon.com.br "{numero}"'),
        ("Google Books", f'isbn:{numero}'),
    ]
    return [
        {"rotulo": rotulo,
         "url": f"https://www.google.com/search?q={quote_plus(consulta)}"}
        for rotulo, consulta in consultas
    ]


def consultar_metadados_isbn_revisao(raiz, isbn, arquivo="", atualizar=False,
                                     imprimir=True):
    """Consulta fontes bibliográficas por ISBN para auxiliar a revisão visual.

    Não altera catálogo, não move arquivo e não aprova ficha. Apenas usa cache
    local e devolve campos que o revisor pode aceitar ou ajustar.
    """
    c = inicializar(raiz)
    numero = prep.isbn_valido(isbn)
    if not numero:
        raise RuntimeError("ISBN inválido; informe ISBN-10 ou ISBN-13 completo")
    catalogo = carregar_catalogo(c)
    pdf = None
    if arquivo:
        _, registro = _localizar_registro(c, catalogo, arquivo)
        pdf = _arquivo_do_registro(c, registro) if registro else None
    referencia_cache = pdf or (c["revisao"] / f"consulta-isbn-{numero}.pdf")
    fontes = []
    erros = []
    sessao = None

    def tentar(nome, func, *args):
        try:
            resultado = func(*args)
        except Exception as exc:
            erros.append({"fonte": nome, "erro": str(exc)})
            return
        if not resultado:
            return
        itens = resultado if isinstance(resultado, list) else [resultado]
        for item in itens:
            if not isinstance(item, dict):
                continue
            item = dict(item)
            item.setdefault("fonte", nome)
            item["isbn_consultado"] = numero
            item["campos"] = _campos_revisao_de_fonte(item, numero)
            item["pontuacao_revisao"] = _pontuar_fonte_isbn(item)
            fontes.append(item)

    if prep.consultar_cbl and prep.consultar_cbl.isbn_brasileiro(numero):
        tentar("CBL/ISBN Brasil", prep.consultar_cbl.consultar, numero,
               prep.consultar_cbl.pasta_cache_para_pdf(referencia_cache),
               sessao, atualizar)
    if prep.fontes_biblio:
        cache = prep.fontes_biblio.pasta_cache_para_pdf(referencia_cache)
        tentar("Open Library", prep.fontes_biblio.consultar_open_library,
               numero, cache, sessao, atualizar)
        tentar("Google Books", prep.fontes_biblio.consultar_google_books,
               numero, cache, sessao, atualizar)
        tentar("Library of Congress",
               prep.fontes_biblio.consultar_library_of_congress,
               numero, cache, sessao, atualizar)
        tentar("HathiTrust", prep.fontes_biblio.consultar_hathitrust,
               numero, cache, sessao, atualizar)
        try:
            candidatos_bnf = prep.fontes_biblio.consultar_bnf(
                numero, cache, sessao, atualizar)
            if candidatos_bnf:
                escolhido, motivo = prep.fontes_biblio.resolver_candidatos(
                    candidatos_bnf)
                if escolhido:
                    tentar("BnF", lambda: escolhido)
                else:
                    erros.append({"fonte": "BnF", "erro": motivo})
        except Exception as exc:
            erros.append({"fonte": "BnF", "erro": str(exc)})
    else:
        tentar("OpenLibrary", prep.open_library, numero)
        tentar("GoogleBooks", prep.google_books, numero)

    fontes.sort(key=lambda x: x.get("pontuacao_revisao", 0), reverse=True)
    melhor = fontes[0] if fontes else {}
    resposta = {
        "isbn": numero,
        "encontrado": bool(fontes),
        "melhor": melhor,
        "campos": melhor.get("campos", {}) if melhor else {},
        "fontes": fontes,
        "erros": erros,
        "links_busca": links_busca_isbn_revisao(numero),
    }
    if imprimir:
        print(json.dumps(resposta, ensure_ascii=False, indent=2))
    return resposta


def diagnosticar_tipo_material_revisao(c, ficha, registro, limite_paginas=12):
    """Mostra sinais que sustentam ou questionam a classificação do material."""
    tipo = str(ficha.get("tipo_documento", "") or "livro").strip().lower()
    rel = _caminho_visualizacao(c, ficha, registro)
    pdf = c["raiz"] / rel if rel else None
    try:
        paginas = (prep.paginas_pdftotext(str(pdf), ate=limite_paginas)
                   if pdf and pdf.is_file() and pdf.suffix.lower() == ".pdf"
                   else [])
    except Exception:
        paginas = []
    texto = "\n".join(paginas or [])
    sinais = []
    if re.search(r"(?i)\b(?:ISBN|ficha catalogr[aá]fica|CDD|CDU|copyright)\b", texto):
        sinais.append({"tipo": "livro", "sinal": "ISBN/CIP/copyright editorial"})
    if re.search(r"(?i)\b(?:revista|magazine|journal|per[ií]odico|boletim)\b", texto):
        sinais.append({"tipo": "revista/artigo", "sinal": "vocabulário de periódico"})
    if re.search(r"(?i)\b(?:resumo|abstract|palavras-chave|keywords)\b", texto):
        sinais.append({"tipo": "artigo/acadêmico", "sinal": "resumo ou palavras-chave"})
    if re.search(r"(?i)\b(?:tese|disserta[çc][aã]o|monografia|orientador|banca examinadora)\b", texto):
        sinais.append({"tipo": "tese/dissertação", "sinal": "estrutura acadêmica"})
    if re.search(r"(?i)\b(?:plano de aula|aula\s+\d+|li[çc][aã]o\s+\d+|slides?|powerpoint)\b", texto):
        sinais.append({"tipo": "documento/apostila", "sinal": "material didático ou apresentação"})
    if re.search(r"(?i)\b(?:serm[aã]o|pregação|estudo bíblico|célula)\b", texto):
        sinais.append({"tipo": "documento/sermão", "sinal": "material ministerial"})
    if not sinais and ficha.get("isbn"):
        sinais.append({"tipo": "livro", "sinal": "ISBN já coletado na ficha"})
    fila = ("livros" if tipo == "livro" else
            "teses/dissertações" if tipo in TIPOS_ACADEMICOS else
            "revistas/periódicos" if tipo in TIPOS_REVISTAS else
            "documentos")
    contradicoes = []
    tipos_sugeridos = {s["tipo"] for s in sinais}
    if tipo == "livro" and any("documento" in t or "artigo" in t
                               or "tese" in t for t in tipos_sugeridos):
        contradicoes.append("tipo atual é livro, mas há sinais de outro material")
    if tipo in TIPOS_DOCUMENTOS and any(t == "livro" for t in tipos_sugeridos):
        contradicoes.append("tipo atual é documento, mas há sinais de livro publicado")
    if tipo in TIPOS_REVISTAS and any("artigo" in t for t in tipos_sugeridos):
        contradicoes.append("distinguir revista completa de artigo avulso")
    return {
        "tipo_atual": tipo,
        "fila_provavel": fila,
        "sinais": sinais,
        "contradicoes": contradicoes,
        "orientacao": (
            "corrija o campo tipo_documento antes de validar"
            if contradicoes else
            "tipo atual sem contradição forte nas páginas lidas"),
    }


def montar_pacote_revisao(c, digest, registro):
    """Dossiê único para a futura bancada visual de revisão."""
    ficha_path, ficha = _ler_ficha_registro(c, registro)
    conflitos = _partes_pipe(ficha.get("conflitos", ""))
    pendencias = _partes_pipe(ficha.get("pendencias", ""))
    ausencias = diagnosticar_ausencias_revisao(ficha)
    return {
        "hash_sha256": digest,
        "arquivo": registro.get("arquivo", ""),
        "estado": registro.get("estado", ""),
        "pdf_visualizacao": _caminho_visualizacao(c, ficha, registro),
        "capa": ficha.get("capa", "") or registro.get("capa", ""),
        "ficha": relativo(c, ficha_path) if ficha_path else "",
        "campos": {campo: ficha.get(campo, "") for campo in (
            "titulo", "subTitulo", "nmAutor0", "autores", "editora", "isbn",
            "edicao", "data", "nPaginas", "lugar", "nmLingua", "tipo_documento",
            "CDD", "assunto", "pchave", "abstract")},
        "conflitos": conflitos,
        "pendencias": pendencias,
        "ausencias": ausencias,
        "fontes_revisao": _partes_pipe(ficha.get("fontes_revisao", "")),
        "fontes_rejeitadas": ficha.get("fontes_rejeitadas", []) or [],
        "evidencias": ficha.get("evidencias", []) or [],
        "paginas_sugeridas": paginas_sugeridas_revisao(c, ficha, registro),
        "busca_isbn": buscar_isbn_para_revisao(c, ficha, registro),
        "classificacao_material": diagnosticar_tipo_material_revisao(
            c, ficha, registro),
        "acoes_sugeridas": acoes_sugeridas_revisao(ficha, conflitos, ausencias),
    }


def acoes_sugeridas_revisao(ficha, conflitos, ausencias):
    acoes = []
    if ficha.get("capa"):
        acoes.append("abrir capa e PDF para confirmação visual")
    else:
        acoes.append("gerar ou conferir capa antes da decisão")
    if conflitos:
        acoes.append("validar qual fonte vence e gravar revisão manual")
    if ausencias:
        acoes.append("preencher somente campos confirmados; deixar causa nos demais")
    if ficha.get("fontes_rejeitadas"):
        acoes.append("usar motivos de rejeição para melhorar busca futura")
    if not conflitos and not ausencias:
        acoes.append("validar ficha e marcar como aprovada para reprocessar")
    return acoes


def pacotes_revisao(raiz, arquivo=None, limite=20, imprimir=True):
    c = inicializar(raiz)
    catalogo = carregar_catalogo(c)
    itens = []
    if arquivo:
        digest, registro = _localizar_registro(c, catalogo, arquivo)
        if registro:
            itens.append(montar_pacote_revisao(c, digest, registro))
    else:
        for digest, registro in sorted(
                catalogo.get("livros", {}).items(),
                key=lambda x: (x[1].get("estado", ""), x[1].get("arquivo", ""))):
            if str(digest).startswith("duplicado:"):
                continue
            ficha_path, ficha = _ler_ficha_registro(c, registro)
            estado = str(registro.get("estado", "") or "")
            # A revisão humana aprovada e os estados prontos são terminais
            # para a bancada visual. A ficha pode manter pendências antigas
            # da extração automática como histórico, mas elas não devem
            # recolocar o item na correção manual.
            if (ficha.get("revisao_manual_aprovada")
                    or estado in ESTADOS_TERMINAIS_REVISAO_VISUAL
                    or registro.get("arquivos_liberados_em")):
                continue
            if (registro.get("estado") in ESTADOS_REVISAO_VISUAL
                    or _partes_pipe(ficha.get("conflitos", ""))
                    or diagnosticar_ausencias_revisao(ficha)):
                itens.append(montar_pacote_revisao(c, digest, registro))
            if limite and len(itens) >= limite:
                break
    resumo = {
        "total": len(itens),
        "limite": limite,
        "itens": itens,
    }
    if imprimir:
        print(json.dumps(resumo, ensure_ascii=False, indent=2))
    return resumo


def _carregar_revisoes(c):
    caminho = c["controle"] / "revisoes-manuais.json"
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        dados = {"versao": 1, "livros": {}}
    dados.setdefault("livros", {})
    return caminho, dados


def _salvar_snapshot_revisao_manual(c, registro, ficha_antes, ficha_depois,
                                    revisao):
    """Guarda uma cópia auditável de cada salvamento feito na bancada."""
    pasta = c["controle"] / "revisoes-manuais-snapshots"
    arquivo_base = pathlib.Path(registro.get("arquivo", "item")).stem
    carimbo = agora().replace(":", "-")
    destino = pasta / f"{carimbo}-{arquivo_base}.json"
    salvar_json(destino, {
        "arquivo": registro.get("arquivo", ""),
        "hash_sha256": revisao.get("hash_sha256", ""),
        "salvo_em": revisao.get("atualizado_em", agora()),
        "campos_revisao": revisao.get("campos", {}),
        "ficha_antes": ficha_antes,
        "ficha_depois": ficha_depois,
    })
    return destino


def _adicionar_ruido_memoria(arquivo, texto, modo, motivo):
    texto = str(texto or "").strip()
    if not texto:
        return False
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        dados = {"versao": 1, "itens": []}
    itens = dados.setdefault("itens", [])
    chave = (prep.identificar.normalizar(texto), modo)
    existentes = {
        (prep.identificar.normalizar(i.get("texto", "")), i.get("modo", "exato"))
        for i in itens if isinstance(i, dict)
    }
    if chave in existentes:
        return False
    itens.append({"texto": texto, "modo": modo, "motivo": motivo})
    dados["atualizado_em"] = agora()
    salvar_json(arquivo, dados)
    return True


def _extensao_imagem_manual(url, content_type, dados):
    content_type = str(content_type or "").split(";")[0].strip().lower()
    if dados.startswith(b"\xff\xd8"):
        return ".jpg"
    if dados.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if dados.startswith(b"GIF87a") or dados.startswith(b"GIF89a"):
        return ".gif"
    if len(dados) >= 12 and dados[:4] == b"RIFF" and dados[8:12] == b"WEBP":
        return ".webp"
    if content_type in {"image/jpeg", "image/jpg"}:
        return ".jpg"
    if content_type == "image/png":
        return ".png"
    if content_type == "image/gif":
        return ".gif"
    if content_type == "image/webp":
        return ".webp"
    sufixo = pathlib.Path(urllib.parse.urlparse(url).path).suffix.lower()
    if sufixo in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
        return ".jpg" if sufixo == ".jpeg" else sufixo
    return ""


def _baixar_capa_manual(url):
    url = str(url or "").strip()
    partes = urllib.parse.urlparse(url)
    if partes.scheme not in {"http", "https"} or not partes.netloc:
        raise RuntimeError("informe uma URL completa da capa, começando por http:// ou https://")
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 Biblio-Revisor/1.0 "
                "(capa manual indicada pelo operador)"
            )
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        tamanho = resp.headers.get("Content-Length") or resp.getheader("Content-Length")
        if tamanho and int(tamanho) > LIMITE_CAPA_MANUAL_BYTES:
            raise RuntimeError("a imagem da capa é grande demais para baixar pela revisão")
        dados = resp.read(LIMITE_CAPA_MANUAL_BYTES + 1)
        content_type = resp.headers.get_content_type()
    if len(dados) > LIMITE_CAPA_MANUAL_BYTES:
        raise RuntimeError("a imagem da capa é grande demais para baixar pela revisão")
    ext = _extensao_imagem_manual(url, content_type, dados)
    if not ext:
        raise RuntimeError("a URL informada não parece apontar para uma imagem de capa")
    return dados, ext, content_type


def _salvar_capa_manual_revisao(c, catalogo, digest, registro, ficha_path,
                                dados, ext, origem, content_type,
                                imprimir=True):
    try:
        ficha = json.loads(ficha_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        ficha = {}
    base = pathlib.Path(registro.get("arquivo", "")).stem
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-._") or digest[:12]
    destino = c["capas"] / f"{base}-capa-manual{ext}"
    if destino.exists():
        destino = c["capas"] / f"{base}-capa-manual-{digest[:8]}{ext}"
    destino.write_bytes(dados)
    rel = relativo(c, destino)
    atualizado_em = agora()
    ficha["capa"] = rel
    ficha["capa_manual_origem"] = origem
    ficha["capa_manual_content_type"] = content_type
    ficha["capa_manual_atualizada_em"] = atualizado_em
    salvar_json(ficha_path, ficha)
    registro["capa"] = rel
    registro["capa_manual_origem"] = origem
    registro["capa_manual_atualizada_em"] = atualizado_em
    salvar_catalogo(c, catalogo)
    resultado = {
        "arquivo": registro.get("arquivo", ""),
        "capa": rel,
        "bytes": len(dados),
        "content_type": content_type,
        "atualizado_em": atualizado_em,
    }
    if imprimir:
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return resultado


def _registro_para_capa_manual(raiz, arquivo):
    c = inicializar(raiz)
    catalogo = carregar_catalogo(c)
    digest, registro = _localizar_registro(c, catalogo, arquivo)
    if not registro:
        raise RuntimeError(f"arquivo não encontrado no catálogo: {arquivo}")
    ficha_path, _ = _ler_ficha_registro(c, registro)
    if not ficha_path or not ficha_path.is_file():
        raise RuntimeError(f"ficha de metadados não encontrada para: {arquivo}")
    return c, catalogo, digest, registro, ficha_path


def substituir_capa_revisao(raiz, arquivo, url, imprimir=True):
    """Baixa uma capa indicada por URL e atualiza ficha e catálogo."""
    c, catalogo, digest, registro, ficha_path = _registro_para_capa_manual(
        raiz, arquivo)
    dados, ext, content_type = _baixar_capa_manual(url)
    return _salvar_capa_manual_revisao(
        c, catalogo, digest, registro, ficha_path, dados, ext,
        str(url).strip(), content_type, imprimir=imprimir)


def substituir_capa_arquivo_revisao(raiz, arquivo, nome, conteudo_base64,
                                    imprimir=True):
    """Recebe uma capa enviada pelo navegador e atualiza ficha e catálogo."""
    c, catalogo, digest, registro, ficha_path = _registro_para_capa_manual(
        raiz, arquivo)
    try:
        dados = base64.b64decode(str(conteudo_base64 or ""), validate=True)
    except (ValueError, TypeError) as exc:
        raise RuntimeError("não foi possível ler o arquivo de capa enviado") from exc
    if not dados:
        raise RuntimeError("o arquivo de capa está vazio")
    if len(dados) > LIMITE_CAPA_MANUAL_BYTES:
        raise RuntimeError("a imagem da capa é grande demais para gravar pela revisão")
    ext = _extensao_imagem_manual(str(nome or ""), "", dados)
    if not ext:
        raise RuntimeError("o arquivo enviado não parece ser uma imagem de capa")
    origem = f"arquivo local: {pathlib.Path(str(nome or 'capa')).name}"
    content_type = {
        ".jpg": "image/jpeg", ".png": "image/png", ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(ext, "image/*")
    return _salvar_capa_manual_revisao(
        c, catalogo, digest, registro, ficha_path, dados, ext, origem,
        content_type, imprimir=imprimir)


def _destino_aprovado_revisao(c, tipo):
    tipo = str(tipo or "livro").strip().lower()
    if tipo in TIPOS_ACADEMICOS:
        return c["academicos"], "pronto para cadastro específico"
    if tipo in TIPOS_DOCUMENTOS:
        return c["documentos"], "pronto para cadastro específico"
    if tipo in TIPOS_REVISTAS:
        return c["revistas"], "pronto para cadastro específico"
    return c["pronto"], "pronto para cadastro"


def _mover_aprovado_revisao(c, digest, registro, ficha):
    pdf = _arquivo_do_registro(c, registro)
    pasta, estado = _destino_aprovado_revisao(
        c, ficha.get("tipo_documento") or "livro")
    if pdf and pdf.is_file():
        destino = pdf if pdf.parent.resolve() == pasta.resolve() else mover_sem_substituir(
            pdf, pasta, digest)
        registro["arquivo"] = destino.name
        registro["caminho"] = relativo(c, destino)
        registro["tamanho_bytes"] = destino.stat().st_size
        ficha["arquivo"] = destino.name
        ficha["pdf_original"] = relativo(c, destino)
    registro["estado"] = estado
    registro["processado_em"] = agora()
    ficha["situacao"] = estado
    ficha["situacao_metadados"] = estado
    return estado


def gravar_decisao_revisao(raiz, arquivo, campos=None, aprovado=True,
                           justificativa="revisão visual",
                           fontes=None, conflitos=None, pendencias=None,
                           ruidos_titulo=None, ruidos_autor=None,
                           confirmacao_soberana=False,
                           motivo_confirmacao="",
                           imprimir=True):
    """Grava decisão humana por hash e alimenta memórias de aprendizado."""
    c = inicializar(raiz)
    catalogo = carregar_catalogo(c)
    digest, registro = _localizar_registro(c, catalogo, arquivo)
    if not registro:
        raise RuntimeError(f"arquivo não encontrado no catálogo: {arquivo}")
    pdf = _arquivo_do_registro(c, registro)
    if not pdf:
        raise RuntimeError(f"PDF não encontrado para revisão: {arquivo}")
    ficha_path, ficha = _ler_ficha_registro(c, registro)
    revisoes_path, revisoes = _carregar_revisoes(c)
    anterior = revisoes["livros"].get(registro.get("arquivo", ""), {})
    campos_mesclados = dict(anterior.get("campos", {}))
    campos_mesclados.update(campos or {})
    revisao = {
        **anterior,
        "hash_sha256": sha256(pdf),
        "campos": campos_mesclados,
        "fontes": list(dict.fromkeys((anterior.get("fontes", []) or [])
                                     + (fontes or ["revisão visual"]))),
        "justificativa": justificativa,
        "aprovado": bool(aprovado),
        "confirmacao_soberana": bool(confirmacao_soberana),
        "motivo_confirmacao_soberana": str(motivo_confirmacao or "").strip(),
        "atualizado_em": agora(),
    }
    if conflitos is not None:
        revisao["conflitos"] = conflitos
    if pendencias is not None:
        revisao["pendencias"] = pendencias
    revisoes["livros"][registro.get("arquivo", "")] = revisao
    revisoes["atualizado_em"] = agora()
    salvar_json(revisoes_path, revisoes)
    if ficha_path and ficha_path.is_file():
        ficha_atualizada = dict(ficha)
        ficha_atualizada.update({k: v for k, v in campos_mesclados.items()
                                 if not k.startswith("_")})
        autor_principal = str(ficha_atualizada.get("nmAutor0", "")).strip()
        autores_atuais = ficha_atualizada.get("autores", []) or []
        if autor_principal and not autores_atuais:
            ficha_atualizada["autores"] = [{
                "nome": autor_principal,
                "desc": "Autor",
            }]
        ficha_atualizada["revisao_manual_aplicada"] = True
        ficha_atualizada["revisao_manual_aprovada"] = bool(aprovado)
        ficha_atualizada["revisao_manual_atualizada_em"] = revisao["atualizado_em"]
        ficha_atualizada["fontes_revisao"] = " | ".join(revisao.get("fontes", []))
        if aprovado:
            conflitos_anteriores = _partes_pipe(
                ficha_atualizada.get("conflitos", ""))
            pendencias_anteriores = _partes_pipe(
                ficha_atualizada.get("pendencias", ""))
            if conflitos_anteriores or pendencias_anteriores:
                resolvidos = list(ficha_atualizada.get(
                    "resolvidos_por_revisao_manual", []) or [])
                resolvidos.append({
                    "em": revisao["atualizado_em"],
                    "fonte": ficha_atualizada.get("fontes_revisao", ""),
                    "confirmacao_soberana": bool(confirmacao_soberana),
                    "motivo_confirmacao_soberana": str(
                        motivo_confirmacao or "").strip(),
                    "conflitos": conflitos_anteriores,
                    "pendencias": pendencias_anteriores,
                })
                ficha_atualizada["resolvidos_por_revisao_manual"] = resolvidos
            ficha_atualizada["conflitos"] = ""
            ficha_atualizada["pendencias"] = ""
            _mover_aprovado_revisao(c, digest, registro, ficha_atualizada)
        snapshot = _salvar_snapshot_revisao_manual(
            c, registro, ficha, ficha_atualizada, revisao)
        ficha_atualizada["ultimo_snapshot_revisao_manual"] = relativo(c, snapshot)
        salvar_json(ficha_path, ficha_atualizada)
    registro["revisao_manual_aprovada"] = bool(aprovado)
    registro["revisao_manual_atualizada_em"] = revisao["atualizado_em"]
    salvar_catalogo(c, catalogo)
    pdf_atual = _arquivo_do_registro(c, registro) or pdf
    aprendizados = prep.registrar_aprendizados_da_revisao(
        str(pdf_atual), ficha, revisao)
    for texto in ruidos_titulo or []:
        _adicionar_ruido_memoria(
            pathlib.Path(prep.ARQUIVO_TITULOS_RUIDOSOS), texto, "exato",
            "confirmado na revisão visual")
    for texto in ruidos_autor or []:
        _adicionar_ruido_memoria(
            pathlib.Path(prep.ARQUIVO_AUTORES_RUIDOSOS), texto, "exato",
            "confirmado na revisão visual")
    resultado = {
        "arquivo": registro.get("arquivo", ""),
        "hash_sha256": revisao["hash_sha256"],
        "revisao": relativo(c, revisoes_path),
        "aprendizados": aprendizados,
    }
    if imprimir:
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return resultado


def aplicar_duplicidade_api_na_ficha(linha, resposta):
    """Marca uma ficha preparada como duplicada sem perder suas evidencias."""
    por_isbn = api_envio.consulta_confirmada_por_isbn(resposta)
    por_titulo_autor = api_envio.consulta_confirmada_por_titulo_autor(resposta)
    estado = ("duplicado confirmado por ISBN" if por_isbn else
              api_envio.ESTADO_DUPLICADO_TITULO_AUTOR if por_titulo_autor else
              "já existente na API - conferir vínculo")
    linha.update({
        "situacao": estado,
        "situacao_metadados": estado,
        "consulta_previa_api": resposta,
        "id_remoto": resposta.get("id", ""),
        "correspondencia_api": str(
            resposta.get("correspondencia", "")).lower(),
        "confirmado_por_api": ("isbn" if por_isbn else
                               "titulo_autor" if por_titulo_autor else
                               "titulo_autor_aproximado"),
    })
    return estado


def registrar_duplicidade_previa(c, catalogo, digest, origem, resposta, pistas):
    """Estaciona o PDF sem OCR; consulta aproximada nunca autoriza exclusao."""
    correspondencia = str(resposta.get("correspondencia", "")).lower()
    por_isbn = api_envio.consulta_confirmada_por_isbn(resposta)
    por_titulo_autor = api_envio.consulta_confirmada_por_titulo_autor(resposta)
    estado = ("duplicado confirmado por ISBN" if por_isbn else
              api_envio.ESTADO_DUPLICADO_TITULO_AUTOR if por_titulo_autor else
              "já existente na API - conferir vínculo")
    destino = mover_sem_substituir(
        origem, c["revisao"] / "DUPLICADOS-API", digest)
    revisao = prep.revisao_manual(str(destino)) or prep.revisao_manual(str(origem))
    campos_revisao = revisao.get("campos", {}) if isinstance(revisao, dict) else {}
    linha = {
        "arquivo": destino.name, "pdf_original": relativo(c, destino),
        "pdf_preparado": "", "capa": "", "titulo": resposta.get("titulo")
        or pistas.get("titulo", ""), "isbn": resposta.get("isbn")
        or pistas.get("isbn", ""), "autores": [
            {"nome": nome, "desc": "Autor"}
            for nome in (resposta.get("autores") or pistas.get("autores") or [])],
        "nmAutor0": ((resposta.get("autores") or pistas.get("autores") or [""])[0]),
        "tipo_documento": "livro", "situacao": estado,
        "situacao_metadados": estado,
        "status_ocr": "não executado - duplicidade detectada antes do preparo",
        "conflitos": "", "pendencias": "",
        "consulta_previa_api": resposta, "pistas_consulta_previa": pistas,
        "id_remoto": resposta.get("id", ""),
        "pasta_origem_importacao": campos_revisao.get(
            "pasta_origem_importacao", ""),
        "arquivos_origem_importacao": campos_revisao.get(
            "arquivos_origem_importacao", []),
        "_diagnostico_ocr": {}, "_evidencias": [],
    }
    ficha = gravar_ficha(c, digest, linha)
    catalogo["livros"][digest] = {
        "hash_sha256": digest, "arquivo": destino.name,
        "caminho": relativo(c, destino), "tamanho_bytes": destino.stat().st_size,
        "estado": estado, "origem": "consulta prévia da API",
        "registrado_em": agora(), "processado_em": agora(),
        "metadados": relativo(c, ficha), "capa": "",
        "id_remoto": resposta.get("id", ""),
        "correspondencia_api": correspondencia,
        "confirmado_por_api": ("isbn" if por_isbn else
                               "titulo_autor" if por_titulo_autor else
                               "titulo_autor_aproximado"),
    }
    salvar_catalogo(c, catalogo)
    return destino, estado


def consolidar(c, catalogo):
    colunas = ["hash_sha256", "arquivo", "estado", "caminho", "tamanho_bytes",
               "processado_em", "metadados", "capa", "duplicado_de",
               "id_remoto", "cadastrado_em"]
    destino = c["controle"] / "catalogo-local.csv"
    tmp = destino.with_name(destino.name + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=colunas, delimiter=";", extrasaction="ignore")
        w.writeheader()
        for registro in sorted(catalogo["livros"].values(),
                               key=lambda x: (x.get("estado", ""), x.get("arquivo", ""))):
            w.writerow(registro)
    os.replace(tmp, destino)
    consolidar_filas_especificas(c, catalogo)


def consolidar_filas_especificas(c, catalogo):
    """Mantem nao-livros em filas proprias, usando os tipos da API atual."""
    grupos = {
        "academico": {
            "tipos": TIPOS_ACADEMICOS,
            "arquivo": "fila-cadastro-academico.json",
            "destino": "cadastro como documento público (tipo 5)",
        },
        "documentos": {
            "tipos": TIPOS_DOCUMENTOS,
            "arquivo": "fila-cadastro-documentos.json",
            "destino": "cadastro público conforme o tipo documental",
        },
        "revistas": {
            "tipos": TIPOS_REVISTAS,
            "arquivo": "fila-cadastro-revistas.json",
            "destino": "cadastro como revista completa pública (tipo 2)",
        },
    }
    itens = {nome: [] for nome in grupos}
    anteriores = {}
    for grupo in grupos.values():
        try:
            fila_anterior = json.loads(
                (c["controle"] / grupo["arquivo"]).read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        for item_anterior in fila_anterior.get("itens", []):
            anteriores[item_anterior.get("hash_sha256", "")] = item_anterior
    catalogo_alterado = False

    # Um ISBN completo identifica a edição. Se outro arquivo do próprio
    # catálogo já teve cadastro ou duplicidade confirmada pelo Biblio, uma
    # cópia posterior com o mesmo ISBN não deve permanecer indefinidamente
    # em "conferir vínculo" nem chegar à etapa de upload. A prova é local e
    # auditável: ficha com ISBN idêntico + estado terminal originado da API.
    isbn_confirmados = {}
    fichas_por_hash = {}
    estados_remotos_confirmados = {
        "cadastrado", "cadastrado - arquivos locais liberados",
        "duplicado na API - arquivos locais liberados",
        "duplicado confirmado por ISBN",
    }
    # Este indice so tem utilidade quando existe uma copia aguardando vinculo.
    # Antes ele abria todas as fichas. No Dropbox, fichas antigas podem estar
    # somente na nuvem e cada leitura dispara um download silencioso.
    ha_vinculo_pendente = any(
        r.get("estado") == "já existente na API - conferir vínculo"
        for r in catalogo["livros"].values())
    if ha_vinculo_pendente:
        for hash_fonte, registro_fonte in catalogo["livros"].items():
            if (str(hash_fonte).startswith("duplicado:")
                    or registro_fonte.get("estado") not in
                    estados_remotos_confirmados):
                continue
            ficha_fonte_path = c["raiz"] / registro_fonte.get("metadados", "")
            try:
                ficha_fonte = json.loads(
                    ficha_fonte_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                ficha_fonte = {}
            fichas_por_hash[hash_fonte] = ficha_fonte
            isbn_fonte = prep.isbn_valido(str(ficha_fonte.get("isbn", "")))
            if isbn_fonte:
                isbn_confirmados.setdefault(
                    isbn_fonte, (hash_fonte, registro_fonte))

    for hash_copia, registro_copia in catalogo["livros"].items():
        if registro_copia.get("estado") != "já existente na API - conferir vínculo":
            continue
        ficha_copia_path = c["raiz"] / registro_copia.get("metadados", "")
        try:
            ficha_copia = json.loads(
                ficha_copia_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            ficha_copia = {}
        fichas_por_hash[hash_copia] = ficha_copia
        isbn_copia = prep.isbn_valido(str(ficha_copia.get("isbn", "")))
        fonte = isbn_confirmados.get(isbn_copia) if isbn_copia else None
        if not fonte or fonte[0] == hash_copia:
            continue
        hash_fonte, registro_fonte = fonte
        registro_copia["estado"] = "duplicado confirmado por ISBN"
        registro_copia["confirmado_por_api"] = "isbn"
        registro_copia["duplicado_de"] = hash_fonte
        if registro_fonte.get("id_remoto"):
            registro_copia["id_remoto"] = registro_fonte["id_remoto"]
        ficha_copia["situacao"] = "duplicado confirmado por ISBN"
        ficha_copia["situacao_metadados"] = "duplicado confirmado por ISBN"
        ficha_copia["confirmado_por_api"] = "isbn"
        ficha_copia["duplicado_de"] = hash_fonte
        if registro_copia.get("id_remoto"):
            ficha_copia["id_remoto"] = registro_copia["id_remoto"]
        salvar_json(c["raiz"] / registro_copia.get("metadados", ""),
                    ficha_copia)
        catalogo_alterado = True

    for digest, registro in catalogo["livros"].items():
        if str(digest).startswith("duplicado:"):
            continue
        # Um estado liberado e definitivo e ja nao forma fila. Os estados
        # usuais podem ser normalizados pelo proprio catalogo, sem abrir a
        # ficha. So um registro legado ambiguo exige consultar seu motivo.
        if registro.get("arquivos_liberados_em"):
            estado_atual = registro.get("estado", "")
            if estado_atual in {"cadastrado",
                                "cadastrado - arquivos locais liberados"}:
                estado_terminal = "cadastrado - arquivos locais liberados"
            elif ("duplicado" in estado_atual.casefold()
                  or estado_atual == "já existente na API - conferir vínculo"):
                estado_terminal = "duplicado na API - arquivos locais liberados"
            elif ("descart" in estado_atual.casefold()
                  or estado_atual == ESTADO_DESCARTE):
                estado_terminal = "descartado - arquivos locais liberados"
            else:
                ficha_legada_path = (
                    c["raiz"] / registro.get("metadados", ""))
                try:
                    ficha_legada = json.loads(
                        ficha_legada_path.read_text(encoding="utf-8"))
                except (OSError, ValueError, json.JSONDecodeError):
                    ficha_legada = {}
                motivo = ficha_legada.get("motivo_liberacao_espaco", "")
                if motivo == "cadastro confirmado pela API":
                    estado_terminal = "cadastrado - arquivos locais liberados"
                elif motivo == "duplicidade confirmada pela API":
                    estado_terminal = "duplicado na API - arquivos locais liberados"
                elif motivo == "item classificado para descarte":
                    estado_terminal = "descartado - arquivos locais liberados"
                else:
                    estado_terminal = estado_atual
            if estado_atual != estado_terminal:
                registro["estado"] = estado_terminal
                catalogo_alterado = True
            continue
        ficha_path = c["raiz"] / registro.get("metadados", "")
        try:
            ficha = json.loads(ficha_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        tipo = ficha.get("tipo_documento", "livro")
        for nome, grupo in grupos.items():
            if tipo in grupo["tipos"]:
                tipo_api = (
                    "artigo de revista" if tipo == "artigo" else
                    "revista" if tipo in TIPOS_REVISTAS else "documento")
                pdf = api_envio.caminho_local(
                    ficha.get("pdf_preparado") or ficha.get("pdf_original")
                    or ficha.get("arquivo"), ficha_path)
                capa = api_envio.caminho_local(ficha.get("capa"), ficha_path)
                erros = api_envio.validar(
                    ficha, pdf, capa, tipo_api=tipo_api)
                estado_atual = registro.get("estado", "")
                if estado_atual == "cadastrado":
                    estado = estado_atual
                elif estado_atual == "já existente na API - conferir vínculo":
                    anterior = anteriores.get(
                        registro.get("hash_sha256", digest), {})
                    consulta = anterior.get("consulta_previa_api", {}) or {}
                    if api_envio.consulta_corresponde_ao_titulo_exato(consulta):
                        por_autor = api_envio.consulta_confirmada_por_titulo_autor(
                            consulta)
                        estado = (
                            api_envio.ESTADO_DUPLICADO_TITULO_AUTOR if por_autor
                            else api_envio.ESTADO_DUPLICADO_TITULO)
                        registro["confirmado_por_api"] = (
                            "titulo_autor" if por_autor else "titulo")
                    else:
                        estado = estado_atual
                elif estado_atual in {
                        "duplicado confirmado por ISBN",
                        api_envio.ESTADO_DUPLICADO_TITULO_AUTOR,
                        api_envio.ESTADO_DUPLICADO_TITULO,
                        "já existente na API - conferir vínculo"}:
                    estado = estado_atual
                elif erros:
                    estado = "aguardando correção para cadastro específico"
                else:
                    estado = "pronto para cadastro específico"
                if registro.get("estado") != estado:
                    registro["estado"] = estado
                    catalogo_alterado = True
                itens[nome].append({
                    "hash_sha256": registro.get("hash_sha256", digest),
                    "tipo_documento": tipo,
                    "titulo": ficha.get("titulo", ""),
                    "autor": ficha.get("nmAutor0", ""),
                    "estado": estado,
                    "id_remoto": registro.get("id_remoto", ""),
                    "confirmado_por_api": registro.get("confirmado_por_api", ""),
                    "tipo_api": tipo_api,
                    "pendencias_envio": erros,
                    "arquivo": registro.get("arquivo", ""),
                    "caminho": registro.get("caminho", ""),
                    "metadados": registro.get("metadados", ""),
                })
                break
    if catalogo_alterado:
        catalogo["atualizado_em"] = agora()
        salvar_catalogo(c, catalogo)
    for nome, grupo in grupos.items():
        fila = sorted(itens[nome], key=lambda x: (
            x.get("titulo", "").casefold(), x.get("arquivo", "").casefold()))
        salvar_json(c["controle"] / grupo["arquivo"], {
            "versao": 1,
            "atualizado_em": agora(),
            "destino": grupo["destino"],
            "api": api_envio.ENDPOINT,
            "envio_automatico_habilitado": True,
            "quantidade": len(fila),
            "itens": fila,
        })


def atualizar_filas_especificas(raiz):
    """Reavalia sem OCR os materiais separados e atualiza seus estados."""
    c = inicializar(raiz)
    catalogo = carregar_catalogo(c)
    consolidar(c, catalogo)
    resultado = {}
    for nome in ("academico", "documentos", "revistas"):
        caminho = c["controle"] / f"fila-cadastro-{nome}.json"
        try:
            fila = json.loads(caminho.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        estados = {}
        for item in fila.get("itens", []):
            estado = item.get("estado", "sem estado")
            estados[estado] = estados.get(estado, 0) + 1
        resultado[nome] = estados
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return resultado


def ler_opf(caminho):
    """Extrai os campos Dublin Core do OPF, sem interpretar HTML embutido."""
    try:
        raiz = ET.parse(caminho).getroot()
    except (OSError, ET.ParseError):
        return {}
    ns = {"dc": "http://purl.org/dc/elements/1.1/"}

    def texto(tag):
        elemento = raiz.find(f".//dc:{tag}", ns)
        return " ".join((elemento.text or "").split()) if elemento is not None else ""

    isbn = asin = ""
    for elemento in raiz.findall(".//dc:identifier", ns):
        valor = " ".join((elemento.text or "").split())
        esquema = " ".join(str(v) for k, v in elemento.attrib.items()
                            if k.endswith("scheme")).upper()
        if "ISBN" in esquema and prep.isbn_valido(valor):
            isbn = prep.isbn_valido(valor)
        elif "ASIN" in esquema:
            asin = valor
    codigo_idioma = texto("language").lower()
    nomes_idioma = {
        "por": "Português", "pt": "Português", "pt-br": "Português",
        "eng": "Inglês", "en": "Inglês", "spa": "Espanhol", "es": "Espanhol",
        "fre": "Francês", "fra": "Francês", "fr": "Francês",
        "ger": "Alemão", "deu": "Alemão", "de": "Alemão",
    }
    codigos = {"pt": "por", "pt-br": "por", "en": "eng", "es": "spa",
               "fr": "fre", "de": "ger"}
    data_opf = texto("date")
    achado_ano = re.search(r"\b(?:19|20)\d{2}\b", data_opf)
    criadores = [" ".join((e.text or "").split())
                 for e in raiz.findall(".//dc:creator", ns) if (e.text or "").strip()]
    if len(criadores) == 1:
        partes = re.split(r"\s+(?:e|and|&|;)\s+", criadores[0], flags=re.I)
        if (len(partes) == 2
                and all(len(p.split()) >= 2 for p in partes)
                and all(re.search(r"[A-ZÀ-Ü]", p) for p in partes)):
            criadores = partes
    autores = [{"nome": prep.sobrenome_virgula(nome), "desc": "Autor"}
               for nome in criadores]
    campos = {
        "titulo": texto("title"),
        "nmAutor0": autores[0]["nome"] if autores else "",
        "autores": autores,
        "editora": texto("publisher"), "isbn": isbn,
        "nmLingua": nomes_idioma.get(codigo_idioma, ""),
        "idioma": codigos.get(codigo_idioma, codigo_idioma),
        "data": achado_ano.group(0) if achado_ano else "",
    }
    return {"campos": {k: v for k, v in campos.items() if v},
            "asin": asin, "data_opf": data_opf}


def _associado_por_nome(pasta, base, extensoes, aceitar_unico=False):
    candidatos = sorted(p for p in pasta.iterdir()
                        if p.is_file() and p.suffix.lower() in extensoes)
    exatos = [p for p in candidatos if p.stem.casefold() == base.casefold()]
    if len(exatos) == 1:
        return exatos[0]
    return candidatos[0] if aceitar_unico and len(candidatos) == 1 else None


def localizar_soffice():
    """Localiza LibreOffice sem depender do diretório de abertura do app."""
    configurado = os.environ.get("BIBLIO_SOFFICE", "").strip()
    candidatos = ([pathlib.Path(configurado)] if configurado else [])
    encontrado = shutil.which("soffice") or shutil.which("libreoffice")
    if encontrado:
        candidatos.append(pathlib.Path(encontrado))
    candidatos.extend(SOFFICE_APLICATIVOS)
    # O app aberto por duplo clique recebe um PATH reduzido. O ambiente do
    # Codex, contudo, já pode trazer um LibreOffice headless privado que não
    # aparece no PATH do Finder. Localizá-lo evita cair desnecessariamente no
    # Microsoft Word, que abre janelas e solicita acesso a cada pasta.
    cache_codex = pathlib.Path.home() / ".cache" / "codex-runtimes"
    if cache_codex.is_dir():
        candidatos.extend(sorted(cache_codex.glob(
            "*/dependencies/bin/override/soffice")))
    return next((p for p in candidatos if p.is_file()), None)


def pdf_convertido_valido(caminho):
    caminho = pathlib.Path(caminho)
    if not caminho.is_file() or caminho.stat().st_size < 5:
        return False
    try:
        with caminho.open("rb") as arquivo:
            if arquivo.read(5) != b"%PDF-":
                return False
        return prep.n_paginas(str(caminho)) > 0
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def _converter_word_libreoffice(origem, destino, soffice,
                                executor=subprocess.run):
    with tempfile.TemporaryDirectory(prefix="biblio-libreoffice-") as td:
        temporario = pathlib.Path(td)
        perfil = temporario / "perfil"
        comando = [
            str(soffice), "--headless", "--nologo", "--nodefault",
            "--nofirststartwizard", f"-env:UserInstallation={perfil.as_uri()}",
            "--convert-to", "pdf", "--outdir", str(temporario), str(origem),
        ]
        resultado = executor(
            comando, capture_output=True, text=True, timeout=600)
        convertido = temporario / (pathlib.Path(origem).stem + ".pdf")
        if resultado.returncode or not pdf_convertido_valido(convertido):
            detalhe = (resultado.stderr or resultado.stdout or
                       "LibreOffice não gerou um PDF válido").strip()
            return False, detalhe
        shutil.copy2(convertido, destino)
    return pdf_convertido_valido(destino), ""


def _converter_word_microsoft(origem, destino, executor=subprocess.run):
    script = r'''
on run argv
    set origem to item 1 of argv
    set destino to item 2 of argv
    tell application "Microsoft Word"
        set documento to open file name origem
        save as documento file name destino file format format PDF
        close documento saving no
    end tell
end run
'''
    resultado = executor(
        ["osascript", "-e", script, str(origem), str(destino)],
        capture_output=True, text=True, timeout=600)
    if resultado.returncode or not pdf_convertido_valido(destino):
        detalhe = (resultado.stderr or resultado.stdout or
                   "Microsoft Word não gerou um PDF válido").strip()
        return False, detalhe
    return True, ""


def converter_word_para_pdf(origem, destino):
    """Converte DOC/DOCX preservando o original e informa o motor utilizado."""
    origem, destino = pathlib.Path(origem), pathlib.Path(destino)
    if origem.suffix.lower() not in EXTENSOES_WORD:
        return {"ok": False, "motor": "", "erro": "formato Word inválido"}
    erros = []
    soffice = localizar_soffice()
    if soffice:
        ok, erro = _converter_word_libreoffice(origem, destino, soffice)
        if ok:
            return {"ok": True, "motor": "LibreOffice", "erro": ""}
        erros.append(f"LibreOffice: {erro}")
        destino.unlink(missing_ok=True)
    # O Word é mantido somente como alternativa explicitamente autorizada.
    # Automatizá-lo via AppleScript aciona a interface gráfica e permissões
    # do macOS, uma experiência inadequada para o processamento em lote.
    permitir_word = os.environ.get(
        "BIBLIO_PERMITIR_WORD", "").strip().casefold() in {
            "1", "sim", "true", "yes",
        }
    if (permitir_word and MICROSOFT_WORD.is_dir()
            and shutil.which("osascript")):
        ok, erro = _converter_word_microsoft(origem, destino)
        if ok:
            return {"ok": True, "motor": "Microsoft Word", "erro": ""}
        erros.append(f"Microsoft Word: {erro}")
        destino.unlink(missing_ok=True)
    if not erros:
        erros.append("conversor silencioso LibreOffice não encontrado")
    elif not permitir_word:
        erros.append("Microsoft Word gráfico desativado para evitar janelas")
    return {"ok": False, "motor": "", "erro": " | ".join(erros)}


def converter_apresentacao_para_pdf(origem, destino):
    """Converte PPT/PPTX/ODP preservando o original.

    Só o LibreOffice: automatizar o Keynote ou o PowerPoint por AppleScript
    abre janela e pede permissão do macOS, inadequado para lote — a mesma
    razão pela qual o Word gráfico está desligado por padrão.
    """
    origem, destino = pathlib.Path(origem), pathlib.Path(destino)
    if origem.suffix.lower() not in EXTENSOES_APRESENTACAO:
        return {"ok": False, "motor": "", "erro": "formato de apresentação inválido"}
    soffice = localizar_soffice()
    if not soffice:
        return {"ok": False, "motor": "",
                "erro": ("LibreOffice não encontrado: instale-o para converter "
                         "apresentações (brew install --cask libreoffice)")}
    ok, erro = _converter_word_libreoffice(origem, destino, soffice)
    if ok:
        return {"ok": True, "motor": "LibreOffice (apresentação)", "erro": ""}
    destino.unlink(missing_ok=True)
    return {"ok": False, "motor": "", "erro": f"LibreOffice: {erro}"}


def _salvar_vinculo_importacao(c, pdf, pasta, arquivos, opf=None):
    revisoes_path = c["controle"] / "revisoes-manuais.json"
    try:
        revisoes = json.loads(revisoes_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        revisoes = {"versao": 1, "livros": {}}
    dados_opf = ler_opf(opf) if opf else {}
    campos = dict(dados_opf.get("campos", {}))
    campos.update({
        "pasta_origem_importacao": str(pasta.resolve()),
        "arquivos_origem_importacao": [str(p.resolve()) for p in arquivos],
        "opf_origem": str(opf.resolve()) if opf else "",
        "asin": dados_opf.get("asin", ""),
    })
    essenciais = all(campos.get(k) for k in
                     ("titulo", "nmAutor0", "editora", "data", "nmLingua"))
    fontes = [f"OPF: {opf.resolve()}"] if opf else ["pasta organizada de entrada"]
    revisoes.setdefault("livros", {})[pdf.name] = {
        "hash_sha256": sha256(pdf), "campos": campos, "fontes": fontes,
        "justificativa": ("metadados estruturados importados do OPF" if opf
                           else "arquivos associados pelo nome-base"),
        "aprovado": essenciais,
    }
    revisoes["atualizado_em"] = agora()
    salvar_json(revisoes_path, revisoes)


def preparar_entrada_organizada(c, catalogo):
    """Organiza PDFs e converte DOC, DOCX ou EPUB antes da preparação."""
    estado_path = c["controle"] / "importacoes-organizadas.json"
    try:
        estado = json.loads(estado_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        estado = {"versao": 1, "itens": {}}
    resumo = {"encontrados": 0, "importados": 0, "convertidos": 0,
              "ambiguos": 0, "ja_conhecidos": 0, "falhas": 0}

    def importar_pdf(origem, opf=None, convertido=False,
                     pasta_fonte=None, base_fonte=None, assinatura=None,
                     chave_fonte=None, conversao=None):
        chave = str(chave_fonte or (opf or origem).resolve())
        digest_origem = sha256(origem)
        assinatura = assinatura or (digest_origem + (sha256(opf) if opf else ""))
        anterior_estado = estado.get("itens", {}).get(chave, {})
        if (anterior_estado.get("estado") == "importado"
                and anterior_estado.get("assinatura") == assinatura):
            return
        resumo["encontrados"] += 1
        pasta_fonte = pathlib.Path(pasta_fonte or origem.parent)
        base = base_fonte or origem.stem
        arquivos = sorted(p for p in pasta_fonte.iterdir()
                          if p.is_file() and not p.is_symlink()
                          and p.name != ".DS_Store"
                          and (p.stem.casefold() == base.casefold() or p == opf))
        if digest_origem in catalogo.get("livros", {}):
            resumo["ja_conhecidos"] += 1
            registro = catalogo["livros"][digest_origem]
            ficha_path = c["raiz"] / registro.get("metadados", "")
            try:
                ficha = json.loads(ficha_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                ficha = {}
            if ficha:
                ficha["pasta_origem_importacao"] = str(pasta_fonte.resolve())
                ficha["arquivos_origem_importacao"] = [
                    str(p.resolve()) for p in arquivos]
                ficha["opf_origem"] = str(opf.resolve()) if opf else ""
                salvar_json(ficha_path, ficha)
            estado.setdefault("itens", {})[chave] = {
                "estado": "importado", "resultado": "PDF já conhecido",
                "atualizado_em": agora(),
                "hash_sha256": digest_origem, "assinatura": assinatura}
            return
        destino = destino_unico(c["entrada"], origem.name, digest_origem,
                                aceitar_igual=True)
        if not destino.exists():
            shutil.copy2(origem, destino)
        capa = _associado_por_nome(pasta_fonte, base, {".jpg", ".jpeg"})
        if capa:
            capa_destino = c["capas"] / f"{destino.stem}.jpg"
            if not capa_destino.exists():
                shutil.copy2(capa, capa_destino)
        _salvar_vinculo_importacao(c, destino, pasta_fonte, arquivos, opf)
        estado.setdefault("itens", {})[chave] = {
            "estado": "importado", "importado_em": agora(),
            "pdf_entrada": str(destino), "hash_sha256": sha256(destino),
            "convertido_de_epub": convertido,
            "convertido_de_word": bool(conversao),
            "motor_conversao": (conversao or {}).get("motor", ""),
            "assinatura": assinatura}
        resumo["importados"] += 1

    # DOC/DOCX entram como fontes: o original permanece preservado e o PDF
    # pesquisável segue pelo mesmo diagnóstico, geração de capa e fila.
    pdfs_tratados = set()
    for word in sorted(
            p for p in c["entrada"].rglob("*")
            if p.is_file() and not p.is_symlink()
            and not p.name.startswith("~$")
            and p.suffix.lower() in EXTENSOES_WORD):
        chave = str(word.resolve())
        assinatura = sha256(word)
        anterior_estado = estado.get("itens", {}).get(chave, {})
        if (anterior_estado.get("estado") == "importado"
                and anterior_estado.get("assinatura") == assinatura):
            continue
        pdf_existente = _associado_por_nome(
            word.parent, word.stem, {".pdf"})
        if pdf_existente:
            pdfs_tratados.add(pdf_existente.resolve())
            importar_pdf(
                pdf_existente, pasta_fonte=word.parent,
                base_fonte=word.stem, assinatura=assinatura,
                chave_fonte=chave,
                conversao={"motor": "PDF já fornecido com o Word"})
            continue
        with tempfile.TemporaryDirectory(prefix="biblio-word-") as td:
            convertido = pathlib.Path(td) / (word.stem + ".pdf")
            resultado = converter_word_para_pdf(word, convertido)
            if not resultado["ok"]:
                resumo["encontrados"] += 1
                resumo["falhas"] += 1
                estado.setdefault("itens", {})[chave] = {
                    "estado": "falha na conversão Word",
                    "arquivo_origem": str(word), "assinatura": assinatura,
                    "erro": resultado["erro"], "atualizado_em": agora(),
                }
                print(f"  não foi possível converter {word.name}: "
                      f"{resultado['erro']}")
                continue
            resumo["convertidos"] += 1
            importar_pdf(
                convertido, pasta_fonte=word.parent,
                base_fonte=word.stem, assinatura=assinatura,
                chave_fonte=chave, conversao=resultado)

    # ------------------------------------------------------------------
    # HTML -> PDF.
    #
    # O Biblio só aceita PDF. Um HTML ficou parado em 00-ENTRADA sem ser
    # convertido, sem ser processado e sem ser reclamado, porque nada na
    # esteira o enxergava.
    #
    # A conversão usa o Chromium (mesmo motor do navegador) COM A REDE
    # DESLIGADA: uma página salva referencia imagens e CSS por URL, e
    # renderizar com rede aberta faria o navegador buscar esses recursos -
    # abrir um arquivo local dispararia conexões que ninguém pediu.
    # ------------------------------------------------------------------
    for html in sorted(
            p for p in c["entrada"].rglob("*")
            if p.is_file() and not p.is_symlink()
            and not p.name.startswith("~$")
            and p.suffix.lower() in converter_html.EXTENSOES_HTML):
        chave = str(html.resolve())
        assinatura = sha256(html)
        anterior_estado = estado.get("itens", {}).get(chave, {})
        if (anterior_estado.get("estado") == "importado"
                and anterior_estado.get("assinatura") == assinatura):
            continue

        # PDF de mesmo nome ao lado: é o próprio documento, melhor que a
        # conversão. Mesma regra já usada para o Word.
        pdf_existente = _associado_por_nome(html.parent, html.stem, {".pdf"})
        if pdf_existente:
            pdfs_tratados.add(pdf_existente.resolve())
            importar_pdf(
                pdf_existente, pasta_fonte=html.parent, base_fonte=html.stem,
                assinatura=assinatura, chave_fonte=chave,
                conversao={"motor": "PDF já fornecido com o HTML"})
            continue

        with tempfile.TemporaryDirectory(prefix="biblio-html-") as td:
            convertido = pathlib.Path(td) / (html.stem + ".pdf")
            ok, aviso = converter_html.converter(html, convertido)
            if not ok:
                resumo["encontrados"] += 1
                resumo["falhas"] += 1
                estado.setdefault("itens", {})[chave] = {
                    "estado": "falha na conversão HTML",
                    "arquivo_origem": str(html), "assinatura": assinatura,
                    "erro": aviso, "atualizado_em": agora(),
                }
                print(f"  não foi possível converter {html.name}: {aviso}")
                continue
            resumo["convertidos"] += 1
            if aviso:
                print(f"  {html.name}: {aviso}")
            importar_pdf(
                convertido, pasta_fonte=html.parent, base_fonte=html.stem,
                assinatura=assinatura, chave_fonte=chave,
                conversao={"motor": "Chromium (HTML)", "aviso": aviso,
                           "titulo_html": converter_html.titulo_do_html(html)})

    # ------------------------------------------------------------------
    # PowerPoint -> PDF.
    #
    # Sete apresentações ficaram paradas em 00-ENTRADA/apresentações: não
    # eram convertidas, não eram processadas e não eram reclamadas. Mesmo
    # ponto cego do HTML, mesmo remédio.
    #
    # Uma apresentação entra como DOCUMENTO, nunca como livro: não tem
    # ISBN nem editora, e muitas não trazem autor. O tipo "apresentação"
    # exige apenas título — quem classifica é `preparar-livros.py`, pela
    # extensão registrada em `arquivos_origem_importacao`.
    # ------------------------------------------------------------------
    for slides in sorted(
            p for p in c["entrada"].rglob("*")
            if p.is_file() and not p.is_symlink()
            and not p.name.startswith("~$")
            and p.suffix.lower() in EXTENSOES_APRESENTACAO):
        chave = str(slides.resolve())
        assinatura = sha256(slides)
        anterior_estado = estado.get("itens", {}).get(chave, {})
        if (anterior_estado.get("estado") == "importado"
                and anterior_estado.get("assinatura") == assinatura):
            continue

        # PDF de mesmo nome ao lado: já é a exportação da apresentação, e
        # mantém a diagramação original melhor que a reconversão.
        pdf_existente = _associado_por_nome(slides.parent, slides.stem, {".pdf"})
        if pdf_existente:
            pdfs_tratados.add(pdf_existente.resolve())
            importar_pdf(
                pdf_existente, pasta_fonte=slides.parent,
                base_fonte=slides.stem, assinatura=assinatura,
                chave_fonte=chave,
                conversao={"motor": "PDF já fornecido com a apresentação"})
            continue

        with tempfile.TemporaryDirectory(prefix="biblio-slides-") as td:
            convertido = pathlib.Path(td) / (slides.stem + ".pdf")
            resultado = converter_apresentacao_para_pdf(slides, convertido)
            if not resultado["ok"]:
                resumo["encontrados"] += 1
                resumo["falhas"] += 1
                estado.setdefault("itens", {})[chave] = {
                    "estado": "falha na conversão da apresentação",
                    "arquivo_origem": str(slides), "assinatura": assinatura,
                    "erro": resultado["erro"], "atualizado_em": agora(),
                }
                print(f"  não foi possível converter {slides.name}: "
                      f"{resultado['erro']}")
                continue
            resumo["convertidos"] += 1
            importar_pdf(
                convertido, pasta_fonte=slides.parent,
                base_fonte=slides.stem, assinatura=assinatura,
                chave_fonte=chave, conversao=resultado)

    # Cada PDF é um livro, mesmo quando muitos estão na pasta do mesmo autor.
    for pdf in sorted(p for p in c["entrada"].rglob("*")
                      if p.is_file() and p.suffix.lower() == ".pdf"):
        if (pdf.parent == c["entrada"] or pdf.is_symlink()
                or pdf.resolve() in pdfs_tratados):
            continue
        opf = _associado_por_nome(pdf.parent, pdf.stem, {".opf"})
        pdfs_irmaos = [p for p in pdf.parent.iterdir()
                       if p.is_file() and p.suffix.lower() == ".pdf"]
        if not opf and len(pdfs_irmaos) == 1:
            opf = _associado_por_nome(pdf.parent, pdf.stem, {".opf"},
                                      aceitar_unico=True)
        importar_pdf(pdf, opf=opf)

    # EPUB sem PDF: o Calibre gera um PDF pesquisável para a mesma fila.
    #
    # Antes esta etapa partia do OPF e ainda ignorava a raiz de 00-ENTRADA.
    # Consequência: um EPUB avulso aparecia no menu como "será convertido",
    # mas nunca era visto pelo conversor. O EPUB agora é a fonte principal;
    # o OPF, quando existir, apenas acrescenta metadados estruturados.
    for epub in sorted(
            p for p in c["entrada"].rglob("*")
            if p.is_file() and not p.is_symlink()
            and p.suffix.lower() == ".epub"):
        pdf = _associado_por_nome(epub.parent, epub.stem, {".pdf"})
        if pdf:
            continue
        opf = _associado_por_nome(epub.parent, epub.stem, {".opf"})
        if not opf:
            opfs = [p for p in epub.parent.iterdir()
                    if p.is_file() and p.suffix.lower() == ".opf"]
            if len(opfs) == 1:
                opf = opfs[0]
        chave = str((opf or epub).resolve())
        assinatura = sha256(epub) + (sha256(opf) if opf else "")
        anterior_estado = estado.get("itens", {}).get(chave, {})
        if (anterior_estado.get("estado") == "importado"
                and anterior_estado.get("assinatura") == assinatura):
            continue
        if not EBOOK_CONVERT.is_file():
            resumo["encontrados"] += 1
            resumo["falhas"] += 1
            estado.setdefault("itens", {})[chave] = {
                "estado": "falha na conversão EPUB",
                "arquivo_origem": str(epub), "assinatura": assinatura,
                "erro": "conversor do Calibre não encontrado",
                "atualizado_em": agora(),
            }
            print(f"  não foi possível converter {epub.name}: "
                  "conversor do Calibre não encontrado")
            continue
        destino = destino_unico(c["entrada"], epub.stem + ".pdf",
                                hashlib.sha256(str(epub).encode()).hexdigest())
        # Um perfil limpo evita que plugins pessoais antigos do Calibre
        # impeçam uma conversão que não depende deles. O diretório é efêmero
        # e não altera as preferências do operador.
        with tempfile.TemporaryDirectory(prefix="biblio-calibre-") as config:
            ambiente = dict(os.environ)
            ambiente["CALIBRE_CONFIG_DIRECTORY"] = config
            resultado = subprocess.run(
                [str(EBOOK_CONVERT), str(epub), str(destino)],
                capture_output=True, text=True, timeout=1800, env=ambiente)
        if resultado.returncode or not destino.is_file():
            resumo["encontrados"] += 1
            resumo["falhas"] += 1
            erro = (resultado.stderr or resultado.stdout or
                    "o Calibre não produziu o PDF").strip()
            estado.setdefault("itens", {})[chave] = {
                "estado": "falha na conversão EPUB",
                "arquivo_origem": str(epub), "assinatura": assinatura,
                "erro": erro[-1000:], "atualizado_em": agora(),
            }
            print(f"  não foi possível converter {epub.name}: {erro[-300:]}")
            continue
        resumo["convertidos"] += 1
        importar_pdf(destino, opf=opf, convertido=True,
                     pasta_fonte=epub.parent, base_fonte=epub.stem,
                     assinatura=assinatura, chave_fonte=chave,
                     conversao={"motor": "Calibre (EPUB)"})
    estado["atualizado_em"] = agora()
    salvar_json(estado_path, estado)
    if resumo["encontrados"] or resumo["ambiguos"] or resumo["falhas"]:
        print("Entrada organizada: " + "; ".join(f"{k}={v}" for k, v in resumo.items()))
    return resumo


def processar_entrada(raiz, usar_api=True):
    c = inicializar(raiz)
    limpar_residuos_temporarios(c)
    catalogo = carregar_catalogo(c)
    preparar_entrada_organizada(c, catalogo)
    pdfs = sorted(p for p in c["entrada"].iterdir()
                  if p.is_file() and p.suffix.lower() == ".pdf")
    if not pdfs:
        print(f"Nenhum PDF novo em {c['entrada']}")
        return {"novos": 0, "duplicados": 0, "prontos": 0, "revisao": 0}

    resumo = {"novos": 0, "duplicados": 0, "prontos": 0, "revisao": 0,
              "duplicados_api": 0}
    chave_api = api_envio.ler_chave_chaves() if usar_api else ""
    sessao_api = None
    if chave_api:
        try:
            sessao_api = api_envio.criar_sessao_api()
        except Exception as exc:
            print(f"  consulta prévia indisponível: {exc}; preparo continuará")
    for i, origem in enumerate(pdfs, 1):
        consulta_nao_bloqueante = {}
        print(f"[{i}/{len(pdfs)}] {origem.name}")
        anunciar_fase_arquivo(
            c, origem.name, i, len(pdfs), 1, 7,
            "identificando cópia exata")
        digest = sha256(origem)
        anterior = catalogo["livros"].get(digest)
        if anterior:
            destino = mover_sem_substituir(origem, c["revisao"] / "DUPLICADOS", digest)
            chave = f"duplicado:{digest}:{agora()}"
            catalogo["livros"][chave] = {
                "hash_sha256": digest, "arquivo": destino.name,
                "caminho": relativo(c, destino), "tamanho_bytes": destino.stat().st_size,
                "estado": "duplicado", "duplicado_de": anterior.get("caminho", ""),
                "registrado_em": agora(), "processado_em": "", "metadados": "",
                "capa": "",
            }
            resumo["duplicados"] += 1
            print(f"  duplicado de {anterior.get('caminho', anterior.get('arquivo'))}")
            salvar_catalogo(c, catalogo)
            continue

        if sessao_api and chave_api:
            anunciar_fase_arquivo(
                c, origem.name, i, len(pdfs), 2, 7,
                "consultando duplicidade no Biblio")
            try:
                resposta, pistas = consultar_duplicidade_antes_do_preparo(
                    origem, sessao_api, chave_api)
                if (resposta.get("encontrado")
                        and api_envio.consulta_com_isbn_divergente(resposta)):
                    consulta_nao_bloqueante = resposta
                    print(
                        "  outra edição localizada pelo título/autor; ISBN "
                        "divergente; OCR e preparo desta edição continuarão")
                elif api_envio.consulta_bloqueia_envio(resposta):
                    destino, estado = registrar_duplicidade_previa(
                        c, catalogo, digest, origem, resposta, pistas)
                    resumo["duplicados_api"] += 1
                    print(
                        f"  já consta na API (ID {resposta.get('id', '?')}, "
                        f"{resposta.get('correspondencia', 'correspondência')}); "
                        f"OCR evitado; movido para {relativo(c, destino)}")
                    continue
            except Exception as exc:
                # Falha da consulta nunca impede a preparação local.
                print(f"  consulta prévia falhou: {exc}; preparo continuará")
        else:
            anunciar_fase_arquivo(
                c, origem.name, i, len(pdfs), 2, 7,
                "consulta ao Biblio indisponível; continuando localmente")

        anunciar_fase_arquivo(
            c, origem.name, i, len(pdfs), 3, 7,
            "extraindo o texto do PDF")
        paginas = prep.paginas_pdftotext(str(origem))
        anunciar_fase_arquivo(
            c, origem.name, i, len(pdfs), 4, 7,
            "comparando a assinatura com o acervo local")
        assinatura, duplicado_textual = localizar_duplicado_textual(
            c, catalogo, paginas, excluir_digest=digest)
        if duplicado_textual:
            destino = registrar_duplicado_textual(
                c, catalogo, digest, origem, assinatura, duplicado_textual)
            resumo["duplicados"] += 1
            print(
                f"  cópia textual de {duplicado_textual['arquivo']} "
                f"({duplicado_textual['similaridade']:.1%}); "
                f"movido para {relativo(c, destino)}")
            continue
        anunciar_fase_arquivo(
            c, origem.name, i, len(pdfs), 5, 7,
            "verificando OCR, páginas e tamanho")
        preparo = preparar_pdf_automaticamente(
            c, origem, digest, paginas,
            progresso_diagnostico=monitor_progresso_diagnostico(
                c, origem.name))
        fonte = preparo["fonte"]
        anunciar_fase_arquivo(
            c, origem.name, i, len(pdfs), 6, 7,
            "gerando capa e levantando metadados")
        capa = prep.gerar_capa(str(fonte), str(c["capas"]))
        try:
            linha = prep.processar(str(fonte), usar_api=usar_api, capa=capa,
                                  paginas=preparo["paginas"],
                                  revisao_caminho=str(origem))
        except Exception as exc:
            # Um arquivo com texto ou metadados inesperados deve ser separado
            # para revisão, sem interromper todos os demais itens do lote.
            erro = f"falha na extração bibliográfica: {exc}"
            print(f"  {erro}; o lote continuará")
            linha = {
                "arquivo": origem.name,
                "titulo": origem.stem,
                "tipo_documento": "livro",
                "situacao": "analisado",
                "situacao_metadados": "analisado",
                "status_ocr": preparo["diagnostico"].get("status", ""),
                "situacao_ocr": preparo["diagnostico"].get("status", ""),
                "conflitos": "",
                "pendencias": erro,
                "erro_processamento": erro,
                "_diagnostico_ocr": preparo["diagnostico"],
                "_evidencias": [],
            }
        if consulta_nao_bloqueante:
            linha["consulta_previa_api_nao_bloqueante"] = consulta_nao_bloqueante
            linha["aviso_consulta_previa"] = (
                "outra edição localizada: ISBN retornado pela API diverge "
                "do ISBN confirmado neste PDF")
        if preparo["erros"]:
            extras = " | ".join(preparo["erros"])
            linha["pendencias"] = " | ".join(
                x for x in (linha.get("pendencias", ""), extras) if x)
            if excedeu_tamanho_apos_preparo(preparo):
                linha["excecao_tamanho"] = True
                linha["motivo_excecao_tamanho"] = extras
                linha["situacao"] = ESTADO_EXCECAO_TAMANHO
            else:
                linha["situacao"] = ("precisa OCR" if
                                     preparo["diagnostico"]["status"] != "OCR aprovado"
                                     else "analisado")
            linha["situacao_metadados"] = linha["situacao"]
        anunciar_fase_arquivo(
            c, origem.name, i, len(pdfs), 7, 7,
            "confirmando a ficha e gravando o resultado")
        duplicado_api_apos_preparo = False
        if (sessao_api and chave_api
                and linha.get("situacao") == "pronto para cadastro"
                and linha.get("tipo_documento", "livro") == "livro"):
            atualizar_processamento_ativo(
                c, etapa="confirmando ficha final na API",
                arquivo=origem.name, item=i, itens_total=len(pdfs),
                pagina=0, paginas=0, percentual=0, eta_segundos=None)
            try:
                resposta_final = consultar_duplicidade_apos_preparo(
                    linha, sessao_api, chave_api)
                if (resposta_final.get("encontrado")
                        and api_envio.consulta_com_isbn_divergente(
                            resposta_final)):
                    linha["consulta_final_api_nao_bloqueante"] = resposta_final
                    linha["aviso_consulta_final"] = (
                        "outra edição localizada: ISBN retornado pela API "
                        "difere do ISBN definitivo desta ficha")
                    print(
                        "  consulta final: outra edição localizada; ISBN "
                        "divergente; esta edição continuará como pronta")
                elif api_envio.consulta_bloqueia_envio(resposta_final):
                    estado_final = aplicar_duplicidade_api_na_ficha(
                        linha, resposta_final)
                    duplicado_api_apos_preparo = True
                    resumo["duplicados_api"] += 1
                    print(
                        f"  consulta final: já consta na API "
                        f"(ID {resposta_final.get('id', '?')}, "
                        f"{resposta_final.get('correspondencia', 'correspondência')}); "
                        f"retirado da fila antes do envio [{estado_final}]")
            except Exception as exc:
                # A proteção do comando de envio consultará novamente; uma
                # indisponibilidade momentânea não descarta o preparo concluído.
                linha["aviso_consulta_final"] = str(exc)
                print(f"  consulta final indisponível: {exc}; ficha preservada")
        estado = linha["situacao"]
        tipo = linha.get("tipo_documento", "livro")
        if estado == ESTADO_DESCARTE:
            pasta_estado = c["descarte"]
        elif estado == ESTADO_EXCECAO_TAMANHO:
            pasta_estado = c["excecoes_tamanho"]
        elif duplicado_api_apos_preparo:
            pasta_estado = c["revisao"] / "DUPLICADOS-API"
        elif tipo in TIPOS_ACADEMICOS:
            pasta_estado = c["academicos"]
        elif tipo in TIPOS_DOCUMENTOS:
            pasta_estado = c["documentos"]
        elif tipo in TIPOS_REVISTAS:
            pasta_estado = c["revistas"]
        else:
            pasta_estado = c["pronto"] if estado == "pronto para cadastro" else c["revisao"]
        destino = mover_sem_substituir(origem, pasta_estado, digest)
        linha["arquivo"] = destino.name
        linha["pdf_original"] = relativo(c, destino)
        linha["pdf_preparado"] = (relativo(c, preparo["preparado"])
                                  if preparo["preparado"] else "")
        linha["preparacao_automatica"] = " | ".join(preparo["acoes"])
        linha["tamanho_original_bytes"] = preparo["tamanho_original"]
        linha["tamanho_envio_bytes"] = preparo["tamanho_envio"]
        linha["hash_pdf_preparado"] = preparo["hash_pdf_preparado"]
        linha["tentativas_compactacao"] = preparo["tentativas_compactacao"]
        linha["preflight_compactacao"] = preparo["preflight_compactacao"]
        linha["diagnostico_estrutura"] = preparo["diagnostico_estrutura"]
        linha["otimizacao_sem_perdas"] = preparo["otimizacao_sem_perdas"]
        linha["capa"] = relativo(c, capa) if capa else ""
        linha["simhash_texto"] = assinatura.get("simhash", "")
        linha["palavras_texto"] = assinatura.get("palavras", 0)
        linha["hash_texto"] = assinatura.get("hash_texto", "")
        ficha = gravar_ficha(c, digest, linha)
        catalogo["livros"][digest] = {
            "hash_sha256": digest, "arquivo": destino.name,
            "caminho": relativo(c, destino), "tamanho_bytes": destino.stat().st_size,
            "estado": estado, "origem": "00-ENTRADA", "registrado_em": agora(),
            "processado_em": agora(), "metadados": relativo(c, ficha),
            "capa": linha["capa"], "duplicado_de": "",
            "id_remoto": linha.get("id_remoto", ""),
            "correspondencia_api": linha.get("correspondencia_api", ""),
            "confirmado_por_api": linha.get("confirmado_por_api", ""),
            "simhash_texto": assinatura.get("simhash", ""),
            "palavras_texto": assinatura.get("palavras", 0),
            "hash_texto": assinatura.get("hash_texto", ""),
        }
        resumo["novos"] += 1
        resumo["prontos" if estado == "pronto para cadastro" else "revisao"] += 1
        print(f"  {estado}; movido para {relativo(c, destino)}")
        salvar_catalogo(c, catalogo)

    consolidar(c, catalogo)
    limpar_residuos_temporarios(c)
    print("\nResumo: " + "; ".join(f"{k}={v}" for k, v in resumo.items()))
    return resumo


def corrigir_ocr_pendentes(raiz, usar_api=True):
    """Retoma OCR pendente e PDFs grandes usando copia preservada."""
    c = inicializar(raiz)
    catalogo = carregar_catalogo(c)
    alvos = []
    total_catalogo = len(catalogo["livros"])
    print(f"  verificando {total_catalogo} registros do catálogo...", flush=True)
    atualizar_processamento_ativo(
        c, etapa="verificando pendências", item=0,
        itens_total=total_catalogo, percentual=0)
    # Apenas estes dois estados podem exigir trabalho nesta etapa. Abrir as
    # fichas dos demais era inutil e, no Dropbox, podia iniciar seu download.
    for lidos, (digest, registro) in enumerate(catalogo["livros"].items(), 1):
        if lidos == 1 or lidos % 25 == 0 or lidos == total_catalogo:
            percentual = (round(lidos * 100 / total_catalogo)
                          if total_catalogo else 100)
            print(f"    ...verificados {lidos}/{total_catalogo} "
                  f"({percentual}%)", flush=True)
            atualizar_processamento_ativo(
                c, etapa="verificando pendências", item=lidos,
                itens_total=total_catalogo, percentual=percentual)
        if str(digest).startswith("duplicado:"):
            continue
        estado = registro.get("estado")
        if estado not in {"precisa OCR", "pronto para cadastro"}:
            continue
        if estado == "precisa OCR":
            alvos.append((digest, registro))
            continue
        origem = c["raiz"] / registro.get("caminho", "")
        ficha_path = c["raiz"] / registro.get("metadados", "")
        preparo_pendente = False
        try:
            ficha = json.loads(ficha_path.read_text(encoding="utf-8"))
            preparo_pendente = preparo_envio_pendente(
                registro, origem, ficha, c["raiz"])
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        if preparo_pendente:
            alvos.append((digest, registro))
    resumo = {"encontrados": len(alvos), "ocr_aprovado": 0,
              "prontos": 0, "revisao": 0, "falhas": 0}
    # Varrer o catalogo inteiro leva alguns segundos e nao imprimia NADA.
    # A etapa 1 do ciclo ficava muda: quem olhava a tela via o titulo e
    # depois silencio, indistinguivel de travamento. Dizer "nada pendente"
    # e o minimo - ausencia precisa de causa (PROCEDIMENTO, item 10).
    print(f"  {len(catalogo['livros'])} itens no catálogo verificados; "
          f"{len(alvos)} precisam de OCR ou de nova cópia para envio",
          flush=True)
    atualizar_processamento_ativo(
        c, etapa=("nada pendente" if not alvos else "preparando"),
        item=0, itens_total=len(alvos))
    if not alvos:
        print("  nada pendente nesta etapa.", flush=True)
        consolidar(c, catalogo)
        return resumo
    for posicao, (digest, registro) in enumerate(alvos, 1):
        origem = c["raiz"] / registro.get("caminho", "")
        ficha_path = c["raiz"] / registro.get("metadados", "")
        atualizar_processamento_ativo(
            c, etapa="analisando", arquivo=registro.get("arquivo", ""),
            item=posicao, itens_total=len(alvos), pagina=0, paginas=0,
            percentual=0, eta_segundos=None)
        print(f"[PREPARO {posicao}/{len(alvos)}] {registro.get('arquivo')}", flush=True)
        if not origem.is_file():
            candidatos = [p for chave, pasta in c.items()
                          if chave not in ("raiz", "controle", "capas",
                                           "metadados", "preparados")
                          for p in [pasta / registro.get("arquivo", "")]
                          if p.is_file()]
            if len(candidatos) == 1:
                origem = candidatos[0]
        if not origem.is_file() or not ficha_path.is_file():
            print("  original ou ficha nao encontrado; mantido para revisao")
            resumo["falhas"] += 1
            continue
        ficha_anterior = json.loads(ficha_path.read_text(encoding="utf-8"))
        preparado_rel = ficha_anterior.get("pdf_preparado", "")
        preparado_existente = (c["raiz"] / preparado_rel
                               if preparado_rel else None)
        fonte_texto = (preparado_existente
                       if preparado_existente and preparado_existente.is_file()
                       else origem)
        preparo = preparar_pdf_automaticamente(
            c, origem, digest, prep.paginas_pdftotext(str(fonte_texto)),
            fonte_preparada=preparado_existente,
            progresso_diagnostico=monitor_progresso_diagnostico(
                c, origem.name))
        if preparo["diagnostico"]["status"] != "OCR aprovado":
            ficha = json.loads(ficha_path.read_text(encoding="utf-8"))
            ficha["ultima_tentativa_preparacao"] = agora()
            ficha["erros_preparacao"] = " | ".join(preparo["erros"])
            ficha["pdf_preparado"] = (relativo(c, preparo["preparado"])
                                      if preparo["preparado"] else "")
            ficha["tentativas_compactacao"] = preparo["tentativas_compactacao"]
            ficha["preflight_compactacao"] = preparo["preflight_compactacao"]
            ficha["diagnostico_estrutura"] = preparo["diagnostico_estrutura"]
            ficha["otimizacao_sem_perdas"] = preparo["otimizacao_sem_perdas"]
            salvar_json(ficha_path, ficha)
            print("  OCR ainda nao aprovado; original preservado")
            resumo["falhas"] += 1
            continue

        fonte = preparo["fonte"]
        capa = prep.gerar_capa(str(fonte), str(c["capas"]))
        linha = prep.processar(str(fonte), usar_api=usar_api, capa=capa,
                              paginas=preparo["paginas"],
                              revisao_caminho=str(origem))
        if preparo["erros"]:
            linha["pendencias"] = " | ".join(
                x for x in (linha.get("pendencias", ""),
                            " | ".join(preparo["erros"])) if x)
            if excedeu_tamanho_apos_preparo(preparo):
                linha["excecao_tamanho"] = True
                linha["motivo_excecao_tamanho"] = " | ".join(preparo["erros"])
                linha["situacao"] = ESTADO_EXCECAO_TAMANHO
            else:
                linha["situacao"] = "analisado"
            linha["situacao_metadados"] = linha["situacao"]
        estado = linha["situacao"]
        destino = origem
        if (estado == ESTADO_DESCARTE and
                origem.parent != c["descarte"]):
            destino = mover_sem_substituir(origem, c["descarte"], digest)
        elif (estado == ESTADO_EXCECAO_TAMANHO and
                origem.parent != c["excecoes_tamanho"]):
            destino = mover_sem_substituir(origem, c["excecoes_tamanho"], digest)
        elif estado == "pronto para cadastro" and origem.parent != c["pronto"]:
            destino = mover_sem_substituir(origem, c["pronto"], digest)
        linha.update({
            "arquivo": destino.name, "pdf_original": relativo(c, destino),
            "pdf_preparado": (relativo(c, preparo["preparado"])
                              if preparo["preparado"] else ""),
            "preparacao_automatica": " | ".join(preparo["acoes"]),
            "tamanho_original_bytes": preparo["tamanho_original"],
            "tamanho_envio_bytes": preparo["tamanho_envio"],
            "hash_pdf_preparado": preparo["hash_pdf_preparado"],
            "tentativas_compactacao": preparo["tentativas_compactacao"],
            "preflight_compactacao": preparo["preflight_compactacao"],
            "diagnostico_estrutura": preparo["diagnostico_estrutura"],
            "otimizacao_sem_perdas": preparo["otimizacao_sem_perdas"],
            "capa": relativo(c, capa) if capa else "",
        })
        ficha = {k: v for k, v in linha.items() if not k.startswith("_")}
        ficha["diagnostico_ocr"] = linha["_diagnostico_ocr"]
        ficha["evidencias"] = linha["_evidencias"]
        ficha["hash_sha256"] = digest
        ficha["gerado_em"] = agora()
        salvar_json(ficha_path, ficha)
        registro.update({
            "arquivo": destino.name, "caminho": relativo(c, destino),
            "estado": estado, "processado_em": agora(),
            "capa": linha["capa"], "tamanho_bytes": destino.stat().st_size,
        })
        salvar_catalogo(c, catalogo)
        resumo["ocr_aprovado"] += 1
        resumo["prontos" if estado == "pronto para cadastro" else "revisao"] += 1
        print(f"  OCR aprovado; estado: {estado}")
    consolidar(c, catalogo)
    if alvos:
        print("\nOCR: " + "; ".join(f"{k}={v}" for k, v in resumo.items()))
    return resumo


def reprocessar_revisao(raiz, usar_api=True, arquivos=None):
    """Reaplica extracao e revisoes documentadas aos itens ainda pendentes."""
    c = inicializar(raiz)
    catalogo = carregar_catalogo(c)
    # Itens prontos ou estacionados para outra API nao devem ser reabertos a
    # cada ciclo. Um --arquivo explicito continua permitindo revisao pontual.
    estados = {"analisado", "conflito", "precisa OCR"}
    filtro = set(arquivos or [])
    alvos = [(h, r) for h, r in catalogo["livros"].items()
             if not str(h).startswith("duplicado:")
             and ((not filtro and r.get("estado") in estados)
                  or (filtro and r.get("arquivo") in filtro))]

    # ------------------------------------------------------------------
    # REVISAO APROVADA QUE AINDA NAO FOI APLICADA entra sempre.
    #
    # Os estados acima nao cobrem quem ja foi movido para uma fila
    # especifica. Uma monografia em 15-TESES com revisao aprovada ficava
    # fora do alcance: a revisao existia, estava correta, e NUNCA valia -
    # o item ja tinha saido de "conflito" e por isso nao era reavaliado.
    #
    # Revisao aprovada e decisao humana registrada. Ela precisa alcancar o
    # item onde quer que ele esteja, menos onde mexer seria perigoso:
    # o que ja foi cadastrado ou ja teve os arquivos liberados.
    # ------------------------------------------------------------------
    if not filtro:
        try:
            revisoes = json.loads(
                (c["controle"] / "revisoes-manuais.json").read_text(
                    encoding="utf-8")).get("livros", {})
        except (OSError, ValueError, json.JSONDecodeError):
            revisoes = {}

        intocaveis = ("cadastrado", "liberados", "descartado")
        ja_alvo = {h for h, _ in alvos}
        for digest, registro in catalogo["livros"].items():
            if digest in ja_alvo or str(digest).startswith("duplicado:"):
                continue
            estado_atual = str(registro.get("estado", ""))
            if any(marca in estado_atual for marca in intocaveis):
                continue
            rev = revisoes.get(registro.get("arquivo", ""), {})
            if not rev.get("aprovado"):
                continue
            campos = rev.get("campos", {}) or {}
            try:
                ficha = json.loads(
                    (c["raiz"] / registro.get("metadados", "")).read_text(
                        encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                ficha = {}
            # so reprocessa quando a ficha DIVERGE: se ja reflete a
            # revisao, refazer seria trabalho perdido
            divergiu = any(
                str(ficha.get(campo, "") or "").strip()
                != str(valor or "").strip()
                for campo, valor in campos.items()
                if campo in ("titulo", "nmAutor0", "editora", "data",
                             "isbn", "tipo_documento", "lugar"))
            if divergiu:
                alvos.append((digest, registro))
                print(f"  revisão aprovada ainda não aplicada: "
                      f"{registro.get('arquivo', '')[:60]}")
    resumo = {"encontrados": len(alvos), "prontos": 0,
              "academicos": 0, "documentos": 0, "revisao": 0, "falhas": 0}
    for posicao, (digest, registro) in enumerate(alvos, 1):
        atualizar_processamento_ativo(
            c, operacao="reprocessar revisão",
            etapa=f"reavaliando {posicao} de {len(alvos)}",
            arquivo=registro.get("arquivo", ""), pagina=posicao,
            paginas=len(alvos),
            percentual=round(posicao * 100 / max(1, len(alvos))),
            eta_segundos=None)
        origem = c["raiz"] / registro.get("caminho", "")
        ficha_path = c["raiz"] / registro.get("metadados", "")
        print(f"[REVISÃO {posicao}/{len(alvos)}] {registro.get('arquivo')}",
              flush=True)
        if not origem.is_file():
            candidatos = [p for chave, pasta in c.items()
                          if chave not in ("raiz", "controle", "capas",
                                           "metadados", "preparados")
                          for p in [pasta / registro.get("arquivo", "")]
                          if p.is_file()]
            if len(candidatos) == 1:
                origem = candidatos[0]
        if not origem.is_file() or not ficha_path.is_file():
            resumo["falhas"] += 1
            print("  original ou ficha não encontrado")
            continue
        anterior = json.loads(ficha_path.read_text(encoding="utf-8"))
        preparado_rel = anterior.get("pdf_preparado", "")
        preparado = c["raiz"] / preparado_rel if preparado_rel else None
        fonte = preparado if preparado and preparado.is_file() else origem
        tamanho_envio = fonte.stat().st_size
        paginas = prep.paginas_pdftotext(str(fonte))
        assinatura, duplicado_textual = localizar_duplicado_textual(
            c, catalogo, paginas, excluir_digest=digest)
        if duplicado_textual:
            destino = registrar_duplicado_textual(
                c, catalogo, digest, origem, assinatura, duplicado_textual)
            resumo["revisao"] += 1
            print(
                f"  duplicado textual de {duplicado_textual['arquivo']} "
                f"({duplicado_textual['similaridade']:.1%}); "
                f"destino: {relativo(c, destino)}")
            continue
        capa = prep.gerar_capa(str(fonte), str(c["capas"]))
        linha = prep.processar(
            str(fonte), usar_api=usar_api, capa=capa, paginas=paginas,
            revisao_caminho=str(origem))
        if tamanho_envio > LIMITE_ENVIO_BYTES:
            linha["excecao_tamanho"] = True
            linha["motivo_excecao_tamanho"] = (
                f"arquivo preparado excede {LIMITE_ENVIO_BYTES/1_000_000:.0f} MB")
            linha["situacao"] = ESTADO_EXCECAO_TAMANHO
            linha["situacao_metadados"] = ESTADO_EXCECAO_TAMANHO
        tipo = linha.get("tipo_documento", "livro")
        estado = linha["situacao"]
        if estado == ESTADO_DESCARTE:
            pasta = c["descarte"]
        elif estado == ESTADO_EXCECAO_TAMANHO:
            pasta = c["excecoes_tamanho"]
        elif tipo in TIPOS_ACADEMICOS:
            pasta = c["academicos"]
            resumo["academicos"] += 1
        elif tipo in TIPOS_DOCUMENTOS:
            pasta = c["documentos"]
            resumo["documentos"] += 1
        elif tipo in TIPOS_REVISTAS:
            pasta = c["revistas"]
            resumo["documentos"] += 1
        elif estado == "pronto para cadastro":
            pasta = c["pronto"]
            resumo["prontos"] += 1
        else:
            pasta = c["revisao"]
            resumo["revisao"] += 1
        destino = origem
        if origem.parent != pasta:
            destino = mover_sem_substituir(origem, pasta, digest)
        linha.update({
            "arquivo": destino.name,
            "pdf_original": relativo(c, destino),
            "pdf_preparado": preparado_rel,
            "preparacao_automatica": anterior.get("preparacao_automatica", ""),
            "tamanho_original_bytes": destino.stat().st_size,
            "tamanho_envio_bytes": tamanho_envio,
            "capa": relativo(c, capa) if capa else "",
            "simhash_texto": assinatura.get("simhash", ""),
            "palavras_texto": assinatura.get("palavras", 0),
            "hash_texto": assinatura.get("hash_texto", ""),
        })
        ficha = {k: v for k, v in linha.items() if not k.startswith("_")}
        ficha["diagnostico_ocr"] = linha["_diagnostico_ocr"]
        ficha["evidencias"] = linha["_evidencias"]
        ficha["hash_sha256"] = digest
        ficha["gerado_em"] = agora()
        salvar_json(ficha_path, ficha)
        registro.update({
            "arquivo": destino.name, "caminho": relativo(c, destino),
            "estado": estado, "processado_em": agora(),
            "capa": linha["capa"], "tamanho_bytes": destino.stat().st_size,
            "simhash_texto": assinatura.get("simhash", ""),
            "palavras_texto": assinatura.get("palavras", 0),
            "hash_texto": assinatura.get("hash_texto", ""),
        })
        salvar_catalogo(c, catalogo)
        print(f"  {tipo}; estado: {estado}; destino: {relativo(c, destino)}")
    consolidar(c, catalogo)
    print("\nRevisão: " + "; ".join(f"{k}={v}" for k, v in resumo.items()))
    return resumo


def mostrar_status(raiz):
    c = inicializar(raiz)
    ativo_path = c["controle"] / "processamento-ativo.json"
    try:
        ativo = json.loads(ativo_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        ativo = {}
    if ativo:
        pid = int(ativo.get("pid", 0) or 0)
        vivo = False
        if pid:
            try:
                os.kill(pid, 0)
                vivo = True
            except (OSError, ProcessLookupError):
                pass
        situacao = "ATIVO" if vivo else "registro antigo"
        print(f"Processamento: {situacao}")
        if ativo.get("arquivo"):
            lote = ""
            if ativo.get("item") and ativo.get("itens_total"):
                lote = f" ({ativo['item']}/{ativo['itens_total']})"
            print(f"  arquivo: {ativo['arquivo']}{lote}")
        print(f"  etapa: {ativo.get('etapa', 'não informada')}")
        if ativo.get("paginas"):
            print(
                f"  progresso: página {ativo.get('pagina', 0)}/"
                f"{ativo['paginas']} ({ativo.get('percentual', 0)}%)")
        if ativo.get("bytes_origem"):
            percorridos = int(ativo.get("bytes_percorridos", 0) or 0)
            total = int(ativo["bytes_origem"])
            print(
                f"  volume percorrido: {percorridos:,}/{total:,} bytes "
                f"({percorridos/1_000_000:.1f}/{total/1_000_000:.1f} MB)"
                .replace(",", "."))
        if ativo.get("bytes_temporarios_processados"):
            temporarios = int(ativo["bytes_temporarios_processados"])
            print(f"  imagens temporárias processadas: {temporarios:,} bytes "
                  f"({temporarios/1_000_000:.1f} MB)".replace(",", "."))
        if ativo.get("bytes_saida_temporaria") is not None:
            saida = int(ativo.get("bytes_saida_temporaria", 0) or 0)
            print(f"  saída temporária: {saida:,} bytes "
                  f"({saida/1_000_000:.1f} MB)".replace(",", "."))
        if ativo.get("eta_segundos") is not None:
            print(f"  estimativa restante: ~{max(0, int(ativo['eta_segundos'])) // 60} min")
        print(f"  atualizado: {ativo.get('atualizado_em', '')}")
    catalogo = carregar_catalogo(c)
    contagem = {}
    bytes_estado = {}
    for r in catalogo["livros"].values():
        e = r.get("estado", "sem estado")
        contagem[e] = contagem.get(e, 0) + 1
        bytes_estado[e] = bytes_estado.get(e, 0) + int(r.get("tamanho_bytes", 0) or 0)
    print(f"Catálogo: {len(catalogo['livros'])} registro(s)")
    for e in sorted(contagem):
        print(f"  {e:.<28} {contagem[e]:4}  ({bytes_estado[e]/1024/1024:.1f} MB)")
    extensoes_entrada = ({".pdf", ".epub"} | EXTENSOES_WORD
                         | EXTENSOES_APRESENTACAO
                         | set(converter_html.EXTENSOES_HTML))
    arquivos_entrada = [
        p for p in c["entrada"].rglob("*")
        if p.is_file() and not p.is_symlink()
        and not arquivo_de_sistema_ignorado(p)
        and not any(parte.endswith(("_files", "_arquivos")) for parte in p.parts)
    ]
    aguardando = len(arquivos_entrada)
    desconhecidos = sum(
        1 for p in arquivos_entrada if p.suffix.lower() not in extensoes_entrada)
    print(f"  {'aguardando na entrada':.<28} {aguardando:4}")
    if desconhecidos:
        print(f"  {'formato não tratado na entrada':.<28} {desconhecidos:4}")


def _resolver_arquivo_local(c, valor):
    if not valor:
        return None
    p = pathlib.Path(valor).expanduser()
    candidatos = [p] if p.is_absolute() else [c["raiz"] / p,
                                                c["raiz"].parent / p]
    for candidato in candidatos:
        try:
            resolvido = candidato.resolve()
            resolvido.relative_to(c["raiz"])
        except (OSError, ValueError):
            continue
        if resolvido.is_file() and not resolvido.is_symlink():
            return resolvido
    return None


def _destino_lixeira(lixeira, origem, identificador):
    identificador = re.sub(r"[^A-Za-z0-9_-]+", "-", str(identificador or "item"))
    base = f"biblio-{identificador}-{origem.name}"
    destino = lixeira / base
    contador = 2
    while destino.exists():
        destino = lixeira / f"biblio-{identificador}-{origem.stem}-{contador}{origem.suffix}"
        contador += 1
    return destino


def _arquivos_origem_importados(ficha, raiz_local):
    """Resolve somente os arquivos associados a este livro pelo importador.

    A pasta pode conter outros livros do mesmo autor; por isso nunca entra no
    plano como um bloco. Cada caminho foi registrado na importacao e precisa
    continuar dentro da pasta declarada.
    """
    valor = ficha.get("pasta_origem_importacao", "")
    registrados = ficha.get("arquivos_origem_importacao", [])
    if not valor or not isinstance(registrados, list) or not registrados:
        return []
    pasta = pathlib.Path(valor).expanduser()
    try:
        pasta = pasta.resolve(strict=True)
    except OSError:
        return []
    if (not pasta.is_dir() or pasta.is_symlink()
            or pasta == pathlib.Path(pasta.anchor)
            or pasta == pathlib.Path.home().resolve()):
        return []
    confirmados = []
    permitidas = ({".pdf", ".epub", ".opf", ".jpg", ".jpeg", ".png",
                   ".gif", ".webp", ".mobi", ".azw", ".azw3", ".doc",
                   ".docx", ".rtf", ".txt"} | EXTENSOES_APRESENTACAO)
    for valor_arquivo in registrados:
        try:
            arquivo = pathlib.Path(valor_arquivo).expanduser().resolve(strict=True)
            arquivo.relative_to(pasta)
        except (OSError, ValueError, TypeError):
            continue
        if (arquivo.is_file() and not arquivo.is_symlink()
                and arquivo.suffix.lower() in permitidas):
            confirmados.append(arquivo)
    # O OPF é aproveitado quando existe, mas não é obrigatório.
    extensoes = {p.suffix.lower() for p in confirmados}
    if not extensoes.intersection(
            {".pdf", ".epub", ".doc", ".docx"} | EXTENSOES_APRESENTACAO):
        return []
    return confirmados


def _arquivos_origem_historico(c, digest, historico):
    """Recupera originais legados pelo hash do PDF gerado pelo importador.

    Somente arquivos ainda existentes dentro de 00-ENTRADA sao aceitos. O
    historico e usado porque fichas de duplicidade criadas antes da correcao
    podiam nao copiar a lista de originais Word/EPUB.
    """
    entrada = c["entrada"].resolve()
    permitidas = ({".pdf", ".epub", ".opf", ".jpg", ".jpeg", ".png",
                   ".gif", ".webp", ".mobi", ".azw", ".azw3", ".doc",
                   ".docx", ".rtf", ".txt"} | EXTENSOES_APRESENTACAO)
    encontrados = []
    for origem, dados in (historico or {}).items():
        if not isinstance(dados, dict) or dados.get("hash_sha256") != digest:
            continue
        for valor in (origem, dados.get("pdf_entrada", "")):
            if not valor:
                continue
            try:
                arquivo = pathlib.Path(valor).expanduser().resolve(strict=True)
                arquivo.relative_to(entrada)
            except (OSError, ValueError, TypeError):
                continue
            if (arquivo.is_file() and not arquivo.is_symlink()
                    and arquivo.suffix.lower() in permitidas
                    and arquivo not in encontrados):
                encontrados.append(arquivo)
    return encontrados


def _pastas_residuais_entrada(c):
    """Lista subpastas sem conteúdo real, ignorando somente .DS_Store."""
    entrada = c["entrada"].resolve()
    residuais = []
    for pasta in sorted((p for p in entrada.rglob("*") if p.is_dir()),
                        key=lambda p: len(p.parts), reverse=True):
        tem_conteudo = False
        try:
            descendentes = pasta.rglob("*")
            for item in descendentes:
                if item.is_symlink():
                    tem_conteudo = True
                    break
                if item.is_file() and item.name != ".DS_Store":
                    tem_conteudo = True
                    break
        except OSError:
            tem_conteudo = True
        if not tem_conteudo:
            residuais.append(pasta)
    return residuais


def _arquivos_orfaos(c, catalogo):
    """Arquivos de apoio que nenhum registro vivo referencia.

    Coleta por ALCANCABILIDADE, como um coletor de lixo: monta o conjunto
    de tudo que o catalogo aponta e chama de orfao o que sobrar nas pastas
    de apoio.

    Origem: `_preparados-envio` guardava copias otimizadas cujos originais
    ja tinham sido liberados. Sao poucos MB hoje, mas crescem a cada envio
    e ninguem os enxergava. `_capas300`, criada pelo TESTAR-CAPAS.command,
    e outro caso - nenhum modulo do aplicativo a referencia.

    So REPORTA. A remocao continua passando pela confirmacao do operador.
    """
    referenciados = set()
    for registro in catalogo.get("livros", {}).values():
        for chave in ("caminho", "capa", "metadados", "pdf_preparado",
                      "pdf_original", "arquivo"):
            valor = registro.get(chave)
            if valor:
                referenciados.add(pathlib.Path(str(valor)).name)
        ficha = c["raiz"] / registro.get("metadados", "")
        try:
            dados = json.loads(ficha.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        for chave in ("capa", "pdf_original", "pdf_preparado", "arquivo"):
            valor = dados.get(chave)
            if valor:
                referenciados.add(pathlib.Path(str(valor)).name)

    orfaos = []
    pastas = [c.get("preparados"), c.get("capas"), c["raiz"] / "_capas300"]
    for pasta in pastas:
        if not pasta or not pathlib.Path(pasta).is_dir():
            continue
        pasta = pathlib.Path(pasta)
        # `_preparados-envio` chegou a receber um `_controle` completo por
        # uma execução antiga com raiz incorreta. A varredura recursiva faz
        # esses caches aparecerem na limpeza; capas continuam rasas.
        arquivos = (pasta.rglob("*") if pasta == c.get("preparados")
                    else pasta.iterdir())
        for arquivo in sorted(arquivos):
            if not arquivo.is_file() or arquivo.name.startswith("."):
                continue
            if arquivo.name in referenciados:
                continue
            # O sufixo de hash distingue a cópia preparada do original.
            # Antes removíamos o sufixo e aceitávamos apenas a semelhança do
            # nome: quatro preparados continuavam presos mesmo depois de o
            # original ter sido cadastrado e liberado. Agora só um apontador
            # EXATO preserva a cópia.
            orfaos.append({"arquivo": relativo(c, arquivo),
                           "bytes": arquivo.stat().st_size,
                           "motivo": "nenhum registro do catálogo referencia"})
    return orfaos


def liberar_espaco(raiz, executar=False, lixeira=None):
    """Leva à Lixeira cadastros, duplicados e descartes confirmados."""
    c = inicializar(raiz)
    catalogo = carregar_catalogo(c)

    # ------------------------------------------------------------------
    # TODAS as filas, derivadas da mesma fonte que o resto do aplicativo.
    #
    # Antes so a fila principal era lida. Documentos, trabalhos academicos
    # e revistas tem filas proprias (api_envio.FILAS_ESPECIFICAS) e nunca
    # eram varridos - dois artigos ficaram parados em
    # 16-ARTIGOS-E-DOCUMENTOS mesmo marcados como duplicados confirmados.
    #
    # Repetir o nome do arquivo aqui foi o que criou a divergencia. Duas
    # listas que precisam concordar, escritas em dois lugares, sempre
    # acabam discordando.
    # ------------------------------------------------------------------
    nomes_filas = ["fila-envio-api.json"]
    nomes_filas += list(getattr(api_envio, "FILAS_ESPECIFICAS", {}).values())

    fila = {"itens": []}
    for nome_fila in dict.fromkeys(nomes_filas):
        try:
            dados = json.loads(
                (c["controle"] / nome_fila).read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        for item in dados.get("itens", []):
            copia = dict(item)
            copia.setdefault("fila_origem", nome_fila)
            fila["itens"].append(copia)
    try:
        historico_importacoes = json.loads(
            (c["controle"] / "importacoes-organizadas.json").read_text(
                encoding="utf-8")).get("itens", {})
    except (OSError, ValueError, json.JSONDecodeError, AttributeError):
        historico_importacoes = {}
    def _chave_ficha(item):
        """A fila principal chama de "ficha"; as especificas, de "metadados".

        Mesmo dado, dois nomes - e a busca so procurava por um deles. E a
        mesma classe de erro das filas: a mesma coisa escrita em dois
        lugares acaba divergindo.
        """
        return item.get("ficha") or item.get("metadados") or ""

    def _vinculo_api_com_id_comprovado(item):
        """Aceita o vínculo pendente quando a própria consulta o prova.

        O estado histórico ``já existente ... conferir vínculo`` também era
        usado para respostas que traziam um ID inequívoco e confirmação por
        título/autor. Manter esses casos bloqueados fazia o comando 12 ignorar
        arquivos cuja existência remota já estava documentada. Não basta ter
        um ID solto: a resposta guardada precisa dizer ``encontrado``, repetir
        o mesmo ID e registrar o critério bibliográfico usado.
        """
        if item.get("estado") != "já existente na API - conferir vínculo":
            return False
        id_remoto = item.get("id_remoto")
        consulta = item.get("consulta_previa_api")
        if not id_remoto or not isinstance(consulta, dict):
            return False
        if not consulta.get("encontrado") or str(consulta.get("id")) != str(id_remoto):
            return False
        return consulta.get("confirmado_por") in {
            "isbn", "titulo", "titulo_autor", "titulo_autor_aproximado"
        }

    liberaveis = {}
    for item in fila.get("itens", []):
        if item.get("estado") == "cadastrado" and item.get("id_remoto"):
            copia = dict(item)
            copia["motivo_liberacao"] = "cadastro confirmado pela API"
            copia["identificador_lixeira"] = item["id_remoto"]
            liberaveis[_chave_ficha(item)] = copia
        # O ESTADO ja e a prova, e o id_remoto nao e exigido.
        #
        # "duplicado confirmado por ISBN" so e atribuido quando
        # consulta_confirmada_por_isbn() aprova, e ela exige que o ISBN
        # enviado seja IDENTICO ao recebido pelo Biblio. O equivalente por
        # titulo exige correspondencia exata, uma unica ocorrencia e autor
        # coincidente. Sao confirmacoes contra a base real.
        #
        # O id_remoto fica vazio apenas porque a resposta de BUSCA do
        # Biblio nao traz o campo "id" - ausencia de um campo da resposta,
        # nao ausencia de prova. Exigi-lo deixava presos itens ja
        # confirmados: dois artigos ficaram parados por esse motivo.
        elif (item.get("estado") in {
                  "duplicado confirmado por ISBN",
                  api_envio.ESTADO_DUPLICADO_TITULO_AUTOR,
                  api_envio.ESTADO_DUPLICADO_TITULO}
              or (item.get("estado") == "duplicado informado pela API - revisar"
                  and int(item.get("http_status", 0) or 0) == 400)
              or _vinculo_api_com_id_comprovado(item)):
            copia = dict(item)
            copia["motivo_liberacao"] = "duplicidade confirmada pela API"
            copia["identificador_lixeira"] = "duplicado-api"
            liberaveis[_chave_ficha(item)] = copia
    permitidas = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp"}
    protegidas = {c["controle"], c["metadados"]}
    planos = []
    vistos = set()

    for chave_catalogo, registro in catalogo["livros"].items():
        item = liberaveis.get(registro.get("metadados"))
        duplicado_local = (
            str(chave_catalogo).startswith("duplicado:")
            or registro.get("estado") in {
                "duplicado", ESTADO_DUPLICADO_CONTEUDO})
        descarte = registro.get("estado") == ESTADO_DESCARTE
        cadastrado_direto = (registro.get("estado") == "cadastrado"
                             and registro.get("id_remoto"))
        if duplicado_local and not item:
            item = {
                "titulo": registro.get("arquivo", "Duplicado local"),
                "id_remoto": "", "motivo_liberacao": "cópia local idêntica",
                "identificador_lixeira": "duplicado-local",
            }
        elif descarte and not item:
            item = {
                "titulo": registro.get("arquivo", "Item descartado"),
                "id_remoto": "", "motivo_liberacao": "item classificado para descarte",
                "identificador_lixeira": "descarte",
            }
        elif cadastrado_direto and not item:
            item = {
                "titulo": registro.get("arquivo", "Cadastro confirmado"),
                "id_remoto": registro.get("id_remoto", ""),
                "motivo_liberacao": "cadastro confirmado pela API",
                "identificador_lixeira": registro.get("id_remoto"),
            }
        elif (not item
              and registro.get("estado") in {
                  "duplicado confirmado por ISBN",
                  api_envio.ESTADO_DUPLICADO_TITULO_AUTOR,
                  api_envio.ESTADO_DUPLICADO_TITULO}
              and registro.get("id_remoto")
              and registro.get("confirmado_por_api") in {
                  "isbn", "titulo_autor", "titulo"}):
            item = {
                "titulo": registro.get("arquivo", "Duplicado na API"),
                "id_remoto": registro.get("id_remoto", ""),
                "motivo_liberacao": "duplicidade confirmada pela consulta prévia",
                "identificador_lixeira": registro.get("id_remoto", "duplicado-api"),
            }
        if not item and registro.get("arquivos_liberados_em"):
            ficha_anterior = c["raiz"] / registro.get("metadados", "")
            try:
                dados_anteriores = json.loads(
                    ficha_anterior.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                dados_anteriores = {}
            motivo_anterior = dados_anteriores.get(
                "motivo_liberacao_espaco", "arquivos locais remanescentes")
            item = {
                "titulo": registro.get("arquivo", "Original remanescente"),
                "id_remoto": registro.get("id_remoto", ""),
                "motivo_liberacao": motivo_anterior,
                "identificador_lixeira": registro.get("id_remoto", "legado"),
            }
        if not item:
            continue
        ficha_path = c["raiz"] / registro.get("metadados", "")
        try:
            ficha = json.loads(ficha_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            ficha = {}
        if not ficha and not duplicado_local:
            continue
        valores = [registro.get("caminho"), ficha.get("pdf_original"),
                   ficha.get("pdf_preparado"), ficha.get("capa"),
                   registro.get("capa")]
        arquivos = []
        for valor in valores:
            arquivo = _resolver_arquivo_local(c, valor)
            if not arquivo or arquivo in vistos or arquivo.suffix.lower() not in permitidas:
                continue
            if any(pasta == arquivo or pasta in arquivo.parents for pasta in protegidas):
                continue
            vistos.add(arquivo)
            arquivos.append({"caminho": arquivo, "bytes": arquivo.stat().st_size})
        origens_importadas = _arquivos_origem_importados(ficha, c["raiz"])
        origens_importadas += _arquivos_origem_historico(
            c, registro.get("hash_sha256", chave_catalogo),
            historico_importacoes)
        for arquivo_origem in origens_importadas:
            if arquivo_origem in vistos:
                continue
            vistos.add(arquivo_origem)
            arquivos.append({"caminho": arquivo_origem,
                             "bytes": arquivo_origem.stat().st_size,
                             "arquivo_importado": True})
        if arquivos:
            planos.append({
                "chave_catalogo": chave_catalogo,
                "hash_sha256": registro.get("hash_sha256", chave_catalogo),
                "titulo": item.get("titulo", ficha.get("titulo", "")),
                "id_remoto": item.get("id_remoto"),
                "identificador_lixeira": item.get("identificador_lixeira"),
                "motivo_liberacao": item.get("motivo_liberacao", ""),
                "metadados": registro.get("metadados", ""),
                "arquivos": arquivos,
            })

    # ------------------------------------------------------------------
    # Itens que o ESTADO diz liberaveis mas que nao trazem PROVA.
    #
    # "duplicado confirmado por ISBN" sem id_remoto e sem referencia ao
    # original nao prova que existe outra copia - liberar seria arriscar o
    # unico exemplar. Nao afrouxamos a trava; tornamos o impasse visivel,
    # que era o que faltava: eles simplesmente ficavam parados, sem
    # aparecer em lugar nenhum.
    # ------------------------------------------------------------------
    # Os estados "confirmado" NAO entram aqui: a confirmacao contra a base
    # do Biblio ja e a prova. Ficam so os que o proprio nome diz precisarem
    # de conferencia humana - correspondencia aproximada, vinculo duvidoso.
    estados_que_pedem_prova = {
        "cadastrado",
        "já existente na API - conferir vínculo",
        "duplicado informado pela API - revisar",
    }
    fichas_planejadas = {p.get("metadados") for p in planos}
    sem_prova = []
    for item in fila.get("itens", []):
        if item.get("estado") not in estados_que_pedem_prova:
            continue
        if item.get("id_remoto") or item.get("metadados") in fichas_planejadas:
            continue
        if item.get("ficha") in fichas_planejadas:
            continue
        sem_prova.append({
            "titulo": (item.get("titulo") or item.get("arquivo") or "")[:70],
            "estado": item.get("estado"),
            "fila": item.get("fila_origem", ""),
            "arquivo": item.get("caminho") or item.get("arquivo", ""),
            "motivo": ("marcado como liberavel, mas sem id remoto nem "
                       "referencia ao original - nao liberado por seguranca"),
        })

    total_arquivos = sum(len(p["arquivos"]) for p in planos)
    total_bytes = sum(a["bytes"] for p in planos for a in p["arquivos"])
    pastas_residuais = _pastas_residuais_entrada(c)
    orfaos = _arquivos_orfaos(c, catalogo)
    bytes_orfaos = sum(o["bytes"] for o in orfaos)

    resumo = {"modo": "EXECUÇÃO" if executar else "SIMULAÇÃO",
              "livros": len(planos), "arquivos": total_arquivos,
              "bytes": total_bytes, "mb": round(total_bytes / 1024 / 1024, 1),
              "itens": [],
              "bloqueados_sem_prova": sem_prova,
              "orfaos": orfaos,
              "orfaos_mb": round(bytes_orfaos / 1024 / 1024, 1),
              "pastas_vazias": [relativo(c, p) for p in pastas_residuais]}
    for plano in planos:
        resumo["itens"].append({
            "id_remoto": plano["id_remoto"], "titulo": plano["titulo"],
            "motivo": plano["motivo_liberacao"],
            "arquivos": [relativo(c, a["caminho"]) for a in plano["arquivos"]],
            "mb": round(sum(a["bytes"] for a in plano["arquivos"]) / 1024 / 1024, 1),
        })
    if not executar:
        print(json.dumps(resumo, ensure_ascii=False, indent=2))
        return resumo

    lixeira = pathlib.Path(lixeira).expanduser().resolve() if lixeira else (
        pathlib.Path.home() / ".Trash")
    lixeira.mkdir(parents=True, exist_ok=True)
    manifesto_path = c["controle"] / "manifesto-liberacao-espaco.json"
    try:
        manifesto = json.loads(manifesto_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        manifesto = {"versao": 1, "operacoes": []}
    operacao = {"executado_em": agora(), "destino": "Lixeira do macOS",
                "livros": [], "orfaos_removidos": [],
                "pastas_vazias_removidas": []}
    for plano in planos:
        movidos = []
        pastas_importadas = set()
        for arquivo in plano["arquivos"]:
            origem = arquivo["caminho"]
            if arquivo.get("arquivo_importado"):
                pastas_importadas.add(origem.parent)
            destino = _destino_lixeira(
                lixeira, origem, plano["identificador_lixeira"])
            shutil.move(str(origem), str(destino))
            movidos.append({"origem": relativo(c, origem),
                            "lixeira": destino.name, "bytes": arquivo["bytes"]})
        # Se era uma pasta exclusiva deste livro, retire tambem o invólucro
        # vazio. Pastas com outros livros permanecem intactas.
        for pasta in sorted(pastas_importadas, key=lambda p: len(p.parts), reverse=True):
            # 00-ENTRADA e uma pasta permanente da interface do aplicativo.
            # Arquivos soltos nela podem ser liberados, mas a propria pasta
            # nunca deve desaparecer quando o ultimo item for removido.
            if pasta.resolve() == c["entrada"].resolve():
                continue
            ds_store = pasta / ".DS_Store"
            if ds_store.is_file() and len(list(pasta.iterdir())) == 1:
                destino = _destino_lixeira(
                    lixeira, ds_store, plano["identificador_lixeira"])
                tamanho = ds_store.stat().st_size
                shutil.move(str(ds_store), str(destino))
                movidos.append({"origem": relativo(c, ds_store),
                                "lixeira": destino.name, "bytes": tamanho})
            try:
                pasta.rmdir()
            except OSError:
                pass
        registro = catalogo["livros"].get(plano["chave_catalogo"])
        if registro is None:
            registro = next((r for r in catalogo["livros"].values()
                             if r.get("metadados") == plano["metadados"]), None)
        if registro is not None:
            if plano["motivo_liberacao"] == "cadastro confirmado pela API":
                estado_final = "cadastrado - arquivos locais liberados"
            elif plano["motivo_liberacao"] == "duplicidade confirmada pela API":
                estado_final = "duplicado na API - arquivos locais liberados"
            elif plano["motivo_liberacao"] == "item classificado para descarte":
                estado_final = "descartado - arquivos locais liberados"
            else:
                estado_final = "duplicado local - arquivos liberados"
            registro.update({
                "estado": estado_final,
                "caminho_anterior": registro.get("caminho", ""),
                "caminho": "", "tamanho_bytes": 0,
                "arquivos_liberados_em": agora(),
                "bytes_liberados": sum(x["bytes"] for x in movidos),
            })
        ficha_path = c["raiz"] / plano["metadados"] if plano["metadados"] else None
        if ficha_path and ficha_path.is_file():
            ficha = json.loads(ficha_path.read_text(encoding="utf-8"))
            ficha["arquivos_locais_liberados_em"] = agora()
            ficha["arquivos_locais_removidos"] = [x["origem"] for x in movidos]
            ficha["motivo_liberacao_espaco"] = plano["motivo_liberacao"]
            salvar_json(ficha_path, ficha)
        if plano["motivo_liberacao"] == "duplicidade confirmada pela API":
            item_fila = next((x for x in fila.get("itens", [])
                              if _chave_ficha(x) == plano["metadados"]), None)
            if item_fila:
                item_fila["estado"] = "duplicado na API - arquivos locais liberados"
                item_fila["arquivos_liberados_em"] = agora()
        operacao["livros"].append({
            "hash_sha256": plano["hash_sha256"], "id_remoto": plano["id_remoto"],
            "titulo": plano["titulo"], "metadados": plano["metadados"],
            "motivo": plano["motivo_liberacao"],
            "arquivos": movidos,
        })
    # O relatório de órfãos sempre existiu, mas a execução esquecia de
    # removê-los. Cada caminho foi produzido por `_arquivos_orfaos` somente
    # dentro das pastas de apoio conhecidas; ainda assim repetimos a validação
    # antes de mover para a Lixeira.
    raizes_apoio = [p.resolve() for p in (
        c["preparados"], c["capas"], c["raiz"] / "_capas300") if p.is_dir()]
    for item in orfaos:
        origem = (c["raiz"] / item["arquivo"]).resolve()
        if (not origem.is_file() or origem.is_symlink()
                or not any(origem == raiz or raiz in origem.parents
                           for raiz in raizes_apoio)):
            continue
        destino = _destino_lixeira(lixeira, origem, "orfao")
        shutil.move(str(origem), str(destino))
        operacao["orfaos_removidos"].append({
            "origem": item["arquivo"], "lixeira": destino.name,
            "bytes": item["bytes"], "motivo": item["motivo"],
        })
    # Retira apenas invólucros vazios criados dentro das pastas de apoio;
    # as três pastas principais fazem parte permanente da interface.
    for raiz_apoio in raizes_apoio:
        for pasta in sorted((p for p in raiz_apoio.rglob("*") if p.is_dir()),
                            key=lambda p: len(p.parts), reverse=True):
            try:
                for ds_store in pasta.glob(".DS_Store"):
                    if ds_store.is_file() and not ds_store.is_symlink():
                        destino = _destino_lixeira(lixeira, ds_store, "apoio-vazio")
                        shutil.move(str(ds_store), str(destino))
                pasta.rmdir()
            except OSError:
                continue
    # Recalcula depois dos livros: a retirada de um livro pode ter esvaziado
    # também a pasta do autor. Remove de baixo para cima e preserva a entrada.
    for pasta in _pastas_residuais_entrada(c):
        try:
            for ds_store in pasta.glob(".DS_Store"):
                if ds_store.is_file() and not ds_store.is_symlink():
                    destino = _destino_lixeira(lixeira, ds_store, "pasta-vazia")
                    shutil.move(str(ds_store), str(destino))
            pasta.rmdir()
            operacao["pastas_vazias_removidas"].append(relativo(c, pasta))
        except OSError:
            continue
    manifesto["operacoes"].append(operacao)
    manifesto["atualizado_em"] = agora()
    salvar_json(manifesto_path, manifesto)
    # Agora que lemos de varias filas, a gravacao devolve cada item para o
    # arquivo de onde veio - por isso cada um carrega "fila_origem".
    por_arquivo = {}
    for item in fila.get("itens", []):
        copia = dict(item)
        origem = copia.pop("fila_origem", "fila-envio-api.json")
        por_arquivo.setdefault(origem, []).append(copia)
    for nome_fila, itens in por_arquivo.items():
        caminho_fila = c["controle"] / nome_fila
        try:
            dados = json.loads(caminho_fila.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            dados = {}
        dados["itens"] = itens
        dados["atualizado_em"] = agora()
        salvar_json(caminho_fila, dados)

    salvar_catalogo(c, catalogo)
    consolidar(c, catalogo)
    print(json.dumps(resumo, ensure_ascii=False, indent=2))
    print("Arquivos enviados para a Lixeira. Esvazie-a quando desejar liberar o disco.")
    return resumo


def main():
    ap = argparse.ArgumentParser(description="Preparacao local incremental de livros")
    ap.add_argument("--raiz", required=True, help="pasta principal da biblioteca local")
    grupo = ap.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--inicializar", action="store_true")
    grupo.add_argument("--registrar-existentes", action="store_true")
    grupo.add_argument("--processar", action="store_true")
    grupo.add_argument("--corrigir-ocr", action="store_true")
    grupo.add_argument("--reprocessar-revisao", action="store_true")
    grupo.add_argument("--status", action="store_true")
    grupo.add_argument("--liberar-espaco", action="store_true")
    grupo.add_argument("--atualizar-filas-especificas", action="store_true")
    grupo.add_argument("--pacote-revisao", action="store_true")
    grupo.add_argument("--gravar-revisao", action="store_true")
    ap.add_argument("--sem-api", action="store_true")
    ap.add_argument("--arquivo", action="append", default=[],
                    help="reprocessa somente este PDF; pode ser repetido")
    ap.add_argument("--limite", type=int, default=20,
                    help="quantos itens retornar no pacote de revisão")
    ap.add_argument("--campos-json", default="{}",
                    help="campos corrigidos para --gravar-revisao")
    ap.add_argument("--justificativa", default="revisão visual")
    ap.add_argument("--fonte-revisao", action="append", default=[])
    ap.add_argument("--conflito-revisao", action="append")
    ap.add_argument("--pendencia-revisao", action="append")
    ap.add_argument("--ruido-titulo", action="append", default=[])
    ap.add_argument("--ruido-autor", action="append", default=[])
    ap.add_argument("--nao-aprovar", action="store_true")
    ap.add_argument("--executar", action="store_true",
                    help="envia os arquivos selecionados para a Lixeira")
    args = ap.parse_args()
    if args.inicializar:
        c = inicializar(args.raiz)
        print(f"Estrutura local pronta em {c['raiz']}")
    elif args.registrar_existentes:
        with trava_execucao(args.raiz, "registrar existentes"):
            registrar_existentes(args.raiz)
    elif args.processar:
        with trava_execucao(args.raiz, "preparar livros"):
            processar_entrada(args.raiz, usar_api=not args.sem_api)
    elif args.corrigir_ocr:
        with trava_execucao(args.raiz, "corrigir OCR"):
            corrigir_ocr_pendentes(args.raiz, usar_api=not args.sem_api)
    elif args.reprocessar_revisao:
        with trava_execucao(args.raiz, "reprocessar revisão"):
            reprocessar_revisao(args.raiz, usar_api=not args.sem_api,
                                arquivos=args.arquivo)
    elif args.liberar_espaco:
        with trava_execucao(args.raiz, "liberar espaço"):
            liberar_espaco(args.raiz, executar=args.executar)
    elif args.atualizar_filas_especificas:
        atualizar_filas_especificas(args.raiz)
    elif args.pacote_revisao:
        alvo = args.arquivo[0] if args.arquivo else None
        pacotes_revisao(args.raiz, arquivo=alvo, limite=args.limite)
    elif args.gravar_revisao:
        if not args.arquivo:
            raise RuntimeError("--gravar-revisao exige --arquivo")
        try:
            campos = json.loads(args.campos_json)
        except json.JSONDecodeError as exc:
            raise RuntimeError("--campos-json inválido") from exc
        if not isinstance(campos, dict):
            raise RuntimeError("--campos-json precisa ser um objeto JSON")
        gravar_decisao_revisao(
            args.raiz, args.arquivo[0], campos=campos,
            aprovado=not args.nao_aprovar,
            justificativa=args.justificativa,
            fontes=args.fonte_revisao or ["revisão visual"],
            conflitos=args.conflito_revisao,
            pendencias=args.pendencia_revisao,
            ruidos_titulo=args.ruido_titulo,
            ruidos_autor=args.ruido_autor)
    else:
        mostrar_status(args.raiz)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(f"\nOperação não iniciada: {exc}")
        sys.exit(2)
    except KeyboardInterrupt:
        print("\nInterrompido. O catálogo salvo permite retomar.")
        sys.exit(130)
