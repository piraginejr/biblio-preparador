"""Travas bibliográficas compartilhadas pelo preparo e envio, sem rede/OCR.

Evidências limitadas à abertura e créditos; bibliografia do fim não é tombo.
Decisão humana com snapshot permanece soberana; importação automática não é
revisão humana, mesmo quando tiver todos os campos preenchidos.
"""
import functools
import pathlib
import re
import shutil
import subprocess
import unicodedata

VERSAO = 1


def informativo_distribuicao(texto):
    """Conteúdo promocional curto; nunca inferir descarte só pela extensão."""
    if not texto or len(texto)>4000:
        return False
    n=normalizar(texto)
    return bool(re.search(r'(?i)https?://|www\.|webmaster@',texto)
                and ('democratizacao da leitura' in n or
                     ('biblioteca virtual gratuita' in n and 'visite' in n))
                and not re.search(r'(?i)\bISBN\b|(?:autor|t[ií]tulo|editora)\s*:',texto))


def normalizar(valor):
    s=unicodedata.normalize('NFKD',str(valor or '')).casefold()
    return ' '.join(re.findall(r'\w+', ''.join(c for c in s if not unicodedata.combining(c))))


def isbn_confirmado(ficha):
    isbn=re.sub(r'[^0-9X]','',str(ficha.get('isbn','')).upper())
    valido=False
    if len(isbn)==10 and isbn[:9].isdigit() and (isbn[-1].isdigit() or isbn[-1]=='X'):
        valido=sum((10-i)*(10 if c=='X' else int(c)) for i,c in enumerate(isbn))%11==0
    elif len(isbn)==13 and isbn.isdigit() and isbn.startswith(('978','979')):
        valido=sum(int(c)*(1 if i%2==0 else 3) for i,c in enumerate(isbn))%10==0
    return bool(ficha.get('isbn_confirmado_na_edicao') and valido)


def revisao_humana(ficha):
    return bool(ficha.get('revisao_manual_aprovada')
                and (ficha.get('ultimo_snapshot_revisao_manual')
                     or ficha.get('origem_decisao_revisao') == 'humana'))


@functools.lru_cache(maxsize=96)
def _ler_pdf(caminho, tamanho, modificado):
    exe=shutil.which('pdftotext')
    if not exe:
        return [], []
    try:
        proc=subprocess.run([exe,'-layout','-f','1','-l','6',caminho,'-'],
                            capture_output=True,text=True,timeout=12,check=True)
        paginas=proc.stdout.split('\f')
        fim=[]
        info=shutil.which('pdfinfo')
        if info:
            p=subprocess.run([info,caminho],capture_output=True,text=True,timeout=6,check=True)
            n=int(re.search(r'Pages:\s+(\d+)',p.stdout)[1])
            if n>6:
                p=subprocess.run([exe,'-layout','-f',str(max(7,n-2)),caminho,'-'],
                                 capture_output=True,text=True,timeout=12,check=True)
                fim=p.stdout.split('\f')
        return paginas,fim
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return [], []


def auditar(ficha, pdf=None, paginas=None, fim=None, confirmacao_humana=False):
    if confirmacao_humana or revisao_humana(ficha):
        return []
    if paginas is None:
        p=pathlib.Path(pdf) if pdf else None
        if p and p.is_file():
            st=p.stat()
            paginas,fim=_ler_pdf(str(p.resolve()),st.st_size,st.st_mtime_ns)
        else:
            paginas=[]
    paginas=list(paginas or [])
    fim=list(fim or [])
    texto='\n'.join(paginas[:6])
    abertura='\n'.join(paginas[:2])
    titulo=str(ficha.get('titulo','') or '')
    autor=str(ficha.get('nmAutor0','') or '')
    tipo=ficha.get('tipo_documento','livro')
    achados=[]
    def registrar(codigo,campo,motivo,evidencia=''):
        if codigo not in {x['codigo'] for x in achados}:
            achados.append({'codigo':codigo,'campo':campo,'motivo':motivo,
                            'evidencia':evidencia[:350]})

    if ('\ufffd' in titulo or re.search(r'(?i)\((?:doc|doc\s+cap[^)]*)\)',titulo)):
        registrar('titulo_tecnico','titulo','título contém ruído técnico/codificação do arquivo')
    if re.search(r'(?i)\b(?:R\.|Rua|Av\.|Avenida)\s+.{2,60},\s*n[ºoQ°.]',titulo):
        registrar('endereco_no_titulo','titulo','endereço editorial incorporado ao título')
    if re.match(r'(?i)^obras\s+completas\s+de\s+[\w. ]{0,12}$',titulo):
        registrar('serie_como_titulo','titulo','nome truncado da coleção usado como título da obra')
    if re.match(r"^[^,]{2,35},\s*(?:[A-Z]\.?\s*){1,4}\s+[A-ZÀ-Üa-zà-ÿ]",titulo):
        registrar('arquivo_como_titulo','titulo','possível autoria do nome do arquivo incorporada ao título')
    if tipo=='livro' and (ficha.get('arquivo_possivelmente_parcial') or
                          re.search(r'(?i)\b(?:incomplet[oa]|parcial)\b',titulo)):
        registrar('livro_parcial','tipo_documento','material parcial não deve ser aprovado como livro integral')
    if normalizar(titulo) in {'info','readme','leia me'} and (
            not texto or re.search(r'(?i)biblioteca\s+virtual|webmaster|visite|democratiza',texto)):
        registrar('informativo_distribuicao','tipo_documento','informativo de distribuição sem conteúdo bibliográfico')
    cidades={'buenos aires','aires buenos','sao paulo','paulo sao','rio de janeiro',
             'janeiro rio de','petropolis','curitiba','lisboa','london','new york'}
    if normalizar(autor) in cidades:
        registrar('cidade_como_autor','nmAutor0','local de publicação confundido com pessoa',autor)

    def conferir_autor(esperado, evidencia):
        esperado=re.split(r'\s+(?:e|and|&)\s+',esperado,maxsplit=1,flags=re.I)[0]
        if not esperado:
            return
        if not autor:
            registrar('autor_declarado_ausente','nmAutor0','autoria declarada no PDF não aproveitada',evidencia)
            return
        # Partículas e iniciais variam entre normas; o sobrenome declarado
        # não pode ser trocado pelo prenome nem por uma cidade.
        sobrenome=(esperado.split(',')[0] if ',' in esperado else esperado.split()[-1])
        atual=autor.split(',')[0] if ',' in autor else autor.split()[-1]
        limpar=lambda v:' '.join(p for p in normalizar(v).split() if p not in {'de','da','do','von','van'})
        if limpar(atual)!=limpar(sobrenome):
            registrar('autor_diverge_pdf','nmAutor0','autoria diverge da identificação explícita no PDF',evidencia)

    for pagina in paginas[:2]:
        m=re.search(r'(?im)^\s*(?:autor(?:es)?|author(?:s)?)\s*:\s*([^\n]{3,100})',pagina)
        if not m:
            # Rótulo separado e nome completo, nunca "Portanto" nem uma
            # frase como "Por su ilustración ..." no corpo do texto.
            m=re.search(r'(?m)^[ \t]*(?i:por|by)(?:[ \t]+|\n(?:[ \t]*\n){0,2}[ \t]*)'
                        r'([A-ZÀ-Ü][A-Za-zÀ-ÿ.\u2019\x27-]*(?:[ \t]+'
                        r'(?:[A-ZÀ-Ü][A-Za-zÀ-ÿ.\u2019\x27-]*|d[aeo]s?|von|van|e|and|&)){1,10})[ \t]*$',pagina)
        if m:
            conferir_autor(m[1].strip(' .'),m[0])
        if re.search(r'(?i)ficha\s+catalog|\bCIP\b|cataloga[çc][aã]o.na.fonte',pagina):
            bloco=re.split(r'(?i)comiss[aã]o|respons[aá]ve[il]s?\s+pela',pagina)[0]
            nome=re.search(r'(?m)^\s*([A-ZÀ-Ü][\wÀ-ÿ -]+,\s*[A-ZÀ-Ü][^\n,]+)(?:,\s*\d{4}|\.)',bloco)
            if nome:conferir_autor(nome[1],nome[0])
            citado=re.search(r'(?im)^\s*[A-Z]\d{2,5}[a-z]?\s+([^/\n]+)\s*/',bloco)
            if citado and normalizar(titulo)!=normalizar(citado[1]):
                registrar('titulo_diverge_cip','titulo','título diverge do título declarado na CIP',citado[0])
            publicacao=re.search(r'(?m)^\s*([A-ZÀ-Ü][^\n,:]{2,45})[, :]\s*([^\n,]{2,60}),\s*((?:18|19|20)\d{2})\.',bloco)
            if publicacao:
                ano=str(ficha.get('data','') or '')
                if re.fullmatch(r'(?:18|19|20)\d{2}',ano) and ano!=publicacao[3] and not isbn_confirmado(ficha):
                    registrar('ano_diverge_cip','data','ano diverge da publicação local declarada na CIP',publicacao[0])

    fonte=re.search(r'(?m)^[ \t]*(?:(?i:FONTE|SOURCE)[ \t]*:[ \t]*|\()'
                    r'([A-ZÀ-Ü][\wÀ-ÿ -]+),[ \t]*([^\n]{2,130})',
                    paginas[0] if paginas else '')
    if not fonte and paginas:
        citacao=re.search(r'(?m)^[ \t]*([A-ZÀ-Ü][\wÀ-ÿ -]+),[ \t]*([^\n]{2,180})',paginas[0])
        if citacao and re.search(r':\s*[^,\n]+,\s*(?:18|19|20)\d{2}',citacao[0]):
            fonte=citacao
    if fonte:
        conferir_autor(fonte[1]+', '+fonte[2].split('.')[0],fonte[0])
        if tipo=='livro' and re.search(r'(?i)\bcap[ií]tulo\b',abertura):
            registrar('capitulo_como_livro','tipo_documento','referência da obra-fonte indica capítulo/trecho, não livro integral',fonte[0])
    if re.search(r'(?im)^\s*CHAPTER\s+(?:[IVX]+|[2-9]\d*)\s*$',abertura) and tipo not in {'trecho'}:
        registrar('capitulo_nao_classificado','tipo_documento','capítulo explícito precisa ser classificado como trecho')

    if autor and ',' in autor:
        ultimo,resto=autor.split(',',1)
        if len(normalizar(ultimo))<=4 and ultimo.strip()[:1].islower():
            fragmento=re.search(r'\b([A-Z][a-z]{1,2})\s+'+re.escape(ultimo.strip())+r'\b',abertura)
            if fragmento and normalizar(fragmento[1]) in normalizar(resto).split():
                registrar('sobrenome_fragmentado','nmAutor0','sobrenome fragmentado pelo OCR; conferir a imagem',fragmento[0])

    atual=str(ficha.get('data','') or '')
    propria=re.search(r'(?i)copyright\s*©\s*((?:19|20)\d{2})[^\n]{0,100}\b1[ªaº]?\s*edi[çc][aã]o',texto)
    if (propria and re.fullmatch(r'(?:19|20)\d{2}',atual) and atual!=propria[1]
            and not isbn_confirmado(ficha)
            and not re.search(r'(?i)t[ií]tulo\s+(?:do\s+)?original|translated\s+by',abertura)):
        registrar('ano_diverge_edicao','data','data contradiz a edição explicitamente declarada no PDF',propria[0])
    texto_fim='\n'.join(fim)
    bibliografia=(len(re.findall(r'(?m)^\s*\d{1,3}\.\s+\S',texto_fim))>=5
                  or bool(re.search(r'(?i)refer[eê]ncias\s+bibliogr|bibliograf[ií]a',texto_fim)))
    if bibliografia:
        for campo in ('editora','data'):
            valor=str(ficha.get(campo,'') or '')
            n=normalizar(valor)
            if (len(n)>=4 and n not in normalizar(texto) and n in normalizar(texto_fim)
                    and not isbn_confirmado(ficha)):
                registrar('bibliografia_como_'+campo,campo,
                          campo+' localizado apenas nas referências finais, não nos créditos iniciais',valor)
    return achados
