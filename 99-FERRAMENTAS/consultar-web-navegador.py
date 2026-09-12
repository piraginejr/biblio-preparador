#!/usr/bin/env python3
"""Pesquisa bibliografica assistida por navegador, sem alterar o catalogo.

Usa uma instancia separada do Chrome, sem login. A pagina de resultados serve
somente para localizar fontes; o texto do Google nunca e tratado como prova.
Interrompe ao detectar verificacao/CAPTCHA e preserva cada consulta em cache.
"""

import argparse
from collections import Counter
import hashlib
import json
import pathlib
import re
import time
import unicodedata
from datetime import datetime
from urllib.parse import parse_qs, quote_plus, urlparse

from playwright.sync_api import sync_playwright


INTERVALO = 8
MAX_RESULTADOS = 5
DOMINIOS_IGNORADOS = {
    "google.com", "www.google.com", "accounts.google.com",
    "support.google.com", "policies.google.com",
    "duckduckgo.com", "www.duckduckgo.com",
}
CACHE_VERSAO = 16

PLACEHOLDERS_ESTANTE = (
    "procurando titulo perfeito", "descobrindo autor",
    "carregando sinopse", "localizando ano",
)

PALAVRAS_VAZIAS_TITULO = {
    "a", "as", "o", "os", "um", "uma", "de", "da", "das", "do", "dos",
    "e", "em", "para", "por", "the", "of", "and", "for", "la", "las",
    "el", "los", "del", "y", "le", "les", "des", "du", "et",
}


def agora():
    return datetime.now().isoformat(timespec="seconds")


def normalizar(valor):
    valor = unicodedata.normalize("NFKD", str(valor or ""))
    valor = "".join(c for c in valor if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", valor.lower()))


def similaridade(a, b):
    aa, bb = set(normalizar(a).split()), set(normalizar(b).split())
    return len(aa & bb) / max(1, len(aa | bb))


def similaridade_titulo(a, b):
    aa, bb = set(normalizar(a).split()), set(normalizar(b).split())
    if not aa or not bb:
        return 0.0
    jaccard = len(aa & bb) / len(aa | bb)
    menor = min(len(aa), len(bb))
    cobertura_menor = len(aa & bb) / menor
    # Titulo local pode estar truncado ("Crítica Textual") e o marketplace
    # trazer a forma completa. Autor/consenso ainda sera exigido abaixo.
    return max(jaccard, cobertura_menor * (0.95 if menor >= 2 else 0.70))


def palavras_chave_titulo(valor):
    return [p for p in normalizar(valor).split()
            if p not in PALAVRAS_VAZIAS_TITULO and len(p) >= 3]


def titulo_pesquisavel(valor):
    """Evita enviar ao comercio trechos de OCR e nomes tecnicos como titulos."""
    bruto = " ".join(str(valor or "").split()).strip()
    normal = normalizar(bruto)
    palavras = normal.split()
    if len(palavras_chave_titulo(bruto)) < 2:
        return False
    if len(bruto) > 180 or len(palavras) > 18:
        return False
    if re.search(r"(?i)(?:\.(?:docx?|indd|pdf)\b|\b(?:docx?|indd|pdf)\s*$|\w+\.org\b)", bruto):
        return False
    if re.match(r"(?i)^(?:microsoft\s+word\s*[-:]|subject\s*:|resumo\s*:)", bruto):
        return False
    if re.match(r"(?i)^\s*(?:sum[aá]rio|[ií]ndice|table\s+of\s+contents)\b", bruto):
        return False
    if (len(re.findall(r"(?i)\b(?:cap[ií]tulo|parte|se[çc][aã]o)\s+\d+", bruto)) >= 2
            or len(re.findall(r"\.{3,}\s*\d+", bruto)) >= 2):
        return False
    if re.fullmatch(r"(?i)livro\s+\d+", bruto):
        return False
    if bruto.startswith("=") or ".." in bruto:
        return False
    if (len(palavras) >= 10 and bruto.endswith(".")
            and re.match(r"(?i)^(?:este|esta|essa|quando|porque|durante|"
                         r"anos?|assim|portanto|segundo|apesar)\b", bruto)):
        return False
    if (sum(len(p) == 1 for p in palavras) >= 3
            or re.search(r"\b[A-ZÀ-Ü]\s+[A-ZÀ-Ü]\s+[A-ZÀ-Ü]\b", bruto)):
        return False
    if re.search(r"(?i)\b(?:de|da|do|das|dos|of|the|del|la)\s*$", bruto):
        return False
    chaves = palavras_chave_titulo(bruto)
    if len(set(chaves)) / len(chaves) < 0.70:
        return False
    return True


def titulo_confere_por_palavras_chave(alvo, candidato):
    """Identidade por termos obrigatorios; nao por media de similaridade."""
    chaves = set(palavras_chave_titulo(alvo))
    palavras = set(normalizar(candidato).split())
    return len(chaves) >= 2 and chaves <= palavras


def resultado_estante_valido(item):
    """Descarta os esqueletos exibidos enquanto a busca ainda carrega."""
    campos = " ".join(str(item.get(k, "")) for k in
                       ("titulo_resultado", "autor", "ano", "trecho"))
    normal = normalizar(campos)
    titulo = normalizar(item.get("titulo_resultado", ""))
    return (len(palavras_chave_titulo(titulo)) >= 2
            and not any(marcador in normal for marcador in PLACEHOLDERS_ESTANTE))


def isbn13_para10(isbn):
    numero = re.sub(r"\D", "", isbn or "")
    if len(numero) != 13 or not numero.startswith("978"):
        return ""
    base = numero[3:12]
    resto = sum((10 - i) * int(n) for i, n in enumerate(base)) % 11
    digito = (11 - resto) % 11
    return base + ("X" if digito == 10 else str(digito))


def isbn10_para13(isbn):
    numero = re.sub(r"[^0-9Xx]", "", isbn or "").upper()
    if len(numero) != 10:
        return ""
    base = "978" + numero[:9]
    soma = sum(int(n) * (1 if i % 2 == 0 else 3)
               for i, n in enumerate(base))
    return base + str((10 - soma % 10) % 10)


def formas_isbn(isbn):
    """Retorna a mesma edição em ISBN-13 e ISBN-10, nessa ordem."""
    numero = re.sub(r"[^0-9Xx]", "", isbn or "").upper()
    if len(numero) == 13:
        formas = [numero, isbn13_para10(numero)]
    elif len(numero) == 10:
        formas = [isbn10_para13(numero), numero]
    else:
        formas = []
    return [x for x in dict.fromkeys(formas) if x]


def isbn_equivalente(a, b):
    aa, bb = set(formas_isbn(a)), set(formas_isbn(b))
    return bool(aa and bb and aa & bb)


def autor_natural(autor):
    autor = " ".join(str(autor or "").split()).strip()
    if "," in autor:
        sobrenome, nomes = [x.strip() for x in autor.split(",", 1)]
        return f"{nomes} {sobrenome}".strip()
    return autor


def sobrenome_autor(autor):
    autor = " ".join(str(autor or "").split()).strip()
    if not autor:
        return ""
    return (autor.split(",", 1)[0].strip() if "," in autor
            else autor.split()[-1].strip())


def retirar_autor_do_titulo(titulo, autor):
    """Remove autoria anexada ao início/fim do título por OCR ou arquivo."""
    titulo = " ".join(str(titulo or "").split()).strip(" -_|,;")
    natural = autor_natural(autor)
    variantes = [natural, autor, sobrenome_autor(autor)]
    for variante in variantes:
        variante = " ".join(str(variante or "").split()).strip()
        if len(normalizar(variante).split()) < 2 and variante != sobrenome_autor(autor):
            continue
        if len(variante) < 4:
            continue
        titulo = re.sub(rf"(?i)^\s*{re.escape(variante)}\s*[-:|,]?\s*", "", titulo)
        titulo = re.sub(rf"(?i)\s*[-:|,]?\s*{re.escape(variante)}\s*$", "", titulo)
    return " ".join(titulo.split()).strip(" -_|,;")


def limpar_titulo_consulta(titulo, autor=""):
    titulo = " ".join(str(titulo or "").replace("_", " ").split())
    titulo = re.sub(r"(?i)\.(?:pdf|docx?|indd)\s*$", "", titulo)
    titulo = re.sub(r"^\s*\d{6,12}[-_ ]+", "", titulo)
    titulo = retirar_autor_do_titulo(titulo, autor)
    return titulo if titulo_pesquisavel(titulo) else ""


def titulo_principal(titulo, subtitulo=""):
    titulo = " ".join(str(titulo or "").split()).strip()
    subtitulo = " ".join(str(subtitulo or "").split()).strip()
    if subtitulo:
        titulo = re.sub(rf"(?i)\s*[:\-–—]\s*{re.escape(subtitulo)}\s*$", "", titulo)
    principal = re.split(r"\s*:\s+|\s+[–—-]\s+", titulo, maxsplit=1)[0]
    return principal.strip(" -:;,") or titulo


def titulo_distintivo(titulo, max_palavras=6):
    """Versão curta, preservando a ordem das palavras mais distintivas."""
    palavras = re.findall(r"[A-Za-zÀ-ÿ0-9]+", str(titulo or ""))
    elegiveis = []
    vistos = set()
    for indice, palavra in enumerate(palavras):
        chave = normalizar(palavra)
        if (not chave or chave in PALAVRAS_VAZIAS_TITULO or len(chave) < 4
                or chave in vistos):
            continue
        vistos.add(chave)
        elegiveis.append((indice, palavra, len(chave)))
    escolhidas = sorted(elegiveis, key=lambda x: (-x[2], x[0]))[:max_palavras]
    return " ".join(x[1] for x in sorted(escolhidas))


def montar_consulta(titulo, autor):
    partes = [f'"{titulo.strip()}"']
    if autor.strip():
        natural = autor.strip()
        if "," in natural:
            sobrenome, nomes = [x.strip() for x in natural.split(",", 1)]
            natural = f"{nomes} {sobrenome}".strip()
        partes.append(f'"{natural}"')
    partes.extend(["editora", "ano", "ISBN"])
    return " ".join(partes)


def montar_consulta_titulo(titulo):
    return f'"{titulo.strip()}" editora autor ano ISBN'


def montar_consultas_comerciais(alvo):
    """Consultas progressivas, da identidade exata à pista mais ampla."""
    consultas = []
    if alvo.get("isbn") and alvo.get("isbn_confirmado", True):
        consultas.extend(formas_isbn(alvo["isbn"]))
    autor = sobrenome_autor(alvo.get("autor", ""))
    completo = limpar_titulo_consulta(alvo.get("titulo", ""),
                                      alvo.get("autor", ""))
    principal = titulo_principal(completo, alvo.get("subtitulo", ""))
    distintivo = titulo_distintivo(principal)
    consultas.extend([
        " ".join(x for x in (completo, autor) if x).strip(),
        " ".join(x for x in (principal, autor) if x).strip(),
        " ".join(x for x in (distintivo, autor) if x).strip(),
        principal,
    ])
    return list(dict.fromkeys(x for x in consultas if x))


def slug_estante(valor):
    """Formato usado pela busca publica da Estante Virtual."""
    return "-".join(normalizar(valor).split())


def bloqueado(page):
    texto = (page.title() + " " + page.locator("body").inner_text()).lower()
    marcadores = (
        "nossos sistemas detectaram tráfego incomum", "unusual traffic",
        "confirme que você não é um robô", "verify you are human",
        "recaptcha", "/sorry/", "anomaly-modal", "challenge-form",
        "amazon.com.br algo deu errado", "digite os caracteres que você vê",
    )
    return any(x in texto or x in page.url.lower() for x in marcadores)


def _url_direta(url):
    consulta = parse_qs(urlparse(url).query)
    return consulta.get("uddg", [url])[0]


def extrair_resultados(page, limite=MAX_RESULTADOS, motor="duckduckgo"):
    if motor == "estante":
        candidatos = page.locator(
            ".product-item, [data-testid*='product-card'], article:has(a[href])"
        ).evaluate_all("""
            els => els.map((bloco, indice) => ({
              titulo: (bloco.querySelector(
                '.product-item__name, [data-testid*="title"], h2, h3'
              )?.innerText || '').trim(),
              autor: (bloco.querySelector(
                '.product-item__author, [data-testid*="author"]'
              )?.innerText || '').trim(),
              ano: (bloco.querySelector(
                '.product-item__year, [data-testid*="year"]'
              )?.innerText || '').trim(),
              trecho: (bloco.querySelector('.product-item__description__text')?.innerText || '').trim(),
              url: (bloco.querySelector(
                'a.product-item__link[href], a[href*="/livro/"], '
                + 'a[href*="/produto/"], a[href*="/p/"] , a[href]'
              )?.href || '')
            }))
        """)
    elif motor == "amazon":
        candidatos = page.locator(
            'div[data-asin]:has(h2)'
        ).evaluate_all("""
            els => els.map(bloco => {
              const h2 = bloco.querySelector('h2');
              const a = h2?.closest('a') || h2?.querySelector('a') ||
                        bloco.querySelector('a.a-link-normal[href*="/dp/"]');
              return {
                titulo: (bloco.querySelector('h2')?.innerText || '').trim(),
                url: a?.href || '',
                trecho: (bloco.innerText || '').trim().slice(0, 1200)
              };
            })
        """)
    elif motor == "duckduckgo":
        candidatos = page.locator("a.result__a").evaluate_all("""
            els => els.map(a => {
              const bloco = a.closest('.result');
              return {
                titulo: (a.innerText || '').trim(),
                url: a.href || '',
                trecho: (bloco?.querySelector('.result__snippet')?.innerText ||
                         bloco?.innerText || '').trim().slice(0, 1200)
              };
            })
        """)
    else:
        candidatos = page.locator("#search a:has(h3)").evaluate_all("""
        els => els.map(a => {
          const bloco = a.closest('.MjjYud') || a.parentElement?.parentElement;
          return {
            titulo: (a.querySelector('h3')?.innerText || '').trim(),
            url: a.href || '',
            trecho: (bloco?.innerText || '').trim().slice(0, 1200)
          };
        })
        """)
    saida, vistos = [], set()
    for item in candidatos:
        url = _url_direta(item.get("url", ""))
        dominio = urlparse(url).netloc.lower()
        if (not url.startswith("http") or dominio in DOMINIOS_IGNORADOS
                or url in vistos or not item.get("titulo")):
            continue
        vistos.add(url)
        resultado = {
            "titulo_resultado": item["titulo"], "url": url,
            "dominio": dominio, "trecho": item.get("trecho", ""),
            "autor": item.get("autor", ""), "ano": item.get("ano", ""),
        }
        if motor == "estante" and not resultado_estante_valido(resultado):
            continue
        saida.append(resultado)
        if len(saida) >= limite:
            break
    return saida


def extrair_facetas_estante(page):
    """Le os totais editoriais expostos pela propria pagina de busca."""
    secoes = page.locator("section.filter-box").evaluate_all("""
      els => els.map(secao => ({
        nome: (secao.querySelector('h3')?.innerText || '').trim(),
        valores: [...secao.querySelectorAll('.filter-box__label')].map(el =>
          (el.innerText || '').trim())
      }))
    """)
    saida = {}
    for secao in secoes:
        valores = []
        for bruto in secao.get("valores", []):
            m = re.match(r"\s*(.*?)\s*\((\d+)\)\s*$", bruto, re.S)
            if m:
                valores.append({"valor": " ".join(m.group(1).split()),
                                "quantidade": int(m.group(2))})
        if secao.get("nome") and valores:
            saida[normalizar(secao["nome"])] = valores
    return saida


def _consenso(valores, minimo=2, fracao=0.60):
    limpos = [" ".join(str(v).split()) for v in valores if str(v).strip()]
    if not limpos:
        return "", 0
    contagem = Counter(normalizar(v) for v in limpos)
    chave, quantidade = contagem.most_common(1)[0]
    exemplar = next(v for v in limpos if normalizar(v) == chave)
    if quantidade >= minimo and quantidade / len(limpos) >= fracao:
        return exemplar, quantidade
    return "", quantidade


def _campo_candidato(candidato, *nomes):
    return next((str(candidato.get(nome, "")).strip() for nome in nomes
                 if str(candidato.get(nome, "")).strip()), "")


def _numero_editorial(valor):
    m = re.search(r"(?<!\d)(\d{1,4})(?!\d)", str(valor or ""))
    return str(int(m.group(1))) if m else ""


def _ano(valor):
    m = re.search(r"\b((?:18|19|20)\d{2})\b", str(valor or ""))
    return m.group(1) if m else ""


def _paginas(valor):
    m = re.search(r"\b(\d{1,5})\s*(?:p(?:ag(?:ina)?s?)?\.?|pp\b)",
                  str(valor or ""), re.I)
    if not m:
        m = re.fullmatch(r"\s*(\d{1,5})\s*", str(valor or ""))
    return int(m.group(1)) if m else 0


def avaliar_correspondencia(alvo, candidato):
    """Pontua identidade da edição e explica confirmações e rejeições."""
    titulo_alvo = titulo_principal(alvo.get("titulo", ""),
                                   alvo.get("subtitulo", ""))
    titulo_candidato = _campo_candidato(
        candidato, "titulo", "titulo_pagina", "titulo_resultado")
    autor_alvo = sobrenome_autor(alvo.get("autor", ""))
    autor_candidato = _campo_candidato(
        candidato, "autores", "autor", "autoria_pagina", "trecho")
    st = similaridade_titulo(titulo_alvo, titulo_candidato)
    autor_ok = bool(autor_alvo and
                    normalizar(autor_alvo) in normalizar(autor_candidato))
    confirmacoes, rejeicoes, bloqueios = [], [], []

    isbns_alvo = formas_isbn(alvo.get("isbn", ""))
    isbns_candidato = []
    for campo in ("isbn", "isbn_13", "isbn_10"):
        isbns_candidato.extend(formas_isbn(candidato.get(campo, "")))
    asin = re.search(r"/dp/([A-Z0-9]{10})(?:[/?]|$)",
                     candidato.get("url", ""), re.I)
    if asin:
        isbns_candidato.extend(formas_isbn(asin.group(1)))
    isbns_candidato = list(dict.fromkeys(isbns_candidato))
    isbn_exato = bool(set(isbns_alvo) & set(isbns_candidato))
    if isbns_alvo and isbns_candidato:
        if isbn_exato:
            confirmacoes.append("ISBN exato")
        else:
            bloqueios.append("ISBN diferente")

    if normalizar(titulo_alvo) == normalizar(titulo_candidato):
        confirmacoes.append("título principal confirmado")
    elif st >= 0.68:
        confirmacoes.append("título truncado ou subtítulo diferente")
    elif not titulo_candidato:
        rejeicoes.append("anúncio sem metadados de título")
    else:
        rejeicoes.append("título divergente")
    if autor_ok:
        confirmacoes.append("autor confirmado")
    elif autor_alvo and autor_candidato:
        rejeicoes.append("autor não encontrado")
    elif autor_alvo:
        rejeicoes.append("anúncio sem metadados de autor")

    for campo, rotulo in (("edicao", "edição"), ("volume", "volume")):
        esperado = _numero_editorial(alvo.get(campo, ""))
        encontrado = _numero_editorial(candidato.get(campo, ""))
        if esperado and encontrado:
            if esperado == encontrado:
                confirmacoes.append(f"{rotulo} confirmada")
            else:
                bloqueios.append(f"{rotulo} diferente")
    ano_alvo = _ano(alvo.get("ano", "") or alvo.get("data", ""))
    ano_candidato = _ano(candidato.get("ano", "") or
                         candidato.get("data_publicacao", ""))
    ano_ok = bool(ano_alvo and ano_candidato and ano_alvo == ano_candidato)
    if ano_ok:
        confirmacoes.append("ano confirmado")

    paginas_alvo = _paginas(alvo.get("paginas", "") or
                            alvo.get("paginas_pdf", ""))
    paginas_candidato = _paginas(candidato.get("paginas", "") or
                                 candidato.get("trecho", ""))
    paginas_ok = bool(paginas_alvo and paginas_candidato and
                      abs(paginas_alvo - paginas_candidato) /
                      max(paginas_alvo, paginas_candidato) <= 0.12)
    if paginas_ok:
        confirmacoes.append("paginação próxima")

    pontos = 0.52 * st + (0.38 if autor_ok else 0)
    if st >= 0.90:
        pontos += 0.04
    pontos += 0.08 if ano_ok else 0
    pontos += 0.06 if paginas_ok else 0
    pontos += 0.03 * sum(x.endswith("confirmada") for x in confirmacoes)
    if isbn_exato:
        pontos = max(1.0, pontos)
    pontos = round(min(1.15, pontos), 3)
    aprovado = not bloqueios and (isbn_exato or
        (st >= 0.68 and (autor_ok or not autor_alvo) and pontos >= 0.68))
    if not aprovado and not bloqueios and not rejeicoes:
        rejeicoes.append("resultado possivelmente correto, mas insuficiente")
    elif not aprovado and not bloqueios and st >= 0.60:
        rejeicoes.append("resultado possivelmente correto, mas insuficiente")
    return {
        "pontuacao": pontos, "aprovado": aprovado,
        "isbn_exato": isbn_exato, "titulo_similaridade": round(st, 3),
        "autor_confirmado": autor_ok, "confirmacoes": confirmacoes,
        "bloqueios": list(dict.fromkeys(bloqueios)),
        "motivos_rejeicao": list(dict.fromkeys(rejeicoes + bloqueios)),
    }


def avaliar_resultados(alvo, resultados):
    avaliados = []
    for resultado in resultados:
        item = dict(resultado)
        item["avaliacao"] = avaliar_correspondencia(alvo, item)
        avaliados.append(item)
    avaliados.sort(key=lambda x: x["avaliacao"]["pontuacao"], reverse=True)
    return avaliados


def candidato_suficientemente_confiavel(alvo, resultados):
    avaliados = avaliar_resultados(alvo, resultados)
    if not avaliados or not avaliados[0]["avaliacao"]["aprovado"]:
        return False
    melhor = avaliados[0]
    avaliacao = melhor["avaliacao"]
    if (alvo.get("isbn") and alvo.get("isbn_confirmado")
            and not avaliacao["isbn_exato"]):
        return False
    if not avaliacao["isbn_exato"]:
        for campo in ("edicao", "volume"):
            if _numero_editorial(alvo.get(campo, "")) and not _numero_editorial(
                    melhor.get(campo, "")):
                return False
    return True


def registrar_rejeicoes(alvo, resultados):
    rejeitados = []
    for item in avaliar_resultados(alvo, resultados):
        avaliacao = item["avaliacao"]
        if avaliacao["aprovado"]:
            continue
        rejeitados.append({
            "titulo": _campo_candidato(
                item, "titulo", "titulo_pagina", "titulo_resultado"),
            "url": item.get("url", ""),
            "pontuacao": avaliacao["pontuacao"],
            "motivos": avaliacao["motivos_rejeicao"],
            "bloqueios": avaliacao["bloqueios"],
        })
    return rejeitados


def escolher_candidato_estante(alvo, resultados, facetas=None, paginas_pdf=""):
    """Concilia anúncios; ISBN exato permite confirmação individual."""
    correspondentes = []
    sobrenome = normalizar(alvo.get("autor", "").split(",", 1)[0])
    for resultado in resultados:
        avaliacao = avaliar_correspondencia(alvo, resultado)
        titulo_ok = titulo_confere_por_palavras_chave(
            alvo.get("titulo"), resultado.get("titulo_resultado"))
        st = similaridade_titulo(alvo.get("titulo"),
                                 resultado.get("titulo_resultado"))
        autor_texto = normalizar(resultado.get("autor") or resultado.get("trecho"))
        autor_ok = bool(sobrenome and sobrenome in autor_texto)
        pontos = avaliacao["pontuacao"]
        if (titulo_ok or st >= 0.68 or avaliacao["isbn_exato"]):
            item = dict(resultado)
            item["pontuacao"] = round(pontos, 3)
            item["autor_alvo_confere"] = autor_ok
            item["avaliacao"] = avaliacao
            correspondentes.append(item)

    isbn_exatos = [x for x in correspondentes
                   if x["avaliacao"]["isbn_exato"]
                   and not x["avaliacao"]["bloqueios"]]

    autores = [x.get("autor", "") for x in correspondentes]
    autor_consenso, votos_autor = _consenso(autores)
    if isbn_exatos:
        exatos = isbn_exatos
    elif sobrenome:
        confirmados = [x for x in correspondentes if x["autor_alvo_confere"]]
        if confirmados:
            exatos = confirmados
        elif autor_consenso and votos_autor >= 2:
            na = normalizar(autor_consenso)
            exatos = [x for x in correspondentes
                      if normalizar(x.get("autor")) == na]
        else:
            exatos = []
    else:
        exatos = correspondentes if autor_consenso and votos_autor >= 2 else []
    if not exatos:
        return {}, 0.0

    melhor = max(exatos, key=lambda x: x["pontuacao"])
    anos = [x.get("ano", "") for x in exatos]
    paginas = []
    for item in exatos:
        m = re.search(r"\b(\d{1,5})\s*(?:p(?:ag(?:ina)?s?)?\.?|pp\b)",
                      item.get("trecho", ""), re.I)
        if m:
            paginas.append(m.group(1))
    ano, votos_ano = _consenso(anos)
    n_paginas, votos_paginas = _consenso(paginas)

    editora = ""
    votos_editora = 0
    facetas = facetas or {}
    editoras = facetas.get("editora", [])
    if editoras:
        # A busca pode trazer obras relacionadas. Uma editora com muito mais
        # ocorrencias que os titulos exatos pertence ao ruido (no teste,
        # Appris 7 contra apenas 4 exemplares Cogeime da obra procurada).
        plausiveis = [x for x in editoras
                      if 2 <= x["quantidade"]
                      and x["quantidade"] >= len(exatos) * 0.60
                      and x["quantidade"] <= max(len(exatos) + 1,
                                                 len(exatos) * 1.20)]
        topo = max(plausiveis, key=lambda x: x["quantidade"], default=None)
        if topo:
            editora, votos_editora = topo["valor"], topo["quantidade"]

    detalhes = {
        "titulo": melhor.get("titulo_resultado", ""),
        "autores": (melhor.get("autores") or autor_consenso or
                     melhor.get("autor", "")),
        "editora": melhor.get("editora") or editora,
        "ano": melhor.get("ano") or ano,
        "edicao": melhor.get("edicao", ""),
        "volume": melhor.get("volume", ""),
        "isbn": (melhor.get("isbn") or melhor.get("isbn_13") or
                 melhor.get("isbn_10", "")),
        "paginas": melhor.get("paginas") or n_paginas,
        "fonte": ("Estante Virtual (ISBN exato no anúncio)" if isbn_exatos
                  else "Estante Virtual (consenso de anúncios)"),
        "url": melhor.get("url", "").split("#", 1)[0],
        "anuncios_exatos": len(exatos),
        "votos": {"autor": votos_autor, "ano": votos_ano, "editora": votos_editora,
                  "paginas": votos_paginas},
        "confianca": ("alta" if isbn_exatos or len(exatos) >= 2
                      else "auxiliar"),
        "avaliacao": melhor.get("avaliacao", {}),
    }
    return detalhes, round(max(x["pontuacao"] for x in exatos), 3)


def escolher_candidato_amazon(alvo, resultados):
    preparados = []
    for resultado in resultados:
        item = dict(resultado)
        asin = (re.search(r"/dp/([A-Z0-9]{10})", resultado.get("url", ""), re.I)
                or [None, ""])[1].upper()
        if asin:
            item.setdefault("isbn_10", asin)
        item["avaliacao"] = avaliar_correspondencia(alvo, item)
        preparados.append(item)
    preparados.sort(key=lambda x: x["avaliacao"]["pontuacao"], reverse=True)
    if not preparados or not preparados[0]["avaliacao"]["aprovado"]:
        return {}, 0.0
    return preparados[0], preparados[0]["avaliacao"]["pontuacao"]


def extrair_detalhes_amazon(page):
    seletores = [
        "#detailBullets_feature_div",
        "#productDetails_detailBullets_sections1",
        "#productDetails_techSpec_section_1",
    ]
    partes = []
    for seletor in seletores:
        loc = page.locator(seletor)
        if loc.count():
            partes.append(loc.first.inner_text())
    bruto = "\n".join(partes)
    limpo = bruto.replace("\u200e", "").replace("\u200f", "")
    campos = {}
    rotulos = {
        "editora": r"(?im)^\s*(?:Editora|Publisher)\s*:\s*(.+)$",
        "data_publicacao": r"(?im)^\s*(?:Data da publica[çc][aã]o|Publication date)\s*:\s*(.+)$",
        "idioma": r"(?im)^\s*(?:Idioma|Language)\s*:\s*(.+)$",
        "paginas": r"(?im)^\s*(?:Capa comum|Livro de bolso|N[uú]mero de p[aá]ginas|Paperback|Hardcover|Print length)\s*:\s*(.+)$",
        "isbn_10": r"(?im)^\s*ISBN-10\s*:\s*([0-9Xx-]+)",
        "isbn_13": r"(?im)^\s*ISBN-13\s*:\s*([0-9Xx-]+)",
        "edicao": r"(?im)^\s*(?:Edi[çc][aã]o|Edition)\s*:\s*(.+)$",
        "volume": r"(?im)^\s*Volume\s*:\s*(.+)$",
    }
    for campo, padrao in rotulos.items():
        achado = re.search(padrao, limpo)
        campos[campo] = achado.group(1).strip() if achado else ""
    campos.update({
        "titulo_pagina": (page.locator("#productTitle").first.inner_text().strip()
                          if page.locator("#productTitle").count() else ""),
        "autoria_pagina": (page.locator("#bylineInfo").first.inner_text().strip()
                           if page.locator("#bylineInfo").count() else ""),
        "url": page.url, "detalhes_brutos": limpo[:4000],
    })
    return campos


def extrair_detalhes_estante_texto(texto, url="", titulo=""):
    """Extrai campos rotulados da página individual de um anúncio."""
    texto = str(texto or "").replace("\u200e", "").replace("\u200f", "")
    padroes = {
        "isbn": r"(?im)^\s*ISBN(?:-1[03])?\s*[:\-]?\s*([0-9Xx -]{10,20})\s*$",
        "editora": r"(?im)^\s*(?:Editora|Publisher)\s*[:\-]\s*(.{2,100})$",
        "ano": r"(?im)^\s*(?:Ano|Ano de publica[çc][aã]o|Publica[çc][aã]o)\s*[:\-]\s*((?:18|19|20)\d{2})\s*$",
        "edicao": r"(?im)^\s*Edi[çc][aã]o\s*[:\-]\s*([^\n]{1,60})$",
        "paginas": r"(?im)^\s*(?:P[aá]ginas|N[uú]mero de p[aá]ginas)\s*[:\-]\s*(\d{1,5})\s*$",
        "autores": r"(?im)^\s*(?:Autor(?:es)?|Por)\s*[:\-]\s*([^\n]{3,120})$",
        "volume": r"(?im)^\s*Volume\s*[:\-]\s*([^\n]{1,40})$",
    }
    dados = {"titulo_resultado": " ".join(str(titulo or "").split()),
             "url": url, "detalhes_brutos": texto[:6000]}
    for campo, padrao in padroes.items():
        m = re.search(padrao, texto)
        dados[campo] = " ".join(m.group(1).split()) if m else ""
    return dados


def _objetos_jsonld(valor):
    if isinstance(valor, dict):
        yield valor
        for item in valor.get("@graph", []):
            yield from _objetos_jsonld(item)
    elif isinstance(valor, list):
        for item in valor:
            yield from _objetos_jsonld(item)


def extrair_detalhes_estante(page):
    corpo = page.locator("body").inner_text()
    titulo = ""
    for seletor in ("h1", "[data-testid*='title']", ".product-name"):
        loc = page.locator(seletor)
        if loc.count():
            titulo = loc.first.inner_text().strip()
            if titulo:
                break
    dados = extrair_detalhes_estante_texto(corpo, page.url, titulo)
    try:
        blocos = page.locator("script[type='application/ld+json']").all_text_contents()
    except Exception:
        blocos = []
    for bloco in blocos:
        try:
            objetos = list(_objetos_jsonld(json.loads(bloco)))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        for obj in objetos:
            tipo = str(obj.get("@type", "")).lower()
            if tipo not in {"book", "product"}:
                continue
            autores = obj.get("author", "")
            if isinstance(autores, dict):
                autores = autores.get("name", "")
            elif isinstance(autores, list):
                autores = "; ".join(
                    x.get("name", "") if isinstance(x, dict) else str(x)
                    for x in autores)
            editora = obj.get("publisher", "")
            if isinstance(editora, dict):
                editora = editora.get("name", "")
            estruturados = {
                "titulo_resultado": obj.get("name", ""),
                "autores": autores, "editora": editora,
                "isbn": obj.get("isbn", ""),
                "ano": obj.get("datePublished", ""),
                "paginas": obj.get("numberOfPages", ""),
            }
            for campo, valor in estruturados.items():
                if valor and not dados.get(campo):
                    dados[campo] = " ".join(str(valor).split())
    return dados


def isbn_confirmado_para_pesquisa(ficha, evidencias):
    isbn = ficha.get("isbn", "")
    if not isbn:
        return False
    if ficha.get("isbn_confirmado_na_edicao") is True:
        return True
    if any(isbn_equivalente(isbn, x) for x in re.findall(
            r"(?:97[89][0-9Xx -]{10,20}|[0-9][0-9Xx -]{8,16}[0-9Xx])",
            ficha.get("isbn_codigo_barras", ""))):
        return True
    motivo = normalizar(ficha.get("isbn_motivo", ""))
    if any(x in motivo for x in ("codigo de barras", "pagina bibliografica",
                                 "ficha catalografica", "cip")):
        return True
    for candidato in evidencias.get("isbn_candidatos", []) or []:
        if (isbn_equivalente(isbn, candidato.get("isbn", ""))
                and candidato.get("origem") in
                {"codigo de barras", "pagina bibliografica"}):
            return True
    return False


def carregar_alvos(raiz, limite, arquivos=None, motor="", atualizar=False):
    catalogo = json.loads((raiz / "_controle" / "catalogo-local.json").read_text(
        encoding="utf-8"))
    alvos = []
    for registro in catalogo.get("livros", {}).values():
        if registro.get("estado") not in {"analisado", "conflito"}:
            continue
        ficha_path = raiz / registro.get("metadados", "")
        try:
            ficha = json.loads(ficha_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if ficha.get("tipo_documento", "livro") != "livro":
            continue
        idioma = ficha.get("idioma", "")
        if motor == "estante" and idioma == "eng":
            continue
        titulo, autor = ficha.get("titulo", ""), ficha.get("nmAutor0", "")
        evidencias = (ficha.get("evidencias") or ficha.get("_evidencias") or {})
        capa = evidencias.get("capa", {}) or {}
        cip = evidencias.get("cip", {}) or {}
        api = evidencias.get("api", {}) or {}
        candidatos_autor = [cip.get("autor", ""), capa.get("nmAutor0", ""),
                             api.get("autores", ""), autor]
        autor = next((x for x in candidatos_autor
                      if palavras_chave_titulo(x.replace(",", " "))), autor)
        candidatos_titulo = [
            cip.get("titulo", ""),
            capa.get("titulo", ""),
            api.get("titulo", ""),
            (evidencias.get("titulo_paginas", {}) or {}).get("titulo", ""),
            titulo,
            (evidencias.get("metadados_pdf", {}) or {}).get("titulo", ""),
            evidencias.get("titulo_nome_arquivo", ""),
        ]
        titulos_limpos = [limpar_titulo_consulta(x, autor)
                          for x in candidatos_titulo]
        titulo = next((x for x in titulos_limpos if x), "")
        if not titulo:
            continue
        isbn_confirmado = isbn_confirmado_para_pesquisa(ficha, evidencias)
        alvos.append({
            "arquivo": ficha.get("arquivo", registro.get("arquivo", "")),
            "ficha": str(ficha_path.relative_to(raiz)),
            "titulo": titulo, "autor": autor,
            "subtitulo": ficha.get("subTitulo", ""),
            "isbn": ficha.get("isbn", ""),
            "isbn_confirmado": isbn_confirmado,
            "ano": ficha.get("data", ""),
            "edicao": ficha.get("edicao", ""),
            "volume": ficha.get("volume", ""),
            "paginas": ficha.get("nPaginas", ""),
            "paginas_pdf": ficha.get("paginas_pdf", ""),
            "idioma": idioma,
            "consulta": montar_consulta(titulo, autor),
        })
    if arquivos:
        ordem = {nome: pos for pos, nome in enumerate(arquivos)}
        alvos = [x for x in alvos if x["arquivo"] in ordem]
        alvos.sort(key=lambda x: ordem[x["arquivo"]])
    else:
        alvos.sort(key=lambda x: x["arquivo"].casefold())
        if motor and not atualizar:
            pesquisados = set()
            pasta_cache = raiz / "_controle" / "cache-pesquisa-web"
            for arquivo_cache in pasta_cache.glob("*.json") if pasta_cache.is_dir() else []:
                try:
                    pacote = json.loads(arquivo_cache.read_text(encoding="utf-8"))
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
                if (pacote.get("motor") == motor
                        and pacote.get("cache_versao") == CACHE_VERSAO):
                    pesquisados.add(pacote.get("arquivo", ""))
            alvos = [x for x in alvos if x["arquivo"] not in pesquisados]
    return alvos[:limite] if limite else alvos


def salvar_json(caminho, dados):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_name(caminho.name + ".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(caminho)


def executar(raiz, alvos, visivel=True, motor="duckduckgo"):
    cache = raiz / "_controle" / "cache-pesquisa-web"
    relatorio = {"versao": 1, "gerado_em": agora(), "modo": "teste controlado",
                 "motor": motor,
                 "alvos": [], "interrompido": False}
    with sync_playwright() as p:
        navegador = p.chromium.launch(channel="chrome", headless=not visivel)
        pagina = navegador.new_page(locale="pt-BR")
        pagina.set_default_timeout(45000)
        for posicao, alvo in enumerate(alvos, 1):
            chave = hashlib.sha256((f"v{CACHE_VERSAO}\n" + motor + "\n" +
                                     alvo["consulta"]).encode(
                "utf-8")).hexdigest()
            arquivo_cache = cache / f"{chave}.json"
            if arquivo_cache.is_file():
                pacote = json.loads(arquivo_cache.read_text(encoding="utf-8"))
                pacote["cache"] = True
                relatorio["alvos"].append(pacote)
                print(f"[{posicao}/{len(alvos)}] cache: {alvo['titulo']}", flush=True)
                continue
            print(f"[{posicao}/{len(alvos)}] pesquisando: {alvo['titulo']}", flush=True)
            if motor in ("amazon", "estante"):
                # O ISBN do código de barras é a busca mais exata e vem antes
                # de título+autor. As demais consultas são fallback.
                consultas = montar_consultas_comerciais(alvo)
            else:
                consultas = [alvo["consulta"], montar_consulta_titulo(alvo["titulo"])]
            resultados, executadas = [], []
            diagnostico_pagina = {}
            for numero_consulta, consulta in enumerate(consultas, 1):
                if motor == "amazon":
                    dominio = ("www.amazon.com" if alvo.get("idioma") == "eng"
                               else "www.amazon.com.br")
                    url_busca = (f"https://{dominio}/s?i=stripbooks&k=" +
                                 quote_plus(consulta))
                elif motor == "estante":
                    url_busca = ("https://www.estantevirtual.com.br/busca/" +
                                 slug_estante(consulta))
                elif motor == "google":
                    url_busca = ("https://www.google.com/search?hl=pt-BR&q=" +
                                 quote_plus(consulta))
                else:
                    url_busca = ("https://html.duckduckgo.com/html/?q=" +
                                 quote_plus(consulta))
                pagina.goto(url_busca, wait_until="domcontentloaded")
                if bloqueado(pagina):
                    relatorio["interrompido"] = True
                    relatorio["motivo"] = f"{motor} solicitou verificacao humana"
                    print("  verificação detectada; pesquisa interrompida", flush=True)
                    break
                executadas.append(consulta)
                if motor == "estante":
                    try:
                        pagina.wait_for_function("""
                          () => [...document.querySelectorAll(
                            '.product-item, [data-testid*="product-card"], article:has(a[href])'
                          )]
                            .some(el => {
                              const t = (el.querySelector(
                                '.product-item__name, [data-testid*="title"], h2, h3'
                              )?.innerText || '').toLowerCase();
                              return t && !t.includes('procurando título perfeito');
                            })
                        """, timeout=15000)
                    except Exception:
                        # A validação da extração abaixo descarta esqueletos.
                        pass
                encontrados = extrair_resultados(
                    pagina, limite=30 if motor == "estante" else MAX_RESULTADOS,
                    motor=motor)
                for encontrado in encontrados:
                    encontrado["consulta_origem"] = consulta
                diagnostico_pagina = {
                    "titulo": pagina.title(), "url": pagina.url,
                    "texto_inicial": pagina.locator("body").inner_text()[:1800],
                    "contagens": {
                        "data_asin": pagina.locator("div[data-asin]").count(),
                        "data_asin_h2": pagina.locator(
                            "div[data-asin]:has(h2)").count(),
                        "h2": pagina.locator("h2").count(),
                    },
                }
                urls = {x["url"] for x in resultados}
                resultados.extend(x for x in encontrados if x["url"] not in urls)
                if motor in ("amazon", "estante"):
                    # Quantidade não é qualidade: duas respostas ruins não
                    # encerram a progressão. Só paramos diante de identidade
                    # bibliográfica suficiente ou após a última alternativa.
                    if (candidato_suficientemente_confiavel(alvo, resultados)
                            or numero_consulta == len(consultas)):
                        break
                elif len(resultados) >= 2 or numero_consulta == len(consultas):
                    break
                time.sleep(3)
            if relatorio["interrompido"]:
                break
            candidato_amazon, pontuacao_amazon, detalhes_amazon = {}, 0.0, {}
            candidato_amazon_preliminar = {}
            produtos_amazon = []
            detalhes_estante, pontuacao_estante = {}, 0.0
            anuncios_estante = []
            if motor == "amazon":
                plausiveis_amazon = [
                    x for x in avaliar_resultados(alvo, resultados)
                    if ((x["avaliacao"]["titulo_similaridade"] >= 0.55
                         or x["avaliacao"]["isbn_exato"])
                        and not x["avaliacao"]["bloqueios"]
                        and x.get("url", "").startswith("http"))]
                for preliminar in plausiveis_amazon[:3]:
                    candidato_amazon_preliminar = dict(preliminar)
                    time.sleep(2)
                    pagina.goto(preliminar["url"],
                                wait_until="domcontentloaded")
                    if bloqueado(pagina):
                        relatorio["interrompido"] = True
                        relatorio["motivo"] = "Amazon solicitou verificacao humana"
                        print("  verificação detectada ao abrir o produto", flush=True)
                        break
                    detalhe = extrair_detalhes_amazon(pagina)
                    combinado = dict(preliminar)
                    combinado.update({k: v for k, v in detalhe.items() if v})
                    avaliacao_produto = avaliar_correspondencia(alvo, combinado)
                    detalhe["avaliacao"] = avaliacao_produto
                    combinado["avaliacao"] = avaliacao_produto
                    produtos_amazon.append(combinado)
                    if avaliacao_produto["aprovado"]:
                        candidato_amazon = preliminar
                        detalhes_amazon = detalhe
                        pontuacao_amazon = avaliacao_produto["pontuacao"]
                        break
                if relatorio["interrompido"]:
                    break
                if not candidato_amazon and produtos_amazon:
                    melhor_rejeitado = max(
                        produtos_amazon,
                        key=lambda x: x["avaliacao"]["pontuacao"])
                    detalhes_amazon = {
                        k: v for k, v in melhor_rejeitado.items()
                        if k in {"titulo_pagina", "autoria_pagina", "editora",
                                 "data_publicacao", "idioma", "paginas",
                                 "isbn_10", "isbn_13", "edicao", "volume",
                                 "url", "detalhes_brutos", "avaliacao"}}
                    pontuacao_amazon = melhor_rejeitado["avaliacao"]["pontuacao"]
            elif motor == "estante":
                facetas_estante = extrair_facetas_estante(pagina)
                plausiveis = [x for x in avaliar_resultados(alvo, resultados)
                              if ((x["avaliacao"]["titulo_similaridade"] >= 0.55
                                   or x.get("consulta_origem") in
                                      formas_isbn(alvo.get("isbn", "")))
                                  and not x["avaliacao"]["bloqueios"]
                                  and x.get("url", "").startswith("http"))]
                urls_abertas = set()
                for item in plausiveis[:3]:
                    if item["url"] in urls_abertas:
                        continue
                    urls_abertas.add(item["url"])
                    time.sleep(2)
                    pagina.goto(item["url"], wait_until="domcontentloaded")
                    if bloqueado(pagina):
                        relatorio["interrompido"] = True
                        relatorio["motivo"] = (
                            "Estante Virtual solicitou verificação humana")
                        print("  verificação ao abrir anúncio; pesquisa interrompida",
                              flush=True)
                        break
                    detalhe = extrair_detalhes_estante(pagina)
                    combinado = dict(item)
                    combinado.update({k: v for k, v in detalhe.items() if v})
                    combinado["avaliacao"] = avaliar_correspondencia(
                        alvo, combinado)
                    anuncios_estante.append(combinado)
                    if combinado["avaliacao"]["isbn_exato"]:
                        break
                if relatorio["interrompido"]:
                    break
                detalhes_estante, pontuacao_estante = escolher_candidato_estante(
                    alvo, anuncios_estante or resultados, facetas_estante)
            rejeitados = registrar_rejeicoes(
                alvo, anuncios_estante or produtos_amazon or resultados)
            pacote = dict(alvo)
            pacote.update({"consultado_em": agora(), "cache": False,
                            "motor": motor, "cache_versao": CACHE_VERSAO,
                            "consultas_executadas": executadas,
                            "diagnostico_pagina": diagnostico_pagina,
                            "resultados": resultados[:MAX_RESULTADOS],
                            "candidatos_rejeitados": rejeitados,
                            "candidato_amazon_preliminar":
                                candidato_amazon_preliminar,
                            "candidato_amazon": candidato_amazon,
                            "produtos_amazon_abertos": produtos_amazon,
                            "pontuacao_amazon": pontuacao_amazon,
                            "detalhes_amazon": detalhes_amazon,
                            "anuncios_estante_abertos": anuncios_estante,
                            "detalhes_estante": detalhes_estante,
                            "pontuacao_estante": pontuacao_estante})
            salvar_json(arquivo_cache, pacote)
            relatorio["alvos"].append(pacote)
            confirmados = ((detalhes_estante or {}).get("anuncios_exatos", 0)
                           if motor == "estante" else int(bool(candidato_amazon)))
            print(f"  {len(pacote['resultados'])} candidato(s) válido(s); "
                  f"{confirmados} correspondência(s) confirmada(s)", flush=True)
            if posicao < len(alvos):
                time.sleep(INTERVALO)
        navegador.close()
    caminho = raiz / "_controle" / "pesquisa-web-ultimo.json"
    salvar_json(caminho, relatorio)
    return caminho, relatorio


def main():
    ap = argparse.ArgumentParser(description="Pesquisa web bibliografica controlada")
    ap.add_argument("--raiz", required=True)
    ap.add_argument("--limite", type=int, default=5)
    ap.add_argument("--arquivo", action="append", default=[],
                    help="nome exato do PDF; pode ser repetido")
    ap.add_argument("--executar", action="store_true")
    ap.add_argument("--oculto", action="store_true")
    ap.add_argument("--motor", choices=("amazon", "estante", "duckduckgo", "google"),
                    default="duckduckgo")
    ap.add_argument("--atualizar", action="store_true",
                    help="repete pesquisas mesmo quando ha cache desta versao")
    args = ap.parse_args()
    raiz = pathlib.Path(args.raiz).expanduser().resolve()
    alvos = carregar_alvos(raiz, args.limite, args.arquivo,
                           motor=args.motor, atualizar=args.atualizar)
    if not args.executar:
        print(json.dumps({"modo": "SIMULACAO", "alvos": alvos},
                         ensure_ascii=False, indent=2))
        return
    caminho, relatorio = executar(
        raiz, alvos, visivel=not args.oculto, motor=args.motor)
    print(f"Relatorio: {caminho}")
    print(f"Consultados: {len(relatorio['alvos'])}; "
          f"interrompido: {'sim' if relatorio['interrompido'] else 'nao'}")


if __name__ == "__main__":
    main()
