# Contrato de retenção e agregação — observabilidade Edge

**Estado:** decisões aprovadas; desenho de implementação  
**Data:** 2026-11-27  
**Retenção dos artefactos de observabilidade:** 90 dias

## Objectivo e limites

Introduzir histórico operacional Edge durável sem duplicar os ledgers de negócio existentes, sem expor métricas numa rota pública e sem tornar a observabilidade uma dependência do processamento de eventos.

A observabilidade é secundária: falhas de escrita, agregação, retenção ou leitura nunca podem bloquear, reverter ou atrasar de forma síncrona a ingestão, o worker, ACK, revisão humana ou inventário.

## Política de retenção aprovada

Aplicar **90 dias** a todos os artefactos derivados desta camada:
- agregações de 15 minutos;
- agregações diárias;
- eventos operacionais do supervisor.

O limite é aplicado por timestamp UTC e por política configurável, com valor por omissão de 90 dias. A limpeza deve ser limitada em lotes, idempotente, observável e executada apenas pelo processo de manutenção/agregação. Não se aplica às fontes de verdade de negócio.

**Fora desta política:** edge_device_event_inbox, edge_device_event_processing, edge_task_acknowledgements, edge_task_acknowledgement_reviews, edge_device_audit_events e telemetria actual em edge_devices. Estas tabelas mantêm as políticas próprias; não se introduz purga automática nem alteração das migrations 0103/0104.

## Fontes de verdade existentes

| Informação | Fonte |
|---|---|
| Eventos autenticados aceites | edge_device_event_inbox |
| Estado actual, tentativas acumuladas e leases | edge_device_event_processing |
| ACK declarados | edge_task_acknowledgements |
| Decisões humanas | edge_task_acknowledgement_reviews |
| Estado actual/última telemetria do dispositivo | edge_devices |
| Operações de dispositivo/credenciais | edge_device_audit_events |

Não criar cópias destes registos. O estado actual de processamento não permite reconstruir cada tentativa e os contadores process-local não permitem reconstruir pedidos rejeitados/duplicados depois de um reinício.

## Agregações

Criar agregados idempotentes em UTC, com dimensões explícitas de métrica, intervalo, início da janela, versão do esquema e tenant quando aplicável:
- janelas fixas de 15 minutos;
- janelas diárias UTC.

As métricas deriváveis da inbox/processing devem ser calculadas a partir dessas fontes, com predicado de loja na query e dimensão de dispositivo quando aplicável. Métricas não reconstruíveis a partir das fontes existentes não podem ser inventadas nem estimadas; permanecem identificadas como lacuna até existir um ponto de captura durável adequado.

O agregador deve recalcular janelas fechadas recentes para absorver atrasos, usar UPSERT/chaves únicas para replay seguro e guardar checkpoints transaccionais. Uma execução repetida para a mesma janela não pode duplicar contagens. As consultas devem ser limitadas por janela e suportadas por índices.

## Eventos do supervisor

Persistir apenas transições operacionais relevantes (arranque, paragem, crash, restart, heartbeat obsoleto, falha de spawn e recuperação), com timestamp UTC, instância/worker, tipo de evento, código limitado e metadados estritamente allowlisted. Não guardar payloads de negócio, credenciais, tokens, assinaturas, mensagens de excepção ou caminhos locais sensíveis.

O supervisor continua independente do worker. Uma falha ao persistir um evento operacional é best-effort e não pode impedir restart, backoff ou shutdown.

## Execução e segurança

- O agregador/manutenção corre como processo/serviço independente do Edge Event Worker.
- Sem endpoint público de métricas ou porta adicional.
- O processo de agregação não altera inbox, processing, ACK, reviews, tarefas, snapshots, movimentos ou inventário.
- store_id é sempre obtido da fonte original; não aceitar tenant fornecido pelo consumidor.
- Agregados globais de infraestrutura devem ser explicitamente separados dos agregados por loja.
- Checkpoints e UPSERTs são transaccionais; falhas provocam rollback apenas do lote de observabilidade.
- Retenção usa lotes limitados e nunca elimina fontes de verdade.
- Compatibilidade PostgreSQL 16 e SQLite nos testes de schema/serviço; concorrência e desempenho real validados em PostgreSQL 16.

## Critérios de aceitação da implementação

1. Migration nova encadeada depois de 0104, sem alterar migrations anteriores.
2. Modelos e constraints para agregados, checkpoints e eventos do supervisor.
3. Agregador idempotente, recuperável após crash e com isolamento multi-loja.
4. Retenção de 90 dias aplicada apenas aos artefactos de observabilidade.
5. Testes para replay, janelas UTC, atraso de eventos, isolamento de lojas, falha parcial, retenção e concorrência PostgreSQL.
6. Processo independente integrado no Docker Compose com hardening e healthcheck apropriado.
7. Nenhum efeito no ciclo de negócio quando a observabilidade está indisponível.
8. CI API/PostgreSQL 16, Quality Gates, Security Scans e Docker Compose aprovados no mesmo SHA antes de marcar como concluído.

## Lacunas deliberadamente não cobertas na primeira versão

- Histórico individual de cada transição/tentativa de processamento.
- Contabilização histórica de pedidos de ingestão rejeitados/duplicados não persistidos na inbox.
- Retenção ou purga dos ledgers de negócio.
- Activação de TASK_ACKNOWLEDGED ou qualquer alteração automática de inventário.
