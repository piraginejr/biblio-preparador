# Procedimento obrigatório

Este documento existe porque cada item abaixo veio de um erro real cometido
nesta biblioteca. Não é estilo nem preferência: é o que impede repetir.

**Leia antes de mexer no código ou nos dados do acervo.**

---

## 1. Ler o código antes de supor como ele funciona

Construí uma trava de segurança sobre a suposição de que
`"duplicado confirmado por ISBN"` sem `id_remoto` não tinha prova. A função
`consulta_confirmada_por_isbn` — dois arquivos ao lado — exige que o ISBN
enviado seja **idêntico** ao devolvido pelo Biblio. O estado *era* a prova.

Custou três idas e voltas. A definição estava escrita.

**Antes de decidir que algo está errado ou faltando, encontre onde aquilo é
produzido e leia.**

---

## 2. Correção manual vai para `revisoes-manuais.json`, nunca para a ficha

As fichas em `_metadados/*.json` são **descartáveis** — reescritas a cada
processamento. Gravei ali a correção do "Eu, um Discipulador" e ela teria
evaporado na primeira reexecução; a ficha depois mudou sozinha para
*"Primeiros passos 4 / Júnior, Paschoal Piragine"*.

O lugar certo é `_controle/revisoes-manuais.json`, protegido pelo SHA-256
do PDF: sobrevive a reprocessamentos e não se aplica ao arquivo errado.

Depois de qualquer correção, rode:

```
python3 conferir_revisoes.py --raiz ../livros
```

---

## 3. Implementar não é resolver

Melhorei o código e disse que as melhorias estavam feitas. Os livros
continuavam em revisão, porque **nunca reprocessei**. A frase "implementei"
deu a entender que o acervo estava pronto, e não estava.

Depois de mexer no código, **rode e mostre o resultado**. Sem isso, o que
existe é uma hipótese.

---

## 4. Medir antes de afirmar

Todo número desta conversa que valeu alguma coisa veio de medição, e várias
das minhas hipóteses caíram:

- classificar capa por geometria: acertou **1 em 12**;
- Vision contra Tesseract: **8/12 contra 4/12** nas mesmas capas;
- `HERMAN BAVINCK` sai `PER`, `PAUL DAVID TRIPP` sai `ORG` — só o teste
  mostrou que a caixa alta quebra o NER;
- o medidor de qualidade de OCR precisou de duas versões: a primeira
  reprovava 11 de 12 livros **bons**, a segunda dava **nota 1.0 para lixo**.

**Não diga que funciona antes de rodar. Não diga a taxa sem contar.**

---

## 5. Uma regra por vez

Liguei três extratores de título juntos. Cada um consertou um caso e quebrou
outro, e passei rodadas ajustando heurística contra 12 amostras — que é
adivinhação disfarçada de trabalho.

**Uma mudança, uma medição, um teste.**

---

## 6. Genérico cede para específico

Coloquei `publicado por X` antes dos padrões de tradução, e
*"Edição publicada pela Kregel"* passou a vencer
*"Copyright da tradução © Editora Proclamação"* — capturando a editora do
original em vez da tradução. Um teste seu pegou.

Padrão amplo vai **no fim** da lista.

---

## 7. A mesma informação em dois lugares sempre diverge

Três desencontros travaram itens no mesmo trecho de código:

| | |
|---|---|
| uma fila codificada à mão | existiam quatro |
| `id_remoto` tratado como prova | a prova era o estado |
| `"ficha"` numa fila, `"metadados"` na outra | mesmo dado, dois nomes |

Nenhum era erro de lógica. **Quem enumera deve enumerar de uma constante só.**

---

## 8. Erro silencioso é pior que conflito

O padrão de tudo que deu errado aqui: o programa produzia algo plausível,
sem marca, tendo a informação certa disponível.

- `"" in "lead"` é sempre verdadeiro em Python — todos os títulos passaram a
  ser sobrescritos pela API e nada avisou;
- um dígito mal lido do ISBN gerou três sintomas e nenhum alarme;
- `Things, Last` e `ORTODOXO, UM` — títulos invertidos virando autor, com a
  pendência acusando "editora";
- `re.I` anulava as guardas `[A-ZÁ-Ú]`, e prosa virava editora.

**Prefira marcar em excesso a acertar em silêncio.** Mas veja o item 9.

---

## 9. Conflito precisa ser acionável

Numa auditoria, os 8 conflitos exibidos eram **todos** ruído, e os dois erros
reais não estavam marcados. Ruído faz o operador parar de ler os avisos, que
é o pior desfecho possível.

A conta certa: **todo erro real marcado, todo conflito marcado real.**

---

## 10. Ausência precisa de causa

`"pendência: editora"` com a editora impressa na página 3 não diz nada.
`"editora: CIP sem resultado, créditos sem padrão, API sem resultado"` diz
onde procurar.

E há duas ausências diferentes: **"não tem"** é legítimo numa obra anterior a
1970 ou num manual de igreja; **"não consegui ler"** é defeito. Confundi-las
custou revisão artificial em sete itens.

---

## 11. Quando texto e imagem discordam, a imagem decide

O `pdftotext` leu `978-65-07-24846-2`; a imagem a 400 dpi mostra
`978-65-01-24846-2`. Enumerar correções deu dez candidatos — **ler a página
deu a resposta**.

Evidência antes de inferência. E guarde as duas leituras: quase sempre é erro
de OCR, mas existe livro impresso com ISBN errado.

---

## 12. Não afrouxar trava sem entender por que ela existe

Duas vezes estive a ponto de liberar exclusão com base em suposição. A regra:
diante de uma trava que atrapalha, **descubra o que ela protege**. Se ainda
assim precisar cair, torne o impasse **visível** em vez de silencioso.

---

## 13. Preservar o trabalho de revisão

São mais de 230 livros revisados à mão. Antes de qualquer mudança que toque
os dados:

```
cp _controle/revisoes-manuais.json _controle/revisoes-manuais.ANTES.json
```

E rode em simulação primeiro. `liberar_espaco` simula por padrão — respeite
esse desenho ao criar coisas novas.

---

## 14. Revisão existente se mescla, nunca se substitui

Ao gravar a correção do Packer sobrescrevi a revisão aprovada que já existia,
destruindo `autores` (com o tradutor) e `nmLingua`. O contador de revisões
pegou; o dado veio do backup.

Toda gravação parte do que já está lá:

```python
campos = dict(antiga.get("campos", {}))   # MESCLA
campos.update({...})
```

E confira o **número de revisões antes e depois**: perder uma é silencioso.

---

## 15. Formato que a esteira não converte é um arquivo invisível

Três vezes o mesmo defeito, com três formatos: um HTML parado meses em
00-ENTRADA, e depois **sete apresentações** `.ppt`/`.pptx`. Não eram
convertidos, não eram processados e **não eram reclamados** — o painel só
contava `*.pdf`.

O Biblio aceita **somente PDF**. Todo formato de entrada precisa de três
coisas, e a terceira é a que faltava:

1. um conversor para PDF;
2. um laço na esteira que o chame;
3. **aparecer na contagem quando não for tratado.**

---

## A sequência correta do fluxo

Erro real: o operador rodou a opção **8** e "nada saiu". Não havia bug — a
fila estava vazia porque as revisões nunca tinham sido aplicadas.

```
  revisão escrita  ->  reprocessar (11)  ->  fila (7)  ->  enviar (8)
```

Pular o reprocessamento faz a fila ficar vazia, e vazio parece defeito.

---

## Decisões tomadas e por quê

Registradas para não serem refeitas do zero — nem revertidas sem saber o
que se perde.

### Cache de ficha: escrito, testado, **não ligado** — 23/08/2026

`ficha_ainda_vale()` em `preparar-livros.py` compara o SHA-256 do PDF e uma
assinatura do programa para decidir se a ficha pode ser reaproveitada sem
reprocessar. **Nenhum módulo a chama.**

Quatro motivos, e o quarto é o que decidiu:

**Esconde melhoria.** Extração melhor não alcança acervo em cache. Invalidar
pela assinatura do programa resolve — mas aí qualquer mudança de código
invalida tudo, e o cache quase nunca serve. Agressivo esconde; conservador
não economiza.

**Cria um segundo caminho.** "O que o programa produz" e "o que está
guardado". Quando divergem, não se sabe qual se está vendo — o item 7 desta
lista já custou três itens travados.

**Interage mal com a revisão manual.** Pular um item cuja revisão acabou de
mudar anula a decisão humana.

**O ganho é menor do que parece.** O gargalo é OCR e consulta externa, e os
dois já têm proteção: o ocrmypdf usa `--skip-text`, e as consultas guardam
cache em `_controle/cache-*`. Sobraria economizar a parte barata.

Quando o acervo tinha 8 arquivos em disco, o custo era zero e o risco não.

**Reconsiderar quando** um lote de centenas tornar o reprocessamento
incômodo — e nesse dia **medir antes onde o tempo vai**. A resposta pode não
ser cache.

### isbnlib: medido contra o acervo, decisão em aberto — 04/09/2026

Avaliação do [isbnlib](https://github.com/xlcnd/isbnlib) 3.10.14 sobre as
fichas e os PDFs reais. **Nada foi implementado**; a biblioteca não está
instalada no Mac. Os números abaixo evitam refazer os testes.

**Vale a pena — 1. Guarda de prefixo.** Nosso `isbn_valido` confere só o
dígito verificador. `7898521805111` (*Antigo Testamento Interlinear*) passa,
mas **789 é código GS1 de produto**, não ISBN: livro é 978 ou 979. A consulta
à API com esse número falha em silêncio (item 8). `isbnlib.notisbn()` rejeita.
Custo: uma linha.

**Vale a pena — 2. `mask()`.** 325 dos 345 ISBNs válidos estão guardados sem
hífen. A posição do hífen depende da faixa de registro, e reproduzi-la exige a
tabela inteira da International ISBN Agency — que o isbnlib traz embutida e
resolve **offline**.

```
080105351X  ->  0-8010-5351-X        9788527507011  ->  978-85-275-0701-1
```

**Vale a pena — 3. `editions()`.** Lista outras edições da mesma obra. É a
pergunta exata dos itens travados como "já existente na API": *Na dinâmica do
Espírito* (id 11171) e o Packer (1991 aqui, 2010 lá). Exige internet; não foi
possível testar a fundo no ambiente de avaliação.

**NÃO usar para idioma — `info()`.** Devolve o grupo de registro. Bateu com o
`nmLingua` em 236 fichas e divergiu em 51 — mas as divergências são em sua
maioria **legítimas**: Portavoz, Kregel e Beacon são editoras americanas que
publicam em espanhol com ISBN do grupo 0.

```
978-0-8254-5608-4  grupo=inglês  ficha=Espanhol  "El Pastor silencioso"
```

O grupo diz onde a **editora** se registrou, não a língua do livro. Corrigir
automaticamente por aí estragaria dezenas de fichas. Serve, no máximo, como
pista de `lugar` quando o campo está vazio.

**NÃO trocar o nosso extrator.** Comparação em todos os PDFs em disco:

```
idênticos: 5 | só nosso: 0 | só isbnlib: 0
```

Empate no número, e o nosso devolve junto **rótulo, linha, contexto, formato
e volume** — é assim que distinguimos `ISBN` de `eISBN` e que o
`conferir_identidade` sabe qual página reler. O isbnlib devolve só o número.

Eu havia sugerido a troca *antes* de medir, e a medição me desmentiu — o
item 4 desta lista em ação.

**`meta()` não interessa:** já consultamos Open Library, Google Books, CBL,
BnF e LoC, mais fontes do que ele.

### Achado de raspão: `nmLingua` com caixa inconsistente — 04/09/2026

Encontrado ao conferir os idiomas, não pelo isbnlib. **11 fichas** vão para o
tombo com o idioma fora do padrão:

```
522 'Português'  80 'Inglês'  49 'Espanhol'
  5 'português'   4 'portugues'   1 'ingles'
```

---

## Decisões aguardando o responsável — 04/09/2026

Nada aqui foi implementado. Cada item tem a medição acima ou na conversa.

| decisão | evidência |
|---|---|
| adotar guarda 978/979, `mask()`, `editions()` do isbnlib | seção acima |
| títulos das apresentações: 5 de 7 errados e **nenhum marcado** | `Estudo 4` / autor `INGLATERRA, NA` |
| *Na dinâmica do Espírito* (id 11171) — correspondência aproximada | o Biblio tem a edição de 2010 |
| *Verdadeiros Adoradores* (id 2882) — **2 registros** no Biblio | subir criaria o terceiro |
| padronizar `nmLingua` em 11 fichas | seção acima |

---

## Lista operacional de melhorias — 05/09/2026

Esta lista transforma as pendências em trabalho executável. Cada item só deve
ser marcado como concluído depois de código, teste e medição em lote real ou
controlado.

### Ordem sugerida para começar

Para reduzir risco e já melhorar o aplicativo com pouco trabalho, a ordem
prática inicial deve ser:

1. **Padronizar `nmLingua`.** Implementado em 05/09/2026.
2. **Validar ISBN `978/979`.** Implementado em 05/09/2026, preservando
   ISBN-10.
3. **Tornar formatos não tratados visíveis.** Implementado em 05/09/2026.
   Não exige resolver todos os
   conversores de uma vez; primeiro impede que arquivos fiquem invisíveis.
4. **Ampliar a lista incremental de títulos/autores falsos recorrentes.**
   Implementado em 05/09/2026.
5. **Registrar motivos de rejeição das fontes.** Implementado em 05/09/2026.
6. **Melhorar títulos de apresentações e apostilas.** Implementado em
   05/09/2026.
7. **Usar `isbnlib` para máscara e edições.** Depois da validação básica estar
   estável, incorporar o benefício complementar.
8. **Consultar duplicidade antes do processamento pesado.** Tem ganho grande,
   mas toca o fluxo principal; deve vir depois das guardas simples.
9. **Comando 12 mais completo.** Depende de estados confiáveis de duplicado,
   descarte e cadastro.
10. **Módulo de revisão manual.** Muito importante, mas maior; fica melhor
    quando as pendências e motivos já estiverem mais limpos.
11. **Envio único de todos os tipos.** Última etapa operacional, depois que os
    tipos e filas estiverem bem classificados.
12. **Progresso granular nas etapas lentas.** Pode ser feito em paralelo quando
    uma etapa específica voltar a dar impressão de travamento.

### Prioridade 1 — evitar erro ou retrabalho caro

- [ ] **Criar o módulo de revisão manual.**
  - Motivo: hoje a revisão manual existe no arquivo
    `_controle/revisoes-manuais.json`, mas falta uma interface/rotina clara
    para revisar, aplicar, conferir e reprocessar sem depender de edição direta
    em JSON.
  - Implementar: listar pendências acionáveis; abrir a ficha atual; permitir
    corrigir título, autor, editora, idioma, edição, tipo, assunto, CDD,
    observações e decisão editorial; gravar sempre mesclando com revisão
    anterior; rodar conferência ao final.
  - Critério de pronto: uma correção feita pelo módulo sobrevive ao
    reprocessamento, não apaga campos anteriores e atualiza a fila correta.

- [x] **Validar ISBN como ISBN, não só como EAN-13.**
  - Motivo: `789...` pode ser código de produto com dígito correto, mas não é
    ISBN. Isso gera consulta inútil e falha silenciosa.
  - Implementar: aceitar ISBN-10 válido e ISBN-13 somente com prefixo `978` ou
    `979`; manter o número rejeitado como evidência, não como ISBN principal.
  - Critério de pronto: teste com `7898521805111` rejeitado como ISBN e teste
    com ISBN-10/ISBN-13 reais aceitos.

- [ ] **Consultar duplicidade na API antes de OCR, capa, compactação e fontes
  externas.**
  - Motivo: duplicatas já custaram muito processamento antes de serem
    descartadas.
  - Implementar: primeira passagem leve por ISBN; se não houver ISBN, título
    confiável + autor confiável; correspondência por ISBN pode descartar,
    correspondência aproximada deve registrar motivo.
  - Critério de pronto: lote com duplicados conhecidos evita processamento
    pesado e aparece no comando 12 para liberar espaço quando a duplicidade for
    confirmada.

- [x] **Tornar formatos não tratados visíveis no painel.**
  - Motivo: `.html`, `.pptx` e outros ficaram parados na entrada sem aparecer
    para o operador.
  - Implementar: contador explícito para formatos aguardando conversão ou
    classificação; nenhum arquivo de entrada pode ficar invisível.
  - Critério de pronto: entrada com `.pptx`, `.docx`, `.epub` e `.html`
    aparece no relatório mesmo quando não for convertida.

### Prioridade 2 — aumentar aprovação automática sem inventar ficha

- [ ] **Usar `isbnlib` de forma limitada.**
  - Motivo: a medição mostrou valor para validação, máscara e edições, mas não
    para idioma nem para substituir o extrator atual.
  - Implementar: `notisbn()`/validação de prefixo, `mask()` para exibição e
    `editions()` como pista de edição diferente.
  - Não implementar: `info()` para corrigir idioma.
  - Critério de pronto: relatório mostra ISBN normalizado com hífen sem perder
    o ISBN bruto extraído.

- [x] **Padronizar `nmLingua` sem inferir pelo ISBN.**
  - Motivo: existem valores equivalentes com caixa/grafia diferente.
  - Implementar: mapa único para `Português`, `Inglês`, `Espanhol`, etc.;
    preservar o idioma detectado/confirmado.
  - Critério de pronto: nenhuma ficha pronta sai com `portugues`, `português`,
    `ingles` ou variações fora do padrão escolhido.

- [x] **Melhorar títulos de apresentações e apostilas.**
  - Motivo: 5 de 7 apresentações medidas tiveram título errado e nenhum alerta.
  - Implementar: se o título extraído parecer aula genérica, país, rodapé,
    sumário, copyright ou fragmento, rebaixar confiança e exigir outra pista.
  - Critério de pronto: casos como `Estudo 4` e autor `INGLATERRA, NA` não
    passam como ficha pronta.

### Prioridade 3 — reduzir revisão humana em casos difíceis

- [x] **Registrar motivos de rejeição de fontes comerciais e acadêmicas.**
  - Motivo: "não aproveitou" não ensina; "ISBN diferente", "autor ausente",
    "título truncado" ensina.
  - Implementar: guardar motivo por candidato rejeitado em campo estruturado da
    ficha.
  - Critério de pronto: uma revisão mostra quais candidatos foram rejeitados e
    por quê.
  - Nota: Estante/Amazon ficam detalhadas por candidato; Crossref/OpenAlex/CORE
    ficam registrados como consulta sem convergência quando a API atual não
    preserva os candidatos rejeitados.

- [ ] **Usar outras edições como pista, não como duplicidade automática.**
  - Motivo: o Biblio pode ter edição diferente da mesma obra, e queremos manter
    histórico de edições quando fizer sentido.
  - Implementar: estado específico para "obra semelhante/edição diferente",
    separando de duplicado confirmado.
  - Critério de pronto: casos como *Na dinâmica do Espírito* e Packer não
    bloqueiam nem duplicam sem explicação.

- [x] **Ampliar lista incremental de títulos e autores falsos recorrentes.**
  - Motivo: erros como copyright, sumário, "todos os direitos reservados" e
    títulos de periódicos aparecem repetidamente.
  - Implementar: arquivo de regras incrementais lido pelo preparador, com
    testes para cada expressão recorrente.
  - Critério de pronto: uma correção manual recorrente vira regra e reduz o
    mesmo erro no próximo lote.

### Prioridade 4 — operação e experiência do usuário

- [ ] **Mostrar progresso granular nas etapas lentas.**
  - Motivo: quando a etapa fica minutos no mesmo item, parece travamento.
  - Implementar: exibir arquivo atual, etapa, porcentagem quando houver, bytes
    quando houver compactação/OCR e tempo decorrido.
  - Critério de pronto: processos longos mostram movimento em tela sem precisar
    abrir outro diagnóstico.

- [ ] **Garantir que o comando 12 limpe tudo que já pode sair da máquina.**
  - Motivo: pastas vazias, duplicados textuais e arquivos já cadastrados
    sobraram em lotes anteriores.
  - Implementar: simulação clara e execução abrangendo cadastrados, duplicados
    confirmados, descartes e pastas órfãs/vazias.
  - Critério de pronto: depois da execução, não sobram pastas vazias nem
    duplicados confirmados nos diretórios operacionais.

- [ ] **Unificar o envio de todos os tipos em uma opção simples.**
  - Motivo: hoje livros e documentos/artigos/revistas exigem comandos
    diferentes, o que cria confusão operacional.
  - Implementar: comando único para enviar tudo que está apto, respeitando
    `tipo`: livro, revista, artigo, jornal, documento, áudio ou vídeo.
  - Critério de pronto: o operador consegue enviar o lote pronto sem lembrar se
    era opção 8, 13/1, 13/2 ou 13/3.

---

## Checklist antes de dizer "está pronto"

- [ ] rodei, não só implementei
- [ ] os números vêm de contagem, não de estimativa
- [ ] `conferir_revisoes.py` sem divergências
- [ ] a suíte passa (`python3 -m pytest -q`)
- [ ] toda regra nova tem teste
- [ ] nenhum PDF foi alterado sem intenção
- [ ] disse com clareza o que **não** foi feito

---

*Escrito em 23 de agosto de 2026, depois do lote que originou cada item.*
