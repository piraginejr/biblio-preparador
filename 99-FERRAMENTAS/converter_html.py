#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Converte HTML em PDF pesquisavel.

O Biblio so aceita PDF. Ate agora o aplicativo convertia .doc e .docx pelo
LibreOffice, mas HTML nao era tratado: o arquivo ficava em 00-ENTRADA sem
ser convertido, sem ser processado e sem ser reclamado - invisivel, porque
o painel contava apenas *.pdf.

MOTOR
-----
Chromium, pelo Playwright, que ja e dependencia da consulta a Estante e a
Amazon. E o mesmo motor que renderiza a pagina no navegador, entao a
fidelidade e muito melhor que a do LibreOffice. O LibreOffice fica como
alternativa quando o Playwright nao estiver instalado.

O PDF sai com CAMADA DE TEXTO REAL - o texto vem do HTML, nao de
reconhecimento de imagem. Nao precisa de OCR e nao ha erro de leitura.

REDE DESLIGADA POR PADRAO
-------------------------
Uma pagina salva referencia imagens, CSS e fontes por URL. Renderizar com
rede aberta faria o navegador buscar esses recursos - ou seja, abrir um
arquivo local dispararia conexoes para onde quer que ele aponte, sem que
ninguem tenha pedido.

Por isso bloqueamos tudo que nao seja file://. E mais seguro, e
determinista e funciona sem internet. Quando o documento sair
visivelmente incompleto, `permitir_rede=True` libera - decisao explicita,
caso a caso.
"""

import os
import pathlib
import re
import shutil
import subprocess
import tempfile

EXTENSOES_HTML = {".html", ".htm", ".xhtml", ".mht", ".mhtml"}

# pasta que o navegador cria ao salvar uma pagina ("pagina_files",
# "pagina_arquivos"). Precisa viajar junto, como o .opf ja faz.
SUFIXOS_RECURSOS = ("_files", "_arquivos", "_ficheiros", ".files")


def pasta_de_recursos(html):
    html = pathlib.Path(html)
    for sufixo in SUFIXOS_RECURSOS:
        candidata = html.with_name(html.stem + sufixo)
        if candidata.is_dir():
            return candidata
    return None


def titulo_do_html(html):
    """<title> da pagina, para nomear o PDF e alimentar a ficha."""
    try:
        bruto = pathlib.Path(html).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    m = re.search(r"<title[^>]*>(.*?)</title>", bruto, re.I | re.S)
    if not m:
        m = re.search(r"<h1[^>]*>(.*?)</h1>", bruto, re.I | re.S)
    if not m:
        return ""
    texto = re.sub(r"<[^>]+>", " ", m.group(1))
    texto = re.sub(r"&nbsp;?", " ", texto)
    return " ".join(texto.split())[:200]


def _converter_chromium(origem, destino, permitir_rede=False):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False, "playwright ausente"

    origem = pathlib.Path(origem).resolve()
    bloqueados = []
    try:
        with sync_playwright() as p:
            navegador = p.chromium.launch(args=["--disable-extensions"])
            pagina = navegador.new_page()

            if not permitir_rede:
                # Deixa passar apenas o que ja esta no disco.
                def filtrar(rota):
                    if rota.request.url.startswith("file://"):
                        rota.continue_()
                    else:
                        bloqueados.append(rota.request.url)
                        rota.abort()
                pagina.route("**/*", filtrar)

            pagina.goto(origem.as_uri(), wait_until="load", timeout=60000)
            pagina.emulate_media(media="print")
            pagina.pdf(path=str(destino), format="A4",
                       print_background=True,
                       margin={"top": "15mm", "bottom": "15mm",
                               "left": "12mm", "right": "12mm"})
            navegador.close()
    except Exception as erro:
        return False, f"chromium: {str(erro)[:120]}"

    if not pathlib.Path(destino).exists():
        return False, "chromium nao gerou o PDF"
    aviso = ""
    if bloqueados:
        dominios = sorted({re.sub(r"^https?://([^/]+).*", r"\1", u)
                           for u in bloqueados})[:5]
        aviso = (f"{len(bloqueados)} recurso(s) externo(s) nao carregado(s) "
                 f"({', '.join(dominios)}) - rede desligada por seguranca")
    return True, aviso


def _converter_libreoffice(origem, destino):
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        for c in ("/Applications/LibreOffice.app/Contents/MacOS/soffice",):
            if os.path.exists(c):
                soffice = c
                break
    if not soffice:
        return False, "LibreOffice ausente"
    with tempfile.TemporaryDirectory(prefix="biblio-html-") as td:
        try:
            subprocess.run(
                [soffice, "--headless", "--nologo", "--nodefault",
                 "--convert-to", "pdf", "--outdir", td, str(origem)],
                capture_output=True, timeout=600)
        except Exception as erro:
            return False, f"libreoffice: {str(erro)[:100]}"
        gerados = list(pathlib.Path(td).glob("*.pdf"))
        if not gerados:
            return False, "libreoffice nao gerou o PDF"
        shutil.move(str(gerados[0]), str(destino))
    return True, "convertido pelo LibreOffice (fidelidade menor que a do navegador)"


def converter(origem, destino, permitir_rede=False):
    """HTML -> PDF. Devolve (ok, aviso_ou_erro).

    Tenta o Chromium primeiro pela fidelidade; cai no LibreOffice.
    """
    origem = pathlib.Path(origem)
    if origem.suffix.lower() not in EXTENSOES_HTML:
        return False, "nao e HTML"
    destino = pathlib.Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)

    ok, aviso = _converter_chromium(origem, destino, permitir_rede)
    if ok:
        return True, aviso
    ok2, aviso2 = _converter_libreoffice(origem, destino)
    if ok2:
        return True, f"{aviso2} ({aviso})"
    return False, f"{aviso}; {aviso2}"


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        raise SystemExit("uso: converter_html.py arquivo.html [saida.pdf] [--rede]")
    entrada = pathlib.Path(sys.argv[1])
    saida = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 and \
        not sys.argv[2].startswith("--") else entrada.with_suffix(".pdf")
    ok, aviso = converter(entrada, saida, permitir_rede="--rede" in sys.argv)
    print(("ok   " if ok else "falha") + f"  {saida.name}" +
          (f"\n      {aviso}" if aviso else ""))
    if titulo_do_html(entrada):
        print(f"      titulo do HTML: {titulo_do_html(entrada)}")
