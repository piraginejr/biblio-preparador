"""Reparo deliberado de anexos por ID, separado das filas de inclusão.

Simulação por padrão. O plano precisa confirmar identidade e hash de cada PDF.
Não executa OCR, não altera metadados e nunca usa cadastrar_livro.
"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import pathlib
import subprocess
import time


def carregar_api():
    spec = importlib.util.spec_from_file_location(
        'api_reparo', pathlib.Path(__file__).with_name('enviar-livro-api.py'))
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)
    return api


def validar_item(item, base, api):
    alvo = item.get('id')
    if isinstance(alvo, bool) or not isinstance(alvo, int) or alvo < 1:
        raise ValueError('ID positivo explícito obrigatório')
    if item.get('confirmado') is not True or not str(item.get('justificativa', '')).strip():
        raise ValueError('vínculo bibliográfico precisa de confirmação e justificativa')
    if not str(item.get('titulo', '')).strip():
        raise ValueError('título confirmado obrigatório')
    pdf = pathlib.Path(item.get('pdf', ''))
    if not pdf.is_absolute():
        pdf = base / pdf
    pdf = pdf.resolve()
    if not pdf.is_file() or pdf.suffix.lower() != '.pdf' or not pdf.stat().st_size:
        raise ValueError('PDF ausente ou vazio')
    digest = api.sha256(pdf)
    if digest != item.get('sha256'):
        raise ValueError('PDF mudou desde a conferência; hash divergente')
    with pdf.open('rb') as f:
        if not f.read(1024).lstrip().startswith(b'%PDF-'):
            raise ValueError('assinatura PDF ausente')
    try:
        p = subprocess.run(['pdfinfo', str(pdf)], capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError('não foi possível validar a estrutura PDF') from exc
    if p.returncode:
        raise ValueError('estrutura PDF inválida ou protegida; reparar antes do envio')
    return pdf, digest


def consultar_id(sessao, chave, item, api):
    r = api.post_consulta_com_espera(sessao, chave,
        {'action': 'consultar_livro', 'id': item['id']})
    q = r.json()
    if (r.status_code != 200 or not q.get('encontrado')
            or str(q.get('id')) != str(item['id'])
            or q.get('total_matches') != 1
            or api._chave_textual(q.get('titulo')) != api._chave_textual(item['titulo'])):
        raise ValueError('ID/título não confirmado no servidor; nenhum anexo enviado')
    return q


def reparar_item(item, base, diario, diario_path, api, sessao=None, chave='', realmente=False):
    pdf, digest = validar_item(item, base, api)
    payload = {'action': 'atualizar_livro', 'id': str(item['id'])}
    identidade = f"biblio-reparo-pdf-{item['id']}-{digest}"
    anteriores = diario.setdefault('reparos', [])
    do_id = [r for r in anteriores if r['id'] == item['id']]
    if do_id:
        ultimo = do_id[-1]
        if ultimo.get('estado') == 'confirmado pela API' and ultimo['sha256'] == digest:
            return {'id': item['id'], 'estado': 'já confirmado; não reenviado'}
        raise ValueError('ID já tem tentativa registrada; conferir diário antes de qualquer reenvio')
    if not realmente:
        return {'id': item['id'], 'estado': 'simulação', 'payload': payload,
                'pdf': str(pdf), 'sha256': digest}
    previa = consultar_id(sessao, chave, item, api)
    registro = {'id': item['id'], 'titulo': item['titulo'], 'sha256': digest,
                'pdf': str(pdf), 'justificativa': item['justificativa'],
                'consulta_anterior': previa, 'iniciado_em': api.agora(),
                'idempotency_key': identidade, 'estado': 'resultado incerto; não reenviar'}
    anteriores.append(registro)
    api.salvar_json(diario_path, diario)
    try:
        # Revalida após a consulta: não transferir arquivo alterado desde a validação.
        if api.sha256(pdf) != digest:
            raise ValueError('PDF alterado antes do envio')
        with pdf.open('rb') as f:
            r = sessao.post(api.ENDPOINT, data=payload,
                files={'arquivo_digital': (pdf.name, f, 'application/pdf')},
                headers={'X-API-Key': chave, 'Idempotency-Key': identidade}, timeout=(30, 600))
        corpo = r.json()
        registro.update(http_status=r.status_code, resposta=corpo)
        if (r.status_code != 200 or str(corpo.get('id')) != str(item['id'])
                or corpo.get('operacao') != 'atualizar_livro'
                or not api.resposta_cadastro_confirmada(200, corpo)):
            raise RuntimeError('API não confirmou o reparo no mesmo ID')
        registro['estado'] = 'confirmado pela API'
        registro['limite_verificacao'] = 'Recibo de atualização confirmado; API não expõe hash do anexo para conferência.'
        registro['concluido_em'] = api.agora()
    except Exception as exc:
        registro['erro'] = str(exc)
        raise
    finally:
        api.salvar_json(diario_path, diario)
    return {'id': item['id'], 'estado': registro['estado']}


def executar(plano_path, diario_path, realmente=False, intervalo=2):
    api = carregar_api()
    plano_path, diario_path = pathlib.Path(plano_path).resolve(), pathlib.Path(diario_path).resolve()
    itens = json.loads(plano_path.read_text(encoding='utf-8'))['itens']
    ids = [i.get('id') for i in itens]
    if len(set(ids)) != len(ids):
        raise ValueError('plano contém IDs repetidos')
    diario_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = diario_path.with_suffix(diario_path.suffix + '.lock')
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('outro reparo usa este diário') from exc
        diario = json.loads(diario_path.read_text()) if diario_path.exists() else {'reparos': []}
        chave = api.ler_chave_chaves() if realmente else ''
        if realmente and not chave:
            raise ValueError('chave não encontrada no Chaves')
        sessao = api.criar_sessao_api() if realmente else None
        resultados = []
        for pos, item in enumerate(itens, 1):
            print(f"[{pos}/{len(itens)}] ID {item.get('id')}: {item.get('titulo')}", flush=True)
            try:
                resultado = reparar_item(item, plano_path.parent, diario, diario_path,
                    api, sessao, chave, realmente)
            except Exception as exc:
                resultado = {'id': item.get('id'), 'estado': 'pendente', 'erro': str(exc)}
            resultados.append(resultado)
            print(json.dumps(resultado, ensure_ascii=False), flush=True)
            if realmente and pos < len(itens):
                time.sleep(max(1, intervalo))
        return resultados


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('plano', help='JSON com itens de ID/título/PDF/hash confirmados')
    p.add_argument('--diario', required=True, help='diário exclusivo deste reparo, fora do Git')
    p.add_argument('--enviar', action='store_true', help='efetuar edições reais; padrão é simulação')
    args = p.parse_args()
    resultados = executar(args.plano, args.diario, args.enviar)
    raise SystemExit(1 if any(r['estado'] == 'pendente' for r in resultados) else 0)
