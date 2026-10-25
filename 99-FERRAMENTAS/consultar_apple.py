"""Camada local auxiliar: sugestões auditáveis, nunca aprovação pela IA."""
import hashlib
import json
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata

VERSAO = 2
CAMPOS = ('titulo', 'subTitulo', 'nmAutor0', 'editora', 'data', 'lugar',
          'edicao', 'tipo_documento', 'volume', 'isbn')


def normalizar(valor):
    return ' '.join(re.findall(r'[a-z0-9]+', ''.join(
        c for c in unicodedata.normalize('NFKD', str(valor or '').lower())
        if not unicodedata.combining(c))))


def igual(a, b, campo):
    a, b = normalizar(a), normalizar(b)
    if not a or not b:
        return False
    if campo == 'nmAutor0':
        return sorted(a.split()) == sorted(b.split())
    return a == b


def executar(comando, entrada=None, limite=180):
    """Tempo limitado e sinal de vida também durante a inferência local."""
    env = dict(os.environ, CLANG_MODULE_CACHE_PATH='/private/tmp/biblio-swift-cache/clang')
    p = subprocess.Popen(comando, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, env=env)
    inicio = time.monotonic()
    primeira = True
    try:
        while True:
            try:
                out, err = p.communicate(input=entrada if primeira else None, timeout=15)
                if p.returncode:
                    raise RuntimeError((err or 'processo Apple falhou')[-500:])
                return out
            except subprocess.TimeoutExpired:
                primeira = False
                decorrido = int(time.monotonic() - inicio)
                print(f'  Apple Intelligence: trabalhando há {decorrido}s; limite {limite}s', flush=True)
                if decorrido >= limite:
                    raise TimeoutError('tempo limite da análise Apple; revisão preservada')
    finally:
        if p.poll() is None:
            p.kill()
            p.communicate()


def binario():
    if sys.platform != 'darwin' or os.environ.get('BIBLIO_APPLE', '1') == '0':
        return None
    if int((platform.mac_ver()[0] or '0').split('.')[0]) < 26:
        return None
    swift = pathlib.Path(__file__).with_name('piloto-apple-bibliografia.swift')
    if not swift.is_file() or not shutil.which('xcrun'):
        return None
    versao = hashlib.sha256(swift.read_bytes()).hexdigest()[:16]
    pasta = pathlib.Path(tempfile.gettempdir()) / f'biblio-apple-{os.getuid()}' / versao
    pasta.mkdir(parents=True, exist_ok=True, mode=0o700)
    alvo = pasta / 'analisar'
    if not alvo.is_file():
        print('  Apple Intelligence: preparando leitor local (uma vez por versão)', flush=True)
        fd, nome = tempfile.mkstemp(dir=pasta, prefix='compilando-')
        os.close(fd)
        try:
            executar(['xcrun', 'swiftc', '-parse-as-library', '-O', str(swift), '-o', nome])
            os.replace(nome, alvo)
        finally:
            if os.path.exists(nome):
                os.unlink(nome)
    return str(alvo)


def selecionar_paginas(paginas):
    """Primeiras páginas e créditos; entrada curta para o modelo local."""
    cip = re.compile(r'ficha\s+catalog|\bCIP\b|catalog[au][çc]|cataloging.in.publication', re.I)
    candidatos = []
    numeros = sorted(set(range(1, min(12, len(paginas)) + 1)) |
                     set(range(max(1, len(paginas) - 1), len(paginas) + 1)))
    for i in numeros:
        texto = paginas[i - 1] or ''
        if not texto.strip():
            continue
        pontos = 100 * bool(cip.search(texto)) + 70 * bool(re.search(r'ISBN', texto, re.I))
        pontos += 50 * bool(re.search(r'organizad|\bby\b|autor\s*:', texto, re.I))
        pontos += 40 * bool(re.search(r'edi[çc][aã]o|\bedition\b', texto, re.I))
        pontos += 25 * (len(texto.strip()) < 900 and i < 8)
        pontos += 10 * (i <= 3)
        pontos -= 80 * bool(re.search(r'cadastro no final|lan[çc]amentos e promo', texto, re.I))
        if pontos > 0:
            candidatos.append((-pontos, i))
    selecionadas = []
    restante = 2700
    for _pontos, n in sorted(candidatos)[:4]:
        if restante <= 0:
            break
        texto = paginas[n - 1] or ''
        # A CIP vence créditos gráficos e avisos no começo da mesma página.
        m = cip.search(texto)
        inicio = max(0, m.start() - 100) if m else 0
        trecho = texto[inicio:inicio + min(restante, 850 if m else 550)]
        selecionadas.append({'pagina': n, 'texto': trecho})
        restante -= len(trecho)
    return selecionadas


def isbn_normalizado(valor):
    s = re.sub(r'[^0-9X]', '', str(valor or '').upper())
    if len(s) == 10 and s[:9].isdigit():
        base = '978' + s[:9]
        s = base + str((-sum(int(c) * (1 if i % 2 == 0 else 3)
                              for i, c in enumerate(base))) % 10)
    return s


def conferir(resposta, paginas, fontes, contexto=None, trechos=None):
    if not isinstance(resposta, dict) or resposta.get('erro'):
        return []
    evidencias = resposta.get('evidencias', [])
    if not isinstance(evidencias, list):
        evidencias = []
    valores = dict(resposta)
    if isinstance(valores.get('titulo'), str) and isinstance(valores.get('subTitulo'), str):
        sub = valores['subTitulo'].strip()
        if sub:
            valores['titulo'] = re.sub(r'\s*[:;—-]?\s*' + re.escape(sub) + r'\s*$', '',
                                       valores['titulo'], flags=re.I).strip()
    autores = resposta.get('autores')
    if isinstance(autores, list) and autores and isinstance(autores[0], str):
        valores['nmAutor0'] = autores[0]
    saida = []
    contexto = contexto or {}
    for campo in CAMPOS:
        valor = valores.get(campo)
        if not isinstance(valor, str) or not valor.strip():
            continue
        provas = []
        for e in evidencias:
            if not isinstance(e, dict):
                continue
            aliases = {'data de publicacao': 'data', 'ano': 'data', 'autor principal': 'nmAutor0',
                       'autor': 'nmAutor0', 'autores': 'nmAutor0', 'subtitulo': 'subTitulo',
                       'titulo': 'titulo', 'editora': 'editora', 'cidade': 'lugar',
                       'edicao': 'edicao', 'tipo de documento': 'tipo_documento', 'isbn': 'isbn'}
            rotulo = aliases.get(normalizar(e.get('campo')), e.get('campo'))
            if rotulo != campo:
                continue
            n, trecho = e.get('pagina'), e.get('trecho')
            if isinstance(n, str) and n.isdigit():
                n = int(n)
            if type(n) is not int or not 1 <= n <= len(paginas) or not isinstance(trecho, str):
                continue
            texto, citacao = normalizar(paginas[n - 1]), normalizar(trecho)
            palavras = normalizar(valor).split()
            # Confere trecho e valor separadamente; uma citação real não prova
            # um dado inventado. Autoria pode estar na ordem bibliográfica.
            sustenta = bool(palavras) and all(p in citacao.split() for p in palavras)
            if len(citacao) >= 12 and citacao in texto and sustenta:
                provas.append({'pagina': n, 'trecho': trecho[:1000], 'origem': 'citação da Apple verificada'})
        # O modelo às vezes omite citações. Nesse caso o motor pode localizar
        # o valor literalmente NOS EXCERTOS ENVIADOS, sem atribuir à IA uma
        # citação que ela não fez. Ainda exige a fonte externa para aplicar.
        if not provas and trechos:
            alvo = normalizar(valor)
            for n, texto in trechos.items():
                linhas = texto.splitlines()
                for i in range(len(linhas)):
                    trecho = '\n'.join(linhas[max(0, i - 1):i + 3]).strip()
                    if (alvo and re.search(r'\b' + re.escape(alvo) + r'\b', normalizar(trecho))
                            and len(normalizar(trecho)) >= 12):
                        provas.append({'pagina': n, 'trecho': trecho[:1000],
                                       'origem': 'localização literal pelo motor'})
                        break
                if provas:
                    break
        confirmacoes = []
        for fonte, candidato in fontes.items():
            if not isinstance(candidato, dict):
                continue
            # Não transformar um homônimo de título em confirmação editorial.
            isbn_a = isbn_normalizado(valores.get('isbn'))
            isbn_b = isbn_normalizado(candidato.get('isbn'))
            if isbn_a and isbn_b and isbn_a != isbn_b:
                continue
            isbn_local = isbn_normalizado(contexto.get('isbn'))
            if isbn_local and ((isbn_a and isbn_a != isbn_local)
                               or (isbn_b and isbn_b != isbn_local)):
                continue
            autor = candidato.get('autores') or candidato.get('autor') or ''
            if isinstance(autor, list):
                autor = autor[0] if autor else ''
            identidade = (igual(valores.get('titulo'), candidato.get('titulo'), 'titulo')
                          and igual(valores.get('nmAutor0'), autor, 'nmAutor0'))
            # Edição/volume divergentes bloqueiam a corroboração automática.
            if any(valores.get(k) and candidato.get(k)
                   and not igual(valores[k], candidato[k], k) for k in ('volume', 'edicao')):
                continue
            if any(contexto.get(k) and candidato.get(k)
                   and not igual(contexto[k], candidato[k], k) for k in ('volume', 'edicao')):
                continue
            if not identidade:
                continue
            aliases = {'nmAutor0': autor, 'data': candidato.get('ano') or candidato.get('data'),
                       'subTitulo': candidato.get('subtitulo')}
            outro = aliases.get(campo, candidato.get(campo))
            if provas and igual(valor, outro, campo):
                confirmacoes.append(fonte)
        saida.append({'campo': campo, 'valor': valor.strip()[:1000], 'evidencias': provas,
                      'fontes_confirmadoras': confirmacoes,
                      'estado': ('confirmado por outra fonte' if confirmacoes else
                                 'conferir na página' if provas else 'sem evidência verificável')})
    return saida


def aplicar_confirmadas(linha, analise):
    """Somente campos com citação real E fonte independente concordante.

    Conflitos de identidade/edição/paginação não são apagados em bloco.
    A decisão de pronto continua nas validações normais do preparador.
    """
    aplicados = []
    for s in analise.get('sugestoes', []):
        campo = s.get('campo')
        if (campo not in CAMPOS or not s.get('evidencias')
                or not s.get('fontes_confirmadoras')):
            continue
        valor = s['valor']
        # Nunca trocar silenciosamente um ISBN/volume/edição já lido.
        if campo in ('isbn', 'volume', 'edicao', 'tipo_documento') and linha.get(campo):
            continue  # inclusive diferenças só de caixa/formatação: preservar o canônico
        anterior = linha.get(campo, '')
        linha[campo] = valor
        if campo == 'nmAutor0':
            linha['origem_autor'] = 'Apple + ' + ', '.join(s['fontes_confirmadoras'])
        if campo == 'titulo':
            linha['origem_titulo'] = 'Apple + ' + ', '.join(s['fontes_confirmadoras'])
        aplicados.append({'campo': campo, 'antes': anterior, 'depois': valor})
        # Estes conflitos são de fallback textual, não de edição divergente.
        prefixos = {'titulo': ('titulo so do nome do arquivo:',),
                    'nmAutor0': ('autor so do nome do arquivo:', 'autor suspeito:',
                                 'autor: copyright=')}
        linha['conflitos'] = [x for x in linha.get('conflitos', [])
                              if not any(normalizar(x).startswith(normalizar(p))
                                         for p in prefixos.get(campo, ()))]
    analise['campos_aplicados'] = aplicados
    return aplicados


def analisar(pdf, paginas, fontes=None, contexto=None, confirmador=None):
    """Não modifica campos do catálogo nem aprova/reabre revisões humanas."""
    try:
        executavel = binario()
        if not executavel:
            return {'estado': 'indisponível', 'motivo': 'Apple local indisponível ou desativada'}
        selecionadas = selecionar_paginas(paginas)
        entrada = {'paginas': '\n\n'.join(
            f'PÁGINA {x["pagina"]}:\n{x["texto"]}' for x in selecionadas)}
        h = hashlib.sha256()
        with open(pdf, 'rb') as f:
            for bloco in iter(lambda: f.read(1024 * 1024), b''):
                h.update(bloco)
        digest = h.hexdigest()
        origem = pathlib.Path(pdf).resolve()
        raiz = next((p for p in origem.parents if (p / '_controle').is_dir()), origem.parent)
        chave = hashlib.sha256((json.dumps(entrada, ensure_ascii=False) + executavel
                                + str(VERSAO)).encode()).hexdigest()[:16]
        pasta = raiz / '_evidencias_apple' / digest / chave
        pasta.mkdir(parents=True, exist_ok=True)
        cache = pasta / 'resposta.json'
        resposta = json.loads(cache.read_text(encoding='utf-8')) if cache.is_file() else None
        # Falha temporária do serviço não pode se tornar uma negativa eterna.
        if (not isinstance(resposta, dict) or resposta.get('erro')
                or resposta.get('disponivel') is False):
            print('  Apple Intelligence: analisando páginas para revisão assistida', flush=True)
            resposta = json.loads(executar([executavel], json.dumps(entrada)))
            if not isinstance(resposta, dict):
                return {'estado': 'falha', 'motivo': 'Apple não retornou um objeto JSON'}
            if not resposta.get('erro') and resposta.get('disponivel') is not False:
                tmp = pasta / 'resposta.tmp'
                tmp.write_text(json.dumps(resposta, ensure_ascii=False, indent=2), encoding='utf-8')
                tmp.replace(cache)
        if resposta.get('disponivel') is False or resposta.get('erro'):
            return {'estado': 'indisponível' if resposta.get('disponivel') is False else 'falha',
                    'motivo': str(resposta.get('motivo') or resposta.get('erro'))[:600]}
        fontes = dict(fontes or {})
        trechos = {x['pagina']: x['texto'] for x in selecionadas}
        sugestoes = conferir(resposta, paginas, fontes, contexto, trechos)
        erro_conferencia = ''
        if confirmador and any(s['evidencias'] for s in sugestoes):
            try:
                print('  Apple Intelligence: conferindo sugestões nas fontes bibliográficas', flush=True)
                fontes.update(confirmador([s for s in sugestoes if s['evidencias']]) or {})
                sugestoes = conferir(resposta, paginas, fontes, contexto, trechos)
            except Exception as exc:
                erro_conferencia = str(exc)[:300]
        imagens = []
        numeros = {x['pagina'] for x in selecionadas}
        numeros.update(e['pagina'] for s in sugestoes for e in s['evidencias'])
        for n in sorted(numeros):
            imagem = pasta / f'pagina-{n}.png'
            if not imagem.is_file() and shutil.which('pdftoppm'):
                try:
                    executar(['pdftoppm', '-f', str(n), '-l', str(n), '-scale-to', '1600',
                              '-singlefile', '-png', str(origem), str(imagem.with_suffix(''))], limite=45)
                except (OSError, RuntimeError, TimeoutError):
                    pass  # PDF ativo e número da página continuam disponíveis.
            imagens.append({'pagina': n, 'imagem': str(imagem) if imagem.is_file() else ''})
        return {'estado': 'revisão assistida', 'sugestoes': sugestoes,
                'paginas': imagens, 'paginas_enviadas': [x['pagina'] for x in selecionadas],
                'hash_pdf': digest, 'cache': str(cache), 'versao': VERSAO,
                'fontes_conferidas': fontes, 'erro_conferencia': erro_conferencia,
                'aviso': 'Sugestões da Apple: não alteram nem aprovam a ficha automaticamente.'}
    except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
        return {'estado': 'falha', 'motivo': str(exc)[:600]}
