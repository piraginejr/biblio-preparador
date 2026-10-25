#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testes automatizados do sincronizador Git e auto-update."""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sincronizador_git as sg


class SincronizadorGitTest(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_parse_versao_compara_corretamente(self):
        self.assertTrue(sg._parse_versao("0.2.1") > sg._parse_versao("0.2.0"))
        self.assertTrue(sg._parse_versao("1.0.0") > sg._parse_versao("0.9.9"))
        self.assertTrue(sg._parse_versao("v1.2.3") == sg._parse_versao("1.2.3"))
        self.assertFalse(sg._parse_versao("0.1.9") > sg._parse_versao("0.2.0"))

    def test_mesclar_dicionario_sem_perda_e_sem_duplicata(self):
        local = {
            "Editora Vida": ["São Paulo"],
            "Ruídos": ["termo1", "termo2"]
        }
        remoto = {
            "Editora Vida": ["São Paulo", "SP"],  # Adiciona "SP"
            "Editora Hagnos": ["São Paulo"],      # Nova editora
            "Ruídos": ["termo2", "termo3"]        # Adiciona "termo3"
        }

        mesclado, qtd = sg.mesclar_dicionario(local, remoto)
        self.assertEqual(qtd, 3)
        self.assertIn("Editora Hagnos", mesclado)
        self.assertEqual(mesclado["Ruídos"], ["termo1", "termo2", "termo3"])
        self.assertEqual(mesclado["Editora Vida"], ["São Paulo", "SP"])

    @patch("sincronizador_git._fazer_requisicao_json")
    def test_verificar_atualizacao_motor_detecta_nova_versao(self, mock_get):
        mock_get.return_value = {
            "versao": "0.3.0",
            "changelog": "Novos filtros de OCR",
            "arquivos_modificados": ["99-FERRAMENTAS/ler-capa.py"]
        }

        info = sg.verificar_atualizacao_motor(versao_local="0.2.0")
        self.assertTrue(info["disponivel"])
        self.assertEqual(info["versao_remota"], "0.3.0")

    @patch("sincronizador_git._fazer_requisicao_json")
    def test_verificar_atualizacao_motor_ignora_versao_igual_ou_menor(self, mock_get):
        mock_get.return_value = {"versao": "0.2.0"}
        info = sg.verificar_atualizacao_motor(versao_local="0.2.0")
        self.assertFalse(info["disponivel"])

    @patch("sincronizador_git._fazer_requisicao_json")
    def test_verificar_atualizacao_motor_resiliente_offline(self, mock_get):
        mock_get.return_value = None  # Simula offline / erro de rede
        info = sg.verificar_atualizacao_motor(versao_local="0.2.0")
        self.assertFalse(info["disponivel"])
        self.assertEqual(info["motivo"], "sem_resposta")

    def test_consultar_ficha_cooperativa_usa_cache_local(self):
        hash_teste = "a1b2c3d4" + "0" * 56
        pasta_cache = self.temp_path / "cache"
        pasta_prefixo = pasta_cache / "a1"
        pasta_prefixo.mkdir(parents=True, exist_ok=True)

        ficha_esperada = {"titulo": "Livro de Teste", "autor": "Autor Teste"}
        with open(pasta_prefixo / f"{hash_teste}.json", "w", encoding="utf-8") as f:
            json.dump(ficha_esperada, f)

        # Sem fazer chamada de rede
        resultado = sg.consultar_ficha_cooperativa(hash_teste, pasta_cache=pasta_cache)
        self.assertEqual(resultado, ficha_esperada)

    @patch("sincronizador_git._fazer_requisicao_json")
    def test_consultar_ficha_cooperativa_baixa_e_salva_no_cache(self, mock_get):
        hash_teste = "e5f6a1b2" + "0" * 56
        pasta_cache = self.temp_path / "cache"
        ficha_remota = {"titulo": "Livro Remoto", "ano": "2024"}
        mock_get.return_value = ficha_remota

        resultado = sg.consultar_ficha_cooperativa(hash_teste, pasta_cache=pasta_cache)
        self.assertEqual(resultado, ficha_remota)

        # Verifica se gravou no cache em disco
        arquivo_gravado = pasta_cache / "e5" / f"{hash_teste}.json"
        self.assertTrue(arquivo_gravado.is_file())

    def test_exportar_revisoes_para_fichas_filtra_somente_aprovados(self):
        arquivo_revisoes = self.temp_path / "revisoes.json"
        pasta_saida = self.temp_path / "fichas"

        conteudo = {
            "livros": {
                "livro1.pdf": {
                    "hash_sha256": "12" + "a" * 62,
                    "aprovado": True,
                    "campos": {"titulo": "Livro Aprovado"}
                },
                "livro2.pdf": {
                    "hash_sha256": "34" + "b" * 62,
                    "aprovado": False,  # Não deve exportar
                    "campos": {"titulo": "Livro Não Aprovado"}
                },
                "livro3.pdf": {
                    "aprovado": True,
                    # Sem hash, não deve exportar
                    "campos": {"titulo": "Livro Sem Hash"}
                }
            }
        }
        with open(arquivo_revisoes, "w", encoding="utf-8") as f:
            json.dump(conteudo, f)

        total = sg.exportar_revisoes_para_fichas(arquivo_revisoes, pasta_saida)
        self.assertEqual(total, 1)

        arquivo_exp = pasta_saida / "12" / f"{'12' + 'a' * 62}.json"
        self.assertTrue(arquivo_exp.is_file())
        with open(arquivo_exp, "r", encoding="utf-8") as f:
            dados = json.load(f)
            self.assertEqual(dados["campos"]["titulo"], "Livro Aprovado")


if __name__ == "__main__":
    unittest.main()
