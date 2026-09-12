import importlib.util
import pathlib
import unittest


ARQUIVO = pathlib.Path(__file__).with_name("testar-grobid.py")
SPEC = importlib.util.spec_from_file_location("testar_grobid", ARQUIVO)
grobid = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(grobid)


TEI = """<TEI xmlns="http://www.tei-c.org/ns/1.0">
<teiHeader><fileDesc><sourceDesc><biblStruct><analytic>
<title level="a">Um artigo de teste</title>
<author><persName><forename>Maria</forename><surname>Silva</surname></persName></author>
</analytic><monogr><title level="j">Revista Exemplo</title><imprint>
<date when="2024-03-01"/></imprint></monogr><idno type="DOI">10.1/ABC</idno>
</biblStruct></sourceDesc></fileDesc><profileDesc>
<abstract><p>Resumo estruturado.</p></abstract>
<textClass><keywords><term>teologia</term></keywords></textClass>
</profileDesc></teiHeader></TEI>"""


class TestarGrobidTest(unittest.TestCase):
    def test_extrai_cabecalho_tei(self):
        dados = grobid.extrair_tei(TEI)
        self.assertEqual("Um artigo de teste", dados["titulo"])
        self.assertEqual(["Maria Silva"], dados["autores"])
        self.assertEqual("10.1/ABC", dados["doi"])
        self.assertEqual("2024", dados["ano"])
        self.assertEqual("Revista Exemplo", dados["periodico"])
        self.assertEqual("Resumo estruturado.", dados["abstract"])
        self.assertEqual(["teologia"], dados["palavras_chave"])

    def test_comparacao_tolera_acentos_e_pontuacao(self):
        extraido = {"titulo": "A ideologia de genero: uma analise",
                    "autores": ["Maria Jose Rosado Nunes"],
                    "doi": "https://doi.org/10.1/ABC", "ano": "2024"}
        esperado = {"titulo": "A ideologia de gênero - uma análise",
                    "autores": ["Maria José Rosado-Nunes"],
                    "doi": "10.1/ABC", "ano": "2024"}
        resultado = grobid.comparar(extraido, esperado)
        self.assertTrue(resultado["titulo_aprovado"])
        self.assertTrue(resultado["autores_aprovados"])
        self.assertTrue(resultado["ano_correto"])
        # A comparação de DOI é deliberadamente estrita e expõe prefixos.
        self.assertFalse(resultado["doi_correto"])


if __name__ == "__main__":
    unittest.main()
