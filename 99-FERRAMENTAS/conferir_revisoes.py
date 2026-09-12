#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Confere se as correcoes manuais estao no lugar certo e ainda valem.

POR QUE ISTO EXISTE
-------------------
Ao corrigir o livro "Eu, um Discipulador" eu gravei os campos direto na
ficha, em `_metadados/*.json`. A ficha e DESCARTAVEL: ela e reescrita a
cada processamento. Na primeira reexecucao a correcao teria evaporado, e
nada avisaria.

O lugar certo e `_controle/revisoes-manuais.json`, protegido por hash do
PDF - e por isso sobrevive a reprocessamentos e nao se aplica ao arquivo
errado quando dois livros tem o mesmo nome.

Ninguem percebia a diferenca porque as duas gravacoes "funcionam" no
momento em que sao feitas. So a reexecucao revela qual delas era real.

O QUE ESTE UTILITARIO ACUSA
---------------------------
1. ficha diverge da revisao aprovada  -> alguem corrigiu no lugar errado
2. revisao com hash que nao bate      -> o PDF mudou; a revisao nao vale
3. revisao sem hash                   -> pode ser aplicada ao arquivo errado
4. revisao orfa                       -> aponta para arquivo que nao existe

So LE. Nao altera nada.

Uso:
    python3 conferir_revisoes.py --raiz ../livros
"""

import argparse
import hashlib
import json
import pathlib
import sys

# Campos em que a divergencia importa: sao os que vao para o tombo.
CAMPOS_CONFERIDOS = ("titulo", "subTitulo", "nmAutor0", "editora", "data",
                     "isbn", "lugar", "cdd", "edicao", "tipo_documento")


def estado_encerrado(estado):
    """Itens definitivamente encerrados nao podem bloquear novos envios."""
    estado = str(estado or "").strip().casefold()
    if any(marca in estado for marca in
           ("cadastrado", "arquivos locais liberados", "descartado")):
        return True
    return estado in {
        "duplicado",
        "duplicado confirmado por isbn",
        "duplicado confirmado por conteúdo",
        "duplicado confirmado por titulo",
        "duplicado confirmado por título",
        "duplicado confirmado por titulo e autor",
        "duplicado confirmado por título e autor",
    }


def sha256(arquivo, bloco=1024 * 1024):
    h = hashlib.sha256()
    with open(arquivo, "rb") as f:
        for pedaco in iter(lambda: f.read(bloco), b""):
            h.update(pedaco)
    return h.hexdigest()


def _pdf_do_registro(raiz, nome, ficha, buscar_por_nome=True):
    for chave in ("pdf_original", "caminho", "pdf_preparado"):
        valor = ficha.get(chave)
        if valor:
            caminho = raiz / str(valor)
            if caminho.is_file():
                return caminho
    if not buscar_por_nome:
        return None
    achados = list(raiz.rglob(nome))
    return achados[0] if achados else None


def conferir(raiz):
    raiz = pathlib.Path(raiz).expanduser().resolve()
    controle = raiz / "_controle" / "revisoes-manuais.json"
    metadados = raiz / "_metadados"

    try:
        revisoes = json.loads(controle.read_text(encoding="utf-8")).get("livros", {})
    except (OSError, ValueError, json.JSONDecodeError):
        revisoes = {}

    fichas = {}
    fichas_por_hash = {}
    for arquivo in sorted(metadados.glob("*.json")):
        try:
            d = json.loads(arquivo.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if d.get("arquivo"):
            fichas[d["arquivo"]] = (arquivo, d)
        if d.get("hash_sha256"):
            fichas_por_hash[d["hash_sha256"]] = (arquivo, d)

    try:
        catalogo = json.loads(
            (raiz / "_controle" / "catalogo-local.json").read_text(
                encoding="utf-8")).get("livros", {})
    except (OSError, ValueError, json.JSONDecodeError):
        catalogo = {}

    relatorio = {"divergentes": [], "hash_mudou": [], "sem_hash": [],
                 "orfas": [], "aguardando_preparo": [],
                 "avisos_encerrados": [],
                 "revisoes": len(revisoes), "fichas": len(fichas)}

    for nome, rev in revisoes.items():
        campos = rev.get("campos", {}) or {}
        esperado = rev.get("hash_sha256", "")
        arquivo_ficha, ficha = (
            fichas_por_hash.get(esperado, (None, None)) if esperado
            else (None, None))
        if ficha is None:
            arquivo_ficha, ficha = fichas.get(nome, (None, None))

        if ficha is None:
            # Importações OPF gravam a revisão antes do preparo. Se a
            # execução for interrompida nesse intervalo, o PDF continua na
            # entrada e ainda não deve ter ficha. Isso é trabalho pendente,
            # não revisão perdida, e não pode bloquear o envio dos prontos.
            pdf_entrada = raiz / "00-ENTRADA" / nome
            if pdf_entrada.is_file() and esperado:
                if sha256(pdf_entrada) == esperado:
                    relatorio["aguardando_preparo"].append({
                        "livro": nome,
                        "arquivo": str(pdf_entrada.relative_to(raiz)),
                        "motivo": ("revisão importada e PDF ainda na entrada; "
                                   "a ficha será criada no próximo preparo")})
                else:
                    relatorio["hash_mudou"].append({
                        "livro": nome,
                        "arquivo": str(pdf_entrada.relative_to(raiz)),
                        "motivo": ("o PDF na entrada não corresponde ao hash "
                                   "da revisão importada")})
            elif pdf_entrada.is_file() and not esperado:
                relatorio["sem_hash"].append({
                    "livro": nome,
                    "motivo": ("revisão sem hash: pode ser aplicada a outro "
                               "PDF que receba o mesmo nome")})
            else:
                relatorio["orfas"].append({
                    "livro": nome,
                    "motivo": "revisão aprovada, mas nenhuma ficha corresponde"})
            continue

        # Revisoes antigas de itens ja encerrados ficam visiveis no historico,
        # mas nao podem bloquear o envio de materiais sem relacao com elas.
        # "ja existente - conferir vinculo" nao entra aqui: ainda e decisao
        # pendente e deve continuar protegida pelas travas.
        registro_catalogo = catalogo.get(esperado, {}) if esperado else {}
        estado = str(registro_catalogo.get("estado", "")
                     or ficha.get("situacao", "") or ficha.get("estado", ""))
        if estado_encerrado(estado):
            # Sem busca por nome: pode existir uma nova copia com o mesmo
            # nome, mas hash diferente. Ela nao pertence a esta revisao.
            pdf = _pdf_do_registro(raiz, nome, ficha, buscar_por_nome=False)
            if esperado and pdf and sha256(pdf) != esperado:
                relatorio["avisos_encerrados"].append({
                    "livro": nome, "arquivo": str(pdf.relative_to(raiz)),
                    "estado": estado,
                    "motivo": ("o PDF mudou depois da revisão, mas o item já "
                               "está encerrado e não bloqueia novos envios")})
            continue

        # --- o hash ainda corresponde ao PDF? ---------------------------
        if not esperado:
            relatorio["sem_hash"].append({
                "livro": nome,
                "motivo": ("revisão sem hash: pode ser aplicada a outro PDF "
                           "que receba o mesmo nome")})
        else:
            pdf = _pdf_do_registro(raiz, nome, ficha)
            if pdf and sha256(pdf) != esperado:
                relatorio["hash_mudou"].append({
                    "livro": nome, "arquivo": str(pdf.relative_to(raiz)),
                    "motivo": ("o PDF mudou depois da revisão: ela deixou de "
                               "ser aplicada e o livro voltará ao estado "
                               "automático")})

        # Item ja encerrado nao e problema, e historia.
        #
        # Um resumo do Kuyper tinha revisao dizendo "resumo" e terminou
        # descartado: a divergencia existe, mas o arquivo nao esta mais
        # aqui e nao ha o que reprocessar. Cobrar isso e ruido, e ruido
        # faz o operador parar de ler os avisos - que e o pior desfecho.
        # --- a ficha concorda com a revisao? ----------------------------
        divergencias = []
        for campo in CAMPOS_CONFERIDOS:
            if campo not in campos:
                continue
            na_revisao = str(campos.get(campo, "") or "").strip()
            na_ficha = str(ficha.get(campo, "") or "").strip()
            if na_ficha != na_revisao:
                divergencias.append({"campo": campo, "revisao": na_revisao,
                                     "ficha": na_ficha})
        if divergencias:
            relatorio["divergentes"].append({
                "livro": nome, "ficha": str(arquivo_ficha.name),
                "campos": divergencias,
                "motivo": ("a ficha não reflete a revisão aprovada: ou o "
                           "livro ainda não foi reprocessado, ou alguém "
                           "editou a ficha em vez da revisão")})

    return relatorio


def imprimir(r):
    print(f"\n  {r['revisoes']} revisões manuais | {r['fichas']} fichas\n")
    problemas = 0
    for chave, titulo in (
            ("divergentes", "FICHA DIVERGE DA REVISÃO"),
            ("hash_mudou", "O PDF MUDOU DEPOIS DA REVISÃO"),
            ("sem_hash", "REVISÃO SEM HASH"),
            ("orfas", "REVISÃO SEM FICHA")):
        itens = r.get(chave, [])
        if not itens:
            continue
        problemas += len(itens)
        print(f"  {titulo}  ({len(itens)})")
        for item in itens[:12]:
            print(f"    {item['livro'][:56]}")
            print(f"       {item['motivo']}")
            for c in item.get("campos", [])[:4]:
                print(f"       {c['campo']}: revisão={c['revisao'][:34]!r} "
                      f"ficha={c['ficha'][:34]!r}")
        if len(itens) > 12:
            print(f"    ... e mais {len(itens) - 12}")
        print()
    if not problemas:
        print("  Nenhum problema: todas as revisões estão no lugar certo,\n"
              "  com hash válido, e as fichas refletem o que foi decidido.\n")
    avisos = r.get("avisos_encerrados", [])
    if avisos:
        print(f"  AVISOS HISTÓRICOS, SEM BLOQUEIO  ({len(avisos)})")
        for item in avisos[:12]:
            print(f"    {item['livro'][:56]}")
            print(f"       {item['motivo']}")
        print()
    pendentes = r.get("aguardando_preparo", [])
    if pendentes:
        print(f"  AGUARDANDO PREPARO, SEM BLOQUEIO  ({len(pendentes)})")
        for item in pendentes[:12]:
            print(f"    {item['livro'][:56]}")
            print(f"       {item['motivo']}")
        print()
    return problemas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raiz", required=True)
    ap.add_argument("--json", action="store_true",
                    help="saída em JSON, para outro programa consumir")
    args = ap.parse_args()
    r = conferir(args.raiz)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0
    return 1 if imprimir(r) else 0


if __name__ == "__main__":
    sys.exit(main())
