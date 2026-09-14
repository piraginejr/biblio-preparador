#!/usr/bin/env python3
"""Envia um livro pronto para a API Biblio, um por vez.

O padrao e simulacao. O envio real exige --enviar e uma chave fornecida por
variavel de ambiente ou digitada sem eco. Cada tentativa e registrada pelo
SHA-256 do PDF antes da requisicao, impedindo repeticao automatica quando a
resposta for incerta.
"""

import argparse
import csv
import getpass
import hashlib
import html
import json
import os
import pathlib
import pty
import re
import select
import signal
import ssl
import subprocess
import sys
import time
import unicodedata
from datetime import datetime

try:
    import requests
    from requests.adapters import HTTPAdapter
except ImportError:
    requests = None
    HTTPAdapter = object


ENDPOINT = "https://apibib.pibcuritiba.org.br/apibiblio.php"
CHAVES_SERVICO = "Biblioteca PIB Curitiba - API Biblio"
CHAVES_CONTA = "envio-de-livros"
NOME_CONTROLE = "envios-api.json"
NOME_FILA = "fila-envio-api.json"
FILAS_ESPECIFICAS = {
    "documentos": "fila-cadastro-documentos.json",
    "academico": "fila-cadastro-academico.json",
    "revistas": "fila-cadastro-revistas.json",
}
# Acima de 50 MB o preparador tenta reduzir o PDF, mas esse valor deixou de
# ser um bloqueio. O PHP em producao aceita ate 500M; mantemos esse teto real
# e conservador para evitar iniciar um upload que o servidor recusaria.
LIMITE_OTIMIZACAO_BYTES = 50_000_000
LIMITE_ENVIO_BYTES = 500_000_000
OPERADOR_EMAIL = "renan@pibcuritiba.org.br"
REMETENTE_EMAIL = "piraginejr@gmail.com"
IDIOMAS = {"por": "portugues", "spa": "espanhol",
           "fre": "frances", "eng": "ingles"}
# Valores confirmados pelo operador do sistema em 18/08/2026. A API atual
# O mesmo endpoint recebe os demais materiais; cada fila escolhe o código
# adequado sem reprocessar OCR ou transformar documento em livro.
TIPOS_API = {
    "livro": "1",
    "revista": "2",
    "artigo de revista": "3",
    "artigo de jornal": "4",
    "documento": "5",
    "áudio": "6",
    "vídeo": "7",
}
CATEGORIAS_API = {"público": "0", "restrito": "1"}
ESTADO_DUPLICADO_TITULO_AUTOR = "duplicado confirmado por título e autor"
ESTADO_DUPLICADO_TITULO = "duplicado confirmado por título"
CERTIFICADO_INTERMEDIARIO = (pathlib.Path(__file__).with_name("certificados") /
                             "SectigoPublicServerAuthenticationCADVR36.pem")
# Durante um POST multipart, urllib3 tambem usa o primeiro prazo nas escritas.
# Trinta segundos interrompia PDFs validos no meio do upload. O servidor aceita
# arquivos grandes; por isso a transferencia e a resposta recebem ate 30 min.
TIMEOUT_ENVIO = (1800, 1800)


class AdaptadorTLSBiblio(HTTPAdapter):
    """Completa com seguranca a cadeia que o servidor da API omite."""

    def init_poolmanager(self, connections, maxsize, block=False,
                         **pool_kwargs):
        contexto = ssl.create_default_context(cafile=requests.certs.where())
        contexto.load_verify_locations(cafile=str(CERTIFICADO_INTERMEDIARIO))
        pool_kwargs["ssl_context"] = contexto
        return super().init_poolmanager(connections, maxsize, block=block,
                                        **pool_kwargs)


def criar_sessao_api():
    if not requests:
        raise RuntimeError("biblioteca requests nao instalada")
    if not CERTIFICADO_INTERMEDIARIO.is_file():
        raise RuntimeError("certificado intermediario da API ausente")
    sessao = requests.Session()
    sessao.mount("https://apibib.pibcuritiba.org.br/", AdaptadorTLSBiblio())
    return sessao


def agora():
    return datetime.now().isoformat(timespec="seconds")


def sha256(arquivo):
    h = hashlib.sha256()
    with open(arquivo, "rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


def salvar_json(destino, dados):
    destino = pathlib.Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_name(destino.name + ".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, destino)


def caminho_local(valor, ficha):
    p = pathlib.Path(str(valor or "")).expanduser()
    candidatos = [p]
    if not p.is_absolute():
        raiz = ficha.parent.parent
        candidatos += [pathlib.Path.cwd() / p, raiz / p, ficha.parent / p]
        # Fichas antigas guardam caminhos como "livros/arquivo.pdf". Quando o
        # app e aberto por dois cliques, o diretorio atual e 99-FERRAMENTAS.
        if p.parts and p.parts[0] == raiz.name:
            candidatos += [raiz.parent / p,
                           raiz / pathlib.Path(*p.parts[1:])]
    for candidato in candidatos:
        if candidato.exists():
            return candidato.resolve()
    return (ficha.parent.parent / p).resolve()


def ler_chave_chaves():
    """Le a credencial no Chaves do macOS, sem expo-la no codigo."""
    try:
        r = subprocess.run(
            ["security", "find-generic-password", "-s", CHAVES_SERVICO,
             "-a", CHAVES_CONTA, "-w"], capture_output=True, text=True,
            check=False)
    except OSError:
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def guardar_chave_chaves(chave=""):
    """Guarda a chave no Chaves sem inclui-la nos argumentos do processo."""
    chave = chave or getpass.getpass("Chave da API (ficara no Chaves do macOS): ")
    if not chave:
        raise ValueError("chave da API ausente")
    argumentos = ["security", "add-generic-password", "-U", "-s",
                  CHAVES_SERVICO, "-a", CHAVES_CONTA, "-l",
                  CHAVES_SERVICO, "-w"]
    pid, terminal = pty.fork()
    if pid == 0:  # pragma: no cover - processo substituido pelo security
        os.execvp(argumentos[0], argumentos)

    buffer = b""
    respondidos = set()
    prazo = time.monotonic() + 30
    status = None
    try:
        while time.monotonic() < prazo:
            pronto, _, _ = select.select([terminal], [], [], 0.2)
            if pronto:
                try:
                    bloco = os.read(terminal, 1024)
                except OSError:
                    bloco = b""
                buffer = (buffer + bloco)[-2048:]
                texto = buffer.lower()
                for marcador in (b"password data", b"retype password"):
                    if marcador in texto and marcador not in respondidos:
                        os.write(terminal, chave.encode("utf-8") + b"\n")
                        respondidos.add(marcador)
            terminou, status = os.waitpid(pid, os.WNOHANG)
            if terminou:
                break
        else:
            os.kill(pid, signal.SIGTERM)
            _, status = os.waitpid(pid, 0)
    finally:
        os.close(terminal)
    if status is None or os.waitstatus_to_exitcode(status) != 0:
        raise RuntimeError("nao foi possivel guardar a chave no Chaves do macOS")
    return True


def nome_natural(nome):
    """Converte o nosso 'Sobrenome, Nomes' para o formato esperado pela API."""
    nome = " ".join(str(nome or "").split())
    if "," not in nome:
        return nome
    sobrenome, restante = (x.strip(" ,") for x in nome.split(",", 1))
    return " ".join(x for x in (restante, sobrenome) if x)


def texto_seguro_api(valor):
    """Remove apostrofos que podem derrubar o banco da API legada.

    A ficha bibliografica local permanece intacta; a limpeza ocorre somente
    na copia transmitida ao servidor.
    """
    return " ".join(str(valor).replace("'", "").replace("’", "").split())


def normalizar_isbn_consulta(valor):
    """Normaliza como a API documentada: somente algarismos e X."""
    return "".join(c for c in str(valor or "").upper()
                   if c.isdigit() or c == "X")


def consulta_confirmada_por_isbn(consulta):
    """Confirma que a resposta corresponde ao ISBN efetivamente consultado."""
    criterios = consulta.get("criterios_enviados", {}) or {}
    enviado = normalizar_isbn_consulta(criterios.get("isbn", ""))
    recebido = normalizar_isbn_consulta(consulta.get("isbn", ""))
    return bool(consulta.get("encontrado") and enviado and recebido
                and enviado == recebido)


def _chave_textual(valor):
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join("".join(c if c.isalnum() else " " for c in
                            texto.casefold()).split())


def _chave_autor(valor):
    if isinstance(valor, dict):
        valor = valor.get("nome", "")
    ignorar = {"da", "das", "de", "do", "dos", "e", "et", "al"}
    tokens = [t for t in _chave_textual(valor).split() if t not in ignorar]
    return tuple(sorted(tokens)) if len(tokens) >= 2 else ()


def consulta_confirmada_por_titulo_autor(consulta):
    """Confirma obra sem ISBN por título exato, único e autor coincidente."""
    criterios = consulta.get("criterios_enviados", {}) or {}
    titulo_enviado = _chave_textual(criterios.get("titulo", ""))
    titulo_recebido = _chave_textual(consulta.get("titulo", ""))
    autores_enviados = {_chave_autor(a) for a in
                        (criterios.get("autores", []) or [])}
    autores_recebidos = {_chave_autor(a) for a in
                         (consulta.get("autores", []) or [])}
    autores_enviados.discard(())
    autores_recebidos.discard(())
    return bool(
        consulta.get("encontrado") and
        str(consulta.get("correspondencia", "")).casefold() == "exata" and
        int(consulta.get("total_matches", 0) or 0) == 1 and
        titulo_enviado and titulo_enviado == titulo_recebido and
        autores_enviados.intersection(autores_recebidos) and
        not consulta_com_isbn_divergente(consulta)
    )


def consulta_corresponde_ao_titulo_exato(consulta):
    """Reconhece título exato e único, mesmo quando o documento não tem autor."""
    criterios = consulta.get("criterios_enviados", {}) or {}
    return bool(
        consulta.get("encontrado") and
        str(consulta.get("correspondencia", "")).casefold() == "exata" and
        int(consulta.get("total_matches", 0) or 0) == 1 and
        _chave_textual(criterios.get("titulo", "")) and
        _chave_textual(criterios.get("titulo", "")) ==
        _chave_textual(consulta.get("titulo", ""))
    )


def consulta_com_isbn_divergente(consulta):
    """Detecta outra edicao: a consulta e a resposta possuem ISBNs diferentes."""
    criterios = consulta.get("criterios_enviados", {}) or {}
    enviado = normalizar_isbn_consulta(criterios.get("isbn", ""))
    recebido = normalizar_isbn_consulta(consulta.get("isbn", ""))
    return bool(consulta.get("encontrado") and enviado and recebido
                and enviado != recebido)


def consulta_bloqueia_envio(consulta):
    """So bloqueia quando a resposta pode representar a mesma edicao.

    Um ISBN completo identifica uma edicao. Se a API devolve outro ISBN, a
    coincidencia de titulo/autor e apenas bibliografica e nao pode impedir o
    cadastro do exemplar consultado.
    """
    return bool(consulta.get("encontrado")
                and not consulta_com_isbn_divergente(consulta))


def consultar_livro(sessao, chave, isbn="", titulo="", autores=None,
                    exato=False):
    """Consulta duplicidade sem anexar capa ou PDF."""
    if not chave:
        raise ValueError("chave da API ausente")
    payload = {"action": "consultar_livro", "exato": bool(exato)}
    isbn = normalizar_isbn_consulta(isbn)
    titulo = " ".join(str(titulo or "").split())
    autores = [" ".join(str(a).split()) for a in (autores or []) if str(a).strip()]
    if isbn:
        payload["isbn"] = isbn
    if titulo:
        payload["titulo"] = titulo
    if autores:
        payload["autores"] = autores
    if len(payload) == 2:
        return {"encontrado": False, "consulta_nao_realizada": True,
                "motivo": "sem ISBN nem titulo/autor suficientes"}
    resposta = sessao.post(
        ENDPOINT, json=payload, headers={"X-API-Key": chave},
        timeout=(30, 90))
    try:
        corpo = resposta.json()
    except ValueError as exc:
        raise RuntimeError("a consulta previa retornou resposta invalida") from exc
    if resposta.status_code != 200:
        mensagem = corpo.get("mensagem", corpo)
        raise RuntimeError(
            f"consulta previa falhou (HTTP {resposta.status_code}): {mensagem}")
    corpo["consultado_em"] = agora()
    corpo["criterios_enviados"] = {
        k: v for k, v in payload.items() if k != "action"}
    corpo["confirmado_por"] = (
        "isbn" if consulta_confirmada_por_isbn(corpo) else
        "isbn_divergente" if consulta_com_isbn_divergente(corpo) else
        "titulo_autor" if consulta_confirmada_por_titulo_autor(corpo) else
        "titulo_autor_aproximado" if corpo.get("encontrado") else "")
    return corpo


def autores_para_consulta(ficha):
    """Extrai autores da ficha, inclusive no formato legado nmAutor0."""
    autores = []
    for autor in ficha.get("autores", []) or []:
        nome = autor.get("nome", "") if isinstance(autor, dict) else str(autor)
        if nome:
            autores.append(nome)
    if not autores and ficha.get("nmAutor0"):
        autores = [ficha["nmAutor0"]]
    return autores


def reconciliar_resultado_incerto(ficha_path, digest, controle, registro,
                                  chave, sessao=None, tipo_api="livro"):
    """Confirma na API um POST cuja resposta local se perdeu.

    Confirma o cadastro quando encontra a mesma edicao. Quando a consulta
    confirma que ela nao existe, arquiva a tentativa anterior e autoriza uma
    unica repeticao pelo chamador.
    """
    if registro.get("estado") != (
            "resultado incerto - nao reenviar sem conferencia"):
        return None
    ficha_path = pathlib.Path(ficha_path).expanduser().resolve()
    ficha = json.loads(ficha_path.read_text(encoding="utf-8"))
    consulta = consultar_livro(
        sessao or criar_sessao_api(), chave,
        isbn=ficha.get("isbn", ""), titulo=ficha.get("titulo", ""),
        autores=autores_para_consulta(ficha), exato=True)
    # Algumas fichas documentais guardam o autor em ordem bibliografica,
    # enquanto a API o normaliza em ordem natural. Antes de concluir que um
    # item sem ISBN nao existe, repetimos somente a consulta (sem arquivo) pelo
    # titulo. Uma correspondencia exata e unica continua sendo obrigatoria.
    if (not consulta.get("encontrado") and not ficha.get("isbn") and
            ficha.get("titulo")):
        consulta = consultar_livro(
            sessao or criar_sessao_api(), chave,
            titulo=ficha.get("titulo", ""), autores=[], exato=False)
    confirmado = (
        consulta_confirmada_por_isbn(consulta) or
        (consulta.get("encontrado") and
         str(consulta.get("correspondencia", "")).lower() == "exata" and
         int(consulta.get("total_matches", 0) or 0) == 1)
    )
    if not confirmado:
        ausente = (not consulta.get("encontrado") or
                   consulta_com_isbn_divergente(consulta))
        if not ausente:
            return None
        anterior = dict(registro)
        anterior.update({
            "arquivado_em": agora(),
            "motivo_reabertura":
                "consulta posterior nao encontrou esta edicao na API",
            "consulta_posterior": consulta,
        })
        controle.setdefault("tentativas_anteriores", {}).setdefault(
            digest, []).append(anterior)
        controle["envios"].pop(digest, None)
        salvar_json(controle_da_ficha(ficha_path), controle)
        return {"reenvio_autorizado": True, "consulta": consulta}
    registro.update({
        "estado": "cadastrado",
        "id_remoto": consulta.get("id", ""),
        "http_status": 200,
        "resposta": consulta,
        "concluido_em": agora(),
        "reconciliado_por": "consulta posterior sem reenvio",
        "tipo_api": tipo_api,
    })
    registro.pop("erro_local", None)
    salvar_json(controle_da_ficha(ficha_path), controle)
    marcar_catalogo_cadastrado(ficha_path.parent.parent, digest, registro)
    return registro


def montar_payload(ficha, tipo_api="livro"):
    if tipo_api not in TIPOS_API:
        raise ValueError(f"tipo de API desconhecido: {tipo_api}")
    idioma = IDIOMAS.get(ficha.get("idioma", ""), "")
    autores = []
    for item in ficha.get("autores", []) or []:
        if isinstance(item, dict) and item.get("nome"):
            autores.append({
                "nome": nome_natural(item["nome"]),
                "desc": item.get("desc", "Autor") or "Autor",
            })
    if not autores:
        autor = nome_natural(ficha.get("nmAutor0", ""))
        autores = [{"nome": autor, "desc": "Autor"}] if autor else []
    mapa = {
        "action": "cadastrar_livro",
        "titulo": ficha.get("titulo", ""),
        "stitle": ficha.get("subTitulo", ""),
        "isbn": ficha.get("isbn", ""),
        "editor": ficha.get("editora", ""),
        "paginas": ficha.get("nPaginas", ""),
        "lingua": idioma,
        # A primeira edição presumida é uma regra de livros. Documentos,
        # artigos e revistas não devem ganhar uma edição bibliográfica que
        # o arquivo nunca declarou.
        "edicao": (ficha.get("edicao") or "1ª edição (presumida)"
                    if tipo_api == "livro" else ficha.get("edicao", "")),
        "lugar": ficha.get("lugar", ""),
        "abstract": ficha.get("abstract", ""),
        "pchave": ficha.get("palavrasChave", ""),
        "CDD": ficha.get("cdd", ""),
        "assunto": ficha.get("tipoAssunto1", ""),
        "series": ficha.get("series", ""),
        "nserie": ficha.get("numSerie", ""),
        "volume": ficha.get("volume", ""),
        "tradutor": ficha.get("tradutor", ""),
        "data": ficha.get("data", ""),
        "categoria": CATEGORIAS_API["público"],
        "tipo": TIPOS_API[tipo_api],
        "status": "1",
        "autores": json.dumps(autores, ensure_ascii=False),
    }
    return {k: texto_seguro_api(v) for k, v in mapa.items()
            if v not in (None, "")}


def assinatura_ficha(ficha, tipo_api="livro"):
    """Identifica os metadados efetivamente enviados, sem incluir arquivos."""
    serializado = json.dumps(montar_payload(ficha, tipo_api), ensure_ascii=False,
                             sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serializado.encode("utf-8")).hexdigest()


def ficha_corrigida_depois(ficha, registro):
    """Confirma que os dados mudaram depois de uma tentativa HTTP 5xx."""
    atual = assinatura_ficha(ficha)
    anterior = registro.get("assinatura_ficha", "")
    if anterior:
        return anterior != atual

    # Compatibilidade com tentativas antigas, que ainda nao guardavam a
    # assinatura. Nesse caso uma ficha regerada depois do erro conta como
    # revisao explicita do operador.
    try:
        gerado = datetime.fromisoformat(str(ficha.get("gerado_em", "")))
        concluido = datetime.fromisoformat(str(registro.get("concluido_em", "")))
    except (TypeError, ValueError):
        return False
    return gerado > concluido


def validar(ficha, pdf, capa, tipo_api="livro"):
    erros = []
    tipo_local = ficha.get("tipo_documento", "livro")
    documento_so_titulo = (
        tipo_api == "documento" and
        tipo_local in {"documento", "apostila", "sermão", "trecho",
                       "apresentação", "opúsculo"})
    if tipo_api == "livro":
        if tipo_local != "livro":
            erros.append("esta fila e API sao exclusivas para livros")
        if ficha.get("situacao") != "pronto para cadastro":
            erros.append("a ficha nao esta marcada como pronta para cadastro")
    elif tipo_api == "documento":
        if tipo_local not in {
                "documento", "apostila", "sermão", "trecho",
                "tese", "dissertação", "trabalho acadêmico",
                "apresentação", "opúsculo"}:
            erros.append("a ficha nao esta classificada como documento")
        if ficha.get("situacao") not in {
                "aguardando cadastro específico", "pronto para cadastro"}:
            erros.append("o documento nao esta pronto para cadastro específico")
    elif tipo_api in {"artigo de revista", "artigo de jornal"}:
        if tipo_local != "artigo":
            erros.append("a ficha nao esta classificada como artigo")
        if ficha.get("situacao") not in {
                "aguardando cadastro específico", "pronto para cadastro"}:
            erros.append("o artigo nao esta pronto para cadastro específico")
    elif tipo_api == "revista":
        if tipo_local not in {"revista", "periódico", "boletim", "jornal"}:
            erros.append("a ficha nao esta classificada como revista ou periódico")
        if ficha.get("situacao") not in {
                "aguardando cadastro específico", "pronto para cadastro"}:
            erros.append("a revista nao esta pronta para cadastro específico")
    if ficha.get("status_ocr") != "OCR aprovado":
        erros.append("o OCR nao esta aprovado")
    if ficha.get("conflitos") and not documento_so_titulo:
        erros.append("a ficha ainda contem conflitos")
    pendencias = str(ficha.get("pendencias", "") or "")
    if tipo_api in {"documento", "revista", "artigo de revista",
                    "artigo de jornal"}:
        pendencias = " | ".join(
            p.strip() for p in pendencias.split("|")
            if p.strip() and p.strip() not in {
                "aguardar endpoint de artigos/documentos",
                "confirmar tela e ação da API para artigos/documentos",
                "aguardar endpoint de trabalhos acadêmicos/documentos",
                "aguardar endpoint de documentos",
                "aguardar endpoint de revistas/periódicos",
                "editora", "data de publicacao"})
    if pendencias and not documento_so_titulo:
        erros.append("a ficha ainda contem pendencias")
    titulo = " ".join(str(ficha.get("titulo", "") or "").split())
    if not titulo:
        erros.append("titulo ausente")
    elif re.search(
            r"(?i)\b(?:todos\s+os\s+direitos\s+reservados|"
            r"proibida\s+a\s+reprodu[çc][aã]o|reprodu[çc][aã]o\s+total\s+ou\s+parcial|"
            r"autoriza[çc][aã]o\s+pr[eé]via|lei\s+n?[.°º\s]*9?\.?610)\b",
            titulo):
        erros.append("titulo parece aviso de direitos autorais; envio bloqueado")
    elif len(titulo) > 240 or len(titulo.split()) > 32:
        erros.append("titulo excessivamente longo; envio bloqueado para revisao")
    elif documento_so_titulo:
        palavras = titulo.split()
        titulo_ruim = (
            len(titulo) > 240 or len(palavras) > 32 or
            titulo.casefold().startswith(("resumo:", "abstract:"))
        )
        if titulo_ruim:
            erros.append("titulo documental parece resumo ou trecho de OCR")
    if not pdf.is_file():
        erros.append(f"PDF nao encontrado: {pdf}")
    elif pdf.is_file():
        with pdf.open("rb") as arquivo_pdf:
            assinatura_pdf = arquivo_pdf.read(5)
        if assinatura_pdf != b"%PDF-":
            erros.append("o arquivo digital nao tem assinatura PDF")
        if pdf.stat().st_size > LIMITE_ENVIO_BYTES:
            erros.append("o PDF excede o limite real de envio de 500 MB")
        hash_esperado = ficha.get("hash_pdf_preparado", "")
        if hash_esperado and sha256(pdf) != hash_esperado:
            erros.append("a copia de envio mudou desde a preparacao")
    if not capa.is_file():
        erros.append(f"capa nao encontrada: {capa}")
    elif capa.suffix.lower() not in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
        erros.append("formato de capa nao aceito pela API")
    return erros


def carregar_controle(caminho):
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        dados = {"versao": 1, "envios": {}}
    dados.setdefault("envios", {})
    return dados


def controle_da_ficha(ficha_path):
    return pathlib.Path(ficha_path).resolve().parent.parent / "_controle" / NOME_CONTROLE


def fila_da_raiz(raiz):
    return pathlib.Path(raiz).expanduser().resolve() / "_controle" / NOME_FILA


def carregar_fila(caminho):
    try:
        dados = json.loads(pathlib.Path(caminho).read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        dados = {"versao": 1, "criada_em": agora(), "itens": []}
    dados.setdefault("itens", [])
    return dados


def ficha_apta(ficha):
    return (ficha.get("tipo_documento", "livro") == "livro" and
            ficha.get("situacao") == "pronto para cadastro" and
            ficha.get("status_ocr") == "OCR aprovado" and
            not ficha.get("conflitos") and not ficha.get("pendencias") and
            bool(ficha.get("titulo")))


def _registro_por_arquivo(controle):
    registros = {}
    for digest, registro_original in controle.get("envios", {}).items():
        registro = dict(registro_original)
        registro["_digest"] = digest
        arquivo = registro.get("arquivo")
        if arquivo:
            registros[str(pathlib.Path(arquivo).expanduser().resolve())] = registro
    return registros


def atualizar_fila(raiz):
    """Mantem historico remoto e deixa pendentes somente fichas ainda aptas."""
    raiz = pathlib.Path(raiz).expanduser().resolve()
    caminho = fila_da_raiz(raiz)
    fila = carregar_fila(caminho)
    controle = carregar_controle(raiz / "_controle" / NOME_CONTROLE)
    por_arquivo = _registro_por_arquivo(controle)
    controle_alterado = False
    adicionados = ignorados = 0

    fichas = []
    for p in (raiz / "_metadados").glob("*.json"):
        try:
            ficha = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            ignorados += 1
            continue
        if not ficha_apta(ficha):
            ignorados += 1
            continue
        fichas.append((ficha.get("gerado_em", ""), p.name, p, ficha))

    aptas = {str(p.relative_to(raiz)) for _, _, p, _ in fichas}
    mantidos = []
    retirados = fila.setdefault("retirados", [])
    for item in fila["itens"]:
        consulta_anterior = item.get("consulta_previa_api", {}) or {}
        if consulta_anterior.get("encontrado"):
            if (consulta_com_isbn_divergente(consulta_anterior)
                    and item.get("estado") in {
                        "duplicado informado pela API - revisar",
                        "duplicado confirmado por ISBN",
                        "já existente na API - conferir vínculo",
                        ESTADO_DUPLICADO_TITULO_AUTOR}):
                retirados.append({
                    "ficha": item.get("ficha", ""),
                    "titulo": item.get("titulo", ""),
                    "estado_anterior": item.get("estado", ""),
                    "consulta_descartada": consulta_anterior,
                    "motivo": "correspondência aproximada com ISBN divergente",
                    "retirado_em": agora(),
                })
                item["estado"] = "pendente"
                item["reativado_em"] = agora()
                item["motivo_reativacao"] = (
                    "ISBN retornado pela API pertence a outra edição")
                item["aviso_consulta_previa"] = (
                    "correspondência aproximada ignorada: ISBN da API diverge "
                    "do ISBN da ficha")
                for campo in ("consulta_previa_api", "id_remoto", "http_status",
                              "concluido_em", "erro"):
                    item.pop(campo, None)
                consulta_anterior = {}
            por_isbn = consulta_confirmada_por_isbn(consulta_anterior)
            por_titulo_autor = consulta_confirmada_por_titulo_autor(
                consulta_anterior)
            consulta_anterior["confirmado_por"] = (
                "isbn" if por_isbn else
                "titulo_autor" if por_titulo_autor else
                "titulo_autor_aproximado")
            if item.get("estado") in {
                    "duplicado informado pela API - revisar",
                    "duplicado confirmado por ISBN",
                    "já existente na API - conferir vínculo",
                    ESTADO_DUPLICADO_TITULO_AUTOR}:
                item["estado"] = (
                    "duplicado confirmado por ISBN" if por_isbn else
                    ESTADO_DUPLICADO_TITULO_AUTOR if por_titulo_autor else
                    "já existente na API - conferir vínculo")
        # Um item ainda nao enviado pode deixar de ser confiavel depois de uma
        # nova consulta ou regra. Ele sai da fila ativa, mas fica auditavel.
        if item.get("estado") == "pendente" and item.get("ficha") not in aptas:
            retirados.append({
                "ficha": item.get("ficha", ""),
                "titulo": item.get("titulo", ""),
                "estado_anterior": "pendente",
                "motivo": "ficha deixou de estar apta após reavaliação",
                "retirado_em": agora(),
            })
            continue
        mantidos.append(item)
    fila["itens"] = mantidos
    existentes = {item.get("ficha"): item for item in fila["itens"]}

    for _, _, p, ficha in sorted(fichas):
        relativo = str(p.relative_to(raiz))
        item = existentes.get(relativo)
        pdf = caminho_local(ficha.get("pdf_preparado") or
                            ficha.get("pdf_original") or ficha.get("arquivo"), p)
        remoto = por_arquivo.get(str(pdf))
        if item is None:
            item = {
                "ordem": len(fila["itens"]) + 1,
                "ficha": relativo,
                "titulo": ficha.get("titulo", ""),
                "isbn": ficha.get("isbn", ""),
                "estado": "pendente",
                "incluido_em": agora(),
            }
            fila["itens"].append(item)
            existentes[relativo] = item
            adicionados += 1
        elif (item.get("estado") in {
                "duplicado informado pela API - revisar",
                "duplicado confirmado por ISBN",
                "já existente na API - conferir vínculo",
                ESTADO_DUPLICADO_TITULO_AUTOR}
              and normalizar_isbn_consulta(item.get("isbn", ""))
              and normalizar_isbn_consulta(ficha.get("isbn", ""))
              and normalizar_isbn_consulta(item.get("isbn", "")) !=
                  normalizar_isbn_consulta(ficha.get("isbn", ""))):
            # A decisão remota foi tomada para outra edição. Isso ocorre em
            # coleções cuja página lista vários ISBNs: corrigir o tomo deve
            # invalidar a duplicidade antiga, sem apagar seu histórico.
            retirados.append({
                "ficha": relativo,
                "titulo": item.get("titulo", ""),
                "estado_anterior": item.get("estado", ""),
                "isbn_anterior": item.get("isbn", ""),
                "isbn_corrigido": ficha.get("isbn", ""),
                "motivo": "ISBN da edição corrigido; decisão remota anterior invalidada",
                "retirado_em": agora(),
            })
            item["estado"] = "pendente"
            item["reativado_em"] = agora()
            item["motivo_reativacao"] = "ISBN da edição corrigido"
            for campo in ("consulta_previa_api", "id_remoto", "http_status",
                          "concluido_em", "erro"):
                item.pop(campo, None)
            item["titulo"] = ficha.get("titulo", "")
            item["isbn"] = ficha.get("isbn", "")
        elif item.get("estado") == "pendente":
            # A ficha pode ter sido corrigida depois de entrar na fila.
            item["titulo"] = ficha.get("titulo", "")
            item["isbn"] = ficha.get("isbn", "")
        # A resposta remota de duplicidade continua no diário, mas depois
        # que o operador liberou os arquivos locais esse estado é definitivo.
        # Uma simples atualização da fila não deve reabrir o descarte.
        if item.get("estado") == "duplicado na API - arquivos locais liberados":
            continue
        if (remoto and remoto.get("estado") in {
                "duplicado informado pela API - revisar",
                "duplicado confirmado por ISBN",
                "já existente na API - conferir vínculo",
                ESTADO_DUPLICADO_TITULO_AUTOR}
                and normalizar_isbn_consulta(remoto.get("isbn", ""))
                and normalizar_isbn_consulta(ficha.get("isbn", ""))
                and normalizar_isbn_consulta(remoto.get("isbn", "")) !=
                    normalizar_isbn_consulta(ficha.get("isbn", ""))):
            digest = remoto["_digest"]
            anterior = {k: v for k, v in remoto.items() if k != "_digest"}
            anterior.update({
                "arquivado_em": agora(),
                "motivo_reabertura": "ISBN da edição corrigido",
            })
            controle.setdefault("tentativas_anteriores", {}).setdefault(
                digest, []).append(anterior)
            del controle["envios"][digest]
            controle_alterado = True
            remoto = None
            item["estado"] = "pendente"

        # Uma falha confirmada do servidor pode ser repetida com seguranca
        # somente depois que a ficha tiver sido efetivamente corrigida. A
        # tentativa anterior permanece no historico para auditoria.
        if (remoto and remoto.get("estado") == "erro confirmado - revisar" and
                int(remoto.get("http_status", 0) or 0) >= 500 and
                ficha_corrigida_depois(ficha, remoto)):
            digest = remoto["_digest"]
            anterior = {k: v for k, v in remoto.items() if k != "_digest"}
            anterior.update({
                "arquivado_em": agora(),
                "motivo_reabertura": "ficha corrigida depois de erro HTTP 5xx",
            })
            controle.setdefault("tentativas_anteriores", {}).setdefault(
                digest, []).append(anterior)
            del controle["envios"][digest]
            controle_alterado = True
            remoto = None
            item["estado"] = "pendente"
            item["reativado_em"] = agora()
            item["motivo_reativacao"] = (
                "ficha corrigida depois de erro HTTP 5xx")
            for campo in ("erro", "concluido_em", "iniciado_em",
                          "http_status", "id_remoto"):
                item.pop(campo, None)
        # Reconcilia uma interrupcao com o diario gravado antes da rede.
        if remoto:
            item["estado"] = remoto.get("estado", "revisar")
            item["id_remoto"] = remoto.get("id_remoto", "")
            item["http_status"] = remoto.get("http_status", "")
        elif item.get("estado") == "enviando":
            item["estado"] = "pendente"
        elif item.get("estado") == "erro local - revisar":
            # Sem entrada no diario remoto, a falha ocorreu antes do POST
            # (arquivo ausente, tamanho, capa etc.). Depois que a ficha volta
            # a ser apta, uma atualizacao explicita da fila pode reativa-la.
            item["estado"] = "pendente"
            item["reativado_em"] = agora()
            item["motivo_reativacao"] = "falha local corrigida"
            for campo in ("erro", "concluido_em", "http_status", "id_remoto"):
                item.pop(campo, None)

    fila["atualizada_em"] = agora()
    if controle_alterado:
        controle["atualizado_em"] = agora()
        salvar_json(raiz / "_controle" / NOME_CONTROLE, controle)
    salvar_json(caminho, fila)
    sincronizar_catalogo_com_fila(raiz, fila)
    return fila, adicionados, ignorados


def resumo_fila(fila):
    contagem = {}
    for item in fila.get("itens", []):
        estado = item.get("estado", "sem estado")
        contagem[estado] = contagem.get(estado, 0) + 1
    return contagem


def reativar_rejeitados_isbn(raiz):
    """Reabre somente rejeicoes da antiga obrigatoriedade de ISBN.

    A tentativa anterior e preservada no historico. Duplicados, falhas
    incertas e quaisquer outras rejeicoes permanecem bloqueados.
    """
    raiz = pathlib.Path(raiz).expanduser().resolve()
    controle_path = raiz / "_controle" / NOME_CONTROLE
    controle = carregar_controle(controle_path)
    fila_path = fila_da_raiz(raiz)
    fila = carregar_fila(fila_path)
    historico = controle.setdefault("tentativas_anteriores", {})
    reativados = []

    for digest, registro in list(controle["envios"].items()):
        mensagem = str(registro.get("resposta", {}).get("mensagem", ""))
        elegivel = (
            registro.get("estado") == "erro confirmado - revisar" and
            int(registro.get("http_status", 0) or 0) == 400 and
            "isbn" in mensagem.casefold() and
            "obrigat" in mensagem.casefold()
        )
        if not elegivel:
            continue
        anterior = dict(registro)
        anterior.update({
            "arquivado_em": agora(),
            "motivo_reabertura": "provedor removeu a obrigatoriedade de ISBN",
        })
        historico.setdefault(digest, []).append(anterior)
        del controle["envios"][digest]
        reativados.append((digest, pathlib.Path(registro.get("arquivo", "")).resolve()))

    for item in fila.get("itens", []):
        ficha_path = raiz / item.get("ficha", "")
        try:
            ficha = json.loads(ficha_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        pdf = caminho_local(ficha.get("pdf_preparado") or
                            ficha.get("pdf_original") or ficha.get("arquivo"),
                            ficha_path).resolve()
        if any(pdf == arquivo for _, arquivo in reativados):
            item["estado"] = "pendente"
            item["reativado_em"] = agora()
            item["motivo_reativacao"] = (
                "provedor removeu a obrigatoriedade de ISBN")
            for campo in ("http_status", "id_remoto", "erro", "concluido_em"):
                item.pop(campo, None)

    controle["atualizado_em"] = agora()
    fila["atualizada_em"] = agora()
    salvar_json(controle_path, controle)
    salvar_json(fila_path, fila)
    return len(reativados)


def reativar_falhas_tls_locais(raiz):
    """Reabre falhas de certificado ocorridas antes de uma resposta HTTP.

    Um erro de verificacao durante o handshake TLS impede o POST de chegar a
    camada HTTP. Por isso ele pode ser repetido depois da cadeia ser corrigida,
    preservando a tentativa local anterior para auditoria.
    """
    raiz = pathlib.Path(raiz).expanduser().resolve()
    controle_path = raiz / "_controle" / NOME_CONTROLE
    controle = carregar_controle(controle_path)
    fila_path = fila_da_raiz(raiz)
    fila = carregar_fila(fila_path)
    historico = controle.setdefault("tentativas_anteriores", {})
    reativados = []

    for digest, registro in list(controle["envios"].items()):
        erro = str(registro.get("erro_local", ""))
        elegivel = (
            registro.get("estado") ==
            "resultado incerto - nao reenviar sem conferencia" and
            not registro.get("http_status") and
            "CERTIFICATE_VERIFY_FAILED" in erro
        )
        if not elegivel:
            continue
        anterior = dict(registro)
        anterior.update({
            "arquivado_em": agora(),
            "motivo_reabertura":
                "falha no handshake TLS antes de qualquer resposta HTTP",
        })
        historico.setdefault(digest, []).append(anterior)
        del controle["envios"][digest]
        reativados.append(pathlib.Path(registro.get("arquivo", "")).resolve())

    for item in fila.get("itens", []):
        ficha_path = raiz / item.get("ficha", "")
        try:
            ficha = json.loads(ficha_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        pdf = caminho_local(ficha.get("pdf_preparado") or
                            ficha.get("pdf_original") or ficha.get("arquivo"),
                            ficha_path).resolve()
        if pdf in reativados:
            item["estado"] = "pendente"
            item["reativado_em"] = agora()
            item["motivo_reativacao"] = (
                "cadeia TLS corrigida; requisicao anterior nao chegou ao HTTP")
            for campo in ("http_status", "id_remoto", "erro", "concluido_em"):
                item.pop(campo, None)

    controle["atualizado_em"] = agora()
    fila["atualizada_em"] = agora()
    salvar_json(controle_path, controle)
    salvar_json(fila_path, fila)
    return len(reativados)


def marcar_catalogo_cadastrado(raiz, digest, registro):
    """Reflete o sucesso no estado exibido pelo aplicativo local."""
    raiz = pathlib.Path(raiz).resolve()
    caminho = raiz / "_controle" / "catalogo-local.json"
    try:
        catalogo = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    livro = catalogo.get("livros", {}).get(digest)
    if not livro:
        return False
    livro.update({"estado": "cadastrado", "id_remoto": registro.get("id_remoto", ""),
                  "cadastrado_em": registro.get("concluido_em", agora())})
    catalogo["atualizado_em"] = agora()
    salvar_json(caminho, catalogo)

    colunas = ["hash_sha256", "arquivo", "estado", "caminho", "tamanho_bytes",
               "processado_em", "metadados", "capa", "duplicado_de",
               "id_remoto", "cadastrado_em"]
    destino = raiz / "_controle" / "catalogo-local.csv"
    tmp = destino.with_name(destino.name + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8-sig") as f:
        escritor = csv.DictWriter(f, fieldnames=colunas, delimiter=";",
                                  extrasaction="ignore")
        escritor.writeheader()
        for item in sorted(catalogo["livros"].values(),
                           key=lambda x: (x.get("estado", ""),
                                          x.get("arquivo", ""))):
            escritor.writerow(item)
    os.replace(tmp, destino)
    return True


def sincronizar_catalogo_com_fila(raiz, fila):
    """Reconcilia pelo caminho da ficha, inclusive PDFs preparados/otimizados."""
    raiz = pathlib.Path(raiz).resolve()
    caminho = raiz / "_controle" / "catalogo-local.json"
    try:
        catalogo = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return 0
    por_ficha = {registro.get("metadados"): registro
                 for registro in catalogo.get("livros", {}).values()
                 if registro.get("metadados")}
    alterados = 0
    for item in fila.get("itens", []):
        registro = por_ficha.get(item.get("ficha"))
        if not registro:
            continue
        estado_fila = item.get("estado", "")
        if estado_fila == "cadastrado":
            novo_estado = "cadastrado"
        elif estado_fila == "duplicado confirmado por ISBN":
            novo_estado = "duplicado confirmado por ISBN"
        elif estado_fila == ESTADO_DUPLICADO_TITULO_AUTOR:
            novo_estado = ESTADO_DUPLICADO_TITULO_AUTOR
        elif estado_fila == ESTADO_DUPLICADO_TITULO:
            novo_estado = ESTADO_DUPLICADO_TITULO
        elif estado_fila in {"duplicado informado pela API - revisar",
                             "já existente na API - conferir vínculo"}:
            novo_estado = "já existente na API - conferir vínculo"
        else:
            continue
        if registro.get("estado") != novo_estado:
            alterados += 1
        registro["estado"] = novo_estado
        if item.get("id_remoto"):
            registro["id_remoto"] = item["id_remoto"]
        if item.get("concluido_em"):
            registro["cadastrado_em"] = item["concluido_em"]
        if item.get("confirmado_por_api"):
            registro["confirmado_por_api"] = item["confirmado_por_api"]
    if alterados:
        catalogo["atualizado_em"] = agora()
        salvar_json(caminho, catalogo)
        colunas = ["hash_sha256", "arquivo", "estado", "caminho", "tamanho_bytes",
                   "processado_em", "metadados", "capa", "duplicado_de",
                   "id_remoto", "cadastrado_em"]
        destino = raiz / "_controle" / "catalogo-local.csv"
        tmp = destino.with_name(destino.name + ".tmp")
        with tmp.open("w", newline="", encoding="utf-8-sig") as f:
            escritor = csv.DictWriter(f, fieldnames=colunas, delimiter=";",
                                      extrasaction="ignore")
            escritor.writeheader()
            for registro in sorted(catalogo["livros"].values(),
                                   key=lambda x: (x.get("estado", ""),
                                                  x.get("arquivo", ""))):
                escritor.writerow(registro)
        os.replace(tmp, destino)
    return alterados


def classificar_rejeicao(registro, ficha):
    mensagem = str(registro.get("resposta", {}).get("mensagem", ""))
    normalizada = mensagem.casefold()
    if "isbn" in normalizada and "obrigat" in normalizada:
        motivo = str(ficha.get("isbn_motivo", ""))
        if "sem isbn" in motivo.casefold() and ("original" in motivo.casefold() or
                                                 "sem isbn próprio" in motivo.casefold()):
            diagnostico = "sem ISBN documentado pela natureza da edicao"
        else:
            diagnostico = "ISBN nao localizado; pesquisa pode ser ampliada"
        return {
            "codigo": "ISBN_OBRIGATORIO_API",
            "classe": "politica da API",
            "diagnostico": diagnostico,
            "acao_recomendada": (
                "Permitir ISBN vazio para obras legitimamente sem ISBN ou aceitar "
                "um identificador interno separado; nunca fabricar ISBN."),
            "reenvio": "somente apos confirmacao da alteracao da API",
        }
    if "existe" in normalizada or "duplic" in normalizada:
        return {
            "codigo": "DUPLICADO_API",
            "classe": "registro ja existente",
            "diagnostico": "a API reconheceu o ISBN como existente",
            "acao_recomendada": "Localizar e vincular o identificador do registro existente.",
            "reenvio": "nao reenviar",
        }
    if int(registro.get("http_status", 0) or 0) >= 500:
        return {
            "codigo": "ERRO_TEMPORARIO_API", "classe": "falha do servidor",
            "diagnostico": "a API devolveu erro interno ou indisponibilidade",
            "acao_recomendada": "Conferir logs e repetir de forma controlada.",
            "reenvio": "permitido apos verificacao",
        }
    return {
        "codigo": "VALIDACAO_API", "classe": "validacao nao classificada",
        "diagnostico": mensagem or "resposta sem mensagem",
        "acao_recomendada": "Conferir a regra de validacao e os logs da API.",
        "reenvio": "somente apos correcao confirmada",
    }


def _valor_relatorio(valor):
    if isinstance(valor, (dict, list)):
        return json.dumps(valor, ensure_ascii=False)
    return "" if valor is None else str(valor)


def gerar_relatorio_rejeicoes(raiz):
    raiz = pathlib.Path(raiz).expanduser().resolve()
    fila, _, _ = atualizar_fila(raiz)
    controle = carregar_controle(raiz / "_controle" / NOME_CONTROLE)
    por_arquivo = _registro_por_arquivo(controle)
    casos = []
    for item in fila["itens"]:
        if item.get("estado") == "cadastrado":
            continue
        ficha_path = raiz / item["ficha"]
        try:
            ficha = json.loads(ficha_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        pdf = caminho_local(ficha.get("pdf_preparado") or
                            ficha.get("pdf_original") or ficha.get("arquivo"),
                            ficha_path)
        capa = caminho_local(ficha.get("capa"), ficha_path)
        registro = por_arquivo.get(str(pdf), {})
        if not registro or not registro.get("http_status"):
            continue
        payload = montar_payload(ficha)
        try:
            payload["autores"] = json.loads(payload.get("autores", "[]"))
        except ValueError:
            pass
        evidencias = ficha.get("evidencias", {}) or {}
        candidatos = evidencias.get("isbn_candidatos", []) or []
        caso = {
            "identificacao": {
                "titulo": ficha.get("titulo", ""), "subtitulo": ficha.get("subTitulo", ""),
                "autor": ficha.get("nmAutor0", ""), "isbn": ficha.get("isbn", ""),
                "isbn_diagnostico": ficha.get("isbn_motivo", ""),
                "editora": ficha.get("editora", ""), "ano": ficha.get("data", ""),
                "edicao": ficha.get("edicao", ""), "paginas": ficha.get("nPaginas", ""),
                "idioma": ficha.get("nmLingua", ficha.get("idioma", "")),
                "lugar": ficha.get("lugar", ""), "cdd": ficha.get("cdd", ""),
                "assunto": ficha.get("tipoAssunto1", ""),
            },
            "arquivo": {
                "pdf": pdf.name, "pdf_bytes": pdf.stat().st_size if pdf.is_file() else "",
                "pdf_sha256": registro.get("sha256", ""),
                "capa": capa.name if capa.is_file() else "",
                "capa_bytes": capa.stat().st_size if capa.is_file() else "",
            },
            "qualidade": {
                "ocr": ficha.get("status_ocr", ""),
                "cobertura_ocr": ficha.get("cobertura_ocr", ""),
                "qualidade_ocr": ficha.get("qualidade_ocr", ""),
                "paginas_pdf": ficha.get("paginas_pdf", ""),
                "conflitos": ficha.get("conflitos", ""),
                "pendencias": ficha.get("pendencias", ""),
            },
            "evidencias_bibliograficas": {
                "isbn_candidatos": candidatos,
                "cip": evidencias.get("cip", {}),
                "copyright": evidencias.get("copyright", {}),
                "fontes_externas": evidencias.get("api", {}),
            },
            "requisicao": {
                "metodo": "POST", "endpoint": registro.get("endpoint", ENDPOINT),
                "content_type": "multipart/form-data",
                "autenticacao": "X-API-Key armazenada no Chaves do macOS; valor omitido",
                "payload_texto": payload,
                "arquivos": ["nome_capa", "arquivo_digital"],
                "iniciada_em": registro.get("iniciado_em", ""),
            },
            "resposta_api": {
                "http_status": registro.get("http_status", ""),
                "corpo": registro.get("resposta", {}),
                "concluida_em": registro.get("concluido_em", ""),
            },
            "classificacao": classificar_rejeicao(registro, ficha),
        }
        casos.append(caso)

    codigos = {}
    for caso in casos:
        codigo = caso["classificacao"]["codigo"]
        codigos[codigo] = codigos.get(codigo, 0) + 1
    relatorio = {
        "versao": 1, "gerado_em": agora(), "endpoint": ENDPOINT,
        "metodo": "POST multipart/form-data", "total_rejeicoes": len(casos),
        "resumo_por_codigo": codigos,
        "observacoes_validacao": [
            "A chave da API foi intencionalmente omitida.",
            "Os hashes SHA-256 permitem correlacionar exatamente cada PDF.",
            "A API nao devolveu identificador de requisicao; recomenda-se inclui-lo nas respostas.",
            "Os horarios usam o fuso local da maquina cliente.",
        ],
        "casos": casos,
    }
    pasta = raiz / "_controle"
    json_path = pasta / "relatorio-rejeicoes-api.json"
    csv_path = pasta / "relatorio-rejeicoes-api.csv"
    html_path = pasta / "relatorio-rejeicoes-api.html"
    salvar_json(json_path, relatorio)

    colunas = ["codigo", "classe", "titulo", "autor", "isbn", "isbn_diagnostico",
               "ano", "editora", "http_status", "mensagem", "iniciada_em",
               "concluida_em", "pdf", "pdf_sha256", "acao_recomendada", "reenvio"]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        escritor = csv.DictWriter(f, fieldnames=colunas, delimiter=";")
        escritor.writeheader()
        for caso in casos:
            i, a, r, q, ar = (caso["identificacao"], caso["classificacao"],
                              caso["resposta_api"], caso["requisicao"], caso["arquivo"])
            escritor.writerow({
                "codigo": a["codigo"], "classe": a["classe"], "titulo": i["titulo"],
                "autor": i["autor"], "isbn": i["isbn"],
                "isbn_diagnostico": i["isbn_diagnostico"], "ano": i["ano"],
                "editora": i["editora"], "http_status": r["http_status"],
                "mensagem": r["corpo"].get("mensagem", ""),
                "iniciada_em": q["iniciada_em"], "concluida_em": r["concluida_em"],
                "pdf": ar["pdf"], "pdf_sha256": ar["pdf_sha256"],
                "acao_recomendada": a["acao_recomendada"], "reenvio": a["reenvio"],
            })

    blocos = []
    for n, caso in enumerate(casos, 1):
        i, a, r, q, ar, e = (caso["identificacao"], caso["classificacao"],
                             caso["resposta_api"], caso["requisicao"],
                             caso["arquivo"], caso["evidencias_bibliograficas"])
        linhas = {
            "Autor": i["autor"], "ISBN enviado": i["isbn"] or "(vazio)",
            "Diagnostico ISBN": i["isbn_diagnostico"], "Editora / ano":
                " / ".join(x for x in (i["editora"], i["ano"]) if x),
            "PDF / SHA-256": f"{ar['pdf']} / {ar['pdf_sha256']}",
            "Requisicao": f"{q['metodo']} {q['endpoint']} em {q['iniciada_em']}",
            "Resposta": f"HTTP {r['http_status']} - {r['corpo'].get('mensagem', '')}",
            "Classificacao": f"{a['codigo']} - {a['classe']}",
            "Acao recomendada": a["acao_recomendada"], "Reenvio": a["reenvio"],
            "ISBNs encontrados no PDF": _valor_relatorio(e["isbn_candidatos"]) or "nenhum",
        }
        tabela = "".join(f"<tr><th>{html.escape(k)}</th><td>{html.escape(str(v))}</td></tr>"
                         for k, v in linhas.items())
        blocos.append(f"<section><h2>{n}. {html.escape(i['titulo'])}</h2><table>{tabela}</table></section>")
    resumo_html = "".join(f"<li>{html.escape(k)}: {v}</li>" for k, v in codigos.items())
    documento = f"""<!doctype html><html lang=\"pt-BR\"><meta charset=\"utf-8\">
<title>Relatorio de rejeicoes - API Biblio</title><style>
body{{font:15px -apple-system,BlinkMacSystemFont,sans-serif;max-width:1100px;margin:40px auto;padding:0 24px;color:#18212b}}
h1{{color:#174d78}} section{{margin:28px 0;padding:20px;border:1px solid #ccd6df;border-radius:8px}}
table{{border-collapse:collapse;width:100%}} th,td{{padding:8px;border-bottom:1px solid #e5eaee;text-align:left;vertical-align:top}}th{{width:240px}}
.nota{{background:#f2f7fa;padding:14px;border-radius:6px}}</style>
<h1>Relatorio tecnico de rejeicoes da API Biblio</h1>
<p>Gerado em {html.escape(relatorio['gerado_em'])}. Endpoint: {html.escape(ENDPOINT)}.</p>
<div class=\"nota\"><strong>Integridade e seguranca:</strong> a chave foi omitida; os PDFs sao identificados por SHA-256. A API nao forneceu ID de requisicao.</div>
<h2>Resumo</h2><ul>{resumo_html}</ul>{''.join(blocos)}</html>"""
    html_path.write_text(documento, encoding="utf-8")
    return relatorio, {"json": json_path, "csv": csv_path, "html": html_path}


def criar_rascunho_operador(raiz, destinatario=OPERADOR_EMAIL,
                            remetente=REMETENTE_EMAIL, executor=subprocess.run):
    raiz = pathlib.Path(raiz).expanduser().resolve()
    relatorio, caminhos = gerar_relatorio_rejeicoes(raiz)
    if not relatorio["casos"]:
        raise ValueError("nao existem rejeicoes para comunicar")
    identidade = hashlib.sha256(json.dumps(
        relatorio["casos"], ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")).hexdigest()
    diario_path = raiz / "_controle" / "comunicacoes-operador.json"
    try:
        diario = json.loads(diario_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        diario = {"versao": 1, "comunicacoes": []}
    if any(c.get("relatorio_sha256") == identidade and
           c.get("estado") in {"rascunho criado", "enviado"}
           for c in diario.get("comunicacoes", [])):
        raise RuntimeError("ja existe rascunho para este mesmo relatorio")

    resumo = relatorio["resumo_por_codigo"]
    assunto = (f"[API Biblio] Relatorio tecnico - "
               f"{relatorio['total_rejeicoes']} rejeicoes no cadastro de livros")
    corpo = f"""Olá, Renan,

Durante o teste controlado de cadastro sequencial de livros, a API aceitou os demais itens e devolveu rejeição confirmada para {relatorio['total_rejeicoes']} casos.

Resumo:
- {resumo.get('ISBN_OBRIGATORIO_API', 0)} livro(s) recusado(s) porque o campo ISBN foi considerado obrigatório;
- {resumo.get('DUPLICADO_API', 0)} livro(s) informado(s) como já existente(s).

Os anexos apresentam, para cada caso, o horário da requisição, endpoint, código HTTP, resposta integral da API, metadados enviados, diagnóstico bibliográfico, evidências de ISBN e SHA-256 do PDF. A chave de acesso e os próprios PDFs foram omitidos.

Solicitação principal: permitir ISBN vazio para obras legitimamente sem ISBN, ou disponibilizar um campo separado de identificador interno. Não devemos fabricar ISBN. Também seria útil a API devolver um identificador de requisição para correlação com os logs do servidor.

Após a correção, faremos um novo teste com somente um livro antes de liberar os demais rejeitados.

Atenciosamente,
Piragine Jr."""
    script = pathlib.Path(__file__).with_name("criar-email-relatorio.applescript")
    if not script.is_file():
        raise FileNotFoundError(f"integracao com Mail nao encontrada: {script}")
    comando = ["osascript", str(script), destinatario, remetente, assunto, corpo,
               str(caminhos["html"]), str(caminhos["csv"])]
    resultado = executor(comando, capture_output=True, text=True, check=False)
    if resultado.returncode != 0:
        raise RuntimeError("o Mail nao conseguiu criar o rascunho: " +
                           (resultado.stderr.strip() or resultado.stdout.strip()))
    registro = {
        "criado_em": agora(), "destinatario": destinatario,
        "remetente": remetente, "assunto": assunto,
        "relatorio_sha256": identidade, "total_rejeicoes": relatorio["total_rejeicoes"],
        "anexos": [caminhos["html"].name, caminhos["csv"].name],
        "estado": "rascunho criado",
    }
    diario.setdefault("comunicacoes", []).append(registro)
    salvar_json(diario_path, diario)
    return registro


def preview(payload, pdf, capa, digest):
    visivel = dict(payload)
    try:
        visivel["autores"] = json.loads(visivel.get("autores", "[]"))
    except ValueError:
        pass
    return {
        "modo": "SIMULACAO",
        "endpoint": ENDPOINT,
        "dados": visivel,
        "pdf": {"nome": pdf.name, "bytes": pdf.stat().st_size,
                "sha256": digest},
        "capa": {"nome": capa.name, "bytes": capa.stat().st_size},
    }


def enviar(ficha_path, realmente=False, chave="", sessao=None,
           tipo_api="livro"):
    ficha_path = pathlib.Path(ficha_path).expanduser().resolve()
    ficha = json.loads(ficha_path.read_text(encoding="utf-8"))
    pdf = caminho_local(ficha.get("pdf_preparado") or ficha.get("pdf_original")
                        or ficha.get("arquivo"), ficha_path)
    capa = caminho_local(ficha.get("capa"), ficha_path)
    erros = validar(ficha, pdf, capa, tipo_api=tipo_api)
    if erros:
        raise ValueError("; ".join(erros))
    digest = sha256(pdf)
    payload = montar_payload(ficha, tipo_api=tipo_api)
    previa = preview(payload, pdf, capa, digest)
    if not realmente:
        print(json.dumps(previa, ensure_ascii=False, indent=2))
        return {"simulacao": True, "preview": previa}

    controle_path = controle_da_ficha(ficha_path)
    controle = carregar_controle(controle_path)
    anterior = controle["envios"].get(digest)
    if anterior:
        if anterior.get("estado") == (
                "resultado incerto - nao reenviar sem conferencia"):
            if not requests:
                raise RuntimeError("biblioteca requests nao instalada")
            if not chave:
                chave = (ler_chave_chaves() or
                         os.environ.get("BIBLIO_API_KEY", "") or
                         getpass.getpass("Chave da API (nao sera gravada): "))
            if not chave:
                raise ValueError("chave da API ausente")
            reconciliado = reconciliar_resultado_incerto(
                ficha_path, digest, controle, anterior, chave,
                sessao=sessao, tipo_api=tipo_api)
            if reconciliado:
                if not reconciliado.get("reenvio_autorizado"):
                    return reconciliado
            else:
                raise RuntimeError(
                    "a consulta da tentativa anterior foi ambigua; "
                    "este PDF nao sera reenviado automaticamente")
        else:
            raise RuntimeError(
                f"este PDF ja possui tentativa registrada: "
                f"{anterior.get('estado')}; nao sera reenviado automaticamente")
    if not requests:
        raise RuntimeError("biblioteca requests nao instalada")
    if not chave:
        chave = (ler_chave_chaves() or os.environ.get("BIBLIO_API_KEY", "") or
                 getpass.getpass("Chave da API (nao sera gravada): "))
    if not chave:
        raise ValueError("chave da API ausente")

    registro = {
        "sha256": digest, "isbn": ficha.get("isbn", ""),
        "titulo": ficha.get("titulo", ""), "arquivo": str(pdf),
        "assinatura_ficha": assinatura_ficha(ficha, tipo_api=tipo_api),
        "tipo_api": tipo_api,
        "estado": "envio iniciado - resultado ainda incerto",
        "iniciado_em": agora(), "endpoint": ENDPOINT,
    }
    controle["envios"][digest] = registro
    salvar_json(controle_path, controle)

    sessao = sessao or criar_sessao_api()
    try:
        with pdf.open("rb") as fp, capa.open("rb") as fc:
            resposta = sessao.post(
                ENDPOINT, data=payload,
                files={
                    "nome_capa": (capa.name, fc, "image/jpeg"),
                    "arquivo_digital": (pdf.name, fp, "application/pdf"),
                },
                headers={"X-API-Key": chave}, timeout=TIMEOUT_ENVIO)
        try:
            corpo = resposta.json()
        except ValueError:
            corpo = {"resposta_texto": resposta.text[:1000]}
        registro.update({"http_status": resposta.status_code,
                         "resposta": corpo, "concluido_em": agora()})
        if resposta.status_code == 201 and corpo.get("id"):
            registro["estado"] = "cadastrado"
            registro["id_remoto"] = corpo["id"]
        elif resposta.status_code == 400 and "existe" in str(
                corpo.get("mensagem", "")).lower():
            registro["estado"] = "duplicado informado pela API - revisar"
        else:
            registro["estado"] = "erro confirmado - revisar"
        salvar_json(controle_path, controle)
        if registro["estado"] == "cadastrado":
            try:
                marcar_catalogo_cadastrado(ficha_path.parent.parent, digest,
                                           registro)
            except OSError as exc:
                registro["aviso_local"] = f"cadastro remoto confirmado; catalogo: {exc}"
                salvar_json(controle_path, controle)
        return registro
    except Exception as exc:
        registro["estado"] = "resultado incerto - nao reenviar sem conferencia"
        registro["erro_local"] = str(exc)
        registro["concluido_em"] = agora()
        salvar_json(controle_path, controle)
        raise


def processar_fila(raiz, limite=0, intervalo=3.0, chave="", sessao=None,
                   dormir=time.sleep):
    """Envia sequencialmente sem deixar uma falha individual travar a fila."""
    raiz = pathlib.Path(raiz).expanduser().resolve()
    fila, _, _ = atualizar_fila(raiz)
    caminho = fila_da_raiz(raiz)
    incertos = [i for i in fila["itens"] if
                "incerto" in i.get("estado", "") or
                i.get("estado", "").startswith("envio iniciado")]
    pendentes = [i for i in fila["itens"] if i.get("estado") == "pendente"]
    if limite and limite > 0:
        pendentes = pendentes[:limite]
    if not pendentes and not incertos:
        return {"enviados": 0, "revisao": 0, "pendentes": 0,
                "reconciliados": 0, "falhas": 0, "interrompido": False}
    chave = chave or ler_chave_chaves()
    if not chave:
        raise ValueError("chave nao configurada no Chaves do macOS")

    resultado = {"enviados": 0, "revisao": 0,
                 "reconciliados": 0, "falhas": 0,
                 "pendentes": len(pendentes), "interrompido": False}

    # Os casos incertos sao deixados para o final. Isso permite que o servidor
    # conclua um cadastro mesmo quando a conexao local perdeu a resposta.
    revisao_final = list(incertos)

    for posicao, item in enumerate(pendentes, 1):
        ficha_path = raiz / item["ficha"]
        print(f"[{posicao}/{len(pendentes)}] {item.get('titulo')}", flush=True)
        try:
            ficha_consulta = json.loads(ficha_path.read_text(encoding="utf-8"))
            autores_consulta = []
            for autor in ficha_consulta.get("autores", []) or []:
                nome = autor.get("nome", "") if isinstance(autor, dict) else str(autor)
                if nome:
                    autores_consulta.append(nome)
            if not autores_consulta and ficha_consulta.get("nmAutor0"):
                autores_consulta = [ficha_consulta["nmAutor0"]]
            consulta = consultar_livro(
                sessao or criar_sessao_api(), chave,
                isbn=ficha_consulta.get("isbn", ""),
                titulo=ficha_consulta.get("titulo", ""),
                autores=autores_consulta, exato=False)
            if consulta.get("encontrado") and consulta_com_isbn_divergente(consulta):
                item["aviso_consulta_previa"] = (
                    "correspondência aproximada ignorada: ISBN da API "
                    f"{consulta.get('isbn', '')} difere do ISBN da ficha "
                    f"{ficha_consulta.get('isbn', '')}")
                item.setdefault("consultas_nao_bloqueantes", []).append(consulta)
                salvar_json(caminho, fila)
                print(
                    "  outra edição localizada pelo título/autor; ISBN "
                    "divergente; o cadastro desta edição continuará",
                    flush=True)
            elif consulta_bloqueia_envio(consulta):
                por_isbn = consulta_confirmada_por_isbn(consulta)
                por_titulo_autor = consulta_confirmada_por_titulo_autor(
                    consulta)
                item.update({
                    "estado": ("duplicado confirmado por ISBN" if por_isbn
                               else ESTADO_DUPLICADO_TITULO_AUTOR
                               if por_titulo_autor
                               else "já existente na API - conferir vínculo"),
                    "id_remoto": consulta.get("id", ""),
                    "consulta_previa_api": consulta,
                    "concluido_em": agora(),
                })
                salvar_json(caminho, fila)
                resultado["revisao"] += 1
                resultado["pendentes"] -= 1
                print(
                    f"  já consta na API; upload evitado; ID "
                    f"{consulta.get('id', '?')} ({consulta.get('correspondencia')})",
                    flush=True)
                continue
        except Exception as exc:
            # Indisponibilidade da consulta nao torna o resultado do upload
            # incerto; registramos o aviso e seguimos com o cadastro normal.
            item["aviso_consulta_previa"] = str(exc)
            salvar_json(caminho, fila)
        item["estado"] = "enviando"
        item["iniciado_em"] = agora()
        salvar_json(caminho, fila)
        try:
            registro = enviar(ficha_path, realmente=True, chave=chave,
                               sessao=sessao)
        except Exception as exc:
            # O diario gravado antes da rede decide se a tentativa ficou
            # incerta. Em qualquer caso, isolamos este item e seguimos.
            ficha = json.loads(ficha_path.read_text(encoding="utf-8"))
            pdf = caminho_local(ficha.get("pdf_preparado") or
                                ficha.get("pdf_original") or
                                ficha.get("arquivo"), ficha_path)
            remoto = carregar_controle(
                raiz / "_controle" / NOME_CONTROLE).get(
                    "envios", {}).get(sha256(pdf), {})
            item["estado"] = remoto.get("estado", "erro local - revisar")
            item["erro"] = str(exc)
            item["concluido_em"] = agora()
            salvar_json(caminho, fila)
            print(f"  falha isolada; mantido em revisão; a fila continuará",
                  flush=True)
            if "incerto" in item.get("estado", ""):
                revisao_final.append(item)
            else:
                resultado["revisao"] += 1
                resultado["falhas"] += 1
            continue

        item["estado"] = registro.get("estado", "revisar")
        item["http_status"] = registro.get("http_status", "")
        item["id_remoto"] = registro.get("id_remoto", "")
        item["concluido_em"] = agora()
        if item["estado"] == "cadastrado":
            resultado["enviados"] += 1
            print(f"  cadastrado; ID {item['id_remoto']}", flush=True)
        else:
            resultado["revisao"] += 1
            print(f"  {item['estado']}", flush=True)
        salvar_json(caminho, fila)
        if posicao < len(pendentes) and intervalo > 0:
            dormir(intervalo)

    # Somente agora conferimos os casos incertos. Se a API ja os registrou,
    # corrigimos o estado local; se nao registrou, enviar() libera exatamente
    # uma nova tentativa. Resultado ambiguo continua bloqueado por seguranca.
    unicos = {item.get("ficha", ""): item for item in revisao_final}
    if unicos and intervalo > 0:
        dormir(intervalo)
    for posicao, item in enumerate(unicos.values(), 1):
        ficha_path = raiz / item.get("ficha", "")
        print(f"[conferência final {posicao}/{len(unicos)}] "
              f"{item.get('titulo', '')}", flush=True)
        try:
            registro = enviar(ficha_path, realmente=True, chave=chave,
                               sessao=sessao)
        except Exception as exc:
            item["erro"] = str(exc)
            item["concluido_em"] = agora()
            resultado["revisao"] += 1
            resultado["falhas"] += 1
            print("  ainda incerto; somente este item permanece em revisão",
                  flush=True)
            salvar_json(caminho, fila)
            continue
        item.update({
            "estado": registro.get("estado", "revisar"),
            "http_status": registro.get("http_status", ""),
            "id_remoto": registro.get("id_remoto", ""),
            "concluido_em": agora(),
        })
        item.pop("erro", None)
        if registro.get("reconciliado_por"):
            resultado["reconciliados"] += 1
            print(f"  confirmado na API sem reenvio; ID "
                  f"{item.get('id_remoto', '')}", flush=True)
        elif item.get("estado") == "cadastrado":
            resultado["enviados"] += 1
            print(f"  não constava na API; reenviado e cadastrado; ID "
                  f"{item.get('id_remoto', '')}", flush=True)
        else:
            resultado["revisao"] += 1
        salvar_json(caminho, fila)

    resultado["pendentes"] = sum(
        1 for i in fila["itens"] if i.get("estado") == "pendente")
    resultado["em_revisao"] = sum(
        1 for i in fila["itens"] if "incerto" in i.get("estado", "") or
        "revisar" in i.get("estado", ""))
    # Reflete imediatamente no catálogo tudo o que a consulta final ou o
    # envio decidiu. Sem isto, um duplicado barrado durante a subida podia
    # continuar aparecendo como "pronto" até a próxima atualização da fila.
    sincronizar_catalogo_com_fila(raiz, fila)
    return resultado


def processar_fila_especifica(raiz, grupo, limite=0, intervalo=3.0,
                              chave="", sessao=None, dormir=time.sleep,
                              realmente=False):
    """Envia documentos, trabalhos academicos ou revistas sem reprocessar OCR."""
    raiz = pathlib.Path(raiz).expanduser().resolve()
    if grupo not in FILAS_ESPECIFICAS:
        raise ValueError(f"fila específica desconhecida: {grupo}")
    caminho = raiz / "_controle" / FILAS_ESPECIFICAS[grupo]
    try:
        fila = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("atualize primeiro as filas específicas") from exc
    controle = carregar_controle(raiz / "_controle" / NOME_CONTROLE)

    def tentativa_incerta(item):
        remoto = controle.get("envios", {}).get(item.get("hash_sha256", ""), {})
        return remoto.get("estado") == (
            "resultado incerto - nao reenviar sem conferencia")

    incertos = [item for item in fila.get("itens", [])
                if tentativa_incerta(item)]
    hashes_incertos = {item.get("hash_sha256", "") for item in incertos}
    pendentes = [item for item in fila.get("itens", [])
                 if item.get("estado") == "pronto para cadastro específico"
                 and item.get("hash_sha256", "") not in hashes_incertos]
    if limite > 0:
        pendentes = pendentes[:limite]
    if not realmente:
        return {"modo": "SIMULAÇÃO", "grupo": grupo,
                "quantidade": len(pendentes),
                "itens": [{k: item.get(k, "") for k in (
                    "titulo", "tipo_documento", "tipo_api", "metadados")}
                          for item in pendentes]}
    chave = chave or ler_chave_chaves()
    if not chave:
        raise ValueError("chave nao configurada no Chaves do macOS")
    resultado = {"grupo": grupo, "enviados": 0, "revisao": 0,
                 "reconciliados": 0, "falhas": 0,
                 "pendentes": len(pendentes), "interrompido": False}
    revisao_final = list(incertos)
    for posicao, item in enumerate(pendentes, 1):
        print(f"[{posicao}/{len(pendentes)}] {item.get('titulo', '')}",
              flush=True)
        ficha_path = raiz / item.get("metadados", "")
        try:
            ficha_consulta = json.loads(ficha_path.read_text(encoding="utf-8"))
            consulta = consultar_livro(
                sessao or criar_sessao_api(), chave,
                isbn=ficha_consulta.get("isbn", ""),
                titulo=ficha_consulta.get("titulo", ""),
                autores=autores_para_consulta(ficha_consulta), exato=False)
            if (consulta_confirmada_por_isbn(consulta) or
                    consulta_corresponde_ao_titulo_exato(consulta)):
                por_isbn = consulta_confirmada_por_isbn(consulta)
                por_titulo_autor = consulta_confirmada_por_titulo_autor(
                    consulta)
                estado = (
                    "duplicado confirmado por ISBN" if por_isbn else
                    ESTADO_DUPLICADO_TITULO_AUTOR if por_titulo_autor else
                    ESTADO_DUPLICADO_TITULO)
                item.update({
                    "estado": estado, "id_remoto": consulta.get("id", ""),
                    "consulta_previa_api": consulta,
                    "confirmado_por_api": (
                        "isbn" if por_isbn else
                        "titulo_autor" if por_titulo_autor else "titulo"),
                    "concluido_em": agora(),
                })
                salvar_json(caminho, fila)
                sincronizar_catalogo_com_fila(raiz, {"itens": [{
                    "ficha": item.get("metadados", ""),
                    "estado": estado, "id_remoto": consulta.get("id", ""),
                    "confirmado_por_api": item["confirmado_por_api"],
                    "concluido_em": item["concluido_em"],
                }]})
                resultado["revisao"] += 1
                print(f"  já consta na API; upload evitado; ID "
                      f"{consulta.get('id', '?')} "
                      f"({consulta.get('correspondencia', '')})", flush=True)
                continue
        except Exception as exc:
            # Se apenas a consulta estiver indisponível, o cadastro continua;
            # a falha não transforma o upload em resultado incerto.
            item["aviso_consulta_previa"] = str(exc)
            salvar_json(caminho, fila)
        try:
            registro = enviar(
                ficha_path, realmente=True, chave=chave, sessao=sessao,
                tipo_api=item.get("tipo_api", "documento"))
        except Exception as exc:
            remoto = carregar_controle(
                raiz / "_controle" / NOME_CONTROLE).get(
                    "envios", {}).get(item.get("hash_sha256", ""), {})
            item["estado"] = remoto.get("estado", "erro confirmado - revisar")
            item["erro"] = str(exc)
            item["concluido_em"] = agora()
            salvar_json(caminho, fila)
            print("  falha isolada; mantido em revisão; a fila continuará",
                  flush=True)
            if "incerto" in item.get("estado", ""):
                revisao_final.append(item)
            else:
                resultado["revisao"] += 1
                resultado["falhas"] += 1
            continue
        item["estado"] = registro.get("estado", "revisar")
        item["http_status"] = registro.get("http_status", "")
        item["id_remoto"] = registro.get("id_remoto", "")
        item["concluido_em"] = agora()
        item.pop("erro", None)
        if item["estado"] == "cadastrado":
            if registro.get("reconciliado_por"):
                resultado["reconciliados"] += 1
                print(f"  confirmado na API sem reenvio; ID "
                      f"{item['id_remoto']}", flush=True)
            else:
                resultado["enviados"] += 1
                print(f"  cadastrado; ID {item['id_remoto']}", flush=True)
            marcar_catalogo_cadastrado(
                raiz, item.get("hash_sha256", ""), registro)
        else:
            resultado["revisao"] += 1
            print(f"  {item['estado']}", flush=True)
        salvar_json(caminho, fila)
        if posicao < len(pendentes) and intervalo > 0:
            dormir(intervalo)

    unicos = {item.get("metadados", ""): item for item in revisao_final}
    if unicos and intervalo > 0:
        dormir(intervalo)
    for posicao, item in enumerate(unicos.values(), 1):
        if item.get("estado") == "cadastrado":
            continue
        print(f"[conferência final {posicao}/{len(unicos)}] "
              f"{item.get('titulo', '')}", flush=True)
        ficha_path = raiz / item.get("metadados", "")
        try:
            registro = enviar(
                ficha_path, realmente=True, chave=chave, sessao=sessao,
                tipo_api=item.get("tipo_api", "documento"))
        except Exception as exc:
            item["erro"] = str(exc)
            item["concluido_em"] = agora()
            resultado["revisao"] += 1
            resultado["falhas"] += 1
            print("  ainda incerto; somente este item permanece em revisão",
                  flush=True)
            salvar_json(caminho, fila)
            continue
        item.update({
            "estado": registro.get("estado", "revisar"),
            "http_status": registro.get("http_status", ""),
            "id_remoto": registro.get("id_remoto", ""),
            "concluido_em": agora(),
        })
        item.pop("erro", None)
        marcar_catalogo_cadastrado(
            raiz, item.get("hash_sha256", ""), registro)
        if registro.get("reconciliado_por"):
            resultado["reconciliados"] += 1
            print(f"  confirmado na API sem reenvio; ID "
                  f"{item.get('id_remoto', '')}", flush=True)
        elif item.get("estado") == "cadastrado":
            resultado["enviados"] += 1
            print(f"  não constava na API; reenviado e cadastrado; ID "
                  f"{item.get('id_remoto', '')}", flush=True)
        else:
            resultado["revisao"] += 1
        salvar_json(caminho, fila)
    resultado["pendentes"] = sum(
        1 for item in fila.get("itens", [])
        if item.get("estado") == "pronto para cadastro específico")
    resultado["em_revisao"] = sum(
        1 for item in fila.get("itens", [])
        if "incerto" in item.get("estado", "") or
        "revisar" in item.get("estado", ""))
    return resultado


def planejar_todas_filas(raiz, limite=0):
    """Monta um lote total preservando a ordem e as filas especializadas."""
    raiz = pathlib.Path(raiz).expanduser().resolve()
    fila_livros, _, _ = atualizar_fila(raiz)
    filas = [("livros", fila_livros, "pendente")]
    for grupo, nome in FILAS_ESPECIFICAS.items():
        caminho = raiz / "_controle" / nome
        try:
            fila = json.loads(caminho.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            fila = {"itens": []}
        filas.append((grupo, fila, "pronto para cadastro específico"))

    restante = limite if limite and limite > 0 else None
    plano = {"modo": "SIMULAÇÃO", "limite_total": limite,
             "total_disponivel": 0, "total_selecionado": 0, "filas": {}}
    for grupo, fila, estado_pendente in filas:
        itens = fila.get("itens", [])
        pendentes = [i for i in itens if i.get("estado") == estado_pendente]
        incertos = [i for i in itens if (
            "incerto" in i.get("estado", "")
            or i.get("estado", "").startswith("envio iniciado"))]
        quantidade = len(pendentes) if restante is None else min(
            len(pendentes), restante)
        plano["filas"][grupo] = {
            "disponiveis": len(pendentes), "selecionados": quantidade,
            "incertos_para_conferir": len(incertos),
        }
        plano["total_disponivel"] += len(pendentes)
        plano["total_selecionado"] += quantidade
        if restante is not None:
            restante -= quantidade
    if plano["total_disponivel"] == 0:
        plano["mensagem"] = (
            "Nenhum material aguarda envio. Arquivos que continuam visiveis "
            "no Finder podem ja estar cadastrados; use Liberar espaco "
            "(com simulacao previa) para retirar apenas os confirmados.")
    return plano


def processar_todas_filas(raiz, limite=0, intervalo=3.0,
                          realmente=False, chave="", sessao=None):
    """Processa livros, documentos, acadêmicos e revistas em um comando.

    O limite é global, não multiplicado por quatro. Cada motor existente
    continua responsável por suas validações, consulta prévia e reconciliação.
    """
    plano = planejar_todas_filas(raiz, limite=limite)
    if not realmente:
        return plano

    chave = chave or ler_chave_chaves()
    if not chave:
        raise ValueError("chave nao configurada no Chaves do macOS")
    sessao = sessao or criar_sessao_api()
    resultados = {}
    for grupo, dados in plano["filas"].items():
        quantidade = dados["selecionados"]
        if quantidade == 0 and dados["incertos_para_conferir"] == 0:
            resultados[grupo] = {"ignorados": True, "motivo": "fila vazia"}
            continue
        # Zero significa "todos" nos processadores antigos; aqui somente o
        # usamos quando o plano global também é ilimitado.
        limite_grupo = 0 if limite == 0 else quantidade
        print(f"\n=== {grupo.upper()} ===", flush=True)
        if grupo == "livros":
            resultados[grupo] = processar_fila(
                raiz, limite=limite_grupo, intervalo=intervalo,
                chave=chave, sessao=sessao)
        else:
            resultados[grupo] = processar_fila_especifica(
                raiz, grupo, limite=limite_grupo, intervalo=intervalo,
                chave=chave, sessao=sessao, realmente=True)
    return {"modo": "ENVIO", "limite_total": limite,
            "planejado": plano["total_selecionado"],
            "resultados": resultados}


def main():
    ap = argparse.ArgumentParser(description="Cadastro seguro de livros na API Biblio")
    grupo = ap.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--ficha")
    grupo.add_argument("--configurar-chave", action="store_true")
    grupo.add_argument("--verificar-chave", action="store_true")
    grupo.add_argument("--atualizar-fila", metavar="PASTA")
    grupo.add_argument("--status-fila", metavar="PASTA")
    grupo.add_argument("--processar-fila", metavar="PASTA")
    grupo.add_argument("--processar-fila-especifica", metavar="PASTA")
    grupo.add_argument("--processar-todas-filas", metavar="PASTA")
    grupo.add_argument("--relatorio-rejeicoes", metavar="PASTA")
    grupo.add_argument("--criar-email-operador", metavar="PASTA")
    grupo.add_argument("--reativar-rejeitados-isbn", metavar="PASTA")
    grupo.add_argument("--reativar-falhas-tls", metavar="PASTA")
    ap.add_argument("--enviar", action="store_true",
                    help="realiza o cadastro; sem esta opcao apenas simula")
    ap.add_argument("--limite", type=int, default=0,
                    help="quantidade maxima neste lote; zero envia todos")
    ap.add_argument("--intervalo", type=float, default=3.0,
                    help="segundos entre cadastros da fila")
    ap.add_argument("--tipo-api", choices=tuple(TIPOS_API), default="livro",
                    help="tipo do registro; o padrao permanece livro")
    ap.add_argument("--grupo-especifico", choices=tuple(FILAS_ESPECIFICAS),
                    default="documentos")
    args = ap.parse_args()
    if args.configurar_chave:
        guardar_chave_chaves()
        print("Chave guardada com seguranca no Chaves do macOS.")
    elif args.verificar_chave:
        if ler_chave_chaves():
            print("Chave configurada no Chaves do macOS.")
        else:
            print("Chave ainda nao configurada.")
            raise SystemExit(1)
    elif args.atualizar_fila:
        fila, adicionados, ignorados = atualizar_fila(args.atualizar_fila)
        print(f"Fila atualizada: {adicionados} novo(s); {ignorados} "
              "ficha(s) nao apta(s).")
        print(json.dumps(resumo_fila(fila), ensure_ascii=False, indent=2))
    elif args.status_fila:
        fila, _, _ = atualizar_fila(args.status_fila)
        print(json.dumps(resumo_fila(fila), ensure_ascii=False, indent=2))
    elif args.processar_fila:
        if not args.enviar:
            fila, _, _ = atualizar_fila(args.processar_fila)
            pendentes = [i for i in fila["itens"]
                         if i.get("estado") == "pendente"]
            if args.limite > 0:
                pendentes = pendentes[:args.limite]
            print(json.dumps({"modo": "SIMULACAO", "quantidade": len(pendentes),
                              "itens": pendentes}, ensure_ascii=False, indent=2))
        else:
            resultado = processar_fila(args.processar_fila, args.limite,
                                       args.intervalo)
            print(json.dumps(resultado, ensure_ascii=False, indent=2))
    elif args.processar_fila_especifica:
        resultado = processar_fila_especifica(
            args.processar_fila_especifica, args.grupo_especifico,
            limite=args.limite, intervalo=args.intervalo,
            realmente=args.enviar)
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
    elif args.processar_todas_filas:
        resultado = processar_todas_filas(
            args.processar_todas_filas, limite=args.limite,
            intervalo=args.intervalo, realmente=args.enviar)
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
    elif args.reativar_rejeitados_isbn:
        quantidade = reativar_rejeitados_isbn(args.reativar_rejeitados_isbn)
        print(f"Rejeitados por ISBN reativados: {quantidade}")
    elif args.reativar_falhas_tls:
        quantidade = reativar_falhas_tls_locais(args.reativar_falhas_tls)
        print(f"Falhas TLS locais reativadas: {quantidade}")
    elif args.relatorio_rejeicoes:
        relatorio, caminhos = gerar_relatorio_rejeicoes(args.relatorio_rejeicoes)
        print(f"Relatorio criado com {relatorio['total_rejeicoes']} caso(s):")
        for formato, caminho in caminhos.items():
            print(f"  {formato.upper()}: {caminho}")
    elif args.criar_email_operador:
        registro = criar_rascunho_operador(args.criar_email_operador)
        print(f"Rascunho criado para {registro['destinatario']} com "
              f"{registro['total_rejeicoes']} caso(s). Confira no Mail antes de enviar.")
    else:
        resultado = enviar(args.ficha, realmente=args.enviar,
                            tipo_api=args.tipo_api)
        if args.enviar:
            print(json.dumps(resultado, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nInterrompido; confira o controle antes de tentar novamente.")
    except Exception as exc:
        sys.exit(f"Erro: {exc}")
