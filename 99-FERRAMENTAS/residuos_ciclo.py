"""Resíduos locais: prova por hash, dependências encerradas e origem externa intocada."""
import hashlib
import json
import pathlib

PASTA_PENDENCIAS = '11-PENDENCIAS-DE-CADASTRO'


def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for bloco in iter(lambda:f.read(1024*1024),b''):h.update(bloco)
    return h.hexdigest()


def ler(p, padrao):
    try:return json.loads(p.read_text(encoding='utf-8'))
    except (OSError,ValueError):return padrao


def local_entrada(c, valor):
    return _local_em(c['entrada'], c['raiz'], valor)


def _local_em(base, raiz, valor):
    p=pathlib.Path(valor)
    if not p.is_absolute():p=raiz/p
    if p.is_symlink():return None
    try:
        resolvido=p.resolve(strict=True)
        resolvido.relative_to(base.resolve())
        for x in [p,*p.parents]:
            if x.is_symlink():return None
            if x.resolve()==base.resolve():break
    except (OSError,ValueError):return None
    return resolvido if resolvido.is_file() else None


def local_residuo(c, valor):
    return (local_entrada(c, valor) or
            _local_em(c['raiz']/PASTA_PENDENCIAS, c['raiz'], valor))


def planejar_pendencias(c, catalogo, historico):
    """Separa originais já convertidos, sem tratar conteúdo novo ou reenviar."""
    saida = []
    for origem, registro in historico.items():
        p = local_entrada(c, origem)
        digest = registro.get('assinatura')
        alvo = registro.get('hash_sha256')
        ficha = catalogo.get('livros', {}).get(alvo, {})
        if not (p and digest and ficha.get('correcao_remota_pendente') and sha(p) == digest):
            continue
        # Não mover a única representação disponível: o PDF correspondente
        # precisa continuar preservado dentro da biblioteca temporária.
        pdf = c['raiz']/ficha.get('caminho', '')
        try:
            pdf.resolve().relative_to(c['raiz'].resolve())
            if pdf.is_symlink() or not pdf.is_file():continue
            with pdf.open('rb') as f:
                if f.read(5) != b'%PDF-':continue
        except (OSError, ValueError):continue
        destino = c['raiz']/PASTA_PENDENCIAS/(digest[:12]+'-'+p.name)
        if destino.exists():continue  # nunca sobrescrever uma preservação anterior
        saida.append({'arquivo': str(p.relative_to(c['raiz'].resolve())),
                      'destino': str(destino.relative_to(c['raiz'])),
                      'sha256': digest, 'hash_catalogo': alvo,
                      'motivo': 'original convertido; correção remota pendente; não reprocessar'})
    return saida


def encerrado(registro):
    if registro.get('correcao_remota_pendente'):return False
    estado=registro.get('estado','')
    return ('arquivos liberados' in estado or 'arquivos locais liberados' in estado
            or estado=='descartado - não é livro'
            or (registro.get('id_remoto') and estado in {
                'cadastrado','duplicado confirmado por ISBN',
                'duplicado confirmado por título','duplicado confirmado por título e autor'}))


def planejar(c, catalogo, historico):
    por_hash={}
    for chave,r in catalogo.get('livros',{}).items():
        if not chave.startswith('duplicado:'):
            por_hash.setdefault(r.get('hash_sha256',chave),[]).append(r)
    def resolvido(digest):
        rs=por_hash.get(digest,[])
        return bool(rs) and all(encerrado(r) for r in rs)
    por_assinatura={}
    for origem,r in historico.items():
        if r.get('assinatura'):
            por_assinatura.setdefault(r['assinatura'],[]).append(r.get('hash_sha256'))
    def conteudo_resolvido(digest):
        hashes=por_assinatura.get(digest) or ([digest] if digest in por_hash else [])
        return bool(hashes) and all(resolvido(h) for h in hashes)
    saida={}
    def incluir(p, digest, motivo):
        if p and sha(p)==digest:
            saida[str(p)]={'arquivo':str(p.relative_to(c['raiz'].resolve())), 'sha256':digest,
                           'bytes':p.stat().st_size,'motivo':motivo}
    # A extensão não decide: assinatura do original + recibo de conversão
    # + cadastro encerrado permitem liberar também HTML/TXT/DOC já tratados.
    for origem, registro in historico.items():
        digest = registro.get('assinatura')
        if digest and conteudo_resolvido(digest):
            incluir(local_residuo(c, origem), digest, 'original convertido: cadastro encerrado')

    def copia_preservada(digest):
        for origem, registro in historico.items():
            if registro.get('assinatura') != digest:continue
            p = local_residuo(c, origem)
            if p and sha(p) == digest:
                return {'arquivo': str(p.relative_to(c['raiz'].resolve())), 'sha256': digest}
        return None
    # Revisão explícita para acessórios/formatos legados. Não são regras globais
    # por extensão: cada aprovação vale apenas para aquele caminho e hash.
    recibos=ler(c['controle']/'residuos-ciclo.json',{'itens':[]})
    for item in recibos.get('itens',[]):
        deps=item.get('hashes_catalogo',[])
        if (item.get('aprovado') is True and all(resolvido(h) for h in deps)):
            incluir(local_entrada(c,item.get('arquivo','')),item.get('sha256'),item.get('motivo','resíduo revisado'))
    # Novas importações guardam hashes internos. Pacotes mistos só saem quando
    # todos os documentos estão resolvidos, inclusive os convertidos de Word.
    manifestos=ler(c['controle']/'importacoes-compactados.json',{'itens':{}})
    for digest,item in manifestos.get('itens',{}).items():
        hashes=item.get('hashes_extraidos',{})
        nomes=item.get('extraidos',[])
        if not item.get('ok') or not nomes:continue
        ignorados=item.get('ignorados',[])
        inofensivos={'.exe','.dll','.msi','.ttf','.otf','.lnk','.url','.ini','.db'}
        if any(pathlib.Path(n).suffix.lower() not in inofensivos for n in ignorados):continue
        # Um pacote de documento único é redundante mesmo com correção remota
        # pendente, desde que a cópia extraída IDÊNTICA continue preservada.
        # Pacotes mistos, sem hashes ou com membros ignorados não usam essa regra.
        if len(nomes) == 1 and not ignorados and hashes.get(nomes[0]):
            preservada = copia_preservada(hashes[nomes[0]])
            origem = local_entrada(c, item.get('origem', ''))
            if preservada and origem:
                incluir(origem, digest, 'compactado redundante: cópia extraída idêntica preservada')
                if str(origem) in saida:
                    saida[str(origem)]['copia_preservada'] = preservada
                continue
        documentos=[];suportes=[];incompleto=False
        for nome in nomes:
            origem=str(pathlib.Path(item.get('destino',''))/nome)
            digest_interno=hashes.get(nome)
            antigo=historico.get(origem,{})
            if digest_interno and conteudo_resolvido(digest_interno):
                documentos.append(nome)
            elif (not digest_interno and antigo.get('hash_sha256')
                  and (conteudo_resolvido(antigo['assinatura']) if antigo.get('assinatura')
                       else resolvido(antigo['hash_sha256']))):
                documentos.append(nome)
            elif pathlib.Path(nome).suffix.lower() in {'.jpg','.jpeg','.png','.opf'} or pathlib.Path(nome).name.casefold() in {'info.txt','readme.txt'}:
                suportes.append(nome)
            else:incompleto=True
        if incompleto or not documentos:continue
        incluir(local_entrada(c,item.get('origem','')),digest,'compactado: todos os documentos resolvidos')
        # Capas e OPF dentro da extração são resíduos do mesmo pacote; nunca
        # estender isso a imagens avulsas de outras pastas.
        for nome in suportes:
            p=local_entrada(c,str(pathlib.Path(item.get('destino',''))/nome))
            if p and hashes.get(nome):incluir(p,hashes[nome],'apoio de compactado encerrado')
    return list(saida.values())


def copia_ainda_preservada(c, item):
    prova = item.get('copia_preservada')
    if not prova:return True
    p = local_residuo(c, prova.get('arquivo', ''))
    return bool(p and sha(p) == prova.get('sha256'))
