#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reconfere na IMAGEM os dados que definem a identidade da obra.

Motivo, com o caso que originou o modulo. O livro "Eu, um Discipulador"
trazia na pagina 3 o ISBN 978-65-01-24846-2. O pdftotext leu
978-65-0*7*-24846-2, que nao fecha o digito verificador. O aplicativo
descartava ISBN invalido em silencio (`if not n: continue`), entao:

  - a ficha registrou "sem ISBN - nao localizado";
  - a CBL nunca foi consultada, porque so se consulta com ISBN valido;
  - o livro parou em revisao por falta de editora, que tambem estava
    escrita na mesma pagina.

Um digito mal lido produziu tres sintomas e nenhum aviso.

DUAS CAMADAS, NESTA ORDEM
-------------------------
1. RELEITURA DIRIGIDA (evidencia).  Renderiza a pagina suspeita em alta
   resolucao e le com o Apple Vision. Foi o que resolveu o caso real: o
   Vision leu "01" onde o pdftotext leu "07".

2. CORRECAO DE UM DIGITO (inferencia).  So quando a imagem tambem nao
   resolve. Enumera as trocas de um digito que fecham o verificador e
   deixa a lista para conferencia. NAO adota sozinha: um ISBN valido e
   existente pode pertencer a outro livro, e ancorar a ficha errada e
   pior do que ficar sem ISBN.

A ordem importa. Ler a pagina e evidencia; enumerar e palpite. No caso
real a enumeracao devolveu dez possibilidades e a leitura devolveu a
resposta.

CUSTO
-----
Renderizar pagina a 400 dpi e caro. Por isso a releitura e DIRIGIDA:
so dispara quando ha sintoma (verificador nao fechou, campo obrigatorio
vazio, fontes discordando) e so nas paginas candidatas, nunca no livro
inteiro.
"""

import os
import re
import subprocess
import sys
import tempfile

DPI_CONFERENCIA = 400        # 300 ja resolve capa; ficha catalografica e
                             # composta em corpo pequeno e pede mais
MAX_PAGINAS_CONFERENCIA = 4  # teto de custo por livro


# ---------------------------------------------------------------------------
# leitura da imagem
# ---------------------------------------------------------------------------

def _auxiliar_vision():
    caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "vision-ocr")
    return caminho if sys.platform == "darwin" and os.path.exists(caminho) else ""


def vision_disponivel():
    return bool(_auxiliar_vision())


def ler_pagina_na_imagem(pdf, pagina, dpi=DPI_CONFERENCIA):
    """Renderiza UMA pagina e devolve o texto lido pelo Vision.

    Devolve "" quando o Vision nao esta disponivel - o chamador entao
    fica com o que o pdftotext deu, que e melhor que nada.
    """
    auxiliar = _auxiliar_vision()
    if not auxiliar:
        return ""
    with tempfile.TemporaryDirectory(prefix="biblio-conferencia-") as td:
        base = os.path.join(td, "p")
        try:
            subprocess.run(
                ["pdftoppm", "-f", str(pagina), "-l", str(pagina),
                 "-r", str(dpi), "-jpeg", "-singlefile", pdf, base],
                capture_output=True, timeout=300)
        except Exception:
            return ""
        imagem = base + ".jpg"
        if not os.path.exists(imagem):
            return ""
        try:
            saida = subprocess.run([auxiliar, imagem], capture_output=True,
                                   text=True, timeout=300)
        except Exception:
            return ""
        return saida.stdout or ""


# ---------------------------------------------------------------------------
# ISBN
# ---------------------------------------------------------------------------

def digitos_isbn(texto):
    return re.sub(r"[^0-9Xx]", "", texto or "")


def _fecha(numero):
    """Verificador do ISBN-13 e do ISBN-10, sem depender do modulo maior."""
    d = digitos_isbn(numero)
    if len(d) == 13 and d.isdigit():
        soma = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(d[:12]))
        return (10 - soma % 10) % 10 == int(d[12])
    if len(d) == 10:
        soma = sum((10 - i) * (10 if c in "Xx" else int(c))
                   for i, c in enumerate(d))
        return soma % 11 == 0
    return False


def candidatos_um_digito(numero):
    """Trocas de UM digito que fazem o verificador fechar.

    Sao poucas - dez, no caso real - e uma delas costuma ser a certa.
    Mantemos apenas prefixos plausiveis de livro (978/979) para nao
    sugerir numeros que nem ISBN seriam.
    """
    d = digitos_isbn(numero)
    if len(d) != 13:
        return []
    saida = []
    for i in range(13):
        for novo in "0123456789":
            if novo == d[i]:
                continue
            candidato = d[:i] + novo + d[i + 1:]
            if candidato.startswith(("978", "979")) and _fecha(candidato):
                saida.append({"isbn": candidato, "posicao": i + 1,
                              "de": d[i], "para": novo})
    return saida


def isbns_no_texto(texto):
    """ISBNs que FECHAM o verificador, na ordem em que aparecem."""
    achados = []
    for m in re.finditer(r"(?:ISBN[^0-9]{0,12})?((?:97[89][\s\-]?)?"
                         r"[\d][\d\s\-–—]{7,20}[\dXx])", texto or "", re.I):
        d = digitos_isbn(m.group(1))
        if len(d) in (10, 13) and _fecha(d) and d not in achados:
            achados.append(d)
    return achados


def isbns_suspeitos_no_texto(texto):
    """Sequencias anunciadas como ISBN que NAO fecham o verificador.

    E a informacao que o aplicativo jogava fora. Ela nao serve como dado,
    mas serve como pista: diz que ha um ISBN impresso ali e que a leitura
    falhou - o que e bem diferente de "este livro nao tem ISBN".
    """
    suspeitos = []
    for m in re.finditer(r"ISBN[^0-9]{0,12}([\d][\d\s\-–—]{7,20}[\dXx])",
                         texto or "", re.I):
        d = digitos_isbn(m.group(1))
        if len(d) in (10, 13) and not _fecha(d) and d not in suspeitos:
            suspeitos.append(d)
    return suspeitos


# ---------------------------------------------------------------------------
# a conferencia propriamente dita
# ---------------------------------------------------------------------------

def conferir_isbn(pdf, texto_pdf, paginas_candidatas=(), pagina_cip=None):
    """Resolve o ISBN quando a leitura de texto falhou.

    Devolve sempre um dicionario com o que foi feito e por que - mesmo
    quando nao resolve. Ausencia com causa registrada e acionavel;
    ausencia muda nao e.

    Chaves:
      isbn        - o numero adotado, ou ""
      origem      - "texto", "imagem" ou "" (nao resolvido)
      motivo      - frase para a ficha e para o operador
      suspeitos   - ISBNs impressos que nao fecham o verificador
      candidatos  - correcoes de um digito, para conferencia humana
      divergencia - texto e imagem discordaram (pode ser erro de impressao)
    """
    r = {"isbn": "", "origem": "", "motivo": "", "suspeitos": [],
         "candidatos": [], "divergencia": "", "paginas_relidas": []}

    validos = isbns_no_texto(texto_pdf)
    if validos:
        r.update(isbn=validos[0], origem="texto",
                 motivo="ISBN lido da camada de texto do PDF")
        return r

    r["suspeitos"] = isbns_suspeitos_no_texto(texto_pdf)

    # --- camada 1: reler a imagem (evidencia) ------------------------------
    paginas = list(dict.fromkeys(
        [p for p in ([pagina_cip] if pagina_cip else []) + list(paginas_candidatas)
         if p]))[:MAX_PAGINAS_CONFERENCIA]

    if vision_disponivel() and paginas:
        for numero in paginas:
            texto_imagem = ler_pagina_na_imagem(pdf, numero)
            if not texto_imagem:
                continue
            r["paginas_relidas"].append(numero)
            lidos = isbns_no_texto(texto_imagem)
            if not lidos:
                continue
            r["isbn"] = lidos[0]
            r["origem"] = "imagem"
            r["motivo"] = (f"ISBN lido na imagem da pagina {numero}; "
                           f"a camada de texto do PDF nao tinha ISBN valido")
            if r["suspeitos"]:
                impresso = r["suspeitos"][0]
                if impresso != lidos[0]:
                    r["motivo"] += (f". O texto do PDF trazia {impresso}, "
                                    f"que nao fecha o digito verificador")
                    # Guardamos os dois: quase sempre e erro de OCR, mas
                    # existe livro impresso com ISBN errado, e so o
                    # registro permite perceber isso depois.
                    r["divergencia"] = f"texto={impresso} imagem={lidos[0]}"
            return r

    # --- camada 2: correcao de um digito (inferencia, nao adotada) ---------
    for suspeito in r["suspeitos"]:
        r["candidatos"] += candidatos_um_digito(suspeito)

    if r["candidatos"]:
        r["motivo"] = (
            f"ISBN impresso ({r['suspeitos'][0]}) nao fecha o digito "
            f"verificador e a imagem nao resolveu. "
            f"{len(r['candidatos'])} correcoes de um digito sao possiveis - "
            f"conferir na fonte antes de adotar")
    elif r["suspeitos"]:
        r["motivo"] = (f"ISBN impresso ({r['suspeitos'][0]}) ilegivel: nao "
                       f"fecha o verificador e nenhuma troca de um digito o "
                       f"corrige")
    else:
        # Esta e a distincao que faltava: nao ter ISBN e legitimo em obra
        # anterior a 1970; nao conseguir ler e um defeito que se conserta.
        r["motivo"] = "nenhum ISBN impresso foi localizado nas paginas lidas"
    return r


def conferir_campo_na_imagem(pdf, pagina, padrao, grupo=1):
    """Reconfere UM campo na imagem, por expressao regular.

    Serve para titulo, autor e editora quando a leitura de texto ficou
    vazia ou implausivel. Devolve "" se nao encontrar.
    """
    texto = ler_pagina_na_imagem(pdf, pagina)
    if not texto:
        return ""
    m = re.search(padrao, texto, re.I | re.M)
    return " ".join(m.group(grupo).split()) if m else ""
