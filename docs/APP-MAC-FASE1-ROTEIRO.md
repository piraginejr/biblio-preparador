# Roteiro da fase 1 — aplicativo Mac instalável

## Objetivo da fase 1

Transformar o sistema atual de preparo de livros em um aplicativo Mac
instalável, sem reescrever o motor que já funciona.

O foco desta fase é sair de:

```text
abrir 99-FERRAMENTAS/LIVROS.command
```

para:

```text
abrir Biblio Preparador.app
```

com interface visual, diagnóstico, progresso e instalador.

## Resultado esperado

Ao final da fase 1, devemos ter:

- `Biblio Preparador.app`;
- instalador `.dmg` ou `.pkg`;
- primeira tela de configuração;
- seleção/criação da biblioteca local;
- botões para as operações principais;
- bancada visual integrada;
- logs acessíveis;
- verificador de dependências;
- envio pela API;
- liberação de espaço;
- documentação curta para voluntários.

## Estratégia

Preservar o motor atual.

O aplicativo visual será uma camada de controle por cima dos módulos existentes.

O motor continua podendo ser testado por comandos internos, mas o voluntário
não precisará vê-los.

## Etapa 0 — preparar a base antes do app

### Objetivo

Garantir que o motor atual esteja suficientemente estável para ser empacotado.

### Tarefas

- [ ] Rodar testes automatizados.
- [ ] Corrigir falhas críticas.
- [ ] Confirmar que o comando 1 processa um lote pequeno.
- [ ] Confirmar que o comando 17 abre a revisão visual.
- [ ] Confirmar que o comando 16 envia tudo que está pronto.
- [ ] Confirmar que o comando 12 libera espaço corretamente.
- [ ] Confirmar que revisões manuais sobrevivem ao reprocessamento.
- [ ] Criar commit de estabilização.

### Critério de aceite

O sistema atual deve funcionar pelo menu antes de ser transformado em app.

## Etapa 1 — inventário do motor

### Objetivo

Separar claramente o que é motor do produto, dado do usuário, cache,
dependência externa e ferramenta antiga.

### Tarefas

- [ ] Listar módulos essenciais.
- [ ] Listar módulos auxiliares.
- [ ] Listar scripts históricos que não entram no app.
- [ ] Listar arquivos JSON de aprendizado.
- [ ] Listar pastas do acervo.
- [ ] Listar arquivos de controle.
- [ ] Listar dependências Python.
- [ ] Listar dependências externas do sistema.

### Entregável

Documento:

```text
docs/APP-MAC-INVENTARIO.md
```

## Etapa 2 — definir a tecnologia da interface Mac

### Opções possíveis

#### Opção A — app nativo simples

Interface nativa para macOS chamando o motor Python.

Vantagens:

- experiência mais parecida com aplicativo Mac;
- melhor integração com arquivos, permissões e Chaves do macOS.

Desvantagens:

- mais trabalho de desenvolvimento visual;
- mais cuidado com empacotamento.

#### Opção B — app web local empacotado

O app abre uma janela local, parecida com a bancada visual atual.

Vantagens:

- reaproveita bastante da bancada visual;
- mais fácil portar depois para Windows;
- uma interface web pode ser compartilhada entre sistemas.

Desvantagens:

- precisa empacotar servidor local;
- aparência pode parecer menos “nativa”.

#### Opção C — wrapper inicial do menu atual

Primeira versão apenas coloca botões sobre os comandos existentes.

Vantagens:

- mais rápido;
- menor risco;
- útil para piloto.

Desvantagens:

- menos bonito;
- ainda não resolve toda a experiência do usuário.

### Recomendação

Usar uma abordagem progressiva:

1. começar pela opção C para empacotar o fluxo real;
2. evoluir para opção B, reaproveitando a bancada visual;
3. só considerar nativo completo se houver necessidade.

Essa escolha acelera a entrega e facilita o futuro Windows.

## Etapa 3 — criar camada única de comandos do motor

### Objetivo

Evitar que a interface chame diretamente dezenas de scripts diferentes.

Criar uma camada única, por exemplo:

```text
99-FERRAMENTAS/biblio_app_service.py
```

Essa camada deve oferecer operações de alto nível:

- status da biblioteca;
- verificar dependências;
- processar ciclo completo;
- processar ciclo sem internet;
- reprocessar revisão;
- atualizar filas;
- enviar tudo;
- enviar por tipo;
- liberar espaço;
- abrir revisão visual;
- testar API;
- testar GROBID;
- abrir logs.

### Critério de aceite

A interface visual deve chamar essa camada, e não conhecer detalhes internos de
cada script.

## Etapa 4 — configuração do app

### Objetivo

Tirar caminhos fixos do ambiente de desenvolvimento.

### Configurações necessárias

- pasta da biblioteca;
- URL da API do Biblio;
- uso de internet;
- uso de GROBID;
- URL do GROBID central, se houver;
- limite de tamanho;
- local dos logs;
- preferências de envio.

### Armazenamento sugerido

Configurações comuns:

```text
~/Library/Application Support/Biblio Preparador/config.json
```

Chave da API:

```text
Chaves do macOS
```

## Etapa 5 — interface inicial

### Layout aprovado em 13/09/2026

O protótipo aprovado para a fase 1 está registrado em:

- `/Users/piraginejr/.codex/visualizations/2026/07/27/019fa273-6b82-7741-802f-cb5b4cb585b1/biblio-app-mockups-lateral.html`
- `/Users/piraginejr/.codex/visualizations/2026/07/27/019fa273-6b82-7741-802f-cb5b4cb585b1/biblio-revisao-bancada-aprovada.html`

Decisão de produto:

- manter o fluxo assistido em cinco etapas:
  1. **Importar** — arquivos ou pasta;
  2. **Preparar** — esteira do lote;
  3. **Enviar** — subir e limpar;
  4. **Revisar** — corrigir pendentes;
  5. **Concluir** — resumo final.
- a tela inicial deve orientar o operador em poucas palavras, sem ocupar espaço
  excessivo com explicações;
- o operador deve poder selecionar vários arquivos, escolher uma pasta local ou
  abrir a pasta de entrada criada pelo aplicativo;
- ao clicar em “Iniciar preparação”, o app deve mudar para uma tela de
  acompanhamento, deixando claro que está trabalhando;
- todos os dados de progresso devem ficar concentrados em um único bloco:
  barras de progresso, arquivo atual, etapa atual e atividade em tempo real;
- o botão “Ver detalhes” abre uma tela ou painel detalhado do processamento,
  sem poluir a visão principal;
- ao terminar a preparação, se houver material pronto, a tela **Enviar** deve
  abrir automaticamente; ela também continua acessível pelo passo 3;
- a tela **Enviar** deve mostrar a fila, o resultado de cada envio, duplicatas
  evitadas, erros recuperáveis e ação de limpeza;
- a tela **Revisar** deve usar a bancada visual já aprovada, sem redesenhar o
  painel de leitura.

Regra específica da bancada de revisão:

- manter o layout em três colunas:
  - lista de itens à esquerda;
  - PDF ou material ativo no centro;
  - campos de cadastro e decisão à direita;
- não empilhar as colunas automaticamente, pois as laterais são parte essencial
  da revisão manual;
- em telas estreitas, preferir rolagem horizontal a empilhamento;
- preservar os botões existentes da bancada:
  - salvar / validar;
  - salvar e próximo;
  - confirmar divergência;
  - salvar sem aprovar;
  - consultar dados por ISBN;
  - usar capa da internet;
  - usar arquivo de capa;
  - abrir PDF ativo;
  - abrir capa;
  - recarregar;
- a bancada pode receber uma faixa discreta do fluxo do app, com retorno para
  **Enviar** e avanço para **Concluir**, mas essa faixa não deve alterar a
  bancada aprovada;
- o fundo deve ser claro, na paleta bege/verde do app, mas a estrutura da
  bancada deve continuar igual à versão testada no navegador.

### Tela inicial

Deve mostrar:

- biblioteca selecionada;
- entrada;
- revisão;
- prontos;
- cadastrados;
- duplicados;
- descartes;
- estado da API;
- estado do GROBID;
- estado das dependências.

### Fluxo assistido principal

A primeira experiência do operador não deve ser escolher entre muitos comandos.
O aplicativo deve conduzir o trabalho em sequência.

Referências de design pesquisadas:

- Calibre: oferece “Adicionar livros” por arquivo, pasta única, pastas e
  subpastas, arquivo compactado e ISBN. A lição para nós é que a entrada deve
  aceitar lote e pasta, não apenas exigir que o operador encontre manualmente a
  pasta interna.
- Paperless-ngx: trabalha com uma pasta de consumo, mas também permite upload
  pela interface. A lição para nós é separar “local temporário de entrada” da
  biblioteca organizada, mostrando ao operador que a entrada é uma bandeja de
  chegada.
- Zotero e Mendeley: permitem arrastar PDFs ou importar pastas inteiras e
  depois tentam recuperar metadados automaticamente. A lição para nós é tratar
  importação e recuperação de dados como uma etapa única, visível e
  tranquilizadora.
- Libib, BookBuddy e apps de catalogação: priorizam ações humanas simples como
  escanear, digitar ISBN, adicionar manualmente e organizar em coleções. A lição
  para nós é esconder complexidade técnica e mostrar ações compreensíveis.

Fluxo recomendado:

1. **Entrada dos materiais**
   - Se a biblioteca ainda não existir, o app cria a estrutura.
   - O app mostra claramente onde colocar os arquivos, mas não depende apenas
     disso.
   - O app oferece três caminhos de entrada:
     - selecionar vários arquivos;
     - escolher uma pasta local inteira para o app importar;
     - abrir a pasta de entrada criada na instalação.
   - Ao escolher arquivos ou uma pasta, o app copia ou move para a entrada
     correta de forma controlada.
   - Antes de preparar, o app mostra uma pré-lista do lote importado:
     - arquivos PDF;
     - Word/PowerPoint/EPUB a converter;
     - pastas com OPF/capa;
     - formatos não reconhecidos;
     - possíveis duplicatas locais.
   - Mensagem desejada:

     ```text
     Escolha arquivos, selecione uma pasta ou abra a pasta de entrada.
     O Biblio Preparador organizará o lote antes de iniciar a preparação.
     ```

2. **Preparação**
   - O operador clica em “Iniciar preparação”.
   - O app executa o ciclo completo.
   - A tela mostra etapa atual, arquivo atual e progresso.
   - Ao terminar, o app mostra um resumo:
     - quantos ficaram prontos;
     - quantos foram para revisão;
     - quantos eram duplicados;
     - quantos falharam;
     - quanto espaço poderá ser liberado depois do envio.

3. **Pergunta sobre envio dos prontos**
   - Se houver itens prontos, o app pergunta:

     ```text
     Há materiais prontos para cadastro. Deseja enviá-los agora?
     ```

   - Essa tela deve abrir automaticamente ao final da preparação quando houver
     materiais prontos.
   - Ela também continua acessível manualmente pelo passo “Enviar”.
   - Opções:
     - “Enviar agora”
     - “Enviar depois”
     - “Ver lista antes”

4. **Envio**
   - Se o operador escolher enviar, o app consulta a API antes de cada envio.
   - Duplicatas confirmadas não são reenviadas.
   - Erro em um item não deve travar o lote inteiro.
   - Ao final, o app mostra:
     - enviados;
     - duplicados evitados;
     - falhas;
     - incertos;
     - pendentes.

5. **Limpeza após envio**
   - Depois do envio, se houver arquivos cadastrados, duplicados confirmados ou
     descartados, o app pergunta:

     ```text
     Deseja liberar espaço local agora?
     ```

   - O app simula primeiro e mostra o que será movido para a Lixeira.
   - Só executa com confirmação explícita.

6. **Revisão dos pendentes**
   - Se houver itens em revisão, o app pergunta:

     ```text
     Deseja abrir agora o painel de revisão dos itens pendentes?
     ```

   - Opções:
     - “Abrir revisão”
     - “Revisar depois”

7. **Após terminar a revisão**
   - Quando o operador concluir a bancada visual, o app volta para o fluxo e
     pergunta novamente:

     ```text
     Alguns materiais ficaram prontos depois da revisão. Deseja enviá-los agora?
     ```

   - Se sim, envia.
   - Depois pergunta novamente se deseja liberar espaço.

8. **Conclusão**
   - O app encerra com uma tela clara:

     ```text
     Trabalho concluído.
     Não há novos materiais prontos para envio.
     Itens restantes precisam de revisão posterior ou ação específica.
     ```

Esse fluxo deve ser o caminho principal do aplicativo. As demais funções
continuam existindo, mas como ações secundárias em “Ferramentas” ou
“Diagnóstico”.

### Botões principais

- Preparar novo lote.
- Reavaliar revisão.
- Abrir revisão visual.
- Enviar tudo pronto.
- Enviar por tipo.
- Liberar espaço.
- Diagnóstico.
- Configurações.

### Progresso

O app deve mostrar:

- etapa atual;
- arquivo atual;
- porcentagem quando disponível;
- contador de itens;
- mensagem clara quando pular uma camada;
- erro recuperável sem parecer travamento.

## Etapa 6 — logs e suporte

### Objetivo

Permitir entender o que aconteceu sem depender da memória do operador.

### Funções

- ver último processamento;
- abrir pasta de logs;
- gerar pacote de suporte;
- copiar resumo técnico;
- mostrar erros recentes em linguagem simples.

### Pacote de suporte

Deve conter:

- versão do app;
- sistema operacional;
- dependências encontradas;
- últimos logs;
- status da biblioteca;
- erros recentes;
- nunca incluir chave da API;
- nunca incluir PDFs completos sem confirmação.

## Etapa 7 — empacotar Python e dependências

### Objetivo

Fazer o aplicativo rodar fora da pasta de desenvolvimento.

### Tarefas

- [ ] Definir ambiente Python do app.
- [ ] Congelar dependências Python.
- [ ] Incluir módulos do motor.
- [ ] Incluir listas de aprendizado.
- [ ] Incluir arquivos Swift/binários do Vision.
- [ ] Criar verificador de binários externos.
- [ ] Testar em pasta limpa.

### Atenção

Não colocar dentro do app:

- PDFs;
- acervo;
- caches grandes;
- logs antigos;
- chaves;
- arquivos temporários.

## Etapa 8 — instalador Mac

### Objetivo

Criar um pacote que possa ser entregue a voluntários.

### Primeira versão

Pode ser:

- `.dmg` com o app;
- instrução “arraste para Aplicativos”;
- primeira execução cria configuração.

### Versão posterior

Pode evoluir para:

- `.pkg`;
- assinatura;
- notarização;
- atualização automática.

### Testes do instalador

- instalar em outra pasta;
- abrir sem terminal;
- escolher biblioteca;
- configurar API;
- processar lote pequeno;
- remover app sem remover biblioteca.

## Etapa 9 — piloto Mac

### Lote de teste

Usar um lote misto:

- livros com ISBN;
- livros sem ISBN;
- livros antigos;
- documentos;
- artigos;
- teses/dissertações;
- revistas;
- Word;
- PowerPoint;
- EPUB;
- duplicatas.

### Métricas

Registrar:

- tempo de instalação;
- dependências faltantes;
- erros;
- quantidade processada;
- quantidade pronta;
- quantidade em revisão;
- quantidade enviada;
- duplicatas evitadas;
- tempo de revisão manual.

## Etapa 10 — Mac 1.0 interno

### Entregáveis

- instalador;
- documentação curta;
- relatório do piloto;
- lista de problemas conhecidos;
- rotina de atualização;
- rotina de suporte.

### Critério de conclusão

Um voluntário consegue preparar e enviar um lote real sem usar terminal.

## Ordem recomendada de execução agora

1. Criar inventário do motor.
2. Criar camada única de serviço do app.
3. Adaptar a bancada visual para ser chamada como módulo do app.
4. Criar protótipo de tela inicial.
5. Criar diagnóstico de dependências.
6. Empacotar protótipo como `.app`.
7. Testar em pasta limpa.
8. Criar `.dmg`.
9. Fazer piloto.

## Decisões pendentes

| Decisão | Opção recomendada inicial |
|---|---|
| Tecnologia da interface | web local empacotada ou wrapper simples |
| Instalador | `.dmg` na primeira versão |
| Python | ambiente próprio empacotado |
| OCR no Mac | Apple Vision mantido |
| GROBID | opcional, local ou central |
| Atualização | manual no piloto |
| Windows | somente depois do Mac estabilizado |

## Relação com o GROBID

O GROBID não é o centro do aplicativo.

Ele é uma camada especializada para material acadêmico dentro do app.

Na fase Mac, o app deve aceitar:

- GROBID desligado;
- GROBID local;
- GROBID central via OpenVPN.

Se o GROBID falhar, o preparo continua.

## Relação com Windows

Tudo que for construído na fase Mac deve evitar depender demais de recursos
exclusivos do Mac, exceto onde isso for inevitável.

Especialmente:

- separar OCR como provedor;
- separar cofre de chave como provedor;
- separar abertura de arquivos como provedor;
- separar instalador como etapa própria.

Essa preparação torna a fase Windows mais barata.
