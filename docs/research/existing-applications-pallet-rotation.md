# REA — Aplicações existentes para rastreabilidade e operações de paletes

Data da análise: 2026-11-12

Esta análise identifica projetos externos que podem informar a arquitetura do
SMART SHELF AI. Não implica copiar código nem adicionar dependências sem uma
avaliação técnica e jurídica própria.

## 1. Sentry WMS

Repositório: https://github.com/hightower-systems/sentry-wms
Licença indicada no repositório: Apache-2.0.

Capacidades relevantes descritas pelo projeto:
- receção e conferência por leitura de códigos de barras;
- put-away e sugestões de localização;
- picking por lotes e otimização de percursos;
- contagens cíclicas, transferências entre posições e entre armazéns;
- movimentos com histórico/auditoria;
- separação entre sistema ERP e camada de execução física;
- bloqueios de linha nas mutações de inventário para reduzir conflitos concorrentes;
- isolamento por armazém e registo de auditoria append-only.

**O que aproveitar conceptualmente:** separar decisão de reposição da execução física;
usar confirmação por leitura/scan para movimentos; registar origem/destino,
quantidade e operador; tornar as mutações transacionais e idempotentes; não
tratar uma recomendação como movimento realizado.

**O que não importar nesta fase:** o Sentry é um WMS completo para operações de
armazém/e-commerce, com stack e modelo de dados próprios. Não é um módulo
específico de reposição de paletes de exposição no retalho. Uma integração
direta acrescentaria complexidade e duplicaria partes do SMART SHELF AI.

## 2. OpenEPCIS Community Edition

Repositório: https://github.com/openepcis/epcis-repository-ce
Licença indicada para Community Edition: Apache-2.0. A Research Edition inclui
componentes que podem estar sujeitos a licença diferente; não assumir que todo
o repositório tem os mesmos termos.

O projeto implementa um repositório compatível com GS1 EPCIS 2.0, com captura e
consulta de eventos, JSON-LD, API REST e pipeline de eventos. O padrão EPCIS
serve para partilhar acontecimentos de cadeia de abastecimento — o que ocorreu,
quando, onde e em que contexto.

**O que aproveitar conceptualmente:** modelar a vida de uma palete como uma
sequência de eventos imutáveis, em vez de apenas sobrescrever a localização e
o estado atual. Exemplos de eventos futuros: receção, colocação em retaguarda,
preparação para exposição, colocação no linear, recolha da palete parcial,
regresso à retaguarda, recomposição e nova disponibilização.

**O que não importar nesta fase:** executar uma infraestrutura EPCIS completa
com Kafka, Quarkus e OpenSearch seria desproporcionado para a aplicação atual.
Podemos manter inicialmente um histórico relacional auditável e desenhar os
eventos com conceitos compatíveis com EPCIS, deixando uma integração externa
para uma fase em que existam parceiros/sistemas que a exijam.

## 3. GS1 EPCIS 2.0

Especificação e bindings REST:
https://ref.gs1.org/standards/epcis/
https://github.com/gs1/EPCIS/tree/master/REST%20Bindings

É a referência normativa para interoperabilidade de eventos de rastreabilidade.
Deve orientar a semântica dos eventos e a eventual troca de informação com
fornecedores, operadores logísticos ou sistemas corporativos.

## Decisão para SMART SHELF AI

A melhor abordagem é **aproveitar padrões, não adotar já outro WMS**:

1. Manter o motor de decisão de rotação de paletes independente e consultivo.
2. Introduzir identidade individual de palete e histórico de eventos antes de
   permitir qualquer movimentação operacional.
3. Usar confirmação do operador e leitura de código/identificador para cada
   transição física.
4. Garantir transações, idempotência, auditoria e controlo de concorrência.
5. Preservar SKU, quantidade em unidade base, lote, validade e localização.
6. Considerar compatibilidade EPCIS 2.0 no desenho dos eventos, sem tornar
   Kafka/OpenSearch requisitos da primeira versão.

## Lacunas de investigação

A pesquisa não identificou ainda um projeto open-source que implemente
exatamente a política de trocar uma palete de exposição parcialmente consumida
durante picos de afluência e recompor essa palete na retaguarda em períodos calmos.
Sentry WMS e OpenEPCIS resolvem problemas adjacentes (execução de armazém e
rastreabilidade de eventos), não a otimização específica proposta.

Antes de selecionar qualquer código externo para reutilização, é necessário
inspecionar a versão concreta, atividade, dependências, testes, modelo de
segurança e licença de cada componente.
