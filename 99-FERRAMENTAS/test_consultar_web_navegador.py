#!/usr/bin/env python3
import importlib.util
import json
import pathlib
import tempfile
import unittest


ARQUIVO = pathlib.Path(__file__).with_name("consultar-web-navegador.py")
SPEC = importlib.util.spec_from_file_location("consultar_web_navegador", ARQUIVO)
web = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(web)


class ConsultarWebNavegadorTest(unittest.TestCase):
    def test_consulta_converte_autor_bibliografico(self):
        consulta = web.montar_consulta("Crítica Textual", "Paroschi, Wilson")
        self.assertIn('"Crítica Textual"', consulta)
        self.assertIn('"Wilson Paroschi"', consulta)
        self.assertIn("editora", consulta)

    def test_normalizacao_remove_acentos(self):
        self.assertEqual("critica textual", web.normalizar("Crítica Textual"))

    def test_remove_redirecionamento_do_buscador(self):
        url = "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexemplo.org%2Flivro"
        self.assertEqual("https://exemplo.org/livro", web._url_direta(url))

    def test_consulta_reserva_sem_autor(self):
        self.assertEqual('"Livro Antigo" editora autor ano ISBN',
                         web.montar_consulta_titulo("Livro Antigo"))

    def test_pesquisa_comercial_comeca_pelo_isbn(self):
        consultas = web.montar_consultas_comerciais({
            "isbn": "9788551018743", "titulo": "Título do livro",
            "autor": "Autor, Nome"})
        self.assertEqual("9788551018743", consultas[0])
        self.assertEqual("8551018744", consultas[1])
        self.assertIn("Título do livro Autor", consultas)

    def test_consultas_progressivas_seguem_ordem_bibliografica(self):
        consultas = web.montar_consultas_comerciais({
            "isbn": "9788551018743", "isbn_confirmado": True,
            "titulo": "O Principal Propósito de Minha Vida: Reflexões Sobre John Owen",
            "subtitulo": "Reflexões Sobre John Owen", "autor": "Piper, John"})
        self.assertEqual([
            "9788551018743", "8551018744",
            "O Principal Propósito de Minha Vida: Reflexões Sobre John Owen Piper",
            "O Principal Propósito de Minha Vida Piper",
            "Principal Propósito Minha Vida Piper",
            "O Principal Propósito de Minha Vida",
        ], consultas)

    def test_isbn_nao_confirmado_nao_vira_primeira_consulta(self):
        consultas = web.montar_consultas_comerciais({
            "isbn": "9788551018743", "isbn_confirmado": False,
            "titulo": "Título Correto do Livro", "autor": "Silva, Ana"})
        self.assertNotIn("9788551018743", consultas)
        self.assertEqual("Título Correto do Livro Silva", consultas[0])

    def test_retira_autor_incorporado_ao_titulo(self):
        self.assertEqual("A mensagem da Epístola aos Hebreus",
            web.limpar_titulo_consulta(
                "A mensagem da Epístola aos Hebreus Albert Vanhoye",
                "Vanhoye, Albert"))

    def test_pendente_com_editora_tambem_entra_na_ultima_camada(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td)
            (raiz / "_controle").mkdir()
            (raiz / "_metadados").mkdir()
            ficha = raiz / "_metadados" / "livro.json"
            ficha.write_text(json.dumps({
                "arquivo": "livro.pdf", "titulo": "Livro ainda pendente",
                "nmAutor0": "Silva, Ana", "editora": "Editora conhecida",
                "tipo_documento": "livro", "isbn": ""}), encoding="utf-8")
            (raiz / "_controle" / "catalogo-local.json").write_text(
                json.dumps({"livros": {"x": {
                    "estado": "conflito", "arquivo": "livro.pdf",
                    "metadados": "_metadados/livro.json"}}}), encoding="utf-8")
            alvos = web.carregar_alvos(raiz, 0, motor="estante")
            self.assertEqual(["livro.pdf"], [x["arquivo"] for x in alvos])

    def test_estante_ignora_livro_ingles_mas_amazon_o_recebe(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td)
            (raiz / "_controle").mkdir()
            (raiz / "_metadados").mkdir()
            (raiz / "_metadados" / "book.json").write_text(json.dumps({
                "arquivo": "book.pdf", "titulo": "English Book",
                "nmAutor0": "Smith, John", "tipo_documento": "livro",
                "idioma": "eng",
            }), encoding="utf-8")
            (raiz / "_controle" / "catalogo-local.json").write_text(
                json.dumps({"livros": {"x": {"estado": "conflito",
                    "arquivo": "book.pdf", "metadados": "_metadados/book.json"}}}),
                encoding="utf-8")
            self.assertEqual([], web.carregar_alvos(
                raiz, 0, motor="estante"))
            amazon = web.carregar_alvos(raiz, 0, motor="amazon")
            self.assertEqual("eng", amazon[0]["idioma"])

    def test_titulo_interno_util_substitui_titulo_local_imprestavel(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td)
            (raiz / "_controle").mkdir()
            (raiz / "_metadados").mkdir()
            ficha = raiz / "_metadados" / "livro.json"
            ficha.write_text(json.dumps({
                "arquivo": "livro.pdf", "titulo": "Livro 10",
                "nmAutor0": "Noll, Mark A.", "tipo_documento": "livro",
                "_evidencias": {"metadados_pdf": {
                    "titulo": "Momentos Decisivos na História do Cristianismo"}}
            }), encoding="utf-8")
            (raiz / "_controle" / "catalogo-local.json").write_text(
                json.dumps({"livros": {"x": {
                    "estado": "conflito", "arquivo": "livro.pdf",
                    "metadados": "_metadados/livro.json"}}}), encoding="utf-8")
            alvos = web.carregar_alvos(raiz, 0, motor="amazon")
            self.assertEqual("Momentos Decisivos na História do Cristianismo",
                             alvos[0]["titulo"])

    def test_escolhe_resultado_amazon_por_titulo_e_autor(self):
        alvo = {"titulo": "Crítica Textual do Novo Testamento",
                "autor": "Paroschi, Wilson", "isbn": "8527501813"}
        resultados = [{
            "titulo_resultado": "Critica Textual Do Novo Testamento",
            "trecho": "por Wilson Paroschi", "url": "https://amazon.com.br/x/dp/8527501813",
        }, {
            "titulo_resultado": "Crítica Textual do Antigo Testamento",
            "trecho": "por Outro Autor", "url": "https://amazon.com.br/y/dp/1234567890",
        }]
        escolhido, pontos = web.escolher_candidato_amazon(alvo, resultados)
        self.assertIn("8527501813", escolhido["url"])
        self.assertGreaterEqual(pontos, 1.0)

    def test_converte_isbn13_em_isbn10_asin(self):
        self.assertEqual("8527501813", web.isbn13_para10("978-85-275-0181-1"))

    def test_converte_isbn10_em_isbn13(self):
        self.assertEqual("9788527501811", web.isbn10_para13("85-275-0181-3"))

    def test_dois_resultados_ruins_nao_encerram_pesquisa(self):
        alvo = {"titulo": "Crítica Textual do Novo Testamento",
                "autor": "Paroschi, Wilson", "isbn": ""}
        ruins = [
            {"titulo_resultado": "Crítica do Antigo Testamento",
             "trecho": "Outro autor", "url": "https://amazon/a"},
            {"titulo_resultado": "Introdução à crítica literária",
             "trecho": "Autor desconhecido", "url": "https://amazon/b"},
        ]
        self.assertFalse(web.candidato_suficientemente_confiavel(alvo, ruins))

    def test_edicao_ausente_no_cartao_mantem_pesquisa_progressiva(self):
        alvo = {"titulo": "Dogmática", "autor": "Barth, Karl",
                "edicao": "2ª", "isbn": ""}
        resultado = [{"titulo_resultado": "Dogmática",
                      "autor": "Karl Barth", "url": "https://amazon/item"}]
        self.assertFalse(web.candidato_suficientemente_confiavel(
            alvo, resultado))

    def test_titulo_truncado_e_autor_confirmado_podem_aprovar(self):
        alvo = {"titulo": "Doutrina Bíblica", "autor": "Grober, Glendon"}
        candidato = {"titulo_resultado": "Doutrina Bíblica da Igreja",
                     "autor": "Glendon Grober"}
        avaliacao = web.avaliar_correspondencia(alvo, candidato)
        self.assertTrue(avaliacao["aprovado"])
        self.assertIn("título truncado ou subtítulo diferente",
                      avaliacao["confirmacoes"])

    def test_isbn_volume_e_edicao_divergentes_bloqueiam(self):
        alvo = {"titulo": "Dogmática", "autor": "Barth, Karl",
                "isbn": "9788527501811", "volume": "3", "edicao": "2ª"}
        candidato = {"titulo_resultado": "Dogmática", "autor": "Karl Barth",
                     "isbn": "9788551018743", "volume": "2", "edicao": "1ª"}
        avaliacao = web.avaliar_correspondencia(alvo, candidato)
        self.assertFalse(avaliacao["aprovado"])
        self.assertEqual(["ISBN diferente", "edição diferente", "volume diferente"],
                         avaliacao["bloqueios"])

    def test_rejeicao_registra_motivos_explicitos(self):
        alvo = {"titulo": "História dos Batistas", "autor": "Mesquita, Antônio"}
        rejeitados = web.registrar_rejeicoes(alvo, [{
            "titulo_resultado": "História dos Metodistas",
            "autor": "João Outro", "url": "https://exemplo/item"}])
        self.assertEqual(1, len(rejeitados))
        self.assertIn("título divergente", rejeitados[0]["motivos"])
        self.assertIn("autor não encontrado", rejeitados[0]["motivos"])

    def test_extrai_dados_da_pagina_individual_da_estante(self):
        detalhes = web.extrair_detalhes_estante_texto("""
Autor: Wilson Paroschi
Editora: Vida Nova
Ano de publicação: 1993
Edição: 1ª edição
Páginas: 248
ISBN-10: 8527501813
""", "https://www.estantevirtual.com.br/livro/x", "Crítica Textual")
        self.assertEqual("8527501813", detalhes["isbn"])
        self.assertEqual("Vida Nova", detalhes["editora"])
        self.assertEqual("1993", detalhes["ano"])
        self.assertEqual("1ª edição", detalhes["edicao"])
        self.assertEqual("248", detalhes["paginas"])
        self.assertEqual("Wilson Paroschi", detalhes["autores"])

    def test_um_anuncio_estante_com_isbn_exato_e_decisivo(self):
        alvo = {"titulo": "Crítica Textual do Novo Testamento",
                "autor": "Paroschi, Wilson", "isbn": "9788527501811"}
        detalhes, pontos = web.escolher_candidato_estante(alvo, [{
            "titulo_resultado": "Crítica Textual do Novo Testamento",
            "autores": "Wilson Paroschi", "isbn": "8527501813",
            "editora": "Vida Nova", "ano": "1993", "paginas": "248",
            "url": "https://www.estantevirtual.com.br/livro/x"}])
        self.assertEqual("alta", detalhes["confianca"])
        self.assertIn("ISBN exato", detalhes["avaliacao"]["confirmacoes"])
        self.assertGreaterEqual(pontos, 1.0)

    def test_estante_exige_consenso_para_campos_editoriais(self):
        alvo = {"titulo": "Crítica Textual do Novo Testamento",
                "autor": "Paroschi, Wilson"}
        resultados = [
            {"titulo_resultado": "Crítica Textual do Novo Testamento",
             "autor": "Wilson Paroschi", "ano": "1993",
             "trecho": "Brochura, 248 páginas", "url": "https://ev/a"},
            {"titulo_resultado": "Critica Textual do Novo Testamento",
             "autor": "Wilson Paroschi", "ano": "1993",
             "trecho": "Livro com 248 paginas", "url": "https://ev/b"},
        ]
        detalhes, pontos = web.escolher_candidato_estante(
            alvo, resultados, {"editora": [
                {"valor": "VIDA NOVA", "quantidade": 2}]})
        self.assertEqual("alta", detalhes["confianca"])
        self.assertEqual("1993", detalhes["ano"])
        self.assertEqual("248", detalhes["paginas"])
        self.assertEqual("VIDA NOVA", detalhes["editora"])
        self.assertGreaterEqual(pontos, 0.9)

    def test_estante_nao_aceita_resultados_apenas_relacionados(self):
        alvo = {"titulo": "Mover para Deus", "autor": "Caetano, Silmara"}
        resultados = [{"titulo_resultado": "Dia a dia com Deus",
                       "autor": "Outro Autor", "ano": "2024",
                       "trecho": "", "url": "https://ev/a"}]
        detalhes, pontos = web.escolher_candidato_estante(alvo, resultados)
        self.assertEqual({}, detalhes)
        self.assertEqual(0.0, pontos)

    def test_consenso_corrige_autor_ruim_do_metadado_pdf(self):
        alvo = {"titulo": "Mais de um Século de Educação Metodista",
                "autor": "luis.cardoso"}
        resultados = [
            {"titulo_resultado": alvo["titulo"], "autor": "Paulo Ayres Mattos",
             "ano": "2000", "trecho": "96 páginas", "url": "https://ev/a"},
            {"titulo_resultado": alvo["titulo"], "autor": "Paulo Ayres Mattos",
             "ano": "2000", "trecho": "96 páginas", "url": "https://ev/b"},
        ]
        detalhes, _ = web.escolher_candidato_estante(
            alvo, resultados, {"editora": [
                {"valor": "Appris", "quantidade": 7},
                {"valor": "Cogeime", "quantidade": 2}]})
        self.assertEqual("Paulo Ayres Mattos", detalhes["autores"])
        self.assertEqual("Cogeime", detalhes["editora"])
        self.assertEqual("alta", detalhes["confianca"])

    def test_titulo_local_truncado_pode_ser_completado(self):
        alvo = {"titulo": "Doutrina Bíblica", "autor": "Grober, Glendon"}
        resultados = [
            {"titulo_resultado": "Doutrina Bíblica da Igreja",
             "autor": "Glendon Grober", "ano": "1980", "trecho": "60 páginas",
             "url": "https://ev/a"},
            {"titulo_resultado": "Doutrina Bíblica da Igreja",
             "autor": "Glendon Grober", "ano": "1980", "trecho": "58 páginas",
             "url": "https://ev/b"},
        ]
        detalhes, pontos = web.escolher_candidato_estante(alvo, resultados)
        self.assertEqual("Doutrina Bíblica da Igreja", detalhes["titulo"])
        self.assertGreaterEqual(pontos, 0.9)

    def test_identidade_do_titulo_usa_palavras_chave_obrigatorias(self):
        self.assertTrue(web.titulo_confere_por_palavras_chave(
            "Doutrina Bíblica", "A Doutrina Bíblica da Igreja"))
        self.assertFalse(web.titulo_confere_por_palavras_chave(
            "Mover para Deus", "Oração intercessória: como Deus age"))

    def test_estante_descarta_cartao_que_ainda_esta_carregando(self):
        self.assertFalse(web.resultado_estante_valido({
            "titulo_resultado": "Procurando título perfeito...",
            "autor": "Descobrindo autor...", "ano": "Localizando ano...",
            "trecho": "Carregando sinopse desta obra fascinante...",
        }))
        self.assertTrue(web.resultado_estante_valido({
            "titulo_resultado": "Uma Questão de Honra",
            "autor": "Luciano Subirá", "ano": "2015", "trecho": "",
        }))

    def test_pesquisa_prefere_autor_e_titulo_limpos_da_capa(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td)
            (raiz / "_controle").mkdir()
            (raiz / "_metadados").mkdir()
            ficha = raiz / "_metadados" / "livro.json"
            ficha.write_text(json.dumps({
                "arquivo": "livro.pdf",
                "titulo": "A mensagem da Epístola aos Hebreus Albert Vanhoye",
                "nmAutor0": "Epístola, da", "tipo_documento": "livro",
                "_evidencias": {"capa": {
                    "titulo": "A mensagem da Epístola aos Hebreus",
                    "nmAutor0": "Vanhoye, Albert"}}
            }), encoding="utf-8")
            (raiz / "_controle" / "catalogo-local.json").write_text(
                json.dumps({"livros": {"x": {"estado": "conflito",
                    "arquivo": "livro.pdf", "metadados": "_metadados/livro.json"}}}),
                encoding="utf-8")
            alvo = web.carregar_alvos(raiz, 0, motor="estante")[0]
            self.assertEqual("A mensagem da Epístola aos Hebreus", alvo["titulo"])
            self.assertEqual("Vanhoye, Albert", alvo["autor"])

    def test_cip_e_isbn_confirmado_preparam_consulta_antes_do_nome(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td)
            (raiz / "_controle").mkdir()
            (raiz / "_metadados").mkdir()
            ficha = raiz / "_metadados" / "livro.json"
            ficha.write_text(json.dumps({
                "arquivo": "nome-errado-do-arquivo.pdf",
                "titulo": "Texto incorreto do arquivo",
                "nmAutor0": "Autor, Errado", "tipo_documento": "livro",
                "isbn": "9788527501811", "isbn_confirmado_na_edicao": True,
                "evidencias": {"cip": {
                    "titulo": "Crítica Textual do Novo Testamento",
                    "autor": "Paroschi, Wilson"},
                    "titulo_nome_arquivo": "Texto incorreto do arquivo"}
            }), encoding="utf-8")
            (raiz / "_controle" / "catalogo-local.json").write_text(
                json.dumps({"livros": {"x": {"estado": "conflito",
                    "arquivo": "nome-errado-do-arquivo.pdf",
                    "metadados": "_metadados/livro.json"}}}), encoding="utf-8")
            alvo = web.carregar_alvos(raiz, 0, motor="amazon")[0]
            self.assertEqual("Crítica Textual do Novo Testamento", alvo["titulo"])
            self.assertEqual("Paroschi, Wilson", alvo["autor"])
            self.assertTrue(alvo["isbn_confirmado"])
            self.assertEqual("9788527501811",
                             web.montar_consultas_comerciais(alvo)[0])

    def test_filtro_impede_lixo_de_ocr_na_pesquisa_comercial(self):
        self.assertTrue(web.titulo_pesquisavel(
            "O Principal Propósito de Minha Vida: Reflexões Sobre John Owen"))
        self.assertFalse(web.titulo_pesquisavel("Subject:"))
        self.assertFalse(web.titulo_pesquisavel(
            "Microsoft Word - Serviço, Santidade e Solidariedade.doc"))
        self.assertFalse(web.titulo_pesquisavel("ROMANOS TAPA.indd"))
        self.assertFalse(web.titulo_pesquisavel("Livro 4"))
        self.assertFalse(web.titulo_pesquisavel("manual de"))
        self.assertFalse(web.titulo_pesquisavel("palavra " * 30))
        self.assertFalse(web.titulo_pesquisavel("do ministério DesiringGod.org"))
        self.assertFalse(web.titulo_pesquisavel(
            "BIBLICA DO THEOLOGÍA THEOLOGIA BIBLICA VELHO DO VELHO TESTAMENTO"))
        self.assertFalse(web.titulo_pesquisavel(
            "anos no Rio de Janeiro.. A eles devem os batistas grande parte do sucesso"))
        self.assertFalse(web.titulo_pesquisavel("Comentario Biblico Beacon pdf"))
        self.assertFalse(web.titulo_pesquisavel(
            "SUMÁRIO Capítulo 1 ..... 12 Capítulo 2 ..... 38"))
        self.assertFalse(web.titulo_pesquisavel(
            "Este livro procura apresentar ao leitor os fatos encontrados na pesquisa."))
        self.assertFalse(web.titulo_pesquisavel(
            "T E O L O G I A fragmento defeituoso"))


if __name__ == "__main__":
    unittest.main()
