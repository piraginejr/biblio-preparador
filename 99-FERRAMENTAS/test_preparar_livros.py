#!/usr/bin/env python3
import importlib.util
import hashlib
import json
import pathlib
import tempfile
import unittest
from unittest import mock


ARQUIVO = pathlib.Path(__file__).with_name("preparar-livros.py")
SPEC = importlib.util.spec_from_file_location("preparar_livros", ARQUIVO)
prep = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prep)


class PrepararLivrosTest(unittest.TestCase):
    def test_isbn_valido_aceita_isbn10_e_recusa_ean13_de_produto(self):
        self.assertEqual("080105351X", prep.isbn_valido("0-8010-5351-X"))
        self.assertEqual("9788577790364", prep.isbn_valido("978-85-7779-036-4"))
        self.assertIsNone(prep.isbn_valido("7898521805111"))

    def test_pagina_tecnica_de_microfilme_nao_e_titulo(self):
        titulo = "TEST TARGET (MT-3) I25 22 11.8 1.4 L125"
        self.assertFalse(prep.titulo_bibliograficamente_plausivel(titulo))
        alertas = prep.alertas_plausibilidade_metadados(titulo, "", "")
        self.assertTrue(any("digitalização" in a for a in alertas))

    def test_capa_tecnica_de_digitalizacao_e_ignorada(self):
        capa = {
            "titulo": "TEST TARGET (MT-3) I25 22 11.8 1.4 L125",
            "nmAutor0": "EVALUATION, IMAGE",
            "texto_ocr": [
                "IMAGE EVALUATION", "TEST TARGET (MT-3)", "I25", "22",
                "11.8", "1.4", "L125",
            ],
        }
        self.assertTrue(prep.capa_tecnica_digitalizacao(capa))

    def test_normaliza_nome_lingua_sem_inferir_idioma(self):
        self.assertEqual("Português", prep.normalizar_nome_lingua("portugues"))
        self.assertEqual("Inglês", prep.normalizar_nome_lingua("inglês"))
        self.assertEqual("Italiano", prep.normalizar_nome_lingua("Italiano"))

    def test_coletanea_de_artigos_e_documento_com_autor_declarado(self):
        paginas = ["""Orlando E. Costas
LA REALIDAD DE LA IGLESIA EVANGELICA LATINOAMERICANA
Texto do primeiro artigo."""]
        tipo, autor = prep.tipo_documento_e_autor(
            "", paginas,
            nome="182_223Coletanea_de_Artigos_Orlando_Costas_Compilados.pdf")
        self.assertEqual("documento", tipo)
        self.assertEqual("Costas, Orlando E.", autor)

    def test_resenha_de_periodico_nao_usa_autor_do_livro(self):
        paginas = [
            """Theology Today
Christ Outside the Gate: Mission Beyond Christendom
By Orlando E. Costas
Texto da resenha.
Downloaded from ttj.sagepub.com""",
            """Review Section
Conclusão da resenha.
HUGHMOFFETT
SAMUEL
Princeton Theological Seminary""",
        ]
        tipo, autor = prep.tipo_documento_e_autor("", paginas)
        self.assertEqual("artigo", tipo)
        self.assertEqual("Moffett, Samuel Hugh", autor)

    def test_curso_basico_sem_ficha_editorial_e_documento(self):
        paginas = ["""CURSO BÁSICO
CRESCIMENTO EQUILIBRADO NA IGREJA LOCAL
CRESÇA PESQUISA E TREINAMENTO"""]
        tipo, autor = prep.tipo_documento_e_autor("", paginas)
        self.assertEqual("documento", tipo)
        self.assertEqual("[autor não identificado]", autor)

    def test_folha_de_rosto_recupera_dissertacao_brasileira(self):
        paginas = ["""UNIVERSIDADE FEDERAL DE JUIZ DE FORA
PROGRAMA DE PÓS-GRADUAÇÃO EM CIÊNCIA DA RELIGIÃO

THIAGO MOREIRA DA SILVA

A HISTÓRIA DOS BATISTAS NO BRASIL
ENTRE A MISSÃO E A IDENTIDADE

Dissertação apresentada ao Programa de Pós-Graduação em Ciência da Religião
como requisito parcial para obtenção do título de Mestre.
Orientador: Prof. Dr. João Pereira

Juiz de Fora
2015"""]
        dados = prep.metadados_academicos_paginas(paginas)
        self.assertEqual("dissertação", dados["tipo_documento"])
        self.assertEqual("Silva, Thiago Moreira Da", dados["autor"])
        self.assertIn("HISTÓRIA DOS BATISTAS", dados["titulo"])
        self.assertEqual("UNIVERSIDADE FEDERAL DE JUIZ DE FORA",
                         dados["instituicao"])
        self.assertEqual("2015", dados["ano"])

    def test_folha_de_rosto_recupera_tese_em_ingles(self):
        paginas = ["""EXAMPLE UNIVERSITY
SCHOOL OF THEOLOGY

JOHN MICHAEL SMITH

CHURCH LEADERSHIP IN URBAN COMMUNITIES

A thesis submitted to the faculty of Example University
in partial fulfillment of the requirements for the degree of Doctor of Philosophy

Boston
2021"""]
        dados = prep.metadados_academicos_paginas(paginas)
        self.assertEqual("tese", dados["tipo_documento"])
        self.assertEqual("Smith, John Michael", dados["autor"])
        self.assertEqual("CHURCH LEADERSHIP IN URBAN COMMUNITIES",
                         dados["titulo"])
        self.assertEqual("2021", dados["ano"])

    def test_isbn_nao_atravessa_quebra_de_linha(self):
        texto = "ISBN 978-0-8010-2656-0\n1. Teologia"
        self.assertEqual(["9780801026560"],
                         [c["isbn"] for c in prep.candidatos_isbn(texto)])

    def test_isbn_do_volume_certo(self):
        texto = """ISBN 978-0-8010-2632-4 (tela: v. 1)
ISBN 978-0-8010-2655-3 (tela: v. 2)
ISBN 978-0-8010-2656-0 (tela: v. 3)"""
        isbn, motivo = prep.escolher_isbn(
            prep.candidatos_isbn(texto), "3-DOGMATICA-volumen.pdf", 2006)
        self.assertEqual("9780801026560", isbn)
        self.assertIn("volume 3", motivo)

    def test_isbn_do_tomo_beacon_nao_usa_primeiro_da_colecao(self):
        texto = """TOMO 1: ISBN 978-1-56344-601-6
TOMO 2: ISBN 978-1-56344-602-3
TOMO 7: ISBN 978-1-56344-607-8
TOMO 9: ISBN 978-1-56344-609-2
TOMO 10: ISBN 978-1-56344-610-8"""
        candidatos = prep.candidatos_isbn_paginas([texto])
        isbn, motivo = prep.escolher_isbn(
            candidatos, "7-Beacon-Juan-a-Hechos.pdf", 2014)
        self.assertEqual("9781563446078", isbn)
        self.assertIn("volume 7", motivo)
        self.assertTrue(prep.isbn_confirmado_na_edicao(
            isbn, candidatos, prep.volume_edicao_do_nome(
                "7-Beacon-Juan-a-Hechos.pdf")))
        self.assertFalse(prep.isbn_confirmado_na_edicao(
            "9781563446016", candidatos, "7"))

    def test_lista_de_isbns_sem_tomo_atual_nao_confirma_edicao(self):
        candidatos = prep.candidatos_isbn_paginas([
            "TOMO 1: ISBN 978-1-56344-601-6\n"
            "TOMO 2: ISBN 978-1-56344-602-3"])
        self.assertFalse(prep.isbn_confirmado_na_edicao(
            "9781563446016", candidatos))

    def test_numeros_de_sumario_nao_viram_isbn(self):
        candidatos = prep.candidatos_isbn_paginas([
            "Diario 4, 1 de noviembre de 1739-3 de septiembre de 1741 "
            "129 133\nDiario 5, 6 de septiembre de 1741"
        ])
        self.assertTrue(candidatos, "a sequência fecha o dígito verificador")
        isbn, motivo = prep.escolher_isbn(candidatos, "diario.pdf", 0)
        self.assertEqual("", isbn)
        self.assertIn("sem rotulo bibliografico", motivo)
        self.assertFalse(prep.isbn_confirmado_na_edicao(
            candidatos[0]["isbn"], candidatos))

    def test_codigo_de_barras_isbn_valido_tem_prioridade(self):
        isbn = "9788551018743"
        self.assertEqual([isbn], prep.isbns_de_codigos_barras([
            {"valor": isbn, "tipo": "EAN13"},
            {"valor": "7891234567895", "tipo": "EAN13"},
        ]))
        escolhido, motivo = prep.escolher_isbn([
            {"isbn": "8573677481", "origem": "texto", "formato": "brochura"},
            {"isbn": isbn, "origem": "codigo de barras", "formato": "impresso"},
        ], "livro.pdf", 2020)
        self.assertEqual(isbn, escolhido)
        self.assertIn("código de barras", motivo)

    def test_isbn_impresso_na_edicao_e_confirmado_mas_o_do_nome_nao(self):
        isbn = "9788551018743"
        self.assertTrue(prep.isbn_confirmado_na_edicao(isbn, [{
            "isbn": isbn, "origem": "pagina bibliografica", "pagina": 4,
            "rotulo": "ISBN", "credito_edicao": True,
        }]))
        self.assertTrue(prep.isbn_confirmado_na_edicao(isbn, [{
            "isbn": isbn, "origem": "codigo de barras", "pagina": 200,
        }]))
        self.assertFalse(prep.isbn_confirmado_na_edicao(isbn, [{
            "isbn": isbn, "origem": "nome do arquivo", "pagina": None,
        }]))

    def test_paginas_bibliograficas_incluem_creditos_no_final(self):
        paginas = [f"Página {numero}" for numero in range(1, 51)]
        paginas[-2] = "More Titles from the Publisher\nISBN 978-0-8308-9926-5"
        paginas[-1] = "Copyright © 2016\nISBN 978-0-8308-9349-2"
        selecionadas = prep.selecionar_paginas_bibliograficas(paginas)
        self.assertEqual(1, selecionadas[0][0])
        self.assertEqual(50, selecionadas[-1][0])
        candidatos = prep.candidatos_isbn_paginas(
            [texto for _numero, texto in selecionadas],
            [numero for numero, _texto in selecionadas])
        escolhido, _motivo = prep.escolher_isbn(candidatos, "obra.pdf", 2016)
        self.assertEqual("9780830893492", escolhido)
        self.assertEqual(49, candidatos[0]["pagina"])
        self.assertTrue(prep.isbn_confirmado_na_edicao(
            escolhido, candidatos))

    def test_isbn_10_e_13_confirmam_a_mesma_edicao(self):
        self.assertTrue(prep.isbn_confirmado_na_edicao(
            "9788534910026", [{
                "isbn": "8534910022", "origem": "pagina bibliografica",
                "rotulo": "ISBN", "credito_edicao": True,
            }]))

    def test_livro_antigo_sem_codigo_nao_e_erro(self):
        self.assertEqual([], prep.isbns_de_codigos_barras([]))

    def test_dados_da_traducao_vencem_os_da_obra_original(self):
        texto = """Título del original: The Silent Shepherd © 1996 por John.
Edición en castellano: El Pastor silencioso © 2015 por Editorial Portavoz,
ISBN 978-0-8254-5608-4 (rústica)"""
        cp = prep.ler_copyright(texto)
        self.assertEqual("El Pastor silencioso", cp["titulo_edicao"])
        self.assertEqual("Editorial Portavoz", cp["editora"])
        self.assertEqual(2015, prep.ano_desta_edicao(texto))

    def test_credito_biblico_nao_muda_ano(self):
        texto = """Appel dangereux Copyright © 2012 par Paul David Tripp et
Crossway
La Bible ESV, copyright © 2001 par Crossway.
ISBN à couverture rigide : 978-1-4335-3582-6"""
        self.assertEqual(2012, prep.ano_desta_edicao(texto))

    def test_publicacao_ebook_vence_ano_de_referencia_bibliografica(self):
        texto = """Publicação no formato e-Book (agosto - 2010)
A paginação obedece à publicação impressa (outubro - 2000)
Cf. Autor, Obra, 2ª edição, Londres, 1937, pp. 20-30."""
        self.assertEqual(2010, prep.ano_desta_edicao(texto))
        self.assertEqual(2010, prep.ano_publicacao(texto))

    def test_ano_da_edicao_vence_ano_do_copyright_original(self):
        texto = """Copyright © 2004 por Luciano Subirá
5ª edição - 2015
Publicado no Brasil por: Editora Orvalho"""
        self.assertEqual(2015, prep.ano_desta_edicao(texto))
        self.assertEqual("Editora Orvalho", prep.ler_copyright(texto)["editora"])

    def test_copyright_da_traducao_decide_ano_e_editora(self):
        texto = """Edição publicada pela Kregel Publications © 1988
        Copyright da tradução © Editora Proclamação Ltda 2011
        ISBN 978-85-86261-05-3"""
        self.assertEqual(2011, prep.ano_desta_edicao(texto))
        self.assertEqual("Editora Proclamação Ltda",
                         prep.ler_copyright(texto)["editora"])

    def test_primeira_edicao_com_rotulo_antes_do_ano(self):
        self.assertEqual(2016, prep.ano_desta_edicao(
            "Primeira Edição: 2016"))

    def test_ano_de_nascimento_na_cip_nao_vira_publicacao(self):
        texto = """Payne, Tony, 1962-. II Título.
        Catalogação na publicação
        Primeira edição em português: 2019"""
        self.assertEqual(2019, prep.ano_desta_edicao(texto))
        self.assertEqual(2019, prep.ano_publicacao(texto))

    def test_pessoa_do_copyright_nao_vira_editora(self):
        cp = prep.ler_copyright("Copyright © 2012 por Tony Cooke")
        self.assertEqual("", cp["editora"])

    def test_edicao_ausente_e_primeira_presumida(self):
        self.assertEqual("1ª edição (presumida)",
                         prep.edicao_catalografica())
        self.assertEqual("5ª edição",
                         prep.edicao_catalografica("5ª edição", ""))

    def test_ano_de_ficha_nao_vira_numero_da_edicao(self):
        texto = """Aparecida, SP: Editora Santuário, 1997.
        97-2253 CDD-220.07
        Ano: 2000 99 98 97
        Edição: 6 5 4 3 2 1"""
        self.assertEqual("", prep.ler_cip(texto).get("edicao", ""))

    def test_bibliotecaria_da_cip_nao_vira_titulo(self):
        texto = """Dados Internacionais de Catalogação na Publicação (CIP)
        Angélica Ilacqua CRB-8/7057
        Scott Jr., J. Julius
        Origens judaicas do Novo Testamento / J. Julius Scott Jr. --
        São Paulo : Shedd Publicações, 2017."""
        self.assertNotEqual("Angelica Ilacqua",
                            prep.identificar.normalizar(
                                prep.ler_cip(texto).get("titulo", "")))

    def test_ano_romano_so_em_contexto_editorial(self):
        self.assertEqual(1942, prep.ano_romano_editorial(
            "PRAYER\nCopyright MCMXLII by Whitmore & Stone"))
        self.assertIsNone(prep.ano_romano_editorial("Capítulo MCMXLII"))

    def test_trabalho_academico_usa_discente_como_autor(self):
        pagina = """UNIVERSIDADE ESTADUAL PAULISTA
Disciplina: História
Docente: Profa. Maria
Discente: Vinícius Soares de Almeida
Assis, julho de 2001"""
        tipo, autor = prep.tipo_documento_e_autor(pagina, [pagina])
        self.assertEqual("trabalho acadêmico", tipo)
        self.assertEqual("Almeida, Vinícius Soares de", autor)

    def test_artigo_impresso_nao_vira_livro_do_biografado(self):
        pagina = """Editora Fiel artigos_print.php?id=211
O Médico Missionário - Robert Reid Kalley
Por Gilson Santos
Imprimir | Fechar"""
        tipo, autor = prep.tipo_documento_e_autor(pagina, [pagina])
        self.assertEqual("artigo", tipo)
        self.assertEqual("Santos, Gilson", autor)

    def test_tcc_e_separado_da_fila_de_livros(self):
        pagina = """UNIVERSIDADE METODISTA
MÁRCIO ROLDAN DE ARAUJO
TRABALHO DE CONCLUSÃO DE CURSO apresentado para obtenção do título"""
        tipo, _ = prep.tipo_documento_e_autor(pagina, [pagina])
        self.assertEqual("trabalho acadêmico", tipo)

    def test_revista_com_issn_e_separada_da_fila_de_livros(self):
        pagina = """REVISTA TEOLÓGICA
Ano 12, nº 3
ISSN 1234-567X
Artigos e resenhas"""
        tipo, _ = prep.tipo_documento_e_autor(pagina, [pagina])
        self.assertEqual("revista", tipo)

    def test_cabecalho_de_artigo_recupera_titulo_autor_e_data(self):
        pagina = """Revista Batista Pioneira
ONLINE ISSN 2316-686X - IMPRESSO ISSN 2316-462X
Vol. 7 n. 1 Junho | 2018
CONTROVÉRSIAS EM TORNO DO MARCO INICIAL
BATISTA: SANTA BÁRBARA D'OESTE OU SALVADOR?
Controversies about the initial landmark baptist
Me. Jorgevan Alves da Silva1
RESUMO
Texto do resumo."""
        dados = prep.metadados_artigo_paginas([pagina])
        self.assertEqual(
            "CONTROVÉRSIAS EM TORNO DO MARCO INICIAL "
            "BATISTA: SANTA BÁRBARA D'OESTE OU SALVADOR?",
            dados["titulo"])
        self.assertEqual("Silva, Jorgevan Alves da", dados["autor"])
        self.assertEqual("2018", dados["ano"])
        self.assertIn("2316-686X", dados["issn"])

    def test_artigo_tyndale_ignora_banner_e_recupera_autor(self):
        paginas = ["""17/04/2024, 09:29  Artefact in focus: Judaean Pillar Figurines
Receive accessible biblical scholarship directly in your inbox Subscribe Now
ARTICLE
3RD NOVEMBER 2023
Artefact in focus: Judaean Pillar Figurines
In this article, George Heath-Whyte seeks to find out what they are.
https://academic.tyndalehouse.com/explore/articles/judaean-pillar-figurines/"""]
        tipo, autor = prep.tipo_documento_e_autor(
            paginas[0], paginas, nome="Artefact in focus.pdf")
        dados = prep.metadados_artigo_paginas(paginas)
        self.assertEqual("artigo", tipo)
        self.assertEqual("Heath-Whyte, George", autor)
        self.assertEqual("Artefact in focus: Judaean Pillar Figurines",
                         dados["titulo"])
        self.assertEqual("2023", dados["ano"])
        self.assertEqual("Tyndale House", dados["editora"])

    def test_artigos_tyndale_preferem_h1_e_recortam_autor_da_chamada(self):
        casos = [
            ("Hebrew Acrostic Poems in the Bible",
             "The ABCS of Hebrew Acrostic Poems",
             "Megan Alsene-Parker delves into the artistry of the form.",
             "The ABCS of Hebrew Acrostic Poems", "Alsene-Parker, Megan"),
            ("How were the books of the Bible put together?",
             "Why do our Bibles contain these books and not others?",
             "Tony Watkins explores how the books were put together.",
             "Why do our Bibles contain these books and not others?",
             "Watkins, Tony"),
            ("Jesus as the second Adam: why does Jesus's humanity matter?",
             "Adam, again: why Jesus’s humanity matters",
             "Kirsten Mackerras looks at how Irenaeus developed his theology.",
             "Adam, again: why Jesus’s humanity matters",
             "Mackerras, Kirsten"),
        ]
        for cabecalho, h1, chamada, titulo, autor in casos:
            with self.subTest(titulo=titulo):
                pagina = f"""17/04/2024, 09:29  {cabecalho}
Receive accessible biblical scholarship directly in your inbox Subscribe Now

ARTICLE

9TH NOVEMBER 2023

{h1}

{chamada}
Texto do artigo.
https://academic.tyndalehouse.com/explore/articles/exemplo/
"""
                dados = prep.metadados_artigo_paginas([pagina])
                self.assertEqual(titulo, dados["titulo"])
                self.assertEqual(autor, dados["autor"])
                self.assertEqual("Tyndale House", dados["fonte_web"])
                self.assertTrue(dados["url"].endswith("/exemplo/"))

    def test_artigo_tyndale_sem_assinatura_nao_inventa_autor(self):
        pagina = """17/04/2024, 09:36  Learning biblical languages – where do I start?
Receive accessible biblical scholarship directly in your inbox Subscribe Now

ARTICLE

9TH FEBRUARY 2023

Starting out with biblical languages

Christians have always believed that God's word is heard through the Bible.
https://academic.tyndalehouse.com/explore/articles/starting-out-with-biblical-languages/
"""
        tipo, autor = prep.tipo_documento_e_autor(pagina, [pagina])
        dados = prep.metadados_artigo_paginas([pagina])
        self.assertEqual("artigo", tipo)
        self.assertEqual("", autor)
        self.assertEqual("", dados["autor"])
        self.assertEqual("Starting out with biblical languages", dados["titulo"])

    def test_artigo_american_bible_ignora_navegacao_e_preserva_url(self):
        pagina = """17/04/2024, 09:04  History of Translation in China | Articles | American Bible Society News
About Us Contact Us
Navigation
News Home
Ministry News
Blog
Record Magazine

History of Translation in China
May 04, 2010
Print this article
Texto do artigo.
https://news.americanbible.org/article/history-of-translation-in-china  1/4
"""
        tipo, autor = prep.tipo_documento_e_autor(pagina, [pagina])
        dados = prep.metadados_artigo_paginas([pagina])
        self.assertEqual("artigo", tipo)
        self.assertEqual("", autor)
        self.assertEqual("History of Translation in China", dados["titulo"])
        self.assertEqual("2010", dados["ano"])
        self.assertEqual("American Bible Society", dados["editora"])
        self.assertEqual(
            "https://news.americanbible.org/article/history-of-translation-in-china",
            dados["url"])

    def test_autor_de_artigo_nao_pode_conter_chamada_ou_titulo(self):
        for autor in (
                "the, Chris Fresch follows the footnotes to unravel",
                "read?, How do we choose which Bible translation to",
                "James, From Tyndale Bulletin:"):
            with self.subTest(autor=autor):
                self.assertFalse(prep.autor_bibliograficamente_plausivel(autor))

    def test_dominio_do_artigo_vence_editora_mencionada_no_corpo(self):
        editoras = {
            "copyright": "Desiring God",
            "capa": "Desiring God",
            "artigo": "Tyndale House",
            "institucional": "Outra instituição",
        }
        self.assertEqual(
            "Tyndale House",
            prep.escolher_editora_final("artigo", editoras))

    def test_artigo_academico_internacional_sem_palavra_journal(self):
        pagina = """Mothoagae & Prior A new leadership for a new ecclesiology

I.D. Mothoagae & L.A. Prior

A New Leadership for a New
Ecclesiology

Abstract
Texto do resumo.
Acta Theologica
2010 30(1): 84-100
ISSN 1015-8758"""
        tipo, autor = prep.tipo_documento_e_autor(pagina, [pagina])
        dados = prep.metadados_artigo_paginas([pagina])
        self.assertEqual("artigo", tipo)
        self.assertEqual("Mothoagae, I.D.", autor)
        self.assertEqual("A New Leadership for a New Ecclesiology",
                         dados["titulo"])
        self.assertEqual("Acta Theologica", dados["editora"])
        self.assertEqual("1015-8758", dados["issn"])

    def test_editora_de_ebook_entre_isbn_e_copyright(self):
        dados = prep.ler_copyright("""First published in 1920
ISBN 978-1-62013-514-3
Duke Classics
© 2014 Duke Classics and its licensors. All rights reserved.""")
        self.assertEqual("Duke Classics", dados["editora"])

    def test_mencao_isolada_a_revista_nao_muda_um_livro(self):
        pagina = "Este livro cita um artigo publicado em revista especializada."
        tipo, _ = prep.tipo_documento_e_autor(pagina, [pagina])
        self.assertEqual("livro", tipo)

    def test_powerpoint_com_paginas_curtas_vai_para_documentos(self):
        paginas = ["TÍTULO DO SLIDE\nPouco texto"] * 8
        tipo, _ = prep.tipo_documento_e_autor(
            "\n".join(paginas), paginas,
            {"criador": "Microsoft PowerPoint 2010"})
        self.assertEqual("documento", tipo)

    def test_powerpoint_nao_basta_sem_perfil_de_apresentacao(self):
        paginas = [("Texto corrido de capítulo. " * 80)] * 8
        tipo, _ = prep.tipo_documento_e_autor(
            "\n".join(paginas), paginas,
            {"criador": "Microsoft PowerPoint"})
        self.assertEqual("livro", tipo)

    def test_relatorio_de_pesquisa_e_documento(self):
        pagina = """Millennials In America
A Research Report by George Barna
Cultural Research Center at Arizona Christian University"""
        tipo, autor = prep.tipo_documento_e_autor(pagina, [pagina])
        self.assertEqual("documento", tipo)
        self.assertEqual("Barna, George", autor)
        self.assertFalse(prep.deve_ler_codigo_barras(tipo))

    def test_trabalho_abibet_e_documento_com_titulo_e_autor(self):
        pagina = """Os Desafios Teológicos Atuais
IV Congresso Brasileiro de Reflexão Teológica: ABIBET
“Os Batistas, seus 400 anos e sua contribuição teológica para o mundo”
Dr. D. B. Riker, Ph.D.
INTRODUÇÃO"""
        dados = prep.metadados_documentais_rotulados([pagina])
        self.assertEqual("documento", dados["tipo_documento"])
        self.assertEqual(
            "Os Batistas, seus 400 anos e sua contribuição teológica para o mundo",
            dados["titulo"])
        self.assertEqual("Riker, D. B.", dados["autor"])

    def test_concilio_pastoral_e_apostila_com_autor_rotulado(self):
        pagina = """Livro de perguntas e respostas e material de apoio
Para Concílio Examinatório ao Ministério Pastoral Batista
José Cícero Moreira, pastor"""
        dados = prep.metadados_documentais_rotulados([pagina])
        self.assertEqual("apostila", dados["tipo_documento"])
        self.assertEqual("Moreira, José Cícero", dados["autor"])

    def test_pregacao_expositiva_tematica_e_apostila(self):
        pagina = "PREGAÇÃO EXPOSITIVA TEMÁTICA\nProf. Itamir Neves de Souza"
        dados = prep.metadados_documentais_rotulados([pagina])
        self.assertEqual("apostila", dados["tipo_documento"])
        self.assertEqual("Souza, Itamir Neves de", dados["autor"])

    def test_manual_institucional_e_documento(self):
        pagina = """PROGRAMA DE FORMAÇÃO MISSIONÁRIA
Manual Institucional
Rio de Janeiro, 2021"""
        tipo, _ = prep.tipo_documento_e_autor(pagina, [pagina])
        self.assertEqual("documento", tipo)
        self.assertFalse(prep.deve_ler_codigo_barras(tipo))

    def test_word_com_cabecalho_fonte_e_autor_vai_para_documento(self):
        paginas = ["""ESTUDO: CURSO DE LIDERANÇA CRISTÃ – Por Pr Josias Moura
de Menezes
Publicado em 23/06/2009 por josiasmoura
A LIDERANÇA CRISTÃ NA ATUALIDADE"""]
        dados = prep.metadados_documentais_genericos(
            paginas, nome="Estudo-sobre-Lideranca.docx", origem_word=True)
        self.assertEqual("documento", dados["tipo_documento"])
        self.assertEqual("CURSO DE LIDERANÇA CRISTÃ", dados["titulo"])
        self.assertEqual("Menezes, Josias Moura de", dados["autor"])
        self.assertEqual("2009", dados["ano"])
        self.assertEqual("alta", dados["confianca"])

    def test_word_sem_autor_nao_inventa_autoria(self):
        paginas = ["A HISTÓRIA DOS BATISTAS\nA ORIGEM DOS ANABATISTAS\nTexto"] * 46
        dados = prep.metadados_documentais_genericos(
            paginas, nome="A-HISTORIA-DOS-BATISTAS.doc", origem_word=True)
        self.assertEqual("documento", dados["tipo_documento"])
        self.assertEqual("A HISTÓRIA DOS BATISTAS", dados["titulo"])
        self.assertEqual("", dados["autor"])
        self.assertEqual("baixa", dados["confianca"])

    def test_livro_word_com_folha_de_rosto_nao_vira_documento(self):
        pagina = """Gene Edwards
Assim uma Igreja conquista almas
Tradutor
João Marques Bentes
EMPREVAN
Caixa Postal 1165"""
        dados = prep.metadados_documentais_genericos(
            [pagina] * 80, nome="Assim-uma-Igreja.doc", origem_word=True)
        self.assertEqual({}, dados)
        tipo, _ = prep.tipo_documento_e_autor(
            pagina, [pagina] * 80, nome="Assim-uma-Igreja.doc",
            origem_word=True)
        self.assertEqual("livro", tipo)
        folha = prep.metadados_livro_word_folha_rosto(
            [pagina] * 80, "Edwards, Gene")
        self.assertEqual("Assim uma Igreja conquista almas", folha["titulo"])
        self.assertEqual("João Marques Bentes", folha["tradutor"])
        self.assertEqual("EMPREVAN", folha["editora"])

    def test_conectores_de_uma_letra_nao_sao_fragmentos_de_ocr(self):
        alertas = prep.alertas_plausibilidade_metadados(
            "A História de John Smith e Thomas Helwys – Parte Final",
            "Paixão, Marcus Vinícius Costa", "")
        self.assertNotIn("titulo com fragmentos de OCR", alertas)

    def test_resumo_ou_questionario_word_vai_para_descarte(self):
        dados = prep.metadados_documentais_genericos(
            ["RESUMO PLANEJAMENTO ESTRATÉGICO\nTexto"],
            nome="resumo-planejamento.docx", origem_word=True)
        self.assertEqual("arquivo inválido", dados["tipo_documento"])
        self.assertEqual("descarte", dados["confianca"])

    def test_lab_de_conferencia_e_apostila(self):
        pagina = """LAB | Gestão de Ministérios
GESTÃO DE MINISTÉRIOS
2 | Conferência Inspire 2021"""
        tipo, _ = prep.tipo_documento_e_autor(pagina, [pagina])
        self.assertEqual("apostila", tipo)
        self.assertFalse(prep.deve_ler_codigo_barras(tipo))

    def test_artigo_web_com_data_relativa_recupera_cabecalho(self):
        pagina = """Batistas Particulares e suas Confissões de
Fé: O início da história confessional dos Batistas
Por Marcus Vinícius Costa Paixão | 12 meses atrás
A Origem dos Batistas"""
        tipo, autor = prep.tipo_documento_e_autor(pagina, [pagina])
        self.assertEqual("artigo", tipo)
        self.assertEqual("Paixão, Marcus Vinícius Costa", autor)
        dados = prep.metadados_artigo_paginas([pagina])
        self.assertEqual(
            "Batistas Particulares e suas Confissões de Fé: O início da "
            "história confessional dos Batistas", dados["titulo"])
        self.assertEqual("Paixão, Marcus Vinícius Costa", dados["autor"])

    def test_arquivo_curto_que_comeca_em_capitulo_sem_creditos_e_trecho(self):
        paginas = [
            "1\nA VELA E O PÁSSARO\nTexto corrido do capítulo sem folha de rosto.",
            "A FOME POR MAIS DE DEUS\nContinuação do texto.",
        ] + ["Continuação do texto."] * 18
        tipo, _ = prep.tipo_documento_e_autor("\n".join(paginas[:10]), paginas)
        self.assertEqual("trecho", tipo)
        self.assertFalse(prep.deve_ler_codigo_barras(tipo))

    def test_livro_curto_com_copyright_nao_vira_trecho(self):
        paginas = [
            "1\nA VELA E O PÁSSARO\nCopyright © 2024\nEditora: Exemplo",
            "Continuação do texto.",
        ]
        tipo, _ = prep.tipo_documento_e_autor("\n".join(paginas), paginas)
        self.assertEqual("livro", tipo)

    def test_livro_continua_lendo_codigo_de_barras(self):
        self.assertTrue(prep.deve_ler_codigo_barras("livro"))

    def test_ficha_brasileira_flexivel_combina_sinais(self):
        pagina = """Dados Internacionais de Catalogação na Publicação (CIP)
SUSIN, Luiz Carlos; RODRIGUES, Jéferson Ferreira.
Fazer Teológico [recurso eletrônico] / Luiz Carlos Susin; Jéferson Ferreira
Rodrigues (Orgs.) -- Porto Alegre, RS: Editora Fi, 2015.
138 p.
ISBN - 978-85-66923-62-9
CDD-210"""
        normalizada = prep.normalizar_rotulos_numeros_ocr(pagina)
        ficha = prep.combinar_fichas_catalograficas(
            prep.ler_cip(normalizada), {},
            prep.ler_ficha_catalografica_por_sinais([pagina]))
        self.assertEqual("Fazer Teológico [recurso eletrônico]", ficha["titulo"])
        self.assertEqual("Susin, Luiz Carlos", ficha["autor"])
        self.assertEqual("Editora Fi", ficha["editora"])
        self.assertEqual("2015", ficha["ano"])
        self.assertEqual("210", ficha["cdd"])

    def test_ficha_sem_cabecalho_e_ocr_espacado(self):
        pagina = """P238o Parker, T.H.L.
O s O rá c u lo s d e D eu s / T.H.L. Parker.
S ã o P a u l o: E d i t o r a C u l t u r a C r i s t ã, 2 0 1 6
176 p.
IS B N 9 7 8 - 8 5 - 7 6 2 2 - 5 8 8 - 1
C D U 2-475"""
        ficha = prep.ler_ficha_catalografica_por_sinais([pagina])
        self.assertEqual("Parker, T.H.L", ficha["autor"])
        self.assertEqual("Editora Cultura Cristã", ficha["editora"])
        self.assertEqual("2016", ficha["ano"])
        self.assertEqual("CDU 2-475", ficha["classificacao_original"])

    def test_cip_brasileira_sem_cabecalho_le_citacao_editorial(self):
        pagina = """M367p Marshall, Colin, 1949-
Projeto videira : cultivando uma cultura de
discipulado / Colin Marshall & Tony Payne. — São José
dos Campos, SP: Fiel, 2019.
ISBN 9788581326450 (brochura)
CDD: 248.486"""
        ficha = prep.ler_ficha_catalografica_por_sinais([pagina])
        self.assertEqual("Projeto videira : cultivando uma cultura de discipulado",
                         ficha["titulo"])
        self.assertEqual("Marshall, Colin", ficha["autor"])
        self.assertEqual("Fiel", ficha["editora"])
        self.assertEqual("2019", ficha["ano"])

    def test_fragmentos_de_ocr_nao_sao_metadados_prontos(self):
        alertas = prep.alertas_plausibilidade_metadados(
            "COMENTARIO BÍBLICO BEACON", "BÍBLICO, COMENTARIO", "David Fisher")
        self.assertTrue(any("autor parece" in a for a in alertas))
        alertas = prep.alertas_plausibilidade_metadados(
            "ENÉAS TO G N IN I", "Tognini, Enéas", "Editora Vida")
        self.assertTrue(any("fragmentos de OCR" in a for a in alertas))

    def test_editora_nao_incorpora_frase_de_apresentacao(self):
        self.assertEqual(
            "Edições Vida Nova",
            prep.limpar_editora_bibliografica(
                "Edições Vida Nova tem, assim, grande prazer"))

    def test_metadado_pdf_confirmado_permite_convencionar_editora_ausente(self):
        resultado = prep.avaliar_convergencia_bibliografica({
            "tipo_documento": "livro", "titulo": "A Study In Church History",
            "nmAutor0": "Taylor, Gene", "editora": "", "data": "1997",
            "isbn": "", "isbn_confirmado_na_edicao": False,
            "origem_titulo": "metadado do PDF confirmado",
            "origem_autor": "metadado do PDF confirmado",
            "conflitos": [], "procedencia": [],
        })
        self.assertTrue(resultado["aprovada"])
        self.assertEqual("[s.n.]",
                         resultado["campos_convencionados"]["editora"])

    def test_documento_usa_nome_limpo_quando_sumario_virou_titulo(self):
        titulo, substituiu = prep.titulo_documental_sem_ruido(
            "3. Capítulo 2: Evolução da Pregação ao Longo dos Séculos "
            "2.1. A Era Apostólica e Patrística o Pregação Monástica",
            "Historia da Pregacao Crista")
        self.assertTrue(substituiu)
        self.assertEqual("Historia da Pregacao Crista", titulo)

    def test_endosso_e_paragrafo_nao_viram_titulo_ou_autor(self):
        alertas = prep.alertas_plausibilidade_metadados(
            "Por causa do seu encorajamento e horas que gastou comigo mostrando Deus",
            "qualquer pessoa que deseja prosperar financeiramente desde que siga",
            "")
        self.assertTrue(any("titulo parece frase" in a for a in alertas))
        self.assertTrue(any("autor parece frase" in a for a in alertas))

    def test_pagina_de_endossos_nao_e_folha_de_rosto(self):
        titulo, _, _ = prep.titulo_nas_paginas_iniciais([
            "ENDOSSOS\nO novo livro de Shawn Bolz é uma leitura incrível",
            "TRADUZINDO DEUS\nSHAWN BOLZ"],
            pistas=["Traduzindo Deus"], autor="Shawn Bolz")
        self.assertEqual("TRADUZINDO DEUS", titulo)

    def test_autor_cip_que_virou_paragrafo_e_rejeitado(self):
        self.assertFalse(prep.autor_bibliograficamente_plausivel(
            "ESTUDOS BIBLICOS, Este dicionário foi preparado para ajudar estudantes"))
        self.assertTrue(prep.autor_bibliograficamente_plausivel(
            "Patzia, Arthur G."))

    def test_editora_institucional_explicita_e_recuperada(self):
        self.assertEqual(
            "Associação de Seminários Teológicos Evangélicos (ASTE)",
            prep.editora_institucional_nas_paginas([
                "Edição portuguesa publicada pela Associação de Seminários "
                "Teológicos Evangélicos\nSão Paulo"]))
        self.assertEqual("World MAP", prep.editora_institucional_nas_paginas(
            ["O CAJADO DO PASTOR\nPublicado pelo: World MAP"]))

    def test_creditos_rotulados_recuperam_autores_e_instituto_editorial(self):
        paginas = ["""Lumko Institute
Lumko is the Pastoral Institute of the Southern African Catholic Bishops' Conference
No part of this book may be reproduced without permission in writing from Lumko.
Authors: Seán O'Leary and Mark Hay
ISBN: 1-874838-33-X"""]
        self.assertEqual(
            ["O'Leary, Seán", "Hay, Mark"],
            prep.autores_rotulados_nas_paginas(paginas))
        self.assertEqual("Lumko Institute",
                         prep.editora_institucional_nas_paginas(paginas))
        self.assertEqual(
            "Social Problems",
            prep.limpar_titulo_com_editora_e_serie(
                "Lumko Social Problems No. 24B- Social Awareness Series",
                "Lumko Institute"))

    def test_isbn_e_ficha_estruturada_corrigem_documento_generico(self):
        self.assertTrue(prep.deve_reclassificar_documento_como_livro(
            "documento", {"confianca": "media"}, True,
            {"titulo": "Mission in the Spirit", "autores": "Julie C. Ma",
             "editora": "Regnum Books"}, 352))
        self.assertFalse(prep.deve_reclassificar_documento_como_livro(
            "artigo", {"confianca": "media"}, True,
            {"titulo": "Artigo", "autores": "Autor",
             "editora": "Revista"}, 352))
        self.assertFalse(prep.deve_reclassificar_documento_como_livro(
            "documento", {"confianca": "media"}, False,
            {"titulo": "Documento", "autores": "Autor",
             "editora": "Instituição"}, 352))

    def test_simbolos_e_autor_incorporado_barram_tombo(self):
        alertas = prep.alertas_plausibilidade_metadados(
            "DESCOBERTAS DO$ TEMPOS BÍBLICOS", "MILLARD, ALAN", "Editora Vida")
        self.assertTrue(any("simbolos suspeitos" in a for a in alertas))
        alertas = prep.alertas_plausibilidade_metadados(
            "Atos Bob Utley", "Utley, Bob", "Darton")
        self.assertTrue(any("nome do autor" in a for a in alertas))
        alertas = prep.alertas_plausibilidade_metadados(
            "AGEU", "SCHWANTES, MILTON", "Aneas Edições Loyola*")
        self.assertTrue(any("editora contem" in a for a in alertas))
        alertas = prep.alertas_plausibilidade_metadados(
            "CATEGORIA: ESPIRITUALIDADE / ENSAIOS",
            "Bomilcar, organização: Nelson", "Editora Mundo Cristão")
        self.assertTrue(any("rotulo de categoria" in a for a in alertas))
        self.assertTrue(any("autor parece" in a for a in alertas))

    def test_cdd_antigo_com_d21(self):
        texto = """Library of Congress Cataloging-in-Publication Data
Bavinck, Herman, 1854-1921.
ISBN 978-0-8010-2656-0 (tela: v. 3)
230.42—d21 2003001037"""
        self.assertEqual("230.42", prep.ler_cip(texto)["cdd"])

    def test_ficha_antiga_sem_cabecalho_decide_a_edicao(self):
        pagina = """260.01
Grober, Glendon
A doutrina bíblica da Igreja. 5ª edição. Rio de Janeiro, Junta de
Educação Religiosa e Publicações, 1987.
58 p.
CDD - 260.01"""
        d = prep.ler_ficha_catalografica_simplificada([pagina])
        self.assertEqual("Grober, Glendon", d["autor"])
        self.assertEqual("Junta de Educação Religiosa e Publicações", d["editora"])
        self.assertEqual("1987", d["ano"])
        self.assertEqual("58", d["paginas"])
        self.assertEqual("5ª edição", d["edicao"])
        self.assertEqual("260.01", d["cdd"])

    def test_folha_de_rosto_em_varias_linhas(self):
        paginas = ["El Dolor de la\nPérdida\nCómo Recuperar la\nEsperanza\nPaul David Tripp"]
        titulo, pagina, origem = prep.titulo_nas_paginas_iniciais(
            paginas, pistas=["El Dolor de la Perdida"], autor="Tripp, Paul David")
        self.assertEqual("El Dolor de la Pérdida", titulo)
        self.assertEqual(1, pagina)
        self.assertEqual("folha de rosto", origem)

    def test_titulo_quebrado_completa_linhas_sem_repetir_pista(self):
        paginas = ["Mais de um Século de\nEducação Metodista"]
        titulo, pagina, _ = prep.titulo_nas_paginas_iniciais(
            paginas, pistas=["Mais de um século de educação metodista"])
        self.assertEqual("Mais de um Século de Educação Metodista", titulo)
        self.assertEqual(1, pagina)

    def test_folha_de_rosto_com_byline_nao_inverte_titulo_e_autor(self):
        titulo, autor = prep.titulo_autor_por_byline_folha(
            "Algo Inimaginável Pelo Dr. Barbet")
        self.assertEqual("Algo Inimaginável", titulo)
        self.assertEqual("Barbet", autor)

    def test_cip_lida_no_ocr_visual_da_capa(self):
        capa = {
            "texto_ocr": [
                "DADOS INTERNACIONAIS DE CATALOGAÇÃO NA PUBLICAÇÃO (CIP)",
                "Chan, Edmund",
                "UM TIPO CERTO - Discipulado intencional que redefine o",
                "sucesso no ministério / Edmund Chan - Curitiba: Editora Betânia,",
                "2021.",
                "272 p.: 13,5 cm x 21 cm",
                "Título original: A Certain Kind",
                "ISBN 978-65-89540-02-1",
                "1. Equipes de ministério, grupos pequenos, vida da igreja, liderança",
                "CDD 248",
            ]
        }
        cip = prep.ler_cip_ocr_visual_capa(capa)
        self.assertEqual("UM TIPO CERTO - Discipulado intencional que redefine o sucesso no ministério", cip["titulo"])
        self.assertEqual("Chan, Edmund", cip["autor"])
        self.assertEqual("Editora Betânia", cip["editora"])
        self.assertEqual("2021", cip["ano"])
        self.assertEqual("272", cip["paginas"])
        self.assertEqual("248", cip["cdd"])
        self.assertEqual([("9786589540021", "isbn")], cip["isbns"])

    def test_rodar_ocr_recusa_substituir_original(self):
        with self.assertRaises(ValueError):
            prep.rodar_ocr("/tmp/livro.pdf", "/tmp/livro.pdf")

    def test_rodar_ocr_corrige_orientacao_e_inclinacao(self):
        with mock.patch.object(prep.os.path, "isfile", return_value=True), \
             mock.patch.object(prep.os, "access", return_value=True), \
             mock.patch.object(prep.subprocess, "run") as executar, \
             mock.patch.object(prep.os, "replace"):
            self.assertTrue(prep.rodar_ocr(
                "/tmp/origem.pdf", "/tmp/destino.pdf"))
        comando = executar.call_args.args[0]
        self.assertIn("--rotate-pages", comando)
        self.assertIn("--rotate-pages-threshold", comando)
        self.assertEqual("1", comando[comando.index(
            "--rotate-pages-threshold") + 1])
        self.assertIn("--deskew", comando)

    def test_refazer_ocr_rotaciona_sem_combinacao_invalida_de_deskew(self):
        with mock.patch.object(prep.os.path, "isfile", return_value=True), \
             mock.patch.object(prep.os, "access", return_value=True), \
             mock.patch.object(prep.subprocess, "run") as executar, \
             mock.patch.object(prep.os, "replace"):
            self.assertTrue(prep.rodar_ocr(
                "/tmp/origem.pdf", "/tmp/destino.pdf", refazer=True))
        comando = executar.call_args.args[0]
        self.assertIn("--redo-ocr", comando)
        self.assertIn("--rotate-pages", comando)
        self.assertNotIn("--deskew", comando)

    def test_indice_legivel_nao_e_ocr_fraco(self):
        pagina = "\n".join(
            f"Sobrenome, Nome Completo, {n}, {n + 10}n3, {n + 20}"
            for n in range(1, 40))
        d = prep.diagnosticar_ocr("/arquivo/inexistente.pdf", [pagina])
        self.assertEqual("OCR aprovado", d["status"])
        self.assertFalse(d["paginas_texto_fraco"])

    def test_indice_curto_limpo_nao_e_texto_fraco(self):
        pagina = """Nossa essência em evidência 01
História dos Batistas 02
Princípios, Doutrinas e Práticas 03
Pastorais e Devocionais 04
Anexo Convenção Batista Brasileira 05
Movimento de igrejas e comunidades 06
Pastores e organizações religiosas 07"""
        d = prep.diagnosticar_ocr("/arquivo/inexistente.pdf", [pagina])
        self.assertEqual("OCR aprovado", d["status"])
        self.assertFalse(d["paginas_texto_fraco"])

    def test_sumario_com_pontilhados_nao_e_ocr_fraco(self):
        pagina = "SUMÁRIO\n" + "\n".join(
            f"Capítulo completo com palavras legíveis {n}"
            f"........................................ {n + 10}"
            for n in range(1, 12))
        d = prep.diagnosticar_ocr("/arquivo/inexistente.pdf", [pagina])
        self.assertEqual("OCR aprovado", d["status"])
        self.assertFalse(d["paginas_texto_fraco"])

    def test_sumario_real_curto_com_24_palavras_e_aprovado(self):
        pagina = """Sumário
Apresentação........................................................07
Introdução..........................................................11
I - O que cremos....................................................13
1.1 - Música Sacra..................................................13
1.2 - Música no Culto...............................................13
1.3 - Valores Inegociáveis..........................................14
II - Conceitos......................................................15
2.1 - Adoração......................................................15
2.2 - Louvor........................................................16
2.3 - Liturgia......................................................17
III - Anexos........................................................19
Anexo 1 - Ordem de Culto............................................19
Anexo 2 - Declaração de Niterói parte...............................23"""
        d = prep.diagnosticar_ocr("/arquivo/inexistente.pdf", [pagina])
        self.assertEqual("OCR aprovado", d["status"])
        self.assertFalse(d["paginas_texto_fraco"])

    def test_continuacao_de_indice_biblico_nao_dispara_novo_ocr(self):
        pagina = "\n".join([
            "14.19 [<<]", "14.20 [<<]", "15 [<<] , [<<]",
            "15.1 [<<]", "15.1-4 [<<]", "15.2-5 [<<]",
            "15.6 [<<] , [<<] , [<<]", "15.7-21 [<<]",
            "15.9-21 [<<]", "15.13-14 [<<]", "16.1 [<<] , [<<]",
            "17.15-19 [<<]", "18.11-12 [<<]",
        ])
        d = prep.diagnosticar_ocr("/arquivo/inexistente.pdf", [pagina])
        self.assertEqual("OCR aprovado", d["status"])
        self.assertFalse(d["paginas_texto_fraco"])

    def test_indice_biblico_sem_hyperlink_nao_dispara_novo_ocr(self):
        pagina = "\n".join([
            "Gênesis", "1.26-28 — 38", "1.28 — 74", "3.15 — 51",
            "12.1-3 — 101", "12.2 — 108", "Salmos", "2.1-3 — 48",
            "2.4-6 — 51", "2.7-9 — 37", "19.7 — 28", "46.10 — 131",
            "Mateus", "5.43-48 — 43", "28.18-20 — 37",
        ])
        d = prep.diagnosticar_ocr("/arquivo/inexistente.pdf", [pagina])
        self.assertEqual("OCR aprovado", d["status"])
        self.assertFalse(d["paginas_texto_fraco"])

    def test_indice_biblico_ingles_sem_travessao_nao_dispara_ocr(self):
        pagina = "\n".join([
            "OLD TESTAMENT", "Genesis", "2:24 77", "4:3-7 17",
            "8:20-21 190", "12:1-3 25, 28", "12:7-8 32", "Exodus",
            "3:1-15 35", "3:7-10 27", "4:27 26", "12:25-26 66",
            "15:1-18 26", "19:5-6 28, 32, 50, 284",
        ])
        d = prep.diagnosticar_ocr("/arquivo/inexistente.pdf", [pagina])
        self.assertEqual("OCR aprovado", d["status"])
        self.assertFalse(d["paginas_texto_fraco"])

    def test_continuacao_de_sumario_pontilhado_sem_cabecalho_e_legivel(self):
        pagina = "\n".join([
            "A PREGAÇÃO EXPOSITIVA ............................... 44",
            "CONCLUSÃO ................................................ 45",
            "APELO .................................................... 46",
            "Tipos de anjos ........................................... 47",
            "Quem são os anjos? ........................................ 48",
            "TIPOS DE ORAÇÃO ......................................... 50",
            "Bibliografia ............................................. 51",
        ])
        d = prep.diagnosticar_ocr("/arquivo/inexistente.pdf", [pagina])
        self.assertEqual("OCR aprovado", d["status"])
        self.assertFalse(d["paginas_texto_fraco"])

    def test_uma_pagina_fraca_em_livro_bom_nao_dispara_ocr_integral(self):
        boa = " ".join(["texto legível corretamente"] * 80)
        fraca = " ".join(["x9z@@@"] * 100)
        paginas = [boa] * 19 + [fraca]
        d = prep.diagnosticar_ocr("/arquivo/inexistente.pdf", paginas)
        self.assertEqual("OCR aprovado", d["status"])
        self.assertEqual([20], d["paginas_texto_fraco"])

    def test_paginas_visualmente_vazias_nao_reduzem_cobertura(self):
        texto = " ".join(["palavra legível"] * 100)
        paginas = [texto, texto, texto, "", ""]
        with mock.patch.object(prep, "_pagina_tem_conteudo_visual",
                               return_value=False):
            d = prep.diagnosticar_ocr("/arquivo/inexistente.pdf", paginas)
        self.assertEqual("OCR aprovado", d["status"])
        self.assertEqual([4, 5], d["paginas_sem_conteudo_visual"])
        self.assertEqual(3, d["paginas_avaliaveis"])

    def test_paginas_curtas_contam_como_pesquisaveis_sem_baixar_qualidade(self):
        texto = " ".join(["texto legível"] * 100)
        d = prep.diagnosticar_ocr(
            "/arquivo/inexistente.pdf",
            [texto, texto, texto, texto, "Capa do livro"])
        self.assertEqual("OCR aprovado", d["status"])
        self.assertEqual(5, d["paginas_pesquisaveis"])
        self.assertEqual([5], d["paginas_texto_curto"])

    def test_autor_do_nome_pode_ser_confirmado_no_miolo(self):
        paginas = ["El Dolor de la Pérdida\nPaul David Tripp"]
        self.assertTrue(prep.autor_confirmado_nas_paginas(
            paginas, "Tripp, Paul David"))

    def test_revisao_manual_exige_hash_correto(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td)
            entrada = raiz / "00-ENTRADA"
            controle = raiz / "_controle"
            entrada.mkdir(); controle.mkdir()
            pdf = entrada / "livro.pdf"
            pdf.write_bytes(b"conteudo identificado")
            digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
            dados = {"livros": {pdf.name: {
                "hash_sha256": digest, "campos": {"titulo": "Revisado"}}}}
            (controle / "revisoes-manuais.json").write_text(
                json.dumps(dados), encoding="utf-8")
            self.assertEqual("Revisado", prep.revisao_manual(pdf)["campos"]["titulo"])
            dados["livros"][pdf.name]["hash_sha256"] = "0" * 64
            (controle / "revisoes-manuais.json").write_text(
                json.dumps(dados), encoding="utf-8")
            self.assertEqual({}, prep.revisao_manual(pdf))

    def test_revisao_registra_aprendizado_sem_promover_regra(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td)
            entrada = raiz / "00-ENTRADA"
            controle = raiz / "_controle"
            entrada.mkdir(); controle.mkdir()
            pdf = entrada / "livro.pdf"
            pdf.write_bytes(b"conteudo")
            revisao = {
                "hash_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
                "campos": {"titulo": "Título verdadeiro"},
            }
            primeira = prep.registrar_aprendizados_da_revisao(
                pdf, {"titulo": "Todos os direitos reservados"}, revisao,
                agora_iso="2026-09-04T10:00:00")
            segunda = prep.registrar_aprendizados_da_revisao(
                pdf, {"titulo": "Todos os direitos reservados"}, revisao,
                agora_iso="2026-09-04T10:01:00")
            self.assertEqual(1, primeira[0]["total_arquivos"])
            self.assertEqual(1, segunda[0]["total_arquivos"])
            memoria = json.loads((controle / "aprendizados-candidatos.json")
                                  .read_text(encoding="utf-8"))
            item = next(iter(memoria["candidatos"].values()))
            self.assertEqual("candidato", item["status"])
            self.assertEqual(1, item["total_arquivos"])
            self.assertEqual(["Título verdadeiro"],
                             item["correcoes_observadas"])

    def test_aprendizado_so_recomenda_regra_apos_tres_pdfs(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td)
            entrada = raiz / "00-ENTRADA"
            controle = raiz / "_controle"
            entrada.mkdir(); controle.mkdir()
            for numero in range(3):
                pdf = entrada / f"livro-{numero}.pdf"
                pdf.write_bytes(f"conteudo-{numero}".encode())
                revisao = {
                    "hash_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
                    "campos": {"titulo": f"Título {numero}"},
                }
                resultado = prep.registrar_aprendizados_da_revisao(
                    pdf, {"titulo": "Microsoft Word"}, revisao,
                    agora_iso=f"2026-09-04T10:0{numero}:00")
            self.assertEqual(3, resultado[0]["total_arquivos"])
            memoria = json.loads((controle / "aprendizados-candidatos.json")
                                  .read_text(encoding="utf-8"))
            item = next(iter(memoria["candidatos"].values()))
            self.assertEqual("avaliar regra geral", item["recomendacao"])

    def test_ausencia_automatica_nao_vira_erro_recorrente(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td)
            entrada = raiz / "00-ENTRADA"
            controle = raiz / "_controle"
            entrada.mkdir(); controle.mkdir()
            pdf = entrada / "livro.pdf"
            pdf.write_bytes(b"conteudo")
            revisao = {"hash_sha256": "abc",
                       "campos": {"editora": "Editora Exemplo"}}
            resultado = prep.registrar_aprendizados_da_revisao(
                pdf, {"editora": ""}, revisao)
            self.assertEqual([], resultado)
            self.assertFalse((controle / "aprendizados-candidatos.json").exists())

    def test_isbn_do_opf_e_confirmado_e_prioritario(self):
        candidatos = [
            {"isbn": "9788577790364", "origem": "arquivo OPF",
             "formato": "impresso", "volume": "", "linha": ""},
            {"isbn": "8573677481", "origem": "nome do arquivo",
             "formato": "", "volume": "", "linha": ""},
        ]
        isbn, motivo = prep.escolher_isbn(candidatos, "livro.pdf", 2021)
        self.assertEqual("9788577790364", isbn)
        self.assertIn("OPF", motivo)
        self.assertTrue(prep.isbn_confirmado_na_edicao(isbn, candidatos))

    def test_plausibilidade_rejeita_ano_catalogador_e_fragmentos(self):
        self.assertFalse(prep.titulo_bibliograficamente_plausivel("2000"))
        self.assertFalse(prep.titulo_bibliograficamente_plausivel(
            "(Angélica Ilacqua CRB-8"))
        self.assertFalse(prep.autor_bibliograficamente_plausivel(
            "Eleitos, mas livres (Vida)"))
        self.assertFalse(prep.editora_bibliograficamente_plausivel(
            "enigmas e contradições da"))

    def test_editora_remove_frase_de_autorizacao(self):
        self.assertEqual("Rhema Brasil Publicações",
                         prep.limpar_editora_bibliografica(
                             "Rhema Brasil Publicações com a devida autorização de"))
        self.assertEqual("Edições Loyola", prep.limpar_editora_bibliografica(
            "Aneas Edições Loyola*"))

    def test_aviso_de_direitos_autorais_nunca_e_titulo(self):
        aviso = ("TODOS OS DIREITOS RESERVADOS - É PROIBIDA A REPRODUÇÃO "
                 "TOTAL OU PARCIAL DA OBRA sem autorização prévia")
        self.assertFalse(prep.titulo_bibliograficamente_plausivel(aviso))

    def test_editora_remove_isbn_corrompido_anexado(self):
        self.assertEqual("EDITORA KELPS", prep.limpar_editora_bibliografica(
            "EDITORA KELPS-ISBN 86 110"))

    def test_folha_word_rejeita_aviso_como_titulo(self):
        paginas = [
            "BRASIL, E ALGUMAS FIGURAS DO\n"
            "TODOS OS DIREITOS RESERVADOS - É PROIBIDA A REPRODUÇÃO\n"
            "TOTAL OU PARCIAL DA OBRA sem autorização prévia\n"
            "EDITORA KELPS-ISBN 86 110"]
        resultado = prep.metadados_livro_word_folha_rosto(
            paginas, "BRASIL, E ALGUMAS FIGURAS DO")
        self.assertEqual("", resultado["titulo"])

    def test_cip_brasileira_antiga_identifica_missionarios_americanos(self):
        texto = """CIP- Brasil- Catalogação na fonte
Biblioteca Pública Estadual Pio Vargas
Martins, Mário Ribeiro, 1943 .
M244d MISSIONÁRIOS AMERICANOS E ALGUMAS FIGURAS DO BRASIL EVANGÉLICO.
Mário Ribeiro Martins .
Goiânia. Kelps, 2007.
233 p.
ISBN:
1. Brasil-Missionários-Biografias.
CDU: 929.821.134-3(817.3)-31"""
        cip = prep.ler_cip(texto)
        self.assertEqual("brasileira antiga", cip["formato_cip"])
        self.assertEqual(
            "MISSIONÁRIOS AMERICANOS E ALGUMAS FIGURAS DO BRASIL EVANGÉLICO",
            cip["titulo"])
        self.assertEqual("Martins, Mário Ribeiro", cip["autor"])
        self.assertEqual("Goiânia", cip["cidade"])
        self.assertEqual("Kelps", cip["editora"])
        self.assertEqual("2007", cip["ano"])
        self.assertEqual("233", cip["paginas"])
        self.assertTrue(cip["classificacao_original"].startswith("CDU "))
        self.assertNotIn("cdd", cip)
        self.assertTrue(prep.cip_tem_identidade_bibliografica(cip))

    def test_cip_brasileira_remove_cabecalho_codigo_e_autor_do_titulo(self):
        texto = """Dados Internacionais de Catalogação na Publicação
CIP-Brasil. Catalogação na fonte
B739d Bost, Bryan Jay
De casa em casa: crescimento da igreja nos lares /
Bryan Jay Bost. - São Paulo : Arte Editorial, 2007.
68p.; 21cm.
ISBN 978-85-98172-17-0
CDD: 261.2"""
        cip = prep.ler_cip(texto)
        self.assertEqual("De casa em casa: crescimento da igreja nos lares",
                         cip["titulo"])
        self.assertEqual("Bost, Bryan Jay", cip["autor"])
        self.assertEqual("Arte Editorial", cip["editora"])

    def test_caderno_de_faculdade_teologica_sem_rotulo_apostila_vai_para_documentos(self):
        paginas = ["""HOMILÉTICA
FACULDADE EVANGÉLICA DE SÃO PAULO - FAESP
© 2020 - Todos os direitos reservados
Uma análise teológica sobre a arte de pregar"""]
        tipo, _autor = prep.tipo_documento_e_autor(
            "\n".join(paginas), paginas,
            nome="FAESP-HOMILETICA-MEDIO-TEOLOGIA.pdf")
        self.assertEqual("apostila", tipo)

    def test_material_de_faculdade_com_professora_autora_e_apostila(self):
        paginas = ["""PSICOLOGIA DA RELIGIÃO
Profa. Dra. Maria Celeste Castro Machado Autora
Faculdade Batista do Rio de Janeiro
Os artigos publicados são de inteira responsabilidade de seus autores"""]
        tipo, autor = prep.tipo_documento_e_autor(
            "\n".join(paginas), paginas, nome="Psicologia-da-Religiao.pdf")
        self.assertEqual("apostila", tipo)
        self.assertEqual("Machado, Maria Celeste Castro", autor)

    def test_sumario_com_sequencia_de_aulas_e_apostila(self):
        paginas = ["""SUMÁRIO
Aula 01 - Os Propósitos de Deus ........ 03
Aula 02 - Destino Ministerial ........... 08
Aula 03 - Liderança Servidora .......... 11
Aula 04 - Dons Espirituais .............. 17"""]
        tipo, _autor = prep.tipo_documento_e_autor(
            "\n".join(paginas), paginas, nome="Destino-Ministerial.pdf")
        self.assertEqual("apostila", tipo)

    def test_codigo_disciplina_e_escola_de_discipulos_e_apostila(self):
        paginas = ["""Código:
CFL6
Disciplina:
SEITAS E HERESIAS
ESCOLA DE DISCÍPULOS
Copyright © 2009 por Sóstenes Mendes Xavier"""]
        tipo, autor = prep.tipo_documento_e_autor(
            "\n".join(paginas), paginas, nome="CFL6.pdf")
        self.assertEqual("apostila", tipo)
        self.assertEqual("Xavier, Sóstenes Mendes", autor)

    def test_artigo_sem_issn_com_titulo_autor_introducao_e_afiliacao(self):
        paginas = ["""1
IGREJA MISSIONAL: O QUE É ISSO?
Rodomar Ricardo Ramlow
1. Introdução
Atualmente vem se tornando comum a utilização do termo missional.
Rodomar Ricardo Ramlow, doutor em teologia, professor e diretor na
Faculdade de Teologia Evangélica em Curitiba (FATEV)."""]
        tipo, autor = prep.tipo_documento_e_autor(
            "\n".join(paginas), paginas, nome="IGREJA-MISSIONAL.pdf")
        self.assertEqual("artigo", tipo)
        self.assertEqual("Ramlow, Rodomar Ricardo", autor)

    def test_cip_incompleta_nao_recebe_prioridade_absoluta(self):
        self.assertFalse(prep.cip_tem_identidade_bibliografica({
            "titulo": "Uma frase solta", "autor": "Silva, João"}))

    def test_similaridade_titulos_tolera_erro_de_ocr(self):
        self.assertGreaterEqual(prep.similaridade_titulos(
            "Pentecostais TOU Carismaticos? 89 1 chamado ao verdadeiro Pentecostes 959",
            "Pentecostais ou Carismáticos? Um chamado ao verdadeiro Pentecostes"),
                                0.55)

    def test_isbn_exato_reconhece_titulo_local_truncado(self):
        self.assertTrue(prep.titulo_local_e_fragmento_do_confirmado(
            "JONAS", "Jonas: introdução, tradução e comentário"))
        self.assertTrue(prep.titulo_local_e_fragmento_do_confirmado(
            "VOCÊ E", "Você é aquilo que ama"))
        self.assertFalse(prep.titulo_local_e_fragmento_do_confirmado(
            "Povo de Deus", "Deus acima de todos"))

    def test_titulo_remove_marca_decorativa_final_da_capa(self):
        self.assertEqual(
            "Deus mandou matar? 4 pontos de vista sobre o genocídio cananeu",
            prep.limpar_titulo_bibliografico(
                "Deus mandou matar? 4 pontos de vista sobre o genocídio "
                "cananeu 5a-"))

    def test_titulo_remove_autor_confirmado_somente_nas_bordas(self):
        self.assertEqual(
            "Exultação Expositiva: a pregação cristã como adoração",
            prep.limpar_titulo_bibliografico(
                "JOHN PIPER Exultação Expositiva: a pregação cristã como adoração",
                "Piper, John"))
        self.assertEqual(
            "Louvor e Adoração",
            prep.limpar_titulo_bibliografico(
                "Louvor e Adoração Domicio Junior", "Junior, Domicio"))
        self.assertEqual(
            "Vida e obra de J. C. Ryle",
            prep.limpar_titulo_bibliografico(
                "Vida e obra de J. C. Ryle", "Marcos, Armando"))
        self.assertEqual(
            "ROMANOS",
            prep.limpar_titulo_bibliografico(
                "ROMANOS Michael J. Gorman", "Gorman, Michael J."))
        self.assertEqual(
            "ISRAELITAS",
            prep.limpar_titulo_bibliografico(
                "ISRAELITAS Richard S. Hess", "Hess, Richard S."))
        self.assertEqual(
            "107 FILMES ERA DIGITAL",
            prep.limpar_titulo_bibliografico(
                "107 FILMES ERA DIGITAL_VS2025"))

    def test_autor_pode_estar_na_folha_de_rosto_depois_de_endossos(self):
        paginas = [
            "Endossos\nRichard Hays\nScott Hahn",
            "Mais endossos\nCraig Keener",
            "",
            "ROMANOS\nUn comentario teológico y pastoral\n"
            "Michael J. Gorman\nPUBLICACIONES KERIGMA",
        ]
        self.assertEqual(
            "Gorman, Michael J.",
            prep.autor_folha_rosto_confirmado(
                paginas, pagina_titulo=4))
        self.assertEqual(
            "PUBLICACIONES KERIGMA",
            prep.editora_institucional_nas_paginas(paginas))

    def test_editor_geral_nao_vira_autor_da_obra(self):
        paginas = ["", "DIARIOS, TOMO I\nEditor General\nJUSTO L. GONZÁLEZ"]
        self.assertEqual("", prep.autor_folha_rosto_confirmado(
            paginas, pagina_titulo=2))

    def test_serie_de_obras_identifica_volume_e_confirma_autor(self):
        paginas = ["", """OBRAS DE WESLEY
Edición auspiciada por
Wesley Heritage Foundation, Inc.
TOMO XI
DIARIOS, TOMO I
Editor General
JUSTO L. GONZÁLEZ"""]
        titulo, pagina, origem = prep.titulo_nas_paginas_iniciais(
            paginas, pistas=["Diario Personal de John Wesley"])
        self.assertEqual("Diarios, tomo I", titulo)
        self.assertEqual(2, pagina)
        self.assertEqual("folha de rosto do volume", origem)
        self.assertEqual(
            "Wesley, John",
            prep.autor_da_serie_obras(
                paginas,
                "245273262-Diario-Personal-de-John-Wesley-Parte-I.pdf"))
        self.assertEqual(
            "Wesley Heritage Foundation, Inc",
            prep.editora_institucional_nas_paginas(paginas))
        convergencia = prep.avaliar_convergencia_bibliografica({
            "tipo_documento": "livro", "titulo": titulo,
            "nmAutor0": "Wesley, John",
            "editora": "Wesley Heritage Foundation, Inc", "data": "",
            "isbn": "", "isbn_confirmado_na_edicao": False,
            "origem_titulo": origem,
            "origem_autor": "autor confirmado pela série de obras",
            "conflitos": [], "procedencia": [],
        })
        self.assertTrue(convergencia["aprovada"])
        self.assertEqual("[s.d.]", convergencia["campos_convencionados"]["data"])

    def test_instituicao_repetida_no_rodape_identifica_responsavel(self):
        paginas = [
            "SERMONES\nBILLY GRAHAM\nBilly Graham Evangelistic Association",
            "La oración\nBilly Graham Evangelistic Association",
            "Otro capítulo\nBilly Graham Evangelistic Association",
        ]
        self.assertEqual(
            "Billy Graham Evangelistic Association",
            prep.editora_institucional_nas_paginas(paginas))
        self.assertNotIn(
            "editora coincide com o nome do autor",
            prep.alertas_plausibilidade_metadados(
                "Sermones", "Graham, Billy",
                "Billy Graham Evangelistic Association"))

    def test_nome_do_arquivo_nao_rouba_ultima_palavra_do_titulo(self):
        self.assertEqual(
            ("Louvor e Adoracao", "Junior, Domicio"),
            prep.do_nome("Louvor-e-Adoracao-Domicio-Junior (1).pdf"))
        self.assertEqual(
            ("A History of the Church", "Pellicciari, Angela"),
            prep.do_nome(
                "A-History-of-the-Church-Angela-Pellicciari-095929.pdf"))

    def test_nome_do_arquivo_reconhece_autor_maiusculo_no_inicio(self):
        self.assertEqual(
            ("Exultacao Expositiva", "Piper, John"),
            prep.do_nome("JOHN-PIPER-Exultacao-Expositiva.pdf"))

    def test_sufixo_de_copia_nao_impede_autor_no_fim(self):
        self.assertEqual(
            ("Mentoria reunioes saudaveis do evangelho", "Moretti, Evandro"),
            prep.do_nome(
                "Mentoria-reunioes-saudaveis-do-evangelho-Evandro-Moretti-2.pdf"))

    def test_autor_da_folha_precisa_de_segunda_evidencia(self):
        paginas = [
            "(DES)CONGREGADOS\n20 RAZÕES E DESCULPAS\n"
            "MIZAEL DE SOUZA XAVIER\nProibida sem autorização assinada "
            "pelo autor, Mizael de Souza Xavier."]
        self.assertEqual(
            "Xavier, Mizael de Souza",
            prep.autor_folha_rosto_confirmado(paginas))
        self.assertEqual("", prep.autor_folha_rosto_confirmado([
            "O REINO DE DEUS\nUMA TEOLOGIA BÍBLICA\nIntrodução"]))

    def test_isbn_e_copyright_no_fim_impedem_livro_de_virar_documento(self):
        paginas = [
            "Engaging with God\nA Biblical Theology of Worship\nDavid Peterson",
            "Contents\nForeword\nIntroduction\nChapter 1",
            "Foreword\nThis book addresses Christian worship.",
        ] + ["Chapter text"] * 8 + [
            "Copyright © 2014 InterVarsity Press\nISBN 978-0-8308-9885-5"]
        resultado = prep.metadados_documentais_genericos(
            paginas, nome="Engaging-with-God.pdf")
        self.assertEqual({}, resultado)

    def test_urls_editoriais_nao_transformam_livro_em_captura_de_site(self):
        texto = """Copyright © 2023 Pro Nobis Editora
ISBN 978-65-81489-29-8
https://editora.example/catalogo
https://autores.example/perfil
https://editora.example/contato"""
        self.assertNotIn(
            "captura de site",
            [tipo for tipo, _ in prep.procedencia_do_arquivo(texto)])

    def test_dominio_repetido_sem_sinais_editoriais_indica_captura_de_site(self):
        texto = """https://site.example/pagina/1
Texto da primeira página
https://site.example/pagina/2
Texto da segunda página
https://site.example/pagina/3"""
        self.assertIn(
            "captura de site",
            [tipo for tipo, _ in prep.procedencia_do_arquivo(texto)])

    def test_editor_declarado_vence_lista_de_colaboradores(self):
        autores = prep.autores_com_papeis(
            "Stanley Gundry; Eugene Merrill; Daniel Gard",
            "Stanley Gundry (editor)-\nEugene Merrill\nDaniel Gard")
        self.assertEqual("Editor", autores[0]["desc"])
        self.assertEqual("Colaborador", autores[1]["desc"])

    def test_pdf_refluido_separa_paginas_sem_criar_conflito(self):
        resultado = prep.avaliar_paginacao_edicao(95, 128, origem_refluida=True)
        self.assertTrue(resultado["paginacao_refluida"])
        self.assertEqual("", resultado["conflito"])
        resultado = prep.avaliar_paginacao_edicao(95, 128, origem_refluida=False)
        self.assertIn("pode estar incompleto", resultado["conflito"])

    def test_pdf_horizontal_com_duas_paginas_nao_parece_incompleto(self):
        resultado = prep.avaliar_paginacao_edicao(
            128, 242, pagina_dupla=True)
        self.assertTrue(resultado["paginacao_dupla"])
        self.assertEqual("", resultado["conflito"])
        vertical = prep.avaliar_paginacao_edicao(
            128, 242, pagina_dupla=False)
        self.assertFalse(vertical["paginacao_dupla"])
        self.assertIn("pode estar incompleto", vertical["conflito"])

    def test_paginacao_interna_com_salto_identifica_pdf_parcial(self):
        paginas = [
            "VOZ DE UM PROFETA\nobra.indd 1",
            "INTRODUÇÃO\nobra.indd 7",
            "Texto\nobra.indd 8",
            "Texto\nobra.indd 9",
        ]
        resultado = prep.diagnosticar_parcialidade_pdf(paginas)
        self.assertTrue(resultado["parcial"])
        self.assertIn("salta de 1 para 7", resultado["motivo"])

    def test_paginacao_interna_continua_nao_marca_folheto_curto(self):
        paginas = [f"Conteúdo\nobra.indd {n}" for n in range(1, 10)]
        resultado = prep.diagnosticar_parcialidade_pdf(paginas)
        self.assertFalse(resultado["parcial"])

    def test_paginas_preliminares_nao_fazem_livro_parecer_parcial(self):
        paginas = ["Capa", "Créditos", "Sumário"] + [
            f"Conteúdo\n{n}" for n in range(6, 18)]
        resultado = prep.diagnosticar_parcialidade_pdf(paginas)
        self.assertFalse(resultado["parcial"])

    def test_arquivo_que_ja_comeca_em_pagina_avancada_parece_parcial(self):
        paginas = [f"Conteúdo\n{n}" for n in (17, 18, 19, 20)]
        resultado = prep.diagnosticar_parcialidade_pdf(paginas)
        self.assertTrue(resultado["parcial"])
        self.assertIn("17", resultado["motivo"])

    def test_titulo_tecnico_do_office_nao_e_metadado_bibliografico(self):
        with mock.patch.object(prep.subprocess, "run") as executar:
            executar.return_value.stdout = (
                "Title: Microsoft PowerPoint - Manual_Diagramado\n"
                "Author: Silvio A. Lacerda\n")
            dados = prep.metadados_pdf("guia.pdf")
        self.assertNotIn("titulo", dados)
        self.assertEqual("Silvio A. Lacerda", dados["autor"])

    def test_aula_com_checklist_e_reflexoes_e_apostila(self):
        paginas = [
            "FORMAÇÃO DE UM LÍDER",
            "I - PEQUENOS COMEÇOS\n> REFLEXÃO",
            "II - INTENCIONALIDADE\n> REFLEXÃO",
            "CHECKLIST DA AULA 2",
        ]
        tipo, autor = prep.tipo_documento_e_autor(
            "\n".join(paginas), paginas,
            nome="621306741-AULA-2-Formacao-de-um-lider.pdf")
        self.assertEqual("apostila", tipo)
        self.assertEqual("", autor)

    def test_cabecalho_de_responsabilidade_nao_e_autor(self):
        self.assertFalse(prep.autor_bibliograficamente_plausivel(
            "Responsabilidade, Isenção de"))

    def test_estrutura_de_livro_reconhece_word_refluido(self):
        paginas = [
            "SUMÁRIO\nPREFÁCIO\nCapítulo 1\nIntrodução",
            "Capítulo 2\nDesenvolvimento",
        ]
        self.assertTrue(prep.estrutura_de_livro(paginas))

    def test_estante_antiga_vence_amazon_recente_sem_trocar_edicao(self):
        evidencias = {
            "estante": {"titulo": "Crítica Textual do Novo Testamento",
                         "autores": "Wilson Paroschi", "editora": "Vida Nova",
                         "ano": "1993", "paginas": "248",
                         "fonte": "Estante Virtual", "confianca": "alta"},
            "amazon": {"titulo": "Crítica Textual do Novo Testamento",
                        "autores": "Wilson Paroschi", "editora": "Vida Nova",
                        "ano": "2022", "paginas": "248",
                        "fonte": "Amazon", "confianca": "alta"},
        }
        d = prep.conciliar_fontes_comerciais(
            evidencias, ano_local="1993", paginas_pdf="248")
        self.assertEqual("1993", d["ano"])
        self.assertEqual("Vida Nova", d["editora"])

    def test_marketplace_nao_troca_ano_da_edicao_do_pdf(self):
        d = prep.conciliar_fontes_comerciais({
            "estante": {},
            "amazon": {"titulo": "Livro", "autores": "Autor",
                        "ano": "2022", "paginas": "248",
                        "fonte": "Amazon", "confianca": "alta"}},
            ano_local="1993", paginas_pdf="248")
        self.assertNotIn("ano", d)
        self.assertEqual("2022", d["ano_divergente"])

    def test_isbn_10_e_13_da_mesma_edicao_sao_equivalentes(self):
        self.assertTrue(prep.isbns_equivalentes(
            "85-349-1002-2", "978-85-349-1002-6"))
        self.assertFalse(prep.isbns_equivalentes(
            "85-349-1002-2", "978-85-7779-044-9"))

    def test_amazon_com_isbn_exato_vence_pontuacao_textual_baixa(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td)
            pdf = raiz / "10-REVISAO" / "josue.pdf"
            cache = raiz / "_controle" / "cache-pesquisa-web"
            pdf.parent.mkdir(); cache.mkdir(parents=True); pdf.write_bytes(b"pdf")
            (cache / "resultado.json").write_text(json.dumps({
                "arquivo": pdf.name, "isbn": "9788534910026",
                "pontuacao_amazon": 0.664,
                "detalhes_amazon": {
                    "titulo_pagina": "Como ler o Livro de Josué",
                    "autoria_pagina": "por Ivo Storniolo (Autor)",
                    "isbn_10": "8534910022", "isbn_13": "9788534910026"}
            }), encoding="utf-8")
            fonte = prep.carregar_fontes_comerciais(pdf)["amazon"]
            self.assertTrue(fonte["isbn_confirmado"])
            self.assertEqual("alta", fonte["confianca"])

    def test_amazon_rejeitada_na_pagina_do_produto_nao_entra_na_ficha(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td)
            pdf = raiz / "10-REVISAO" / "livro.pdf"
            cache = raiz / "_controle" / "cache-pesquisa-web"
            pdf.parent.mkdir(); cache.mkdir(parents=True); pdf.write_bytes(b"pdf")
            (cache / "resultado.json").write_text(json.dumps({
                "arquivo": pdf.name, "isbn": "9788534910026",
                "pontuacao_amazon": 1.0,
                "detalhes_amazon": {
                    "titulo_pagina": "Outra edição", "isbn_13": "9788577790449",
                    "avaliacao": {"aprovado": False,
                                   "bloqueios": ["ISBN diferente"]}}
            }), encoding="utf-8")
            self.assertEqual({}, prep.carregar_fontes_comerciais(pdf)["amazon"])

    def test_cache_comercial_e_indexado_uma_vez_por_execucao(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td)
            pasta = raiz / "_controle" / "cache-pesquisa-web"
            pasta.mkdir(parents=True)
            pdf_a = raiz / "10-REVISAO" / "a.pdf"
            pdf_b = raiz / "10-REVISAO" / "b.pdf"
            pdf_a.parent.mkdir()
            pdf_a.write_bytes(b"pdf"); pdf_b.write_bytes(b"pdf")
            for nome in ("a.pdf", "b.pdf"):
                (pasta / f"{nome}.json").write_text(
                    json.dumps({"arquivo": nome}), encoding="utf-8")
            leitura_real = pathlib.Path.read_text
            leituras = []

            def contar(caminho, *args, **kwargs):
                if caminho.name in {"a.pdf.json", "b.pdf.json"}:
                    leituras.append(caminho.name)
                return leitura_real(caminho, *args, **kwargs)

            with mock.patch.object(pathlib.Path, "read_text", contar):
                self.assertEqual(1, len(
                    prep.carregar_fontes_comerciais(pdf_a)["pacotes"]))
                self.assertEqual(1, len(
                    prep.carregar_fontes_comerciais(pdf_b)["pacotes"]))
            self.assertEqual(2, len(leituras))

    def test_cache_somente_na_nuvem_e_ignorado_sem_leitura(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td)
            pasta = raiz / "_controle" / "cache-pesquisa-web"
            pasta.mkdir(parents=True)
            pdf = raiz / "10-REVISAO" / "livro.pdf"
            pdf.parent.mkdir(); pdf.write_bytes(b"pdf")
            remoto = pasta / "remoto.json"
            remoto.write_text(json.dumps({"arquivo": pdf.name}),
                               encoding="utf-8")
            with mock.patch.object(
                    prep, "cache_disponivel_localmente", return_value=False):
                with mock.patch.object(
                        pathlib.Path, "read_text",
                        side_effect=AssertionError("cache remoto foi aberto")):
                    resultado = prep.carregar_fontes_comerciais(pdf)
            self.assertEqual([], resultado["pacotes"])

    def test_diagnostico_ocr_publica_progresso_por_paginas(self):
        eventos = []
        pagina = ("Este é um texto perfeitamente pesquisável com palavras "
                  "suficientes para avaliar a qualidade da camada OCR. " * 8)
        prep.diagnosticar_ocr(
            "/arquivo/inexistente.pdf", [pagina] * 30,
            progresso=lambda *dados: eventos.append(dados))
        self.assertEqual(("analisando texto", 1, 30, 1), eventos[0])
        self.assertIn(("analisando texto", 25, 30, 25), eventos)
        self.assertEqual(("analisando texto", 30, 30, 30), eventos[-1])

    def test_curso_encontro_com_a_palavra_e_apostila(self):
        tipo, autor = prep.tipo_documento_e_autor("", [
            "CURSO BÍBLICO INTERNACIONAL\nENCONTRO COM A PALAVRA\n"
            "Livro 10\nPR. DICK WOODWARD"])
        self.assertEqual("apostila", tipo)
        self.assertEqual("WOODWARD, DICK".casefold(), autor.casefold())

    def test_plano_de_aula_apostilado_nao_vira_livro(self):
        tipo, autor = prep.tipo_documento_e_autor("", [
            "PLANO DE AULA APOSTILADO\n"
            "Escola Superior de Teologia do Espírito Santo\n"
            "História dos Avivamentos"])
        self.assertEqual("apostila", tipo)
        self.assertIn("Escola Superior", autor)

    def test_unidade_tematica_com_plano_de_ensino_e_apostila(self):
        tipo, autor = prep.tipo_documento_e_autor("", [
            "História, Princípios e Organizações Batistas\n"
            "Unidade Temática 08\nFaculdade Teológica Batista\n"
            "Breve Biografia do Autor\nEDILSON SOARES DE SOUZA\n"
            "Plano de Ensino\nEmenta"])
        self.assertEqual("apostila", tipo)
        self.assertEqual("Souza, Edilson Soares De", autor)

    def test_aviso_editorial_na_capa_nao_e_parte_do_titulo(self):
        alertas = prep.alertas_plausibilidade_metadados(
            "CORAÇÃO EM CHAMAS UM RECURSO PARA PREGADORES "
            "Livro adotado como Manual de Estudo", "Morelli, João", "")
        self.assertTrue(any("aviso editorial" in a for a in alertas))
        alertas = prep.alertas_plausibilidade_metadados(
            "Pregue durante um Ano # 1 Pregue durante um Ano # 2 "
            "Pregue durante um Ano # 3", "Campbell, Roger", "")
        self.assertTrue(any("lista de colecao" in a for a in alertas))

    def test_fragmento_isolado_nao_vence_metadado_pdf(self):
        alertas = prep.alertas_plausibilidade_metadados(
            "F CULTIVANDO UMA CULTURA DE DISCIPULADO PROJETO VIDEIRA", "", "")
        self.assertTrue(any("fragmento isolado" in a for a in alertas))

    def test_coautoria_preserva_primeiro_autor(self):
        self.assertEqual("Colin Marshall", prep.primeiro_autor(
            "Colin Marshall & Tony Payne"))
        self.assertEqual(
            ["Tim Chester", "Steve Timmis"],
            prep.separar_autores("Tim Chester y Steve Timmis"))

    def test_funcoes_editoriais_em_ingles_nao_viram_autoria_comum(self):
        autores = prep.autores_com_papeis(
            "Julie C. Ma; Wonsuk Ma; Andrew F. Walls",
            "Mission in the Spirit\nJulie C. Ma and Wonsuk Ma\n"
            "Foreword by Andrew F. Walls")
        self.assertEqual("Prefácio", autores[2]["desc"])
        editor = prep.autores_com_papeis(
            "by Charles E. Van Engen (Editor) Format: Kindle Edition",
            "Edited by\nCHARLES E. VAN ENGEN")
        self.assertEqual("Editor", editor[0]["desc"])

    def test_titulo_remove_byline_e_repeticao_mecanica(self):
        self.assertEqual(
            "X: Multiply Your God-Given Potential",
            prep.limpar_titulo_bibliografico(
                "X: Multiply Your God-Given Potential, by John P. Bevere",
                "Bevere, John P."))
        self.assertEqual(
            "PREGAÇÃO EXPOSITIVA Temática",
            prep.limpar_titulo_bibliografico(
                "PREGAÇÃO EXPOSITIVA Pregação Expositiva Temática"))

    def test_autor_explicitamente_declarado_em_aviso(self):
        tipo, autor = prep.tipo_documento_e_autor("", [
            "Livro adotado como manual, usado com a permissão do autor "
            "Pr. João Morelli"])
        self.assertEqual("livro", tipo)
        self.assertEqual("Morelli, João", autor)

    def test_transcricao_de_video_e_sermao(self):
        tipo, autor = prep.tipo_documento_e_autor("", [
            "Transcrição feita a partir do vídeo, A Videira e os Ramos\n"
            "Por: Paul Washer\npublicação oficial deste sermão"])
        self.assertEqual("sermão", tipo)
        self.assertEqual("Washer, Paul", autor)

    def test_material_digital_sem_edicao_publicada_vai_para_documentos(self):
        paginas = [
            "© COPYRIGHT – TODOS OS DIREITOS RESERVADOS\n"
            "Este livro está protegido por direitos autorais e é apenas "
            "para uso pessoal. Não é permitida a revenda deste material "
            "sem o consentimento expresso do autor ou do proprietário dos direitos.",
            "SUMÁRIO\n1. Introdução\n2. História da Pregação Cristã",
            "CAPÍTULO 1\nGrandes pregadores da história",
        ]
        tipo, autor = prep.tipo_documento_e_autor(
            "\n".join(paginas), paginas,
            nome="Historia-da-Pregacao-Crista.pdf")
        self.assertEqual("documento", tipo)
        self.assertEqual("", autor)

    def test_esboco_com_texto_e_tema_e_sermao(self):
        tipo, _ = prep.tipo_documento_e_autor("", [
            "Tema: Liderança cristã\nTexto: João 10\nSermão para domingo"])
        self.assertEqual("sermão", tipo)

    def test_artigo_de_periodico_nao_vira_revista(self):
        tipo, autor = prep.tipo_documento_e_autor("", [
            "UM ESTUDO DA DEPRESSÃO\nPérsio Ribeiro Gomes de Deus\n"
            "Mestre em Ciências da Religião\nRESUMO\n"
            "CIÊNCIAS DA RELIGIÃO – HISTÓRIA E SOCIEDADE\n"
            "Volume 7 • N. 1 • 2009"])
        self.assertEqual("artigo", tipo)
        self.assertIn("Deus", autor)

    def test_artigos_sem_issn_usam_numero_ano_paginas_e_resumo(self):
        casos = [
            ("""JETS 35/3 (September 1992) 341-360

WOMEN IN CHURCH OFFICE:
HERMENEUTICS OR EXEGESIS?
A SURVEY OF APPROACHES TO 1 TIM 2:8-15
GORDON P. HUGENBERGER*

ABSTRACT
This essay examines the interpretation.""", "Women in Church Office", "Hugenberger"),
            ("""FIDES REFORMATA XXI, N° 2 (2016): 97-123

OS PERIGOS DO MOVIMENTO DE CRESCIMENTO DA IGREJA
PARA A REVITALIZAÇÃO DE IGREJAS
Jedeías de Almeida Duarte*

RESUMO
Este artigo busca analisar o movimento.""", "Os Perigos", "Duarte"),
            ("""ESTILHAÇANDO REPRESENTAÇÕES:
A ICONOCLASTIA CONTEMPORÂNEA
Aline Gomes 1
Antonio Paulo Benatte 2

RESUMO
O objetivo do artigo é analisar o fenômeno.
Ateliê de História UEPG, 2(2): 197-219, 2014""",
             "Estilhaçando", "Gomes"),
            ("""\"OIL FROM FLINTY ROCK\": OLIVE CULTIVATION
AND OLIVE OIL PROCESSING IN THE HEBREW BIBLE
Frank S. Frick
Albion College

ABSTRACT
This essay examines olive cultivation.
Athalya Brenner e Jan Willem van Henten, orgs., Semeia 86 (1999).""",
             "Oil From", "Frick"),
        ]
        for pagina, trecho_titulo, trecho_autor in casos:
            with self.subTest(titulo=trecho_titulo):
                tipo, autor = prep.tipo_documento_e_autor(pagina, [pagina])
                dados = prep.metadados_artigo_paginas([pagina])
                self.assertEqual("artigo", tipo)
                self.assertIn(trecho_titulo.casefold(),
                              dados["titulo"].casefold())
                self.assertIn(trecho_autor.casefold(), autor.casefold())

    def test_resenha_curta_com_cabecalho_de_periodico_e_artigo(self):
        paginas = [
            """FIDES REFORMATA 6/1 (2001)
ROLDÁN, Alberto Fernando. Do terror à esperança: paradigmas para uma
escatologia integral. Trad. Hans Udo Fuchs. Londrina: Editora Descoberta, 2001.
Texto da resenha.""",
            """Conclusão.
- Carlos Ribeiro Caldas Filho""",
        ]
        tipo, autor = prep.tipo_documento_e_autor("", paginas)
        dados = prep.metadados_artigo_paginas(paginas)
        self.assertEqual("artigo", tipo)
        self.assertEqual("Filho, Carlos Ribeiro Caldas", autor)
        self.assertIn("Do terror à esperança", dados["titulo"])

    def test_apostila_colada_a_numero_no_nome_e_reconhecida(self):
        pagina = """Pr Paschoal Piragine Junior

CONCEITO E MISSÃO

Treinamento de diáconos e estudo da missão da igreja."""
        tipo, autor = prep.tipo_documento_e_autor(
            pagina, [pagina], nome="11520apostila_treinamento_diaconos.pdf")
        self.assertEqual("apostila", tipo)
        self.assertEqual("Junior, Paschoal Piragine", autor)

    def test_ebook_gratuito_do_autor_e_documento(self):
        paginas = [
            "Introdução aos princípios de liderança cristã.",
            "Esse e-book foi disponibilizado totalmente gratuito para você. "
            "Faça uma doação pelo PayPal ou leia o QR Code.",
        ]
        tipo, autor = prep.tipo_documento_e_autor(
            "\n".join(paginas), paginas,
            metadados={"autor": "Felipe Bernardino"},
            nome="9-Principios-Para-Uma-Verdadeira-Lideranca-Crista.pdf")
        self.assertEqual("documento", tipo)
        self.assertEqual("Bernardino, Felipe", autor)

    def test_chamada_promocional_nao_e_titulo_e_nome_limpo_vence(self):
        promocional = "Esse e-book foi disponibilizado totalmente gratuito para você"
        self.assertFalse(prep.titulo_bibliograficamente_plausivel(promocional))
        titulo_nome, autor_nome = prep.do_nome(
            "556218991-9-Principios-Para-Uma-Verdadeira-Lideranca-Crista-"
            "Livro-Digital-1.pdf")
        self.assertEqual("9 Principios Para Uma Verdadeira Lideranca Crista",
                         titulo_nome)
        self.assertEqual("", autor_nome)
        escolhido, substituiu = prep.titulo_documental_sem_ruido(
            promocional, titulo_nome)
        self.assertTrue(substituiu)
        self.assertEqual(titulo_nome, escolhido)
        escolhido, substituiu = prep.titulo_documental_sem_ruido(
            "Apresentação do PowerPoint", titulo_nome)
        self.assertTrue(substituiu)
        self.assertEqual(titulo_nome, escolhido)

    def test_memoria_de_titulos_ruidosos_aceita_nova_descoberta_manual(self):
        with tempfile.TemporaryDirectory() as tmp:
            cadastro = pathlib.Path(tmp) / "ruidos.json"
            cadastro.write_text(json.dumps({"itens": [{
                "texto": "Baixe agora sua cópia",
                "modo": "prefixo",
                "motivo": "chamada de download"
            }]}), encoding="utf-8")
            arquivo_anterior = prep.ARQUIVO_TITULOS_RUIDOSOS
            cache_anterior = prep._CACHE_TITULOS_RUIDOSOS
            try:
                prep.ARQUIVO_TITULOS_RUIDOSOS = cadastro
                prep._CACHE_TITULOS_RUIDOSOS = None
                itens = prep.carregar_titulos_ruidosos(atualizar=True)
                self.assertEqual(
                    "chamada de download",
                    prep.identificar_titulo_ruidoso(
                        "BAIXE AGORA SUA CÓPIA GRATUITA", itens))
                self.assertFalse(prep.titulo_bibliograficamente_plausivel(
                    "Baixe agora sua cópia gratuita"))
            finally:
                prep.ARQUIVO_TITULOS_RUIDOSOS = arquivo_anterior
                prep._CACHE_TITULOS_RUIDOSOS = cache_anterior

    def test_manual_metodologia_nao_vira_dissertacao_pelo_sumario(self):
        paginas = [
            """Alfredo dos Santos Oliva
Jorge Henrique Barro

MANUAL DE METODOLOGIA DA PESQUISA CIENTÍFICA
Manual visando a normatização técnica para os trabalhos acadêmicos.
Londrina
2001""",
            "SUMÁRIO\nCAPÍTULO IV\nDISSERTAÇÃO\nFormato da Dissertação",
            "Exemplo: dissertação apresentada como requisito parcial.",
        ]
        tipo, autor = prep.tipo_documento_e_autor(
            "\n".join(paginas), paginas, nome="Manual_20de_20metodologia.pdf")
        self.assertEqual("apostila", tipo)
        self.assertIn("Oliva, Alfredo dos Santos", autor)
        self.assertIn("Barro, Jorge Henrique", autor)

    def test_dissertacao_de_mestrado_por_nao_inverte_autor_e_titulo(self):
        paginas = ["""UERJ - UNIVERSIDADE DO ESTADO DO RIO DE JANEIRO
Dissertação de Mestrado por:
Nailda Marinho da Costa Bonato
EDUCAÇÃO [SEXUAL] E SEXUALIDADE:
O VELADO E O APARENTE
1996

Dissertação apresentada como requisito parcial à obtenção do título de Mestre."""]
        dados = prep.metadados_academicos_paginas(paginas)
        self.assertEqual("dissertação", dados["tipo_documento"])
        self.assertEqual("Bonato, Nailda Marinho da Costa", dados["autor"])
        self.assertIn("EDUCAÇÃO [SEXUAL] E SEXUALIDADE", dados["titulo"])
        self.assertIn("VELADO E O APARENTE", dados["titulo"])

    def test_numero_de_periodico_e_resumo_sem_autodeclaracao_nao_decidem_tipo(self):
        pagina = """REVISTA EXEMPLO 12/2 (2024) 10-28
CAPÍTULO SOBRE HISTÓRIA
Autor de um livro citado
RESUMO
Reprodução de material dentro de uma coletânea."""
        tipo, _autor = prep.tipo_documento_e_autor(pagina, [pagina])
        self.assertEqual("livro", tipo)

    def test_cadastro_reconhece_alias_voice_sem_aceitar_palavra_no_corpo(self):
        periodicos = prep.carregar_periodicos_conhecidos(
            incluir_catalogo=False)
        self.assertEqual(
            "Full Gospel Business Men's Voice",
            prep.identificar_periodico_conhecido(
                "CAPA\nVOICE\nMARCH 1959", periodicos))
        self.assertEqual(
            "",
            prep.identificar_periodico_conhecido(
                "The author's voice is important in this chapter.",
                periodicos))

    def test_voice_com_volume_data_e_varias_paginas_e_revista(self):
        paginas = [
            "FULL GOSPEL BUSINESS MEN'S VOICE\nVOL. 7 N. 2\nMARCH 1959",
            "Mensagem do presidente", "Notícias dos capítulos",
            "Testemunhos", "Eventos", "Anúncios", "Expediente",
        ]
        tipo, autor = prep.tipo_documento_e_autor("", paginas)
        self.assertEqual("revista", tipo)
        self.assertEqual("", autor)

    def test_periodico_conhecido_ajuda_artigo_mas_nao_decide_sozinho(self):
        artigo = [
            "FIDES REFORMATA\nUM ESTUDO SOBRE A IGREJA\nJoão da Silva\n"
            "RESUMO: Este artigo examina a história da igreja."
        ]
        tipo, _autor = prep.tipo_documento_e_autor("", artigo)
        self.assertEqual("artigo", tipo)
        tipo, _autor = prep.tipo_documento_e_autor(
            "", ["FIDES REFORMATA\nUma citação isolada no corpo do livro."])
        self.assertEqual("livro", tipo)

    def test_sumario_de_periodico_conhecido_identifica_edicao_completa(self):
        paginas = [
            "CHRISTIAN HISTORY MAGAZINE\nISSUE 28\nCONTENTS\n"
            "The Early Church ........ 4\nThe Reformers ........ 12\n"
            "Modern Missions ........ 26",
            "Primeiro artigo", "Segundo artigo",
        ]
        tipo, _autor = prep.tipo_documento_e_autor("", paginas)
        self.assertEqual("revista", tipo)

    def test_catalogo_so_ensina_nome_de_periodico_quando_ele_recorrer(self):
        with tempfile.TemporaryDirectory() as tmp:
            pasta = pathlib.Path(tmp)
            (pasta / "um.json").write_text(json.dumps({
                "tipo_documento": "artigo",
                "editora": "Revista Exemplo Confirmada",
            }), encoding="utf-8")
            cache_anterior = prep._CACHE_PERIODICOS
            try:
                with mock.patch.object(
                        prep, "_pastas_metadados_catalogo",
                        side_effect=lambda: iter([pasta])):
                    prep._CACHE_PERIODICOS = None
                    uma = prep.carregar_periodicos_conhecidos(atualizar=True)
                    self.assertNotIn(
                        "Revista Exemplo Confirmada",
                        [x["nome"] for x in uma])
                    (pasta / "dois.json").write_text(json.dumps({
                        "tipo_documento": "artigo",
                        "editora": "Revista Exemplo Confirmada",
                    }), encoding="utf-8")
                    prep._CACHE_PERIODICOS = None
                    duas = prep.carregar_periodicos_conhecidos(atualizar=True)
                    aprendido = next(
                        x for x in duas
                        if x["nome"] == "Revista Exemplo Confirmada")
                    self.assertEqual("catalogo", aprendido["origem"])
                    self.assertEqual(2, aprendido["ocorrencias"])
            finally:
                prep._CACHE_PERIODICOS = cache_anterior

    def test_manual_que_ensina_dissertacao_nao_e_dissertacao(self):
        paginas = [
            "MANUAL DE METODOLOGIA DA PESQUISA CIENTÍFICA\nAlfredo dos Santos Oliva",
            "SUMÁRIO\nCapítulo IV - Dissertação",
            "Introdução ao trabalho científico",
            "Normas gerais",
            "Dissertação apresentada como exemplo de formatação",
        ]
        self.assertEqual({}, prep.metadados_academicos_paginas(paginas))

    def test_limpa_rotulos_da_autoria_da_amazon(self):
        self.assertEqual("Michel Gourgues", prep.limpar_autoria_comercial(
            "Edição Português por Michel Gourgues (Autor) Formato: Capa comum"))
        self.assertEqual("John Stott", prep.limpar_autoria_comercial(
            "Edition English by John Stott (Author) Paperback"))

    def test_traducao_biblica_nao_vira_nome_de_tradutor(self):
        self.assertEqual("", prep.ler_copyright(
            "A tradução aramaica (Targum), era relacionada ao texto")["tradutor"])
        self.assertEqual("João Ferreira de Almeida", prep.ler_copyright(
            "Tradução: João Ferreira de Almeida\nEditora Exemplo")["tradutor"])

    def test_capa_confirma_editora_externa(self):
        self.assertEqual("Vida Nova", prep.editora_confirmada_na_capa(
            ["CRÍTICA TEXTUAL", "WILSON PAROSCHI", "VIDA NOVA"],
            ["Vida Nova"]))

    def test_memoria_incremental_rejeita_autor_ruidoso(self):
        self.assertFalse(prep.autor_bibliograficamente_plausivel("INGLATERRA, NA"))
        alertas = prep.alertas_plausibilidade_metadados("", "INGLATERRA, NA", "")
        self.assertTrue(any("memoria de ruidos" in a for a in alertas))

    def test_titulo_didatico_generico_nao_e_bibliografico(self):
        self.assertFalse(prep.titulo_bibliograficamente_plausivel("Aula 2"))
        self.assertFalse(prep.titulo_bibliograficamente_plausivel("Estudo 4"))
        self.assertTrue(prep.titulo_bibliograficamente_plausivel(
            "Estudo sobre o discipulado cristão"))

    def test_rejeicoes_de_fontes_registram_motivo_acionavel(self):
        rejeicoes = prep.rejeicoes_fontes_bibliograficas(
            fontes_comerciais={"pacotes": [{
                "arquivo": "livro.pdf",
                "isbn": "9788577790364",
                "pontuacao_amazon": 0.52,
                "detalhes_estante": {
                    "titulo": "Livro parecido",
                    "confianca": "baixa",
                    "avaliacao": {"aprovado": False,
                                  "motivos": ["autor não encontrado"]},
                },
                "detalhes_amazon": {
                    "titulo_pagina": "Outra edição",
                    "isbn_13": "9788527507011",
                    "url": "https://exemplo.invalid/livro",
                },
            }]},
            consultas_academicas=[("OpenAlex", True, {})])
        motivos = " | ".join(r["motivo"] for r in rejeicoes)
        self.assertIn("autor não encontrado", motivos)
        self.assertIn("confianca baixa", motivos)
        self.assertIn("ISBN diferente", motivos)
        self.assertIn("sem candidato suficientemente convergente", motivos)


class MaterialInstitucionalDeIgrejaTest(unittest.TestCase):
    """Manual de ministerio nao e livro - achado nos pendentes reais.

    Sete itens estavam presos por falta de editora, sendo material interno
    de igreja que nunca teve editora nem ISBN.
    """

    MANUAL = """MINISTERIO DE LOUVOR
Manual de Orientacoes
1a Edicao
Janeiro de 2022
Igreja Batista da Lagoinha"""

    ESTUDOS = """Esta serie de estudos e uma ferramenta valiosa para
envolver os membros do Pequeno Grupo na pesquisa aplicativa da Biblia."""

    def test_manual_de_ministerio_vira_documento(self):
        self.assertEqual("documento", prep.material_institucional_de_igreja(
            self.MANUAL, self.MANUAL))

    def test_serie_de_estudos_vira_apostila(self):
        self.assertEqual("apostila", prep.material_institucional_de_igreja(
            self.ESTUDOS, self.ESTUDOS))

    def test_obra_com_isbn_continua_livro(self):
        texto = self.MANUAL + "\nISBN 978-65-01-24846-2"
        self.assertEqual("", prep.material_institucional_de_igreja(texto, texto))

    def test_obra_com_editora_continua_livro(self):
        texto = self.MANUAL + "\nPublicado por Editora Vida"
        self.assertEqual("", prep.material_institucional_de_igreja(texto, texto))

    def test_livro_comum_sobre_igreja_nao_e_confundido(self):
        texto = ("A Igreja e o Reino de Deus\nGeorge Eldon Ladd\n"
                 "Um estudo sobre eclesiologia biblica")
        self.assertEqual("", prep.material_institucional_de_igreja(texto, texto))

    def test_texto_vazio_nao_quebra(self):
        self.assertEqual("", prep.material_institucional_de_igreja("", ""))


if __name__ == "__main__":
    unittest.main()
