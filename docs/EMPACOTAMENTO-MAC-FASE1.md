# Empacotamento Mac — fase 1

## Objetivo

Começar o empacotamento do Biblio Preparador sem alterar o que já está
funcional.

Nesta fase, o app Mac é apenas uma camada externa de lançamento. O motor atual
continua sendo:

- `99-FERRAMENTAS/LIVROS.command`
- `99-FERRAMENTAS/biblioteca-local.py`
- `99-FERRAMENTAS/enviar-livro-api.py`
- `99-FERRAMENTAS/revisao-visual.py`
- demais módulos já testados em `99-FERRAMENTAS/`

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
- abre o `BIBLIO-VISUAL.command`, que inicia a interface visual local;
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

1. o app abre o Terminal;
2. a interface visual local abre no navegador;
3. a biblioteca usada fica em:

   ```text
   ~/Library/Application Support/Biblio Preparador/revista/livros
   ```

4. o menu antigo continua disponível em `99-FERRAMENTAS/LIVROS.command`;
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
3. Trocar a abertura do Terminal pela interface visual aprovada.
4. Criar rotina segura de atualização das ferramentas empacotadas.
5. Definir estratégia para Python e dependências:
   - usar ambiente próprio em `~/.biblio-venv`, como hoje;
   - ou embutir runtime Python no app final.
6. Preparar assinatura/notarização em fase posterior.
