# Empacotamento Mac — fase 1

## Objetivo

### Formatos de entrada — atualização de 25/10/2026

Além de PDF, DOC/DOCX, apresentações e HTML, o importador aceita:

- TXT: texto UTF-8, UTF-16 com BOM, Windows-1252 ou Latin-1, convertido para
  PDF com texto real. HTML contido no texto é escapado e não executado.
- RTF, ODT e FODT: conversão silenciosa pelo LibreOffice.
- MOBI, AZW3 e FB2: mesmo fluxo Calibre do EPUB, sem remover DRM. Ausência
  do conversor, proteção do arquivo ou falha mantém o original e registra causa.

Arquivos de ajuda HLP e CHM são identificados como aguardando conversor
específico; não são executados nem anunciados como convertidos.

A conversão ocorre ao iniciar a preparação habitual. Não cadastra materiais
sozinha. O PDF passa pelo diagnóstico, capa e metadados existentes. Originais
ficam associados ao PDF para a liberação de espaço após cadastro/duplicidade
confirmados. A associação agora também contempla os novos formatos e HTML.
Um PDF homônimo já fornecido tem prioridade; a repetição do preparo não
reconverte uma origem inalterada.

### Atualização de 25/10/2026 — motor auditável e camada Apple

O pacote usa `versao-motor.json` para comparar código-fonte, pacote-base e
instalação ativa. A atualização preserva binários auxiliares e mescla listas
incrementais do operador; não apaga a pasta de ferramentas. Um servidor antigo
em memória não é aceito silenciosamente como se fosse o motor novo. Encerre as
tarefas antes de fechar/reabrir o aplicativo atualizado.

A Apple Intelligence é uma camada auxiliar automática nos pendentes, depois
das pesquisas existentes. Não refaz OCR, não consulta a internet e não altera
decisões humanas aprovadas. Requer Mac compatível com Apple Intelligence
disponível. Nos demais computadores, o fluxo anterior continua funcionando.

Para aplicar um campo, o motor exige trecho literal verificável na página e
concordância com fonte independente de identidade compatível. ISBN, volume ou
edição divergentes não são resolvidos apagando conflitos. Os validadores normais
continuam decidindo se o material está pronto; sugestões sem confirmação vão
para a bancada, no filtro **Análise da Apple**, com páginas citadas e imagens.

Os dados enviados ao modelo são somente excertos numerados das páginas (não
o nome de arquivo nem a ficha anterior). O cache é separado por hash do PDF,
entrada e versão do modelo/leitor. Respostas, imagens e histórico ficam em
`livros/_evidencias_apple/`, fora do Git. Os PDFs não são modificados.
Há limite de tempo e indicação de atividade a cada 15 segundos. Falhas ou
indisponibilidade mantêm a revisão, sem bloquear o lote. Para diagnóstico,
`BIBLIO_APPLE=0` desativa a camada. A primeira análise de cada versão prepara
o leitor Swift; as seguintes reutilizam o binário e as respostas em cache.

O piloto independente anterior não demonstrou segurança para aprovação pela
Apple sozinha. Por isso, citação sem confirmação externa continua sendo apenas
sugestão. O operador conserva a decisão final.

Começar o empacotamento do Biblio Preparador sem alterar o que já está
funcional.

Nesta fase, o app Mac passa a ser uma janela nativa com WebView. A interface
aprovada roda dentro dessa janela, e o motor atual continua sendo:

- `99-FERRAMENTAS/LIVROS.command`
- `99-FERRAMENTAS/biblioteca-local.py`
- `99-FERRAMENTAS/enviar-livro-api.py`
- `99-FERRAMENTAS/revisao-visual.py`
- demais módulos já testados em `99-FERRAMENTAS/`

Assim, o operador usa um aplicativo normal, mas não reescrevemos o motor já
validado.

## Princípio de segurança

O empacotamento não deve colocar livros, revisões, filas ou metadados dentro do
`.app`.

Motivo: aplicativos podem ser substituídos durante atualização. Se a biblioteca
ficasse dentro do app, uma atualização poderia apagar dados do operador.

Por isso, o app usa uma pasta externa do usuário:

```text
~/Library/Application Support/Biblio Preparador/revista
```

Dentro dela fica uma duplicata funcional do pacote-base:

```text
99-FERRAMENTAS/   cópia das ferramentas empacotadas
docs/             documentação operacional
livros/           biblioteca local do operador
```

## O que foi criado

Construtor:

```text
packaging/macos/build_app.sh
```

Ele gera:

```text
dist/Biblio Preparador.app
```

O app gerado:

- contém uma duplicata funcional em `Contents/Resources/pacote-base`;
- copia essa duplicata para a pasta externa do usuário na primeira abertura;
- abre uma janela Mac própria usando WebView;
- inicia automaticamente o servidor local do Biblio Preparador em
  `127.0.0.1:65087`;
- reutiliza a instância já aberta quando a porta fixa já está ocupada pelo
  próprio Biblio;
- mantém o `LIVROS.command` no pacote como plano B operacional;
- deixa o fluxo funcional exatamente como está hoje;
- não executa preparo, OCR, envio ou limpeza durante o build;
- não inclui o acervo local, filas reais, revisões reais, PDFs, caches ou
  segredos;
- não inclui senhas;
- não altera o script funcional.

## O que entra no pacote-base

Entra:

```text
99-FERRAMENTAS/
docs/
AGENTS.md
.gitignore
livros/ com estrutura vazia
```

Não entra:

```text
00-INDICE/
01-EDICOES-PDF/
02-MINERACAO/
03-REGISTROS-SELECIONADOS/
tmp/
livros/00-ENTRADA real
livros/10-REVISAO real
livros/20-PRONTOS real
livros/_controle real
livros/_metadados real
PDFs
chaves
caches
```

## Como gerar

Na raiz do projeto:

```bash
./packaging/macos/build_app.sh
```

## Como testar

Depois de gerar:

```bash
open "dist/Biblio Preparador.app"
```

O teste esperado nesta fase é simples:

1. o app abre uma janela própria chamada `Biblio Preparador`;
2. o servidor local é iniciado automaticamente em `127.0.0.1:65087`;
3. a biblioteca usada fica em:

   ```text
   ~/Library/Application Support/Biblio Preparador/revista/livros
   ```

4. o menu antigo continua disponível em `99-FERRAMENTAS/LIVROS.command` como
   plano B;
5. nenhum dado da pasta atual é modificado pelo simples ato de abrir o app.

## Limites desta primeira etapa

Esta fase já abre uma primeira interface visual operacional baseada no fluxo
aprovado no mockup.

Ela serve para:

- validar a estrutura de app instalável;
- separar ferramenta e dados do usuário;
- ligar os botões principais ao motor funcional existente;
- permitir que voluntários abram o sistema por ícone, sem conhecer a pasta de
  desenvolvimento.

## Próximas etapas

1. Criar instalador que copie o `.app` para `/Applications` ou para
   `~/Applications`.
2. Adicionar verificador visual de dependências.
3. Trazer a bancada de revisão para dentro da mesma janela WebView quando
   concluirmos o fluxo principal.
4. Criar rotina segura de atualização das ferramentas empacotadas.
5. Definir estratégia para Python e dependências:
   - usar ambiente próprio em `~/.biblio-venv`, como hoje;
   - ou embutir runtime Python no app final.
6. Preparar assinatura/notarização em fase posterior.
