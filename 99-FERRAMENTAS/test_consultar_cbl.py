#!/usr/bin/env python3
import importlib.util
import json
import pathlib
import tempfile
import unittest
from unittest import mock


ARQUIVO = pathlib.Path(__file__).with_name("consultar_cbl.py")
SPEC = importlib.util.spec_from_file_location("consultar_cbl_teste", ARQUIVO)
cbl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cbl)


class RespostaFalsa:
    def __init__(self, texto="", dados=None):
        self.text = texto
        self._dados = dados or {}

    def raise_for_status(self):
        return None

    def json(self):
        return self._dados


class SessaoFalsa:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.chamadas = []
        self.headers = {}

    def get(self, url, **kwargs):
        self.chamadas.append((url, kwargs))
        return self.respostas.pop(0)


class ConsultarCBLTest(unittest.TestCase):
    def setUp(self):
        cbl._CONFIG = None
        cbl._ULTIMA_CONSULTA = 0.0

    def test_reconhece_prefixos_brasileiros_sem_generalizar(self):
        self.assertTrue(cbl.isbn_brasileiro("978-85-64536-07-4"))
        self.assertTrue(cbl.isbn_brasileiro("978-65-00000-00-9"))
        self.assertTrue(cbl.isbn_brasileiro("85-64536-07-2"))
        self.assertFalse(cbl.isbn_brasileiro("978-0-8010-2656-0"))
        self.assertFalse(cbl.isbn_brasileiro("978-85-64536-07-5"))

    def test_busca_exata_mapeia_campos_e_grava_cache(self):
        pagina = '''<script>window.searchConfig = {
          "IndexName": "isbn-index",
          "QueryKey": "chave-publica",
          "ServiceName": "isbn-search-br"
        };</script>'''
        item = {
            "PartitionKey": "ISBN_Brasil_1", "RowKey": "9788564536074",
            "FormattedKey": "9788564536074", "Authors": ["Robson Rodovalho"],
            "Date": "2011-04-12T03:00:00Z", "Imprint": "Sara Brasil",
            "Subject": "Religião", "Title": "Beleza de Cristo",
            "Subtitle": None, "Countries": ["Brasil"],
            "IdiomasObra": ["Português"], "Ano": 2011,
        }
        sessao = SessaoFalsa([
            RespostaFalsa(texto=pagina), RespostaFalsa(dados={"value": [item]})])
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(cbl, "INTERVALO_MINIMO", 0):
            resultado = cbl.consultar("978-85-64536-07-4", td, sessao=sessao)
            self.assertEqual("Beleza de Cristo", resultado["titulo"])
            self.assertEqual("CBL/ISBN Brasil", resultado["fonte"])
            self.assertEqual("2011", resultado["ano"])
            cache = pathlib.Path(td, "9788564536074.json")
            self.assertTrue(cache.exists())
            self.assertEqual("ISBN exato",
                             json.loads(cache.read_text(encoding="utf-8"))["tipo_consulta"])
            # A segunda leitura vem do cache; nenhuma nova chamada e feita.
            self.assertEqual(resultado, cbl.consultar(
                "9788564536074", td, sessao=sessao))
            self.assertEqual(2, len(sessao.chamadas))

    def test_descarta_resultado_aproximado(self):
        cbl._CONFIG = {"IndexName": "indice", "QueryKey": "chave",
                       "ServiceName": "servico"}
        sessao = SessaoFalsa([RespostaFalsa(dados={"value": [{
            "RowKey": "9788564536075", "Title": "Outra edição"}]})])
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(cbl, "INTERVALO_MINIMO", 0):
            self.assertEqual({}, cbl.consultar(
                "9788564536074", td, sessao=sessao))
            dados = json.loads(pathlib.Path(
                td, "9788564536074.json").read_text(encoding="utf-8"))
            self.assertEqual("nao_encontrado", dados["status"])


if __name__ == "__main__":
    unittest.main()
