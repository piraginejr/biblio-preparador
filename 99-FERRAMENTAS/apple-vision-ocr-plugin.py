"""Motor OCRmyPDF que usa nosso auxiliar Swift do Apple Vision."""

import json
import html
import os
import pathlib
import platform
import re
import subprocess

import ocrmypdf
from ocrmypdf import OcrEngine, hookimpl
from ocrmypdf.pluginspec import OrientationConfidence
from PIL import Image


HELPER = pathlib.Path(__file__).with_name("vision-ocr")


def registrar_progresso(imagem):
    """Comunica uma pagina concluida ao aplicativo sem misturar os logs."""
    destino = os.environ.get("BIBLIO_OCR_PROGRESS_FILE", "")
    if not destino:
        return
    pagina = re.search(r"(\d{6})_ocr", pathlib.Path(imagem).name)
    if not pagina:
        return
    try:
        tamanho = pathlib.Path(imagem).stat().st_size
        with open(destino, "a", encoding="ascii") as arquivo:
            arquivo.write(f"{int(pagina.group(1))}\t{tamanho}\n")
    except OSError:
        pass


def reconhecer(imagem):
    resultado = subprocess.run(
        [str(HELPER), str(imagem), "--json"], capture_output=True, text=True,
        timeout=300, check=False)
    if resultado.returncode != 0:
        raise RuntimeError(resultado.stderr.strip() or "falha no Apple Vision")
    linhas = json.loads(resultado.stdout or "[]")
    with Image.open(imagem) as img:
        largura, altura = img.size
        dpi = img.info.get("dpi", (300, 300))
    caixas = []
    for linha in linhas:
        x = float(linha["x"]); y = float(linha["y"])
        w = float(linha["largura"]); h = float(linha["altura"])
        esquerda = int(x * largura)
        direita = int((x + w) * largura)
        topo = int((1 - y - h) * altura)
        base = int((1 - y) * altura)
        caixas.append({
            "texto": linha["texto"], "esquerda": esquerda, "topo": topo,
            "direita": direita, "base": base,
            "confianca": int(float(linha["confianca"]) * 100),
        })
    return caixas, largura, altura, dpi


def reconhecer_tesseract(imagem, output_hocr, output_text, idiomas="por+eng+spa"):
    """Fallback por pagina quando o Vision nao consegue abrir a imagem."""
    hocr = subprocess.run(
        ["tesseract", str(imagem), "stdout", "-l", idiomas, "hocr"],
        capture_output=True, text=True, timeout=300, check=True)
    conteudo = hocr.stdout
    if "ocr_page" not in conteudo:
        raise RuntimeError("Tesseract nao produziu hOCR valido")
    pathlib.Path(output_hocr).write_text(conteudo, encoding="utf-8")
    texto = html.unescape(re.sub(r"<[^>]+>", " ", conteudo))
    texto = "\n".join(" ".join(linha.split()) for linha in texto.splitlines()
                       if linha.strip())
    pathlib.Path(output_text).write_text(texto, encoding="utf-8")


def criar_hocr(caixas, largura, altura, dpi):
    """Gera hOCR simples, sem depender de outro plugin externo."""
    dx = max(1, round(float(dpi[0])))
    dy = max(1, round(float(dpi[1])))
    partes = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<html xmlns="http://www.w3.org/1999/xhtml"><head>',
        '<meta name="ocr-system" content="Apple Vision"/>',
        '<meta name="ocr-capabilities" content="ocr_page ocr_line ocrx_word"/>',
        '</head><body>',
        (f'<div class="ocr_page" id="page_1" title="bbox 0 0 {largura} '
         f'{altura}; ppageno 0; scan_res {dx} {dy}">'),
        (f'<p class="ocr_par" id="par_1" lang="eng" dir="ltr" '
         f'title="bbox 0 0 {largura} {altura}">'),
    ]
    for indice, caixa in enumerate(caixas, 1):
        texto = caixa["texto"].strip()
        if not texto:
            continue
        e, t, d, b = (caixa["esquerda"], caixa["topo"],
                      caixa["direita"], caixa["base"])
        partes.append(
            f'<span class="ocr_line" id="line_{indice}" '
            f'title="bbox {e} {t} {d} {b}; baseline 0 0">')
        palavras = texto.split()
        total = max(1, sum(len(p) for p in palavras) + len(palavras) - 1)
        posicao = 0
        for num, palavra in enumerate(palavras, 1):
            pe = e + round((d - e) * posicao / total)
            posicao += len(palavra)
            pd = e + round((d - e) * posicao / total)
            posicao += 1
            partes.append(
                f'<span class="ocrx_word" id="word_{indice}_{num}" '
                f'title="bbox {pe} {t} {max(pe + 1, pd)} {b}; '
                f'x_wconf {caixa["confianca"]}">{html.escape(palavra)}</span>')
        partes.append('</span>')
    partes.extend(['</p>', '</div>', '</body></html>'])
    return "\n".join(partes)


class VisionEngine(OcrEngine):
    def __str__(self):
        return "Apple Vision"

    @staticmethod
    def version():
        return "1.0"

    @staticmethod
    def creator_tag(options):
        return f"Biblioteca Apple Vision OCR 1.0 (macOS {platform.mac_ver()[0]})"

    @staticmethod
    def languages(options):
        return ["por", "spa", "eng", "fra", "und"]

    @staticmethod
    def get_orientation(input_file, options):
        # O Apple Vision faz o reconhecimento final, mas o OCRmyPDF precisa
        # de um angulo antes de renderizar a pagina. O OSD do Tesseract e
        # usado somente como sensor de orientacao; nenhum texto reconhecido
        # por ele entra no PDF.
        try:
            resultado = subprocess.run(
                ["tesseract", str(input_file), "stdout", "-l", "osd",
                 "--psm", "0"], stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, timeout=60,
                check=False)
        except (OSError, subprocess.TimeoutExpired):
            return OrientationConfidence(angle=0, confidence=0.0)
        if resultado.returncode:
            return OrientationConfidence(angle=0, confidence=0.0)
        angulo = re.search(r"(?im)^Orientation in degrees:\s*(\d+)",
                            resultado.stdout or "")
        confianca = re.search(r"(?im)^Orientation confidence:\s*([\d.]+)",
                               resultado.stdout or "")
        return OrientationConfidence(
            angle=int(angulo.group(1)) if angulo else 0,
            confidence=float(confianca.group(1)) if confianca else 0.0)

    @staticmethod
    def get_deskew(input_file, options):
        return 0.0

    @staticmethod
    def generate_pdf(input_file, output_pdf, output_text, options):
        raise NotImplementedError("use o renderizador hocr")

    @staticmethod
    def generate_hocr(input_file, output_hocr, output_text, options):
        try:
            caixas, largura, altura, dpi = reconhecer(input_file)
        except RuntimeError as exc:
            if "nilError" not in str(exc):
                raise
            reconhecer_tesseract(input_file, output_hocr, output_text)
            registrar_progresso(input_file)
            return
        pathlib.Path(output_hocr).write_text(
            criar_hocr(caixas, largura, altura, dpi), encoding="utf-8")
        pathlib.Path(output_text).write_text(
            "\n".join(c["texto"] for c in caixas), encoding="utf-8")
        registrar_progresso(input_file)


@hookimpl
def check_options(options):
    options.pdf_renderer = "hocr"


@hookimpl
def get_ocr_engine(options=None):
    if options is not None and getattr(options, "ocr_engine", "auto") not in (
            "auto", "applevision"):
        return None
    return VisionEngine()
