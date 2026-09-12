#!/usr/bin/env python3
import importlib.util
import pathlib
import tempfile
import unittest
from unittest import mock


ARQUIVO = pathlib.Path(__file__).with_name("consultar_fontes_bibliograficas.py")
SPEC = importlib.util.spec_from_file_location("fontes_biblio_teste", ARQUIVO)
fontes = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fontes)


class RespostaFalsa:
    def __init__(self, texto="", dados=None, status_code=200):
        self.text = texto
        self._dados = dados or {}
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._dados


class SessaoFalsa:
    def __init__(self, resposta):
        self.resposta = resposta
        self.headers = {}
        self.chamadas = 0

    def get(self, *args, **kwargs):
        self.chamadas += 1
        return self.resposta


class SessaoSequencialFalsa:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.headers = {}
        self.chamadas = []

    def get(self, *args, **kwargs):
        chamada = dict(kwargs)
        if "params" in chamada:
            chamada["params"] = dict(chamada["params"])
        self.chamadas.append(chamada)
        return self.respostas.pop(0)


class FontesBibliograficasTest(unittest.TestCase):
    def test_cache_do_pdf_preparado_e_o_cache_unico_da_biblioteca(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td) / "livros"
            (raiz / "_controle").mkdir(parents=True)
            preparado = raiz / "_preparados-envio" / "livro.pdf"
            preparado.parent.mkdir()
            self.assertEqual(
                (raiz / "_controle" / "cache-fontes").resolve(),
                fontes.pasta_cache_para_pdf(preparado))

    def test_bnf_exige_isbn_exato_e_extrai_ficha(self):
        xml = '''<srw:searchRetrieveResponse xmlns:srw="http://www.loc.gov/zing/srw/">
          <srw:records><srw:record><srw:recordData>
          <oai_dc:dc xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/"
                     xmlns:dc="http://purl.org/dc/elements/1.1/">
            <dc:identifier>http://catalogue.bnf.fr/ark:/12148/cb1</dc:identifier>
            <dc:identifier>ISBN 2070363732</dc:identifier>
            <dc:title>La Promesse de l'aube / Romain Gary</dc:title>
            <dc:creator>Gary, Romain (1914-1980). Auteur du texte</dc:creator>
            <dc:publisher>Gallimard (Paris)</dc:publisher><dc:date>1973</dc:date>
            <dc:format>370 p. ; 18 cm</dc:format><dc:language>fre</dc:language>
          </oai_dc:dc></srw:recordData></srw:record></srw:records>
        </srw:searchRetrieveResponse>'''
        sessao = SessaoFalsa(RespostaFalsa(texto=xml))
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(fontes, "INTERVALO_MINIMO", 0):
            candidatos = fontes.consultar_bnf("2-07-036373-2", td, sessao=sessao)
            self.assertEqual(1, len(candidatos))
            self.assertEqual("La Promesse de l'aube", candidatos[0]["titulo"])
            self.assertEqual("Gary, Romain", candidatos[0]["autores"])
            self.assertEqual("Paris", candidatos[0]["lugar_fonte"])
            self.assertEqual("370", candidatos[0]["paginas"])
            # Cache evita uma segunda chamada.
            self.assertEqual(candidatos, fontes.consultar_bnf(
                "2070363732", td, sessao=sessao))
            self.assertEqual(1, sessao.chamadas)

    def test_bnf_so_escolhe_reimpressao_com_contexto_suficiente(self):
        candidatos = [
            {"titulo": "La promesse de l'aube", "ano": "1973", "paginas": "370"},
            {"titulo": "La promesse de l'aube", "ano": "1980", "paginas": "390"},
        ]
        escolhido, motivo = fontes.resolver_candidatos(candidatos)
        self.assertEqual({}, escolhido)
        self.assertIn("2 registros", motivo)
        escolhido, motivo = fontes.resolver_candidatos(
            candidatos, ano="1980", paginas="390", titulo="La promesse de l'aube")
        self.assertEqual("1980", escolhido["ano"])
        self.assertIn("distinguida", motivo)

    def test_internet_archive_descarta_documento_sem_isbn_exato(self):
        dados = {"response": {"docs": [
            {"identifier": "certo", "isbn": ["9780801026560"],
             "title": "Reformed dogmatics", "creator": "Herman Bavinck"},
            {"identifier": "errado", "isbn": ["9780801026577"],
             "title": "Outro volume"},
        ]}}
        self.assertEqual(["certo"], [x["identificador_fonte"]
                         for x in fontes._parse_ia(dados, "9780801026560")])

    def test_open_library_usa_chave_exata_e_cache(self):
        dados = {"ISBN:9780801026560": {
            "title": "Reformed Dogmatics", "authors": [{"name": "Herman Bavinck"}],
            "publishers": [{"name": "Baker Academic"}], "publish_date": "2008",
            "number_of_pages": 688, "subjects": [{"name": "Theology"}],
        }}
        sessao = SessaoFalsa(RespostaFalsa(dados=dados))
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(fontes, "INTERVALO_MINIMO", 0):
            resultado = fontes.consultar_open_library(
                "9780801026560", td, sessao=sessao)
            self.assertEqual("Herman Bavinck", resultado["autores"])
            self.assertEqual(resultado, fontes.consultar_open_library(
                "9780801026560", td, sessao=sessao))
            self.assertEqual(1, sessao.chamadas)

    def test_google_books_rejeita_item_de_outro_isbn(self):
        dados = {"items": [{"volumeInfo": {
            "title": "Livro aproximado", "industryIdentifiers": [
                {"type": "ISBN_13", "identifier": "9780801026577"}]}}]}
        sessao = SessaoFalsa(RespostaFalsa(dados=dados))
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(fontes, "INTERVALO_MINIMO", 0):
            self.assertEqual({}, fontes.consultar_google_books(
                "9780801026560", td, sessao=sessao))

    def test_google_books_sem_isbn_aceita_titulo_autor_fortes(self):
        dados = {"items": [{"volumeInfo": {
            "title": "Ide e fazei discípulos",
            "subtitle": "Uma introdução às missões cristãs",
            "authors": ["Roger S. Greenway"],
            "publisher": "Editora Cultura Cristã",
            "publishedDate": "2001", "pageCount": 205,
        }}]}
        sessao = SessaoFalsa(RespostaFalsa(dados=dados))
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(fontes, "INTERVALO_MINIMO", 0):
            resultado = fontes.consultar_google_books_titulo_autor(
                "Ide e fazei discípulos", "Greenway, Roger", td,
                sessao=sessao)
            self.assertEqual("titulo_autor", resultado["correspondencia"])
            self.assertEqual("Editora Cultura Cristã", resultado["editora"])
            self.assertEqual("205", resultado["paginas"])
            self.assertEqual(resultado,
                fontes.consultar_google_books_titulo_autor(
                    "Ide e fazei discípulos", "Greenway, Roger", td,
                    sessao=sessao))
            self.assertEqual(1, sessao.chamadas)

    def test_google_books_sem_isbn_rejeita_edicoes_empatadas(self):
        dados = {"items": [
            {"volumeInfo": {"title": "Livro antigo", "authors": ["Ana Silva"],
                            "publisher": "Editora A", "publishedDate": "1990"}},
            {"volumeInfo": {"title": "Livro antigo", "authors": ["Ana Silva"],
                            "publisher": "Editora B", "publishedDate": "2001"}},
        ]}
        sessao = SessaoFalsa(RespostaFalsa(dados=dados))
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(fontes, "INTERVALO_MINIMO", 0):
            self.assertEqual({}, fontes.consultar_google_books_titulo_autor(
                "Livro antigo", "Silva, Ana", td, sessao=sessao))

    def test_library_of_congress_exige_isbn_exato_e_extrai_marc(self):
        xml = '''<zs:searchRetrieveResponse xmlns:zs="http://www.loc.gov/zing/srw/">
          <zs:records><zs:record><zs:recordData>
          <record xmlns="http://www.loc.gov/MARC21/slim">
            <controlfield tag="001">12345</controlfield>
            <datafield tag="020"><subfield code="a">9781620135143</subfield></datafield>
            <datafield tag="100"><subfield code="a">Mulli, Charles</subfield></datafield>
            <datafield tag="245"><subfield code="a">Chinese diamonds for the King</subfield>
              <subfield code="b">a testimony</subfield></datafield>
            <datafield tag="264"><subfield code="a">New York</subfield>
              <subfield code="b">Example Press</subfield><subfield code="c">2015</subfield></datafield>
            <datafield tag="300"><subfield code="a">240 pages</subfield></datafield>
          </record></zs:recordData></zs:record></zs:records>
        </zs:searchRetrieveResponse>'''
        sessao = SessaoFalsa(RespostaFalsa(texto=xml))
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(fontes, "INTERVALO_MINIMO", 0):
            resultado = fontes.consultar_library_of_congress(
                "978-1-62013-514-3", td, sessao=sessao)
            self.assertEqual("Chinese diamonds for the King", resultado["titulo"])
            self.assertEqual("Mulli, Charles", resultado["autores"])
            self.assertEqual("240", resultado["paginas"])
            self.assertEqual("Example Press", resultado["editora"])

    def test_hathitrust_rejeita_registro_sem_isbn_exato(self):
        dados = {"records": {
            "a": {"isbns": ["9781620135143"], "titles": ["Correct title"],
                  "authors": ["Correct Author"], "publishers": ["Press"],
                  "publishDates": ["2015"]},
            "b": {"isbns": ["9781620135150"], "titles": ["Wrong title"]},
        }}
        sessao = SessaoFalsa(RespostaFalsa(dados=dados))
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(fontes, "INTERVALO_MINIMO", 0):
            resultado = fontes.consultar_hathitrust(
                "9781620135143", td, sessao=sessao)
            self.assertEqual("Correct title", resultado["titulo"])

    def test_crossref_aceita_artigo_com_titulo_e_autor_fortes(self):
        dados = {"message": {"items": [{
            "title": ["A New Leadership for a New Ecclesiology"],
            "author": [{"given": "I. D.", "family": "Mothoagae"},
                       {"given": "L. A.", "family": "Prior"}],
            "container-title": ["Acta Theologica"],
            "published-print": {"date-parts": [[2010]]},
            "page": "84-100", "ISSN": ["1015-8758"],
            "DOI": "10.0000/example", "type": "journal-article",
        }]}}
        sessao = SessaoFalsa(RespostaFalsa(dados=dados))
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(fontes, "INTERVALO_MINIMO", 0):
            resultado = fontes.consultar_crossref_artigo(
                "A New Leadership for a New Ecclesiology",
                "Mothoagae, I. D.", td, sessao=sessao)
            self.assertEqual("Acta Theologica", resultado["editora"])
            self.assertEqual("2010", resultado["ano"])
            self.assertEqual("1015-8758", resultado["issn"])

    def test_openalex_recupera_tese_com_autoria_e_instituicao(self):
        dados = {"results": [{
            "display_name": "Church Leadership in Urban Communities",
            "publication_year": 2021, "type": "dissertation",
            "language": "en", "id": "https://openalex.org/W123",
            "doi": "https://doi.org/10.1234/example",
            "authorships": [{
                "author": {"display_name": "John Michael Smith"},
                "institutions": [{"display_name": "Example University"}],
            }],
            "primary_location": {
                "landing_page_url": "https://repository.example/thesis",
                "source": {"display_name": "Example Repository"},
            },
            "biblio": {"first_page": "1", "last_page": "214"},
            "topics": [{"display_name": "Practical Theology"}],
        }]}
        sessao = SessaoFalsa(RespostaFalsa(dados=dados))
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(fontes, "INTERVALO_MINIMO", 0):
            resultado = fontes.consultar_openalex_academico(
                "Church Leadership in Urban Communities", "Smith, John Michael",
                "tese", td, chave="segredo", sessao=sessao)
            self.assertEqual("OpenAlex", resultado["fonte"])
            self.assertIn("Example University", resultado["instituicao"])
            self.assertEqual("1-214", resultado["paginas"])
            self.assertEqual("10.1234/example", resultado["doi"])

    def test_openalex_rejeita_autor_divergente(self):
        dados = {"results": [{
            "display_name": "Church Leadership in Urban Communities",
            "publication_year": 2021, "type": "dissertation",
            "authorships": [{"author": {"display_name": "Other Person"},
                             "institutions": []}],
            "primary_location": {},
        }]}
        sessao = SessaoFalsa(RespostaFalsa(dados=dados))
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(fontes, "INTERVALO_MINIMO", 0):
            self.assertEqual({}, fontes.consultar_openalex_academico(
                "Church Leadership in Urban Communities", "Smith, John Michael",
                "tese", td, chave="segredo", sessao=sessao))

    def test_openalex_chave_invalida_repete_no_modo_publico(self):
        dados = {"results": [{
            "display_name": "Church Leadership in Urban Communities",
            "publication_year": 2021, "type": "dissertation",
            "authorships": [{"author": {"display_name": "John Michael Smith"},
                             "institutions": []}],
            "primary_location": {},
        }]}
        sessao = SessaoSequencialFalsa([
            RespostaFalsa(dados={"error": "invalid key"}, status_code=401),
            RespostaFalsa(dados=dados),
        ])
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(fontes, "INTERVALO_MINIMO", 0):
            resultado = fontes.consultar_openalex_academico(
                "Church Leadership in Urban Communities", "Smith, John Michael",
                "tese", td, chave="inválida", sessao=sessao)
            self.assertEqual("OpenAlex", resultado["fonte"])
            self.assertEqual(2, len(sessao.chamadas))
            self.assertIn("api_key", sessao.chamadas[0]["params"])
            self.assertNotIn("api_key", sessao.chamadas[1]["params"])

    def test_core_e_fallback_opcional_com_titulo_autor_fortes(self):
        dados = {"results": [{
            "title": "Church Leadership in Urban Communities",
            "authors": [{"name": "John Michael Smith"}],
            "yearPublished": 2021, "documentType": "thesis",
            "dataProviders": [{"name": "Example University Repository"}],
            "downloadUrl": "https://example.test/thesis.pdf", "id": 42,
        }]}
        sessao = SessaoFalsa(RespostaFalsa(dados=dados))
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(fontes, "INTERVALO_MINIMO", 0):
            resultado = fontes.consultar_core_academico(
                "Church Leadership in Urban Communities", "Smith, John Michael",
                "tese", td, chave="segredo", sessao=sessao)
            self.assertEqual("CORE", resultado["fonte"])
            self.assertEqual("Example University Repository",
                             resultado["instituicao"])

    def test_core_funciona_no_modo_publico_sem_chave(self):
        dados = {"results": [{
            "title": "Church Leadership in Urban Communities",
            "authors": [{"name": "John Michael Smith"}],
            "yearPublished": 2021, "documentType": "thesis",
            "dataProviders": [{"name": "Example University Repository"}],
            "downloadUrl": "https://example.test/thesis.pdf", "id": 42,
        }]}
        sessao = SessaoSequencialFalsa([RespostaFalsa(dados=dados)])
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(fontes, "INTERVALO_MINIMO", 0), \
                mock.patch.object(fontes, "ler_chave_academica",
                                  return_value=""):
            resultado = fontes.consultar_core_academico(
                "Church Leadership in Urban Communities", "Smith, John Michael",
                "tese", td, sessao=sessao)
            self.assertEqual("CORE", resultado["fonte"])
            self.assertEqual({}, sessao.chamadas[0]["headers"])
            self.assertEqual(
                "Church Leadership in Urban Communities Smith, John Michael",
                sessao.chamadas[0]["params"]["q"])

    def test_core_amplia_para_titulo_sem_reduzir_validacao_do_autor(self):
        dados = {"results": [{
            "title": "Church Leadership in Urban Communities",
            "authors": [{"name": "John Michael Smith"}],
            "yearPublished": 2021, "documentType": "thesis",
            "dataProviders": [{"name": "Example University Repository"}],
            "downloadUrl": "https://example.test/thesis.pdf", "id": 42,
        }]}
        sessao = SessaoSequencialFalsa([
            RespostaFalsa(dados={"results": []}),
            RespostaFalsa(dados=dados),
        ])
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(fontes, "INTERVALO_MINIMO", 0), \
                mock.patch.object(fontes, "ler_chave_academica",
                                  return_value=""):
            resultado = fontes.consultar_core_academico(
                "Church Leadership in Urban Communities", "Smith, John Michael",
                "tese", td, sessao=sessao)
            self.assertEqual("CORE", resultado["fonte"])
            self.assertEqual(2, len(sessao.chamadas))
            self.assertEqual(
                "Church Leadership in Urban Communities",
                sessao.chamadas[1]["params"]["q"])

    def test_core_chave_invalida_repete_no_modo_publico(self):
        dados = {"results": [{
            "title": "Church Leadership in Urban Communities",
            "authors": [{"name": "John Michael Smith"}],
            "yearPublished": 2021, "documentType": "thesis",
            "dataProviders": [{"name": "Example University Repository"}],
            "downloadUrl": "https://example.test/thesis.pdf", "id": 42,
        }]}
        sessao = SessaoSequencialFalsa([
            RespostaFalsa(dados={"error": "invalid key"}, status_code=401),
            RespostaFalsa(dados=dados),
        ])
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(fontes, "INTERVALO_MINIMO", 0):
            resultado = fontes.consultar_core_academico(
                "Church Leadership in Urban Communities", "Smith, John Michael",
                "tese", td, chave="inválida", sessao=sessao)
            self.assertEqual("CORE", resultado["fonte"])
            self.assertEqual(2, len(sessao.chamadas))
            self.assertIn("Authorization", sessao.chamadas[0]["headers"])
            self.assertEqual({}, sessao.chamadas[1]["headers"])

    def test_oatd_gera_apenas_link_de_conferencia(self):
        link = fontes.link_oatd("Church Leadership", "Smith, John")
        self.assertTrue(link.startswith("https://oatd.org/oatd/search?"))
        self.assertIn("Church+Leadership+Smith%2C+John", link)


if __name__ == "__main__":
    unittest.main()
