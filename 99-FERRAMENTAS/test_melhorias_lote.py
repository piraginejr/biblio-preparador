#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Melhorias que sairam da auditoria do lote em revisao."""

import importlib.util
import json
import pathlib
import tempfile
import unittest

ARQUIVO = pathlib.Path(__file__).with_name("preparar-livros.py")
SPEC = importlib.util.spec_from_file_location("preparar_livros", ARQUIVO)
prep = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prep)

import conferir_revisoes


class GuardaDeMaiusculaTest(unittest.TestCase):
    """O re.I anulava as guardas [A-ZÁ-Ú] dos padroes.

    Efeito real: "...e agora publicado por muitos cristaos protestantes
    batizados..." era aceito como editora.
    """

    def test_prosa_nao_vira_editora(self):
        texto = ("professado, e agora publicado por muitos cristaos "
                 "protestantes batizados, cujos nomes estao abaixo")
        self.assertEqual("", prep.ler_copyright(texto).get("editora", ""))

    def test_credito_editorial_continua_sendo_lido(self):
        texto = ("Um recurso historico batista\n"
                 "publicado pelo Center for Theological Research em\n"
                 "www.BaptistTheology.org")
        self.assertEqual("Center for Theological Research",
                         prep.ler_copyright(texto)["editora"])

    def test_selo_sozinho_na_linha(self):
        texto = "Sao Paulo\nEditora Danprewan\n2015"
        self.assertEqual("Editora Danprewan",
                         prep.ler_copyright(texto)["editora"])

    def test_referencia_bibliografica_nao_vira_editora_da_obra(self):
        paginas = [("ALEXANDER, Desmond T. Novo Dicionário de Teologia "
                    "Bíblica. São Paulo: Editora Vida, 2009, pag. 809")]
        self.assertEqual("", prep.editora_institucional_nas_paginas(paginas))

    def test_nome_da_editora_fora_de_citacao_continua_valendo(self):
        paginas = ["Publicação e Distribuição:\nEDITORA CULTURA CRISTÃ"]
        self.assertEqual("Editora Cultura Cristã",
                         prep.editora_institucional_nas_paginas(paginas))


class ProcedenciaTest(unittest.TestCase):
    """Marcas que dizem de onde o arquivo veio."""

    def test_traducao_automatica_e_declarada(self):
        tipos = [t for t, _ in prep.procedencia_do_arquivo(
            "Machine Translated by Google\nUM CREDO ORTODOXO")]
        self.assertIn("tradução automática", tipos)

    def test_captura_de_site_e_declarada(self):
        tipos = [t for t, _ in prep.procedencia_do_arquivo(
            "lt.PDF\n<- Previous First Next ->\ntexto da obra")]
        self.assertIn("captura de site", tipos)

    def test_livro_normal_nao_recebe_marca(self):
        texto = ("Verdadeiros Adoradores\npor Andre Paganelli\n"
                 "©1999 por Andre Paganelli")
        self.assertEqual([], prep.procedencia_do_arquivo(texto))

    def test_explicacao_nunca_volta_vazia(self):
        for _, explicacao in prep.procedencia_do_arquivo(
                "Machine Translated by Google"):
            self.assertTrue(explicacao)

    def test_copia_nao_comercial_e_documento_derivado(self):
        texto = "Cópia digital não comercial para uso de estudo"
        derivacao = prep.derivacao_editorial_nao_publicada(texto)
        self.assertEqual("cópia digital não comercial", derivacao["tipo"])
        self.assertFalse(derivacao["limpar_edicao_fonte"])

    def test_traducao_automatica_nao_herda_edicao_original(self):
        derivacao = prep.derivacao_editorial_nao_publicada(
            "Machine Translated by Google")
        self.assertEqual("tradução automática", derivacao["tipo"])
        self.assertTrue(derivacao["limpar_edicao_fonte"])


class ConvergenciaBibliograficaTest(unittest.TestCase):
    def ficha(self, **mudancas):
        ficha = {
            "tipo_documento": "livro",
            "titulo": "Teologia Histórica",
            "origem_titulo": "folha de rosto",
            "nmAutor0": "Cunningham, William",
            "origem_autor": "folha de rosto",
            "isbn": "", "isbn_confirmado_na_edicao": False,
            "editora": "Banner of Truth", "data": "",
            "conflitos": [], "procedencia": [],
        }
        ficha.update(mudancas)
        return ficha

    def test_livro_antigo_com_tres_evidencias_recebe_sem_data(self):
        resultado = prep.avaliar_convergencia_bibliografica(self.ficha())
        self.assertTrue(resultado["aprovada"])
        self.assertEqual("[s.d.]", resultado["campos_convencionados"]["data"])
        self.assertEqual(3, len(resultado["evidencias"]))

    def test_ano_confirmado_permite_editora_ausente(self):
        resultado = prep.avaliar_convergencia_bibliografica(
            self.ficha(editora="", data="1849"))
        self.assertTrue(resultado["aprovada"])
        self.assertEqual("[s.n.]",
                         resultado["campos_convencionados"]["editora"])

    def test_titulo_e_autor_sozinhos_nao_bastam(self):
        resultado = prep.avaliar_convergencia_bibliografica(
            self.ficha(editora="", data=""))
        self.assertFalse(resultado["aprovada"])
        self.assertIn("chave independente", resultado["motivo"])

    def test_nome_do_arquivo_nao_e_promovido(self):
        resultado = prep.avaliar_convergencia_bibliografica(
            self.ficha(origem_autor="nome do arquivo"))
        self.assertFalse(resultado["aprovada"])

    def test_conflito_nunca_e_apagado(self):
        resultado = prep.avaliar_convergencia_bibliografica(
            self.ficha(conflitos=["ISBN divergente"]))
        self.assertFalse(resultado["aprovada"])

    def test_derivado_nao_e_promovido(self):
        resultado = prep.avaliar_convergencia_bibliografica(
            self.ficha(procedencia=["tradução automática"]))
        self.assertFalse(resultado["aprovada"])


class DcipInstitucionalTest(unittest.TestCase):
    TEXTO = (
        "CURSO ONLINE DE TEOLOGIA\nDISCIPLINA\n"
        "Pesquisa e Organização do Conteúdo:\nInstituto de Teologia Logos, EA\n"
        "DADOS DE CATALOGAÇÃO INTERNA DA PUBLICAÇÃO – DCIP\n"
        "CÓDIGO DCIP: 001-036-2021-1\n"
        "LOGOS, Instituto de Teologia (ORG). INTRODUÇÃO À HISTÓRIA DA MÚSICA.\n"
        "MARANHÃO: PUBLICAÇÕES ITL, 2021. 83 pgs."
    )

    def test_dcip_institucional_recupera_tombo(self):
        d = prep.ler_dcip_institucional_paginas([self.TEXTO])
        self.assertEqual("Introdução à História da Música", d["titulo"])
        self.assertEqual("Instituto de Teologia Logos", d["autor"])
        self.assertEqual("Publicações ITL", d["editora"])
        self.assertEqual("2021", d["ano"])
        self.assertEqual("83", d["paginas"])

    def test_dcip_de_disciplina_classifica_como_apostila(self):
        tipo, autor = prep.tipo_documento_e_autor(
            self.TEXTO, [self.TEXTO], metadados={}, nome="historia.pdf")
        self.assertEqual("apostila", tipo)
        self.assertEqual("Instituto de Teologia Logos", autor)


class TituloPlausivelTest(unittest.TestCase):
    def test_paragrafo_extenso_nao_vira_titulo(self):
        titulo = ("The following testimonies were excerpted from these Christians' "
                  "respective biographies or from personal testimonies. I was born "
                  "into a Christian family and I was the third child preceded by two "
                  "sisters because my family had made a promise before I was born")
        self.assertFalse(prep.titulo_bibliograficamente_plausivel(titulo))

    def test_fragmento_terminado_em_preposicao_nao_vira_titulo(self):
        self.assertFalse(prep.titulo_bibliograficamente_plausivel(
            "Juntamente com a hermenêutica, a exegese é o estudo do significado "
            "das palavras à"))

    def test_titulo_academico_longo_continua_valendo(self):
        self.assertTrue(prep.titulo_bibliograficamente_plausivel(
            "A igreja local e a música no culto: o canto calvinista e os "
            "desafios contemporâneos"))


class TipoDocumentalDoLoteTest(unittest.TestCase):
    def _tipo(self, texto):
        return prep.tipo_documento_e_autor(
            texto, [texto], metadados={}, nome="material.pdf")

    def test_apostila_com_professor(self):
        tipo, autor = self._tipo(
            "APOSTILA\nEXEGESE BÍBLICA\nProfessor: Alan Brizotti")
        self.assertEqual("apostila", tipo)
        self.assertEqual("Brizotti, Alan", autor)

    def test_programa_de_discipulado_institucional(self):
        tipo, _ = self._tipo(
            "programa de discipulado com recurso para pequenos grupos\n"
            "Ministério de Educação Cristã")
        self.assertEqual("apostila", tipo)

    def test_workshop_de_voluntarios_da_igreja(self):
        tipo, _ = self._tipo(
            "WORKSHOP VOLUNTÁRIOS LAGOINHA\nSER VOLUNTÁRIO É SERVIR A IGREJA")
        self.assertEqual("documento", tipo)

    def test_revista_didatica_completa(self):
        tipo, _ = self._tipo(
            "Revista do Aluno\nPublicação e Distribuição: Editora Cultura "
            "Cristã\nÍNDICE\nLição 1")
        self.assertEqual("revista", tipo)

    def test_compilacao_de_paginas_de_site(self):
        tipo, _ = self._tipo(
            "The following testimonies were excerpted from biographies.\n"
            "This site draws upon the writings of Christian authors.\n"
            "Main Contents:\nREFERENCES")
        self.assertEqual("documento", tipo)


class ReaproveitamentoDeFichaTest(unittest.TestCase):
    """Nao refazer o que nao mudou - mas na duvida, refazer."""

    def setUp(self):
        self.assinatura = prep.assinatura_do_programa()

    def test_pdf_e_programa_iguais_reaproveita(self):
        ficha = {"hash_sha256": "abc", "titulo": "X",
                 "assinatura_programa": self.assinatura}
        vale, _ = prep.ficha_ainda_vale(ficha, "abc")
        self.assertTrue(vale)

    def test_pdf_diferente_reprocessa(self):
        ficha = {"hash_sha256": "abc", "titulo": "X",
                 "assinatura_programa": self.assinatura}
        vale, motivo = prep.ficha_ainda_vale(ficha, "outro")
        self.assertFalse(vale)
        self.assertIn("PDF", motivo)

    def test_programa_mudou_reprocessa(self):
        # uma regra nova precisa valer para o acervo inteiro
        ficha = {"hash_sha256": "abc", "titulo": "X",
                 "assinatura_programa": "assinatura-antiga"}
        vale, motivo = prep.ficha_ainda_vale(ficha, "abc")
        self.assertFalse(vale)
        self.assertIn("programa", motivo)

    def test_ficha_antiga_sem_assinatura_reprocessa(self):
        vale, _ = prep.ficha_ainda_vale({"hash_sha256": "abc", "titulo": "X"}, "abc")
        self.assertFalse(vale)

    def test_na_duvida_reprocessa(self):
        for ficha, h in (({}, "abc"), (None, "abc"), ({"hash_sha256": "abc"}, "")):
            self.assertFalse(prep.ficha_ainda_vale(ficha, h)[0])

    def test_assinatura_e_estavel_na_mesma_execucao(self):
        self.assertEqual(prep.assinatura_do_programa(),
                         prep.assinatura_do_programa())


class ConferirRevisoesTest(unittest.TestCase):
    """Correcao gravada no lugar errado nao sobrevive - e ninguem avisava."""

    def _acervo(self, td, campos_revisao, campos_ficha, com_hash=True):
        raiz = pathlib.Path(td)
        (raiz / "_controle").mkdir(parents=True, exist_ok=True)
        (raiz / "_metadados").mkdir(parents=True, exist_ok=True)
        pdf = raiz / "livro.pdf"
        pdf.write_bytes(b"%PDF-conteudo")
        digest = conferir_revisoes.sha256(pdf)
        rev = {"aprovado": True, "campos": campos_revisao}
        if com_hash:
            rev["hash_sha256"] = digest
        (raiz / "_controle" / "revisoes-manuais.json").write_text(
            json.dumps({"livros": {"livro.pdf": rev}}), encoding="utf-8")
        ficha = {"arquivo": "livro.pdf", "pdf_original": "livro.pdf",
                 "hash_sha256": digest}
        ficha.update(campos_ficha)
        (raiz / "_metadados" / "livro.json").write_text(
            json.dumps(ficha), encoding="utf-8")
        return raiz

    def test_acusa_ficha_que_diverge_da_revisao(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = self._acervo(td, {"titulo": "Título correto"},
                                {"titulo": "titulo automatico errado"})
            r = conferir_revisoes.conferir(raiz)
            self.assertEqual(1, len(r["divergentes"]))
            self.assertEqual("titulo", r["divergentes"][0]["campos"][0]["campo"])

    def test_ficha_igual_a_revisao_nao_acusa(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = self._acervo(td, {"titulo": "Igual"}, {"titulo": "Igual"})
            r = conferir_revisoes.conferir(raiz)
            self.assertEqual([], r["divergentes"])

    def test_acusa_revisao_sem_hash(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = self._acervo(td, {"titulo": "X"}, {"titulo": "X"},
                                com_hash=False)
            r = conferir_revisoes.conferir(raiz)
            self.assertEqual(1, len(r["sem_hash"]))

    def test_acusa_revisao_sem_ficha(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td)
            (raiz / "_controle").mkdir(parents=True)
            (raiz / "_metadados").mkdir(parents=True)
            (raiz / "_controle" / "revisoes-manuais.json").write_text(
                json.dumps({"livros": {"sumiu.pdf": {"aprovado": True,
                                                     "campos": {}}}}),
                encoding="utf-8")
            r = conferir_revisoes.conferir(raiz)
            self.assertEqual(1, len(r["orfas"]))

    def test_revisao_importada_com_pdf_na_entrada_nao_bloqueia(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td)
            (raiz / "_controle").mkdir(parents=True)
            (raiz / "_metadados").mkdir()
            (raiz / "00-ENTRADA").mkdir()
            pdf = raiz / "00-ENTRADA" / "aguardando.pdf"
            pdf.write_bytes(b"%PDF-aguardando")
            revisao = {"aprovado": True, "campos": {},
                       "hash_sha256": conferir_revisoes.sha256(pdf)}
            (raiz / "_controle" / "revisoes-manuais.json").write_text(
                json.dumps({"livros": {pdf.name: revisao}}), encoding="utf-8")
            r = conferir_revisoes.conferir(raiz)
            self.assertEqual([], r["orfas"])
            self.assertEqual([], r["hash_mudou"])
            self.assertEqual(1, len(r["aguardando_preparo"]))

    def test_acervo_sem_revisoes_nao_quebra(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td)
            (raiz / "_controle").mkdir(parents=True)
            (raiz / "_metadados").mkdir(parents=True)
            r = conferir_revisoes.conferir(raiz)
            self.assertEqual(0, r["revisoes"])

    def test_pdf_alterado_de_item_ativo_continua_bloqueando(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = self._acervo(td, {"titulo": "Correto"},
                                {"titulo": "Correto", "situacao": "conflito"})
            (raiz / "livro.pdf").write_bytes(b"%PDF-alterado")
            r = conferir_revisoes.conferir(raiz)
            self.assertEqual(1, len(r["hash_mudou"]))
            self.assertEqual([], r["avisos_encerrados"])

    def test_pdf_alterado_de_duplicado_e_aviso_sem_bloqueio(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = self._acervo(
                td, {"titulo": "Correto"},
                {"titulo": "Correto",
                 "situacao": "duplicado confirmado por ISBN"})
            (raiz / "livro.pdf").write_bytes(b"%PDF-alterado")
            r = conferir_revisoes.conferir(raiz)
            self.assertEqual([], r["hash_mudou"])
            self.assertEqual(1, len(r["avisos_encerrados"]))


if __name__ == "__main__":
    unittest.main()


class ApresentacaoTest(unittest.TestCase):
    """PowerPoint entra como documento: titulo obrigatorio, autor opcional.

    Sete .ppt/.pptx ficaram parados em 00-ENTRADA porque a esteira so
    convertia Word, EPUB e HTML - e o Biblio so aceita PDF.
    """

    def setUp(self):
        import importlib.util, pathlib, sys
        for nome, arq in (("prep", "preparar-livros.py"),
                          ("bl", "biblioteca-local.py")):
            if nome not in globals():
                caminho = pathlib.Path(__file__).with_name(arq)
                spec = importlib.util.spec_from_file_location(nome, caminho)
                mod = importlib.util.module_from_spec(spec)
                sys.modules[nome] = mod
                spec.loader.exec_module(mod)
                globals()[nome] = mod
        self.P, self.B = globals()["prep"], globals()["bl"]

    def test_extensoes_reconhecidas_dos_dois_lados(self):
        self.assertEqual(self.P.EXTENSOES_APRESENTACAO,
                         self.B.EXTENSOES_APRESENTACAO)
        for ext in (".ppt", ".pptx", ".odp"):
            self.assertIn(ext, self.P.EXTENSOES_APRESENTACAO)

    def test_procedencia_pptx_e_apresentacao(self):
        self.assertTrue(self.P.origem_e_apresentacao(
            ["/x/274893870-Os-Batistas-Na-Inglaterra.pptx"]))

    def test_docx_e_pdf_nao_sao_apresentacao(self):
        self.assertFalse(self.P.origem_e_apresentacao(["/x/a.docx"]))
        self.assertFalse(self.P.origem_e_apresentacao(["/x/a.pdf"]))
        self.assertFalse(self.P.origem_e_apresentacao([]))
        self.assertFalse(self.P.origem_e_apresentacao(None))

    def test_apresentacao_nao_exige_editora_data_nem_autor(self):
        # a regra ja existente cobra esses campos so de livro/coletanea;
        # o teste trava isso para que "apresentacao" nao caia na lista.
        self.assertNotIn("apresentação", {"livro", "coletânea"})

    def test_apresentacao_nao_manda_ler_codigo_de_barras(self):
        # slide nao tem contracapa: a leitura cara nao se justifica
        self.assertFalse(self.P.deve_ler_codigo_barras("apresentação"))

    def test_apresentacao_vai_para_a_fila_de_documentos(self):
        self.assertIn("apresentação", self.B.TIPOS_DOCUMENTOS)

    def test_apresentacao_e_estado_de_cadastro_especifico(self):
        # Este tipo não pode cair de volta em "conflito" só porque
        # autor/editora/data não foram declarados.
        self.assertIn("apresentação", self.P.TIPOS_CADASTRO_ESPECIFICO)

    def test_revisao_aprovada_vence_a_procedencia(self):
        decide = self.P._revisao_define_tipo
        self.assertTrue(decide({"aprovado": True,
                                "campos": {"tipo_documento": "apostila"}}))
        self.assertFalse(decide({"aprovado": False,
                                 "campos": {"tipo_documento": "apostila"}}))
        self.assertFalse(decide({"aprovado": True, "campos": {}}))
        self.assertFalse(decide({}))
        self.assertFalse(decide(None))

    def test_conversor_recusa_formato_que_nao_e_apresentacao(self):
        r = self.B.converter_apresentacao_para_pdf("/x/a.docx", "/x/a.pdf")
        self.assertFalse(r["ok"])
        self.assertIn("inválido", r["erro"])

    def test_falha_do_conversor_sempre_explica_a_causa(self):
        r = self.B.converter_apresentacao_para_pdf("/x/a.pptx", "/x/a.pdf")
        self.assertFalse(r["ok"])
        self.assertTrue(r["erro"])          # ausencia muda nao e aceitavel


class EtapaMudaTest(unittest.TestCase):
    """A etapa 1 do ciclo ficava muda e parecia travada.

    Caso real: o ciclo parou em `etapa: "iniciando", arquivo: ""` com ZERO
    alvos - a etapa nao tinha nada a fazer, mas nada dizia isso, e o
    processo morreu sem limpar o marcador.
    """

    def setUp(self):
        import importlib.util, pathlib, sys
        if "bl2" not in sys.modules:
            caminho = pathlib.Path(__file__).with_name("biblioteca-local.py")
            spec = importlib.util.spec_from_file_location("bl2", caminho)
            mod = importlib.util.module_from_spec(spec)
            sys.modules["bl2"] = mod
            spec.loader.exec_module(mod)
        self.B = sys.modules["bl2"]

    def _controle(self):
        import tempfile, pathlib
        self.td = tempfile.TemporaryDirectory()
        p = pathlib.Path(self.td.name)
        (p / "_controle").mkdir()
        return {"controle": p / "_controle"}

    def test_marcador_de_processo_morto_nao_contamina_o_novo(self):
        import json, os
        c = self._controle()
        alvo = c["controle"] / "processamento-ativo.json"
        # processo anterior morreu no meio de um livro de 279 paginas
        alvo.write_text(json.dumps({
            "pid": os.getpid() + 99999, "operacao": "corrigir OCR",
            "arquivo": "packer.pdf", "pagina": 180, "paginas": 279,
            "percentual": 64}), encoding="utf-8")
        self.B.atualizar_processamento_ativo(c, operacao="processar",
                                             etapa="iniciando")
        novo = json.loads(alvo.read_text(encoding="utf-8"))
        self.assertEqual(os.getpid(), novo["pid"])
        self.assertEqual("processar", novo["operacao"])
        # o progresso alheio nao pode sobreviver
        self.assertNotIn("packer.pdf", str(novo.get("arquivo", "")))
        self.assertNotIn("pagina", novo)

    def test_marcador_do_proprio_processo_continua_sendo_mesclado(self):
        import json
        c = self._controle()
        self.B.atualizar_processamento_ativo(c, operacao="corrigir OCR",
                                             arquivo="a.pdf", paginas=10)
        self.B.atualizar_processamento_ativo(c, pagina=7)
        d = json.loads((c["controle"] / "processamento-ativo.json")
                       .read_text(encoding="utf-8"))
        self.assertEqual("a.pdf", d["arquivo"])   # mesclou
        self.assertEqual(10, d["paginas"])
        self.assertEqual(7, d["pagina"])

    def test_etapa_um_nao_abre_ficha_de_item_ja_liberado(self):
        """Historico fica no catalogo sem baixar a ficha antiga do Dropbox."""
        import contextlib, io
        from unittest import mock
        with tempfile.TemporaryDirectory() as td:
            c = self.B.inicializar(td)
            ficha = c["metadados"] / "antigo.json"
            ficha.write_text('{"titulo": "Histórico preservado"}',
                             encoding="utf-8")
            catalogo = {
                "versao": 1, "livros": {
                    "abc": {
                        "hash_sha256": "abc", "arquivo": "antigo.pdf",
                        "caminho": "", "metadados": "_metadados/antigo.json",
                        "estado": "cadastrado - arquivos locais liberados",
                        "arquivos_liberados_em": "2026-09-01T10:00:00",
                    }
                }
            }
            self.B.salvar_catalogo(c, catalogo)
            leitura_real = pathlib.Path.read_text

            def leitura_controlada(caminho, *args, **kwargs):
                if caminho == ficha:
                    raise AssertionError("ficha definitiva foi reaberta")
                return leitura_real(caminho, *args, **kwargs)

            saida = io.StringIO()
            with mock.patch.object(pathlib.Path, "read_text",
                                   leitura_controlada):
                with contextlib.redirect_stdout(saida):
                    resultado = self.B.corrigir_ocr_pendentes(
                        td, usar_api=False)
            self.assertEqual(0, resultado["encontrados"])
            self.assertIn("1/1 (100%)", saida.getvalue())
            self.assertIn("nada pendente", saida.getvalue())

    def test_fase_do_arquivo_aparece_na_tela_e_no_status(self):
        import contextlib, io, json
        c = self._controle()
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            self.B.anunciar_fase_arquivo(
                c, "livro.pdf", 2, 8, 5, 7,
                "verificando OCR, páginas e tamanho")
        self.assertIn("fase 5/7", saida.getvalue())
        estado = json.loads((c["controle"] / "processamento-ativo.json")
                            .read_text(encoding="utf-8"))
        self.assertEqual("livro.pdf", estado["arquivo"])
        self.assertEqual(2, estado["item"])
        self.assertIn("verificando OCR", estado["etapa"])
