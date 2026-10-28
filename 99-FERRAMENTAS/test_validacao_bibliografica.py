import unittest
import validacao_bibliografica as v


class ValidacaoBibliograficaTest(unittest.TestCase):
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
