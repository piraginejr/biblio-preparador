#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testes da reconferencia de identidade.

O caso real que originou o modulo esta no primeiro teste: o livro
"Eu, um Discipulador" traz 978-65-01-24846-2 impresso, o pdftotext leu
978-65-0*7*-24846-2, e o aplicativo descartava ISBN invalido em silencio.
"""

import unittest
import conferir_identidade as ci


IMPRESSO = "9786501248462"     # o que esta na pagina 3
LIDO_ERRADO = "9786507248462"  # o que o pdftotext devolveu


class VerificadorTest(unittest.TestCase):

    def test_isbn_impresso_no_livro_fecha_o_verificador(self):
        self.assertTrue(ci._fecha(IMPRESSO))

    def test_isbn_lido_pelo_ocr_nao_fecha(self):
        self.assertFalse(ci._fecha(LIDO_ERRADO))

    def test_isbn10_tambem_e_verificado(self):
        self.assertTrue(ci._fecha("8535606432"))      # ISBN-10 real
        self.assertFalse(ci._fecha("8535606433"))


class CandidatosTest(unittest.TestCase):

    def test_o_isbn_correto_esta_entre_as_correcoes_de_um_digito(self):
        candidatos = [c["isbn"] for c in ci.candidatos_um_digito(LIDO_ERRADO)]
        self.assertIn(IMPRESSO, candidatos)

    def test_todo_candidato_fecha_o_verificador(self):
        for c in ci.candidatos_um_digito(LIDO_ERRADO):
            self.assertTrue(ci._fecha(c["isbn"]), c["isbn"])

    def test_candidato_registra_a_posicao_trocada(self):
        certo = [c for c in ci.candidatos_um_digito(LIDO_ERRADO)
                 if c["isbn"] == IMPRESSO][0]
        self.assertEqual(7, certo["posicao"])
        self.assertEqual("7", certo["de"])
        self.assertEqual("1", certo["para"])

    def test_numero_ja_valido_nao_gera_lista_util(self):
        # trocar um digito de um ISBN valido nunca devolve ele mesmo
        candidatos = [c["isbn"] for c in ci.candidatos_um_digito(IMPRESSO)]
        self.assertNotIn(IMPRESSO, candidatos)

    def test_so_aceita_prefixo_de_livro(self):
        for c in ci.candidatos_um_digito(LIDO_ERRADO):
            self.assertTrue(c["isbn"].startswith(("978", "979")))


class LeituraDeTextoTest(unittest.TestCase):

    def test_extrai_isbn_valido_com_tracos(self):
        texto = "Editora X\nISBN 978-65-01-24846-2\nCDD 248.4"
        self.assertEqual([IMPRESSO], ci.isbns_no_texto(texto))

    def test_isbn_invalido_nao_entra_como_valido(self):
        texto = "ISBN 978-65-07-24846-2"
        self.assertEqual([], ci.isbns_no_texto(texto))

    def test_isbn_invalido_e_registrado_como_suspeito(self):
        # esta e a informacao que o aplicativo jogava fora
        texto = "ISBN 978-65-07-24846-2"
        self.assertEqual([LIDO_ERRADO], ci.isbns_suspeitos_no_texto(texto))

    def test_texto_sem_isbn_nao_inventa_suspeito(self):
        texto = "Rua Cristiano Viana, 91 - CEP 05411-000 - telefone 2722-0355"
        self.assertEqual([], ci.isbns_suspeitos_no_texto(texto))
        self.assertEqual([], ci.isbns_no_texto(texto))


class ConferenciaTest(unittest.TestCase):
    """A conferencia sempre devolve causa - ausencia muda nao e aceitavel."""

    def test_isbn_valido_no_texto_dispensa_reler_imagem(self):
        r = ci.conferir_isbn("/nao/existe.pdf", "ISBN 978-65-01-24846-2")
        self.assertEqual(IMPRESSO, r["isbn"])
        self.assertEqual("texto", r["origem"])
        self.assertEqual([], r["paginas_relidas"])

    def test_sem_vision_cai_para_candidatos_e_nao_adota_nenhum(self):
        r = ci.conferir_isbn("/nao/existe.pdf", "ISBN 978-65-07-24846-2",
                             paginas_candidatas=[3])
        self.assertEqual("", r["isbn"])          # nao adota por inferencia
        self.assertEqual([LIDO_ERRADO], r["suspeitos"])
        self.assertTrue(r["candidatos"])
        self.assertIn("nao fecha", r["motivo"])

    def test_distingue_sem_isbn_de_isbn_ilegivel(self):
        sem = ci.conferir_isbn("/nao/existe.pdf", "Livro de 1958, sem numero")
        self.assertIn("nenhum ISBN impresso", sem["motivo"])
        self.assertEqual([], sem["suspeitos"])

        ilegivel = ci.conferir_isbn("/nao/existe.pdf", "ISBN 978-65-07-24846-2")
        self.assertIn("nao fecha", ilegivel["motivo"])
        self.assertTrue(ilegivel["suspeitos"])

    def test_motivo_nunca_volta_vazio(self):
        for texto in ("", "qualquer coisa", "ISBN 978-65-07-24846-2"):
            self.assertTrue(ci.conferir_isbn("/nao/existe.pdf", texto)["motivo"])



class AutorFragmentoDoTituloTest(unittest.TestCase):
    """Autor montado a partir do titulo - achado auditando o acervo real."""

    def setUp(self):
        import identificar
        self.I = identificar

    def test_acusa_fragmento_vindo_do_nome_do_arquivo(self):
        suspeito, motivo = self.I.autor_e_fragmento_do_titulo(
            "Things, Last", "The Church and the Last Things", "nome do arquivo")
        self.assertTrue(suspeito)
        self.assertIn("nome do arquivo", motivo)

    def test_preserva_autor_legitimo_citado_no_titulo(self):
        # "Graham, Billy" e autor de verdade, e o nome esta no titulo
        suspeito, _ = self.I.autor_e_fragmento_do_titulo(
            "Graham, Billy", "El Manual de Billy Graham para Obreros",
            "folha de rosto")
        self.assertFalse(suspeito)

    def test_fonte_forte_nunca_e_acusada(self):
        for origem in ("cip", "api", "copyright", "CIP revisada"):
            suspeito, _ = self.I.autor_e_fragmento_do_titulo(
                "Reformada, Dogmatica", "Dogmatica Reformada", origem)
            self.assertFalse(suspeito, origem)

    def test_autor_fora_do_titulo_nunca_e_acusado(self):
        suspeito, _ = self.I.autor_e_fragmento_do_titulo(
            "Bavinck, Herman", "Dogmatica Reformada", "nome do arquivo")
        self.assertFalse(suspeito)

    def test_campos_vazios_nao_quebram(self):
        for a, t in (("", "Titulo"), ("Autor", ""), ("", "")):
            self.assertEqual((False, ""),
                             self.I.autor_e_fragmento_do_titulo(a, t, ""))


if __name__ == "__main__":
    unittest.main()
