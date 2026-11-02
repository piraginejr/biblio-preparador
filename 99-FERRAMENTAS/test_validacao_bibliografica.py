import unittest
import validacao_bibliografica as v


class ValidacaoBibliograficaTest(unittest.TestCase):
    def test_artigo_springer_nao_e_livro_parcial_pela_marca_13(self):
        pagina='Journal of Autism and Developmental Disorders (2023) 53:3460–3474\nhttps://doi.org/10.1007/s10803-022-05645-5\n\nORIGINAL PAPER\n\nCoping with uncertainty in everyday situations (CUES)\nto address intolerance of uncertainty in autistic children\nJacqui Rodgers1 · Jane Goodwin1\n\nAbstract\nTexto.\n13'
        cab=v.cabecalho_periodico([pagina])
        self.assertEqual('Jacqui Rodgers',cab['autor']);self.assertEqual('2023',cab['ano'])
        self.assertIn('autistic children',cab['titulo'])

    def test_edicao_expressa_nao_e_substituida_pela_primeira_presumida(self):
        self.assertIn('edicao_presumida_contradiz_pdf',self.codigos({'edicao':'1ª edição (presumida)'},['2nd Edition\nUpdated and Expanded']))
        self.assertNotIn('edicao_presumida_contradiz_pdf',self.codigos({'edicao':'2ª edição'},['2nd Edition']))
        texto='FICHA TÉCNICA\n1ª edição – 2012\n2ª edição – 2019 – Atualizada e Revisada'
        self.assertIn('ano_diverge_edicao_declarada',self.codigos({'data':'2012'},[texto]))
        self.assertNotIn('ano_diverge_edicao_declarada',self.codigos({'data':'2019'},[texto]))

    def test_rotulo_completo_e_email_nao_identificam_a_obra(self):
        for titulo in ('(livro completo)','TEXTO COMPLETO','Email: autor@universidade.edu'):
            self.assertIn('titulo_sem_identidade',self.codigos({'titulo':titulo}))
        self.assertFalse(v.titulo_sem_identidade('Cristianismo puro e simples'))

    def test_cabecalho_wiley_prevalece_sobre_notas_de_rodape(self):
        pagina='Modern Theology 42:3 July 2026 DOI:10.1111/moth.70070\nISSN 0266-7177 (Print)\nISSN 1468-0025 (Online)\n\nCONSCIENCE AND THE ENDS OF\nHUMANITY: CHRISTIAN HUMANISM\nAND ARTIFICIAL INTELLIGENCE\n\nWILLIAM SCHWEIKER\n\nAbstract\nArtigo.\nEmail: w-schweiker@uchicago.edu'
        cab=v.cabecalho_periodico([pagina])
        self.assertEqual('William Schweiker',cab['autor']);self.assertEqual('2026',cab['ano'])
        self.assertIn('ARTIFICIAL INTELLIGENCE',cab['titulo'])
        self.assertIn('artigo_como_livro',self.codigos({'titulo':'Email: w-schweiker@uchicago.edu','tipo_documento':'livro'},[pagina]))
        self.assertEqual({},v.cabecalho_periodico(['Referências\nModern Theology DOI 10.1111/moth.70070']))

    def test_resumo_bookey_e_promocao_nao_sao_livro_integral(self):
        self.assertIn('resumo_terceiros',self.codigos({},['A Praying Life\nWritten by Bookey\nSummary Content List']))
        self.assertIn('publicidade_download',self.codigos({},['DESCARGAR EBOOK\nHaga clic en el enlace y regístrese gratis']))
        self.assertNotIn('publicidade_download',self.codigos({},['Guia para descargar ebook legalmente: estudo acadêmico.']))

    def test_primeiro_paragrafo_de_introducao_nao_e_titulo(self):
        titulo='Há momentos na vida em que nos deparamos com situações que parecem'
        self.assertIn('paragrafo_como_titulo',self.codigos({'titulo':titulo},['Introdução\n\n'+titulo+' definitivas.']))

    def test_versiculo_e_creditos_nao_sao_titulo(self):
        self.assertIn('versiculo_como_titulo',self.codigos({'titulo':'[1,1] PAULOS APOSTOLOS'}))
        self.assertIn('rotulos_no_titulo',self.codigos({'titulo':'O Anticristo Autor: Nietzsche Fonte: Labyrinth'}))
        self.assertNotIn('versiculo_como_titulo',self.codigos({'titulo':'Novo Testamento — Romanos'}))

    def test_autora_e_sobre_autor_sao_rotulos_validos(self):
        for texto in ('Autora: Nise da Silveira','Sobre o Autor: Prof. Alexander Raspa da Silva'):
            self.assertIn('autor_declarado_ausente',self.codigos({},[texto]))
    def test_frases_e_parenteses_do_corpo_nao_sao_creditos(self):
        for texto in ('Portanto, seguem, agora, estas linhas, para que me saibam',
                      'Por su ilustración del uso curativo de la religión',
                      '(na verdade, uma prima sua), o que acabou sendo o material'):
            self.assertEqual(set(),self.codigos({'nmAutor0':'Jung, Carl Gustav'},[texto]))
        self.assertEqual(set(),self.codigos({'nmAutor0':'Jung, Carl Gustav'},['Carl Gustav Jung']))

    def codigos(self,f,paginas=None,fim=None):
        return {a['codigo'] for a in v.auditar(f,paginas=paginas or [],fim=fim)}

    def test_cidade_e_titulo_tecnico_nao_sao_identidade(self):
        self.assertIn('cidade_como_autor',self.codigos({'nmAutor0':'Aires, Buenos'}))
        self.assertIn('titulo_tecnico',self.codigos({'titulo':'Von Franz tema (doc cap 2)'}))
        self.assertIn('serie_como_titulo',self.codigos({'titulo':'OBRAS COMPLETAS DE C'}))

    def test_autor_declarado_e_inversao_bibliografica(self):
        paginas=['Encuentro\nPor\nMircea Eliade']
        self.assertIn('autor_diverge_pdf',self.codigos({'nmAutor0':'Mircea, Eliade'},paginas))
        self.assertNotIn('autor_diverge_pdf',self.codigos({'nmAutor0':'Eliade, Mircea'},paginas))
        self.assertIn('autor_declarado_ausente',self.codigos({},paginas))
        self.assertIn('autor_diverge_pdf',self.codigos({'nmAutor0':'Mircea, Eliade'},['Por\n\nMircea Eliade\n']))
        self.assertEqual(set(),self.codigos({'titulo':'Relatório institucional','tipo_documento':'documento'},['Relatório institucional\nTexto sem autor declarado.']))

    def test_cip_prevalece_sobre_copyright_do_original(self):
        paginas=['FICHA CATALOGRÁFICA\nJung, Carl Gustav, 1875-1961.\nJ92p Psicologia do inconsciente / C G Jung\nPetrópolis, Vozes, 1980.']
        ruins=self.codigos({'titulo':'OBRAS COMPLETAS DE C','nmAutor0':'Inconsciente, Psicologia do','data':'1971'},paginas)
        self.assertTrue({'titulo_diverge_cip','ano_diverge_cip','autor_diverge_pdf'}<=ruins)
        self.assertEqual(set(),self.codigos({'titulo':'Psicologia do inconsciente','nmAutor0':'Jung, Carl Gustav','data':'1980'},paginas))

    def test_isbn_confirmado_preserva_prioridade_editorial(self):
        paginas=['FICHA CATALOGRÁFICA\nLisboa, Editora Histórica, 1980.']
        for isbn in ('9780306406157','0306406152','080442957X'):
            self.assertTrue(v.isbn_confirmado({'isbn':isbn,'isbn_confirmado_na_edicao':True}))
            self.assertNotIn('ano_diverge_cip',self.codigos({'data':'2000','isbn':isbn,'isbn_confirmado_na_edicao':True},paginas))
        self.assertIn('ano_diverge_cip',self.codigos({'data':'2000','isbn_confirmado_na_edicao':True},paginas))

    def test_bibliografia_nao_e_editora_da_obra(self):
        fim=['\n'.join(f'{n}. Autor. Obra. Harper & Row, 1978.' for n in range(1,7))]
        a=self.codigos({'titulo':'Sincronicidad','editora':'Harper & Row','data':'1978'},['Título\nTexto'],fim)
        self.assertIn('bibliografia_como_editora',a)
        self.assertIn('bibliografia_como_data',a)
        self.assertNotIn('bibliografia_como_editora',self.codigos({'editora':'Harper & Row'},['Published by Harper & Row'],fim))

    def test_parcial_e_chapter_nao_passam_como_integral(self):
        self.assertIn('livro_parcial',self.codigos({'titulo':'Memórias [incompleto]','tipo_documento':'livro'}))
        self.assertNotIn('livro_parcial',self.codigos({'titulo':'Memórias [incompleto]','tipo_documento':'trecho'}))
        self.assertIn('capitulo_nao_classificado',self.codigos({'titulo':'Psychological Types','tipo_documento':'documento'},['Psychological Types\nCHAPTER X\nGENERAL DESCRIPTION']))
        self.assertNotIn('capitulo_nao_classificado',self.codigos({'titulo':'General description','tipo_documento':'trecho'},['CHAPTER X\nGENERAL DESCRIPTION']))

    def test_info_publicitario_e_nao_todo_texto_com_url(self):
        self.assertIn('informativo_distribuicao',self.codigos({'titulo':'Info'},['Biblioteca virtual gratuita\nVisite www.exemplo.org\nwebmaster@exemplo.org']))
        self.assertEqual(set(),self.codigos({'titulo':'Pesquisa sobre bibliotecas','tipo_documento':'documento'},['Biblioteca virtual gratuita é tema da pesquisa. Veja https://exemplo.org']))

    def test_decisao_humana_soberana_nao_e_importacao_automatica(self):
        f={'titulo':'Info','revisao_manual_aprovada':True}
        self.assertIn('informativo_distribuicao',self.codigos(f))
        f['ultimo_snapshot_revisao_manual']='_controle/snapshot.json'
        self.assertEqual(set(),self.codigos(f))

    def test_sobrenome_fragmentado(self):
        self.assertIn('sobrenome_fragmentado',self.codigos({'nmAutor0':'eree, C. George Bo'},['Dr. C. George Bo eree']))
        self.assertNotIn('sobrenome_fragmentado',self.codigos({'nmAutor0':'Boeree, C. George'},['Dr. C. George Boeree']))
