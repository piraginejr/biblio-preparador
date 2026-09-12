# Engenharia — GROBID central compartilhado via OpenVPN

## Objetivo

Disponibilizar um serviço GROBID central, rodando no servidor já usado pela
PIB/Biblio, para ser compartilhado pelos computadores dos voluntários que
preparam livros, artigos, teses, dissertações e documentos.

O objetivo imediato não é transformar o Biblio inteiro em um processador de
PDFs, mas retirar dos computadores dos voluntários a necessidade de instalar e
manter o GROBID localmente.

## Decisão de arquitetura

Usaremos, na fase inicial, o OpenVPN já existente no servidor.

Fluxo:

```text
App local do voluntário
        ↓
OpenVPN
        ↓
IP interno do servidor na VPN
        ↓
GROBID em contêiner
```

O app local continuará funcionando sem GROBID. Se a VPN estiver desconectada ou
o serviço central indisponível, o preparo prossegue pelas demais camadas.

## Por que não expor o GROBID diretamente na internet

Mesmo sendo software livre, o GROBID é um serviço técnico que aceita upload de
PDFs e consome CPU/memória. Deixá-lo aberto em IP público e porta pública cria
riscos desnecessários:

- uso indevido por scanners ou terceiros;
- consumo de recursos do servidor;
- uploads grandes ou malformados;
- dificuldade de distinguir voluntários autorizados de tráfego externo.

Com OpenVPN, o serviço fica acessível apenas a máquinas autorizadas.

## O que fica no servidor

Componentes previstos:

- contêiner GROBID;
- porta exposta apenas no IP/interface da VPN;
- script de limpeza de temporários/logs;
- regra de firewall impedindo acesso pelo IP público;
- teste de saúde do serviço.

Opcional em fase posterior:

- proxy do Biblio na frente do GROBID;
- autenticação por usuário do Biblio;
- fila central;
- histórico de uso por voluntário.

## O que fica no app local

O app local terá configurações:

- usar GROBID central: sim/não;
- URL do GROBID central, por exemplo `http://10.8.0.1:8070`;
- timeout curto;
- tamanho máximo de PDF a enviar;
- teste de conexão;
- fallback automático.

O app local só deve chamar GROBID para materiais em que ele realmente ajuda:

- artigo;
- tese;
- dissertação;
- trabalho acadêmico;
- material com aparência acadêmica.

Livros comuns não devem ser enviados ao GROBID por padrão.

## Política de falha

O GROBID central é uma camada auxiliar, não um bloqueador.

Se ocorrer:

- VPN desconectada;
- timeout;
- erro HTTP;
- GROBID indisponível;
- PDF acima do limite;

então o app deve registrar o motivo e continuar o processamento pelas demais
camadas.

Mensagem esperada ao operador:

> GROBID central indisponível; prosseguindo sem essa camada.

## Segurança mínima da fase 1

Requisitos:

- porta GROBID não exposta no IP público;
- acesso apenas pela rede OpenVPN;
- limite de tamanho no app antes do envio;
- timeout curto;
- limpeza programada no servidor;
- logs sem guardar PDFs permanentemente.

Não é requisito da fase 1:

- login integrado ao Biblio;
- tela administrativa web;
- auditoria por voluntário;
- fila central no site.

Esses itens ficam para fase posterior.

## Limpeza no servidor

Mesmo que o GROBID não seja um repositório de arquivos, o servidor deve ter uma
rotina de limpeza defensiva.

Critérios:

- apagar temporários antigos por idade;
- limitar crescimento de logs;
- opcionalmente alertar se uso de disco passar de um limite.

Política inicial sugerida:

- apagar temporários com mais de 24 horas;
- rotacionar logs;
- verificar uso de disco diariamente.

## Fase 1 — piloto técnico

### Resultado esperado

Ao final da fase 1:

- o GROBID roda no servidor;
- o serviço responde apenas pela VPN;
- o computador local, conectado à OpenVPN, consegue chamar o GROBID;
- o app local consegue testar a URL configurada;
- o app local usa o GROBID central quando disponível;
- se indisponível, o app continua sem travar;
- há um script de limpeza no servidor.

### Entradas necessárias

Antes de executar a fase 1, precisamos confirmar:

| Item | Valor |
|---|---|
| IP interno do servidor na OpenVPN | a definir |
| Porta desejada para GROBID | sugestão: `8070` |
| Sistema do servidor | a definir |
| Docker/Podman disponível | a verificar |
| Caminho para scripts de manutenção | a definir |
| Usuários/voluntários piloto | a definir |

### Roteiro técnico da fase 1

1. Confirmar IP interno da VPN no servidor.
2. Confirmar que o servidor aceita contêiner Docker/Podman.
3. Subir GROBID em contêiner.
4. Publicar a porta somente no IP/interface da VPN.
5. Bloquear acesso pelo IP público.
6. Testar do próprio servidor.
7. Testar de um Mac conectado à OpenVPN.
8. Criar script de limpeza.
9. Configurar o app local com a URL do GROBID central.
10. Processar lote pequeno de teste com artigos/teses.
11. Comparar resultado com o fluxo anterior.
12. Registrar tempo, erros e qualidade dos metadados.

### Critérios de aceitação

Fase 1 só é considerada concluída quando:

- o GROBID responde pela VPN;
- a porta não responde pelo IP público;
- o app local não trava se o GROBID cair;
- pelo menos 10 documentos acadêmicos são testados;
- o resultado é registrado em relatório;
- a limpeza automática foi instalada ou documentada.

## Fase 2 — integração no app dos voluntários

Objetivo:

- deixar o instalador local mais leve;
- permitir configurar GROBID central pela interface do app;
- exibir status claro ao operador.

Funcionalidades:

- campo para URL do GROBID central;
- botão “testar conexão”;
- opção “usar somente quando VPN estiver ativa”;
- limite local de tamanho;
- log por arquivo: usado, indisponível ou pulado.

## Fase 3 — integração com o Biblio

Somente depois da fase 1 estabilizada.

Possíveis melhorias:

- Biblio como proxy/porteiro;
- autenticação por usuário;
- painel de uso;
- fila central;
- auditoria;
- priorização por tipo de material;
- envio temporário do PDF com exclusão automática.

## Riscos e mitigação

| Risco | Mitigação |
|---|---|
| GROBID consumir CPU demais | limitar uso por contêiner e chamar só em material acadêmico |
| Voluntário sem VPN | app segue sem GROBID |
| Porta exposta sem querer | teste obrigatório por IP público |
| Arquivos grandes | limite antes do upload |
| Disco cheio | limpeza programada e alerta |
| Resultado ruim em livros comuns | não enviar livros comuns por padrão |

## Decisão atual

Começar pela fase 1 com GROBID central via OpenVPN, sem integração profunda com
o Biblio neste primeiro momento.

Depois de validado, integrar a configuração no app local dos voluntários.

O Biblio como proxy fica reservado para uma fase futura, quando houver volume,
mais voluntários ou necessidade de auditoria centralizada.
