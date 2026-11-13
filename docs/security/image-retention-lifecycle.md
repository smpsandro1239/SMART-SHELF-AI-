# Ciclo de vida, retenção e eliminação de imagens

## Estado

Proposta técnica para orientar a implementação. **Não existe ainda endpoint de eliminação, job de purga nem política de retenção ativa.** Não assumir que imagens são eliminadas automaticamente.

## Objetivos e invariantes

- Aplicar minimização e limitação da conservação: conservar a imagem apenas pelo período e finalidade aprovados pela organização.
- Separar ocultação operacional, eliminação do ficheiro binário e eliminação de evidência derivada.
- Preservar a rastreabilidade necessária a revisões, auditoria, investigação de incidentes e obrigações legais.
- Impedir acesso cross-store e impedir que uma referência de armazenamento alcance ficheiros fora da raiz configurada e do diretório da loja.
- Não inferir que uma fotografia de prateleira está livre de dados pessoais. A captura deve minimizar pessoas e áreas não necessárias; a retenção requer avaliação de privacidade e aprovação do responsável competente.

## Dependências existentes

Uma linha `shelf_images` é referenciada por:

- `shelf_image_detections` — deteções de visão;
- `shelf_image_ocr_runs` — execuções OCR;
- `product_embedding_exemplars.shelf_image_id` — exemplar de embedding, com `ON DELETE SET NULL`.

As deteções são referenciadas por:

- `detection_sku_reviews` — decisões humanas;
- `shelf_image_ocr_evidence` — evidência OCR, com `ON DELETE SET NULL` para a deteção;
- `shelf_image_ocr_matches` — matching OCR;
- `shelf_image_fused_evidence` — fusão visual/OCR.

As execuções OCR são referenciadas por evidência, matches e fusões. As relações atuais usam várias regras `ON DELETE CASCADE`; apagar fisicamente uma imagem pode, portanto, apagar histórico técnico e decisões humanas. A eliminação física direta não deve ser exposta como operação normal.

## Ciclo de vida proposto

1. **ACTIVE** — imagem visível e elegível para análise conforme permissões e estado operacional.
2. **RESTRICTED** — acesso operacional bloqueado enquanto existe pedido de eliminação, incidente, revisão ou retenção legal; o binário não é servido por endpoints normais.
3. **PENDING_PURGE** — pedido aprovado e elegível para purga após período de segurança configurado; não permite novas análises nem retry.
4. **PURGED** — binário removido e metadados identificadores minimizados conforme política aprovada; manter apenas recibo de purga não reversível quando necessário.

A transição deve ser explícita, auditada, idempotente e autorizada. A purga não deve começar enquanto a análise estiver `PROCESSING`, enquanto existir uma operação dependente em curso ou enquanto uma retenção legal estiver ativa.

## Política de retenção

- Não fixar um prazo universal no código. O prazo depende da finalidade, enquadramento jurídico, contrato e política da loja.
- Antes de ativar o piloto, definir por escrito prazo por categoria de imagem, evento que inicia a contagem, exceções, retenção legal, responsável e processo de revisão.
- Tornar o prazo configurável por ambiente/loja, com limites validados e registo da versão da política aplicada a cada decisão.
- Separar a retenção do binário da retenção de métricas agregadas e de evidência técnica. A conservação de metadados derivados também exige finalidade e prazo definidos.
- Não usar imagens para treino ou dataset apenas porque continuam armazenadas; exigir autorização, proveniência e processo de release próprios.

## Requisitos de implementação da purga

- Usar um worker/job separado da API de pedidos, com lote limitado, reexecução segura e métricas.
- Revalidar autorização, loja, estado, prazo e retenção legal imediatamente antes da operação.
- Resolver o caminho real sob a raiz configurada e diretório da loja; rejeitar traversal, symlinks e ficheiros fora do âmbito.
- Evitar corrida entre validação e remoção: abrir/operar com diretório controlado, permissões restritas e estratégia resistente a troca de symlink (por exemplo, operações baseadas em descritores de diretório quando suportadas).
- Remover primeiro o binário de forma idempotente e registar o resultado. Não apagar metadados de evidência em cascata sem uma política de preservação aprovada.
- Se a remoção do ficheiro falhar, manter estado recuperável e registar erro; não declarar a imagem purgada.
- Se o ficheiro já não existir, tratar como resultado idempotente, mas registar que estava ausente.
- Garantir que backups, réplicas, caches e exports têm prazos próprios e que a eliminação neles é tratada pela política de backup; apagar o ficheiro principal não elimina cópias.
- Emitir evento de auditoria com ator ou identidade do job, motivo, política/versão, timestamps, resultado e identificador técnico não reversível. Não incluir o conteúdo da imagem nem dados pessoais desnecessários no evento.

## Critérios mínimos de aceitação

- Um utilizador de outra loja não consegue consultar, restringir ou purgar a imagem.
- Um EMPLOYEE não consegue executar ações administrativas de retenção.
- Uma imagem em processamento ou sob retenção legal não pode ser purgada.
- Uma repetição do job não causa erro nem apaga recursos não relacionados.
- Traversal, symlink e caminhos de outra loja são rejeitados.
- Falha de I/O deixa estado recuperável, não marca falsamente como purgado e permite retry auditado.
- Evidência OCR, deteções, revisões humanas e exemplares derivados seguem a política definida, sem cascatas acidentais.
- Testes de integração PostgreSQL verificam concorrência entre pedido de retenção, worker e análise.
- Testes verificam que os endpoints de listagem, conteúdo, retry, OCR, matching e fusão respeitam o estado de retenção.

## Sequência de implementação

1. Adicionar estado e timestamps de retenção com migração Alembic; sem alterar ainda as FKs históricas.
2. Introduzir serviço único de autorização/estado e aplicá-lo a todos os endpoints de imagem.
3. Adicionar pedido de restrição/eliminação lógica com auditoria e isolamento multi-loja.
4. Adicionar worker de purga com política configurável, proteção de caminhos e tratamento de falhas.
5. Definir tratamento de evidência derivada e anonimização/minimização dos metadados após validação jurídica.
6. Testar em PostgreSQL 16, incluindo concorrência, rollback, falhas de filesystem e reexecução idempotente.

## Limitação

Este documento é uma especificação técnica inicial, não um parecer jurídico nem uma política de retenção aprovada. A duração e as condições de conservação têm de ser definidas pela organização com o responsável de proteção de dados e assessoria jurídica antes de ativar a funcionalidade.
