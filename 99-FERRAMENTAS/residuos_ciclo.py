"""Resíduos locais: prova por hash, dependências encerradas e origem externa intocada."""
import hashlib
import json
import pathlib


def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for bloco in iter(lambda:f.read(1024*1024),b''):h.update(bloco)
    return h.hexdigest()


def ler(p, padrao):
    try:return json.loads(p.read_text(encoding='utf-8'))
    except (OSError,ValueError):return padrao


def local_entrada(c, valor):
    p=pathlib.Path(valor)
    if not p.is_absolute():p=c['raiz']/p
    if p.is_symlink():return None
    try:
        resolvido=p.resolve(strict=True)
        resolvido.relative_to(c['entrada'].resolve())
        for x in [p,*p.parents]:
            if x.is_symlink():return None
            if x.resolve()==c['entrada'].resolve():break
    except (OSError,ValueError):return None
    return resolvido if resolvido.is_file() else None


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
