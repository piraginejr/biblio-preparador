"""Falha operacional com ficha completa não pode sumir da bancada."""
import importlib.util
import pathlib
import unittest
from unittest import mock

s = importlib.util.spec_from_file_location('bancada_falhas',
    pathlib.Path(__file__).with_name('biblioteca-local.py'))
b = importlib.util.module_from_spec(s)
s.loader.exec_module(b)


class BancadaFalhasTest(unittest.TestCase):
    def pacotes(self, estado):
        catalogo = {'livros': {'h': {'estado': estado, 'arquivo': 'teste.pdf'}}}
        with mock.patch.object(b, 'inicializar', return_value={}), \
             mock.patch.object(b, 'carregar_catalogo', return_value=catalogo), \
             mock.patch.object(b, '_ler_ficha_registro', return_value=(None, {'titulo': 'Completo'})), \
             mock.patch.object(b, 'diagnosticar_ausencias_revisao', return_value=[]), \
             mock.patch.object(b, 'montar_pacote_revisao', return_value={'hash': 'h'}):
            return b.pacotes_revisao('/unused', imprimir=False)['total']

    def test_ficha_completa_com_homonimo_ou_falha_aparece(self):
        for estado in b.api_envio.ESTADOS_FALHA_ENVIO:
            with self.subTest(estado=estado):
                self.assertEqual(1, self.pacotes(estado))

    def test_ficha_confirmada_ou_pronta_nao_reabre(self):
        for estado in ('cadastrado', 'pronto para cadastro', 'duplicado confirmado por ISBN'):
            self.assertEqual(0, self.pacotes(estado))


if __name__ == '__main__':
    unittest.main()
