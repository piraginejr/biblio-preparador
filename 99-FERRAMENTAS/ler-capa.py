#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ler-capa.py - le a capa do livro como TEXTO, nao como desenho.

A versao anterior deste arquivo classificava cegamente por geometria: maior
corpo = titulo, rodape = autor. Acertou 1 capa em 12. O motivo esta nas
proprias capas do lote: em "Dogmatica Reformada" e em "Se Lider" o elemento
maior da capa pode ser o NOME DO AUTOR, porque e o autor que vende.

Por isso a camada principal continua semantica: extraimos linhas e entregamos
ao identificar.py. A geometria voltou apenas como evidencia auxiliar para um
caso recorrente: o OCR linear captura uma chamada promocional antes do titulo,
mas o titulo real esta em letras muito maiores no centro da capa. A regra
visual so sugere titulo quando o bloco maior e plausivel e nao coincide com o
autor conhecido nem com chamadas como "do autor campeao de vendas".

Uso:
    python3 ler-capa.py capa.jpg [--autor "Herman Bavinck"]
    python3 ler-capa.py pasta/
"""

import subprocess, sys, os, glob, shutil, re, json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import identificar

IDIOMAS  = "spa+por+eng"   # brew install tesseract-lang
DPI_CAPA = 300             # a 100 dpi o Tesseract devolve lixo; medido
CONF_MIN = 45

PROMOCIONAL = re.compile(
    r"(?i)\b(?:do\s+autor|da\s+autora|from\s+the\s+author|campe[aã]o\s+de\s+vendas|"
    r"best\s*-?\s*seller|bestseller|pref[aá]cio\s+de|foreword\s+by|"
    r"nova\s+edi[çc][aã]o|edi[çc][aã]o\s+revista|inclui|com\s+coment[aá]rios)\b")

SUBTITULO_VISUAL = re.compile(
    r"(?i)\b(?:todos\s+podem|everyone\s+can|como\s+|how\s+to|"
    r"guia\s+|manual\s+|princ[ií]pios|steps?|passos?)\b")


def _ocr_tesseract(img):
    try:
        out = subprocess.run(
            ["tesseract", img, "-", "-l", IDIOMAS, "--psm", "3", "tsv"],
            capture_output=True, text=True, timeout=180).stdout
    except Exception:
        return []

    # agrupamos por linha SO para remontar as palavras na ordem certa.
    # a posicao nao entra na decisao de qual campo e qual.
    linhas = {}
    for ln in out.splitlines()[1:]:
        c = ln.split("\t")
        if len(c) < 12 or not c[11].strip():
            continue
        try:
            if float(c[10]) < CONF_MIN:
                continue
            chave = (int(c[2]), int(c[3]), int(c[4]))   # block, par, line
        except ValueError:
            continue
        linhas.setdefault(chave, []).append(c[11].strip())
    return [" ".join(v) for _, v in sorted(linhas.items())]


def _ocr_tesseract_blocos(img):
    """Retorna linhas com geometria para estimar hierarquia visual da capa.

    A geometria nunca decide sozinha: ela só ajuda a priorizar blocos que já
    parecem título e a rejeitar chamadas promocionais ou nomes de autor.
    """
    try:
        out = subprocess.run(
            ["tesseract", img, "-", "-l", IDIOMAS, "--psm", "3", "tsv"],
            capture_output=True, text=True, timeout=180).stdout
    except Exception:
        return []

    linhas = {}
    for ln in out.splitlines()[1:]:
        c = ln.split("\t")
        if len(c) < 12 or not c[11].strip():
            continue
        try:
            conf = float(c[10])
            if conf < CONF_MIN:
                continue
            chave = (int(c[2]), int(c[3]), int(c[4]))
            left, top, width, height = map(int, c[6:10])
        except ValueError:
            continue
        item = linhas.setdefault(chave, {
            "palavras": [], "left": left, "top": top,
            "right": left + width, "bottom": top + height, "heights": []})
        item["palavras"].append(c[11].strip())
        item["left"] = min(item["left"], left)
        item["top"] = min(item["top"], top)
        item["right"] = max(item["right"], left + width)
        item["bottom"] = max(item["bottom"], top + height)
        item["heights"].append(height)
    saida = []
    for item in linhas.values():
        texto = " ".join(item["palavras"]).strip()
        if not texto:
            continue
        largura = max(1, item["right"] - item["left"])
        altura = max(1, item["bottom"] - item["top"])
        saida.append({
            "texto": texto,
            "left": item["left"], "top": item["top"],
            "right": item["right"], "bottom": item["bottom"],
            "width": largura, "height": altura,
            "area": largura * altura,
            "altura_media": sum(item["heights"]) / max(1, len(item["heights"])),
        })
    return sorted(saida, key=lambda x: (x["top"], x["left"]))


def _tamanho_imagem(img_path):
    """Obtém dimensões em pixels da imagem via utilitário nativo sips no macOS."""
    try:
        out = subprocess.run(
            ["sips", "-g", "pixelWidth", "-g", "pixelHeight", img_path],
            capture_output=True, text=True, timeout=10).stdout
        w_m = re.search(r"pixelWidth:\s*(\d+)", out)
        h_m = re.search(r"pixelHeight:\s*(\d+)", out)
        if w_m and h_m:
            return int(w_m.group(1)), int(h_m.group(1))
    except Exception:
        pass
    return 1000, 1500


def _ocr_vision_blocos(img):
    """Lê caixas delimitadoras e texto com o Apple Vision (--json).

    No macOS, o Apple Vision é o motor principal para reconhecimento de texto e
    hierarquia geométrica da capa (VNRecognizeTextRequest em .accurate).
    """
    helper = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "vision-ocr")
    if sys.platform != "darwin" or not os.path.exists(helper):
        return []
    try:
        out = subprocess.run([helper, "--json", img], capture_output=True,
                             text=True, timeout=180)
        itens = json.loads(out.stdout)
        if not isinstance(itens, list) or not itens:
            return []
    except Exception:
        return []

    w, h = _tamanho_imagem(img)
    saida = []
    for it in itens:
        t = str(it.get("texto", "")).strip()
        if not t:
            continue
        try:
            x = float(it["x"])
            y = float(it["y"])
            largura_norm = float(it["largura"])
            altura_norm = float(it["altura"])
        except (KeyError, ValueError, TypeError):
            continue

        left = int(x * w)
        width = max(1, int(largura_norm * w))
        right = left + width
        # No Vision o y=0 é no rodapé da imagem; convertemos para sistema top-down:
        top = max(0, int((1.0 - (y + altura_norm)) * h))
        height = max(1, int(altura_norm * h))
        bottom = top + height
        saida.append({
            "texto": t,
            "left": left, "top": top,
            "right": right, "bottom": bottom,
            "width": width, "height": height,
            "area": width * height,
            "altura_media": height,
        })
    return sorted(saida, key=lambda x: (x["top"], x["left"]))


_RAPID_ENGINE = None
_RAPID_TENTADO = False


def _obter_rapid_engine():
    """Retorna uma instância reutilizável do RapidOCR com lazy loading.

    Se a biblioteca não estiver instalada, retorna None silenciosamente.
    """
    global _RAPID_ENGINE, _RAPID_TENTADO
    if _RAPID_ENGINE is not None or _RAPID_TENTADO:
        return _RAPID_ENGINE
    _RAPID_TENTADO = True
    try:
        from rapidocr_onnxruntime import RapidOCR
        _RAPID_ENGINE = RapidOCR()
    except Exception:
        _RAPID_ENGINE = None
    return _RAPID_ENGINE


def _ocr_rapidocr_blocos(img):
    """Lê caixas delimitadoras e texto via RapidOCR (ONNX Runtime).

    Multiplataforma (Windows/Linux/macOS), muito mais resiliente que o
    Tesseract em fontes decoradas e capas artísticas.
    """
    engine = _obter_rapid_engine()
    if engine is None:
        return []
    try:
        resultado, _ = engine(img)
        if not resultado:
            return []
    except Exception:
        return []

    saida = []
    for item in resultado:
        if not item or len(item) < 3:
            continue
        box, texto, score = item[0], str(item[1]).strip(), float(item[2])
        if not texto or score < 0.40:
            continue
        try:
            xs = [pt[0] for pt in box]
            ys = [pt[1] for pt in box]
            left = int(min(xs))
            top = int(min(ys))
            right = int(max(xs))
            bottom = int(max(ys))
            width = max(1, right - left)
            height = max(1, bottom - top)
            saida.append({
                "texto": texto,
                "left": left, "top": top,
                "right": right, "bottom": bottom,
                "width": width, "height": height,
                "area": width * height,
                "altura_media": height,
            })
        except Exception:
            continue
    return sorted(saida, key=lambda x: (x["top"], x["left"]))


def _ocr_rapidocr(img):
    """Extrai linhas de texto pelo RapidOCR ordenadas de cima para baixo."""
    blocos = _ocr_rapidocr_blocos(img)
    if not blocos:
        return None
    linhas = [b["texto"].strip() for b in blocos if b.get("texto", "").strip()]
    return linhas or None


def blocos_da_capa(img):
    """Retorna blocos geométricos da capa com a cascata de prioridade:

    1. Apple Vision (leitor principal nativo no macOS)
    2. RapidOCR (rede neural ONNX multiplataforma, primário no Windows)
    3. Tesseract (contingência universal)
    """
    blocos = _ocr_vision_blocos(img)
    if blocos:
        return blocos
    blocos = _ocr_rapidocr_blocos(img)
    if blocos:
        return blocos
    return _ocr_tesseract_blocos(img)


def _parece_titulo_visual(texto, autor_conhecido=""):
    t = " ".join(str(texto or "").split()).strip(" .,:;·•-")
    if not t:
        return False
    n = identificar.normalizar(t)
    if not n or PROMOCIONAL.search(t) or identificar.RUIDO.match(t):
        return False
    if re.fullmatch(r"(?:19|20)\d{2}|\d{1,3}", n):
        return False
    palavras = [p for p in n.split() if p]
    if len(palavras) > 12:
        return False
    autor_n = {p for p in identificar.normalizar(
        autor_conhecido.replace(",", " ")).split() if len(p) > 2}
    if autor_n and autor_n <= {p for p in palavras if len(p) > 2}:
        return False
    t_limpo = " ".join(re.sub(r"[^\w\s]", "", n).split())
    tabela_autores = identificar.carregar_autores_conhecidos()
    if t_limpo in tabela_autores:
        return False
    return True


def titulo_visual_por_geometria_blocos(blocos, autor_conhecido=""):
    """Sugere título pela hierarquia visual da capa.

    O algoritmo procura a maior linha plausível e junta linhas vizinhas que
    compõem o mesmo bloco de título. Chamadas promocionais perdem peso.
    """
    candidatos = [dict(b) for b in blocos if _parece_titulo_visual(
        b.get("texto", ""), autor_conhecido)]
    if not candidatos:
        return {}
    altura_mediana = sorted(b["altura_media"] for b in candidatos)[len(candidatos)//2]
    for b in candidatos:
        n = identificar.normalizar(b["texto"])
        bonus = 1.0
        if SUBTITULO_VISUAL.search(b["texto"]):
            bonus += 0.20
        if len(n.split()) == 1 and len(n) >= 4:
            bonus += 0.15
        b["score_visual"] = b["area"] * bonus + b["altura_media"] * 800
    principal = max(candidatos, key=lambda b: b["score_visual"])
    grupo = [principal]
    # Junta linhas próximas acima/abaixo: "Tornando-se um" + "LÍDER" +
    # "Todos podem conseguir". Não junta autor conhecido nem promoção.
    for b in candidatos:
        if b is principal:
            continue
        distancia = min(abs(b["bottom"] - principal["top"]),
                        abs(b["top"] - principal["bottom"]))
        centro_b = (b["left"] + b["right"]) / 2
        centro_p = (principal["left"] + principal["right"]) / 2
        largura_ref = max(principal["width"], b["width"], 1)
        perto_vertical = distancia <= max(principal["height"], b["height"], altura_mediana) * 2.4
        alinhado = abs(centro_b - centro_p) <= largura_ref * 0.45
        tamanho_ok = b["altura_media"] >= max(8, principal["altura_media"] * 0.35)
        if perto_vertical and alinhado and tamanho_ok:
            grupo.append(b)
    grupo = sorted(grupo, key=lambda b: (b["top"], b["left"]))
    titulo = " ".join(b["texto"] for b in grupo)
    titulo = re.sub(r"\s+", " ", titulo).strip(" .,:;·•-")
    if not _parece_titulo_visual(titulo, autor_conhecido):
        titulo = principal["texto"].strip(" .,:;·•-")
    return {
        "titulo": titulo,
        "principal": principal["texto"],
        "linhas": [b["texto"] for b in grupo],
        "score": round(principal["score_visual"], 2),
    } if titulo else {}


def _ocr_vision(img):
    """No macOS, o Vision (.accurate) e bem melhor que o Tesseract.

    E o mesmo motor que o app usa (VNRecognizeTextRequest). Se o helper
    existir ao lado deste script, preferimos ele.
    """
    helper = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "vision-ocr")
    if sys.platform != "darwin" or not os.path.exists(helper):
        return None
    try:
        out = subprocess.run([helper, img], capture_output=True,
                             text=True, timeout=180)
        linhas = [l.strip() for l in out.stdout.splitlines() if l.strip()]
        return linhas or None
    except Exception:
        return None


def texto_da_capa(img):
    """Extrai linhas de texto com a cascata de prioridade:

    1. Apple Vision (leitor principal nativo no macOS)
    2. RapidOCR (rede neural ONNX multiplataforma, primário no Windows)
    3. Tesseract (contingência universal)
    """
    return _ocr_vision(img) or _ocr_rapidocr(img) or _ocr_tesseract(img)


def capa_do_pdf(pdf, destino, dpi=DPI_CAPA):
    """Extrai a capa. Importa o dpi: a 100 o OCR nao le capa decorada."""
    base = os.path.splitext(destino)[0]
    subprocess.run(["pdftoppm", "-f", "1", "-l", "1", "-r", str(dpi),
                    "-jpeg", "-singlefile", pdf, base],
                   capture_output=True, timeout=300)
    return base + ".jpg" if os.path.exists(base + ".jpg") else ""


def ler(img, autor_conhecido=""):
    linhas = texto_da_capa(img)
    r = identificar.separar(linhas, autor_conhecido=autor_conhecido)
    blocos = blocos_da_capa(img)
    visual = titulo_visual_por_geometria_blocos(
        blocos, autor_conhecido=autor_conhecido)
    if visual and visual.get("titulo"):
        r["titulo_visual"] = visual["titulo"]
        r["titulo_visual_linhas"] = visual.get("linhas", [])
        r["titulo_visual_score"] = visual.get("score", 0)
    r["linhas_ocr"] = len(linhas)
    # O preparo bibliografico usa estas linhas tambem para confirmar a marca
    # da editora. Mantemos o texto, nao coordenadas nem a imagem inteira.
    r["texto_ocr"] = linhas[:40]
    return r


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    autor = ""
    if "--autor" in sys.argv:
        autor = sys.argv[sys.argv.index("--autor") + 1]
    alvo = args[0] if args else "."

    helper_vision = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vision-ocr")
    tem_motor = (
        (sys.platform == "darwin" and os.path.exists(helper_vision))
        or _obter_rapid_engine() is not None
        or shutil.which("tesseract")
    )
    if not tem_motor:
        sys.exit("Nenhum motor de OCR disponível (instale vision-ocr, rapidocr-onnxruntime ou tesseract).")

    imgs = ([alvo] if os.path.isfile(alvo)
            else sorted(glob.glob(os.path.join(alvo, "*.jpg"))))
    if not identificar.tem_ner():
        print("  (sem spaCy - rodando so com o score)\n")

    for i in imgs:
        d = ler(i, autor)
        print(f"── {os.path.basename(i)[:50]}   [{d['confianca']}]")
        for k in ("volume", "titulo", "nmAutor0", "papeis"):
            if d[k]:
                print(f"     {k:9} {d[k][:66]}")
        print(f"     {'origem':9} {d['origem_autor']}\n")
