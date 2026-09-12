import importlib.util
import pathlib
import tempfile
import unittest
from unittest import mock


ARQUIVO = pathlib.Path(__file__).with_name("consultar_grobid.py")
SPEC = importlib.util.spec_from_file_location("consultar_grobid", ARQUIVO)
grobid = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(grobid)


TEI = """<TEI xmlns="http://www.tei-c.org/ns/1.0">
<teiHeader><fileDesc><sourceDesc><biblStruct><analytic>
<title level="a">Faith and public life</title>
<author><persName><forename>Anne</forename><surname>Smith</surname></persName></author>
<author><persName>Abstract</persName></author>
</analytic><monogr><title level="j">Journal of Religion</title><imprint>
<date when="2024"/></imprint></monogr><idno type="DOI">10.1000/ABC</idno>
</biblStruct></sourceDesc></fileDesc><profileDesc><abstract><p>Study.</p></abstract>
<textClass><keywords><term>religion</term></keywords></textClass>
</profileDesc></teiHeader></TEI>"""


class ConsultarGrobidTest(unittest.TestCase):
    def test_extrai_e_filtra_falso_autor(self):
        dados = grobid.extrair_tei(TEI)
        self.assertEqual("Faith and public life", dados["titulo"])
        self.assertEqual(["Anne Smith"], dados["autores"])
        self.assertEqual("10.1000/abc", dados["doi"])

    def test_artigo_reconhecido_sempre_e_candidato(self):
        decisao = grobid.sinais_academicos("artigo", "texto curto", 12)
        self.assertTrue(decisao["consultar"])
        self.assertFalse(decisao["reclassificar_artigo"])

    def test_livro_so_reclassifica_com_pacote_academico_forte(self):
        texto = ("Abstract: study. Keywords: faith. References. "
                 "DOI: 10.1000/test")
        decisao = grobid.sinais_academicos("livro", texto, 22)
        self.assertTrue(decisao["consultar"])
        self.assertTrue(decisao["reclassificar_artigo"])

    def test_livro_extenso_com_doi_nao_e_reclassificado(self):
        texto = ("Abstract: study. Keywords: faith. References. "
                 "DOI: 10.1000/test")
        decisao = grobid.sinais_academicos("livro", texto, 350)
        self.assertFalse(decisao["consultar"])
        self.assertFalse(decisao["reclassificar_artigo"])

    def test_titulo_de_dossie_e_rejeitado(self):
        self.assertFalse(grobid.titulo_aceitavel(
            "Dossier: Religion and Health - Original article"))

    def test_nome_curto_de_periodico_nao_vira_titulo(self):
        self.assertFalse(grobid.titulo_aceitavel(
            "HTS Teologiese Studies/Theological Studies"))

    def test_doi_normaliza_travessao_tipografico(self):
        self.assertEqual(
            ["10.13154/er.v9.2019.108-138"],
            grobid.dois_no_texto(
                "http://doi.org/10.13154/er.v9.2019.108–138"))

    def test_repara_sobrenome_truncado_somente_com_recorrencia(self):
        reparado, motivo = grobid.reparar_autor_truncado(
            "Birgit Me", "Meyer (2015). Texto. Meyer (2018).")
        self.assertEqual("Birgit Meyer", reparado)
        self.assertIn("2 vezes", motivo)

    def test_nao_adivinha_sobrenome_curto_sem_recorrencia(self):
        reparado, motivo = grobid.reparar_autor_truncado(
            "Ana Li", "Li apresentou o estudo.")
        self.assertEqual("Ana Li", reparado)
        self.assertEqual("", motivo)

    def test_servico_desligado_nao_levanta_erro(self):
        with tempfile.TemporaryDirectory() as pasta:
            pdf = pathlib.Path(pasta) / "artigo.pdf"
            pdf.write_bytes(b"%PDF-test")
            with mock.patch.object(grobid, "esta_disponivel", return_value=False):
                resultado = grobid.consultar(
                    pdf, "artigo", "Abstract", 2,
                    pathlib.Path(pasta) / "cache")
        self.assertFalse(resultado["consultado"])
        self.assertIn("indisponível", resultado["motivo"])


if __name__ == "__main__":
    unittest.main()
