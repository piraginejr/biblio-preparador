import json
import pathlib
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

import biblio_app_visual as app
import consultar_claude as claude


class ClaudeUITest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = mock.patch.object(claude, 'pasta_config', return_value=pathlib.Path(self.tmp.name))
        self.cfg.start(); self.addCleanup(self.cfg.stop)
        self.cli = mock.patch.object(claude, 'binario', return_value='/bin/agy')
        self.cli.start(); self.addCleanup(self.cli.stop)
        self.busy = mock.patch.object(app.svc.JOBS, 'ultimo', return_value=None)
        self.job = self.busy.start(); self.addCleanup(self.busy.stop)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def post(self, dados, origin=None, tipo='application/json'):
        req = urllib.request.Request(self.url + '/api/claude', data=json.dumps(dados).encode(),
                                     headers={'Content-Type': tipo, 'Origin': origin or self.url})
        return urllib.request.urlopen(req, timeout=3)

    def test_status_e_ativacao_desativacao(self):
        with mock.patch.dict(claude.os.environ, {'BIBLIO_CLAUDE': '1'}):
            with self.post({'ativo': True}) as r:
                self.assertTrue(json.load(r)['ativo'])
            with urllib.request.urlopen(self.url + '/api/claude', timeout=3) as r:
                self.assertEqual(claude.MODELO, json.load(r)['modelo'])
            with self.post({'ativo': False}) as r:
                self.assertFalse(json.load(r)['ativo'])

    def test_configuracao_rejeita_formulario_cross_site(self):
        for origin, tipo in [('https://outro.site', 'application/json'), (self.url, 'text/plain')]:
            with self.assertRaises(urllib.error.HTTPError) as e:
                self.post({'ativo': True}, origin, tipo)
            self.assertEqual(403, e.exception.code)

    def test_nao_altera_configuracao_no_meio_de_lote(self):
        self.job.return_value = mock.Mock(estado='rodando')
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.post({'ativo': True})
        self.assertEqual(409, e.exception.code)

    def test_bancada_e_versao_contem_nova_camada(self):
        base = pathlib.Path(__file__).parent
        texto = (base / 'revisao-visual.py').read_text()
        self.assertIn('mostrarClaude(item)', texto)
        self.assertIn('esc(s.valor)', texto)
        swift = (base.parent / 'packaging/macos/BiblioPreparador.swift').read_text()
        self.assertIn('"consultar_claude.py"', swift)
        self.assertIn('"validacao_bibliografica.py"', swift)


if __name__ == '__main__':
    unittest.main()
