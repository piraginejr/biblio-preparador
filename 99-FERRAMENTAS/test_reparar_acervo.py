import json
import pathlib
import tempfile
import unittest
from unittest import mock

import reparar_acervo as reparo


class ReparoTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = pathlib.Path(self.temp.name)
        self.pdf = self.base / 'obra.pdf'
        self.pdf.write_bytes(b'%PDF-1.4\nconteudo de teste')
        self.api = reparo.carregar_api()
        self.item = {'id': 2016, 'titulo': 'Os Livros Poéticos', 'pdf': 'obra.pdf',
                     'sha256': self.api.sha256(self.pdf), 'confirmado': True,
                     'justificativa': 'Título e autor conferidos com o PDF e cadastro'}
        self.diario = {'reparos': []}
        self.path = self.base / 'diario.json'
        self.sessao = mock.Mock()
        self.patch = mock.patch.object(reparo.subprocess, 'run', return_value=mock.Mock(returncode=0))
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def executar(self, real=True):
        return reparo.reparar_item(self.item, self.base, self.diario, self.path,
                                  self.api, self.sessao, 'chave-teste', real)

    def consulta(self, titulo='Os Livros Poéticos'):
        r = mock.Mock(status_code=200)
        r.json.return_value = {'encontrado': True, 'id': 2016, 'total_matches': 1, 'titulo': titulo}
        return r

    def sucesso(self):
        r = mock.Mock(status_code=200)
        r.json.return_value = {'id': 2016, 'operacao': 'atualizar_livro',
                               'mensagem': 'Livro atualizado com sucesso'}
        self.sessao.post.side_effect = [self.consulta(), r]

    def test_simulacao_nao_consulta_nao_envia_nao_registra(self):
        r = self.executar(False)
        self.assertEqual('simulação', r['estado'])
        self.sessao.post.assert_not_called()
        self.assertFalse(self.path.exists())

    def test_envia_apenas_anexo_preserva_metadados_e_id(self):
        self.sucesso()
        self.executar()
        envio = self.sessao.post.call_args.kwargs
        self.assertEqual({'action': 'atualizar_livro', 'id': '2016'}, envio['data'])
        self.assertEqual({'arquivo_digital'}, set(envio['files']))
        self.assertEqual('confirmado pela API', json.loads(self.path.read_text())['reparos'][0]['estado'])
        self.executar()
        self.assertEqual(2, self.sessao.post.call_count)

    def test_timeout_registra_intencao_e_impede_repeticao(self):
        self.sessao.post.side_effect = [self.consulta(), TimeoutError('rede')]
        with self.assertRaises(TimeoutError):
            self.executar()
        self.assertIn('incerto', json.loads(self.path.read_text())['reparos'][0]['estado'])
        with self.assertRaisesRegex(ValueError, 'tentativa registrada'):
            self.executar()
        self.assertEqual(2, self.sessao.post.call_count)

    def test_titulo_divergente_nao_envia(self):
        self.sessao.post.return_value = self.consulta('Outra obra')
        with self.assertRaisesRegex(ValueError, 'ID/título'):
            self.executar()
        self.assertEqual(1, self.sessao.post.call_count)
        self.assertFalse(self.path.exists())

    def test_hash_alterado_bloqueia_antes_da_consulta(self):
        self.item['sha256'] = 'errado'
        with self.assertRaisesRegex(ValueError, 'hash divergente'):
            self.executar()
        self.sessao.post.assert_not_called()

    def test_sem_confirmacao_bloqueia(self):
        self.item['confirmado'] = False
        with self.assertRaisesRegex(ValueError, 'confirmação'):
            self.executar()

    def test_arquivo_vazio_ou_invalido_nao_sobe(self):
        self.pdf.write_bytes(b'')
        with self.assertRaisesRegex(ValueError, 'vazio'):
            self.executar()
        self.pdf.write_bytes(b'nao sou PDF')
        self.item['sha256'] = self.api.sha256(self.pdf)
        with self.assertRaisesRegex(ValueError, 'assinatura'):
            self.executar()

    def test_inclusao_em_vez_de_edicao_nao_e_confirmada(self):
        r = mock.Mock(status_code=201)
        r.json.return_value = {'id': 999, 'operacao': 'cadastrar_livro'}
        self.sessao.post.side_effect = [self.consulta(), r]
        with self.assertRaisesRegex(RuntimeError, 'mesmo ID'):
            self.executar()
        self.assertIn('incerto', self.diario['reparos'][0]['estado'])


if __name__ == '__main__':
    unittest.main()
