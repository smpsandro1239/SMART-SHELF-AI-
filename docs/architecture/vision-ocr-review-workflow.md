# Fluxo operacional de visão, OCR e revisão humana

## Objetivo

Este documento descreve a sequência operacional desde a fotografia até à decisão humana. A arquitetura separa deteção, leitura de texto, matching de catálogo, fusão de evidência e decisão de revisão.

## Configuração opcional do worker

O OCR está desligado por omissão. Para o ativar, instalar as dependências CPU compatíveis e configurar no ambiente do worker:

```dotenv
VISION_PROVIDER_FACTORY=app.vision_onnx:create_provider
OCR_PROVIDER_FACTORY=app.ocr_paddle:create_provider
OCR_PROVIDER_NAME=paddleocr
OCR_MODEL_VERSION=PP-OCRv5-pt
```

Os modelos ONNX de deteção e embeddings têm de existir nos caminhos configurados. O runtime PaddlePaddle e os pesos PaddleOCR devem ser instalados separadamente, de acordo com a plataforma. A configuração de exemplo encontra-se em `apps/api/.env.vision.example`.

Executar o worker a partir de `apps/api`:

```bash
python -m app.vision_worker --once
```

Sem `OCR_PROVIDER_FACTORY`, o worker executa apenas a visão. Se a inicialização ou inferência OCR falhar, a análise visual é preservada e a tentativa OCR fica registada como `FAILED`. A escrita de cada execução OCR usa um savepoint: uma falha durante a leitura ou persistência não deixa regiões parciais nem elimina deteções visuais. As tentativas são append-only, permitindo distinguir falhas de execuções concluídas.

Para repetir apenas o OCR de uma imagem cuja análise visual já terminou, configurar `OCR_PROVIDER_FACTORY` e executar:

```bash
python -m app.vision_worker --retry-failed-ocr-image-id 123
```

O comando só aceita imagens `ACTIVE` com análise visual `COMPLETED` e cuja tentativa OCR mais recente esteja `FAILED`. Bloqueia a linha da imagem durante a operação para serializar a repetição com alterações de retenção. Não volta a executar deteção nem embeddings; preserva as deteções e as tentativas OCR anteriores. A suite `test_product_pipeline.py` também verifica que imagens `RESTRICTED` e imagens sem uma última tentativa `FAILED` são rejeitadas antes de resolver o caminho do ficheiro ou chamar o provider OCR. O teste de repetição confirma ainda que, depois de uma tentativa bem-sucedida, uma segunda invocação não cria uma nova execução. Código de saída `0` indica uma nova execução OCR concluída, `1` indica que a imagem não era elegível ou que a repetição falhou, e `2` indica configuração/provider indisponível.

## Sequência funcional

1. Carregar a fotografia para `POST /api/v1/shelf-images`.
2. O worker cria deteções visuais e, se configurado, persiste regiões OCR.
3. Cada região OCR é associada geometricamente a, no máximo, uma deteção. Regiões sem sobreposição suficiente ficam `UNASSIGNED`.
4. Depois de persistir uma execução OCR concluída, o worker chama automaticamente o serviço `app.product_pipeline.process_completed_ocr_run`: cria correspondências textuais contra produtos ativos e funde-as com os resultados visuais.
5. O matching e a fusão são executados num savepoint isolado. Uma falha nesta fase é registada, mas não invalida as deteções visuais nem as regiões OCR já persistidas.
6. O serviço é idempotente: preserva correspondências e fusões existentes e cria apenas os registos em falta. Os endpoints `POST /api/v1/shelf-images/{image_id}/ocr-matches` e `POST /api/v1/shelf-images/{image_id}/evidence-fusion` continuam disponíveis para execução manual.
7. Consultar os totais por estado em `GET /api/v1/shelf-image-review-queue/summary` e a fila em `GET /api/v1/shelf-image-review-queue`; filtrar por `status`, `limit` e `offset`.
8. Consultar a fotografia e as deteções e submeter a decisão humana em `POST /api/v1/shelf-image-detections/{detection_id}/reviews`.

## Prioridade e decisão

A fila ordena `CONFLICT`, `AMBIGUOUS`, `TEXT_ONLY`, `UNKNOWN` e `VISUAL_ONLY`. `CONSENSUS` também pode ser consultado, mas não é uma aprovação automática.

Uma revisão é um registo append-only. Se for criada nova evidência depois da última revisão, a deteção volta a aparecer na fila. A confirmação/correção valida um SKU ativo associado à prateleira; rejeitar não seleciona SKU.

## Limites de segurança e validade

- O worker nunca atualiza stock nem cria movimentos de inventário.
- OCR e visão não são probabilidades intercambiáveis; os scores são apresentados separadamente.
- A caixa OCR representa texto, não o produto.
- A associação geométrica não garante que o texto pertence semanticamente ao produto; reflexos, etiquetas de preço e cartazes podem exigir revisão.
- A decisão humana não reescreve a saída original do modelo.
- A execução com provider simulado valida integração, não a precisão em imagens reais.
- Antes de um piloto, medir precisão/recall OCR, taxa de associação correta, precisão de SKU quando sugerido, cobertura, taxa de abstenção e tempo médio de revisão num conjunto de imagens autorizado e representativo.


## Interface de operação

O dashboard React apresenta a fila de revisão a administradores e supervisores, com contagens por estado, prioridade, identificação da fotografia e motivo da decisão. A ação **Abrir fotografia e rever** leva à captura correspondente, onde o operador pode consultar as caixas de deteção, os produtos atribuídos à prateleira e o histórico de decisões humanas.

A fila do dashboard carrega até 50 itens prioritários. O endpoint suporta paginação por `limit` e `offset`; a navegação de todas as páginas pode ser adicionada quando o volume operacional o justificar.

## Recuperação de tarefas de inferência interrompidas

O worker reencaminha tarefas `PROCESSING` abandonadas para `PENDING` quando `analysis_started_at` é anterior ao limite configurado em `VISION_PROCESSING_TIMEOUT_SECONDS` (24 horas por omissão; intervalo permitido de 60 segundos a 7 dias). Apenas imagens com retenção `ACTIVE` são elegíveis. O mecanismo limpa os timestamps de execução e conserva uma indicação de recuperação em `analysis_error`. Imagens recentes e imagens `RESTRICTED` não são recuperadas. A recuperação é executada antes de cada procura de novo trabalho.

## Exclusão de resultados de leases expirados

Cada tentativa de processamento fica identificada pelo valor de `analysis_started_at` gravado quando a imagem é reclamada. Após a inferência, o worker bloqueia e atualiza a leitura da linha (`populate_existing`) e verifica que o estado continua `PROCESSING` e que o timestamp ainda pertence à sua tentativa. Se o timeout tiver reencaminhado a tarefa e outro worker a tiver reclamado, a tentativa anterior termina sem persistir deteções ou evidência OCR. A mesma verificação é repetida antes de marcar a imagem como `COMPLETED`. O teste `test_worker_discards_result_when_processing_lease_changes_during_inference` cobre a substituição do lease durante a inferência. A validação CI ainda está pendente.

## Retenção, restrição e purge definitivo

A restrição (RESTRICTED) é uma suspensão de acesso e processamento, não uma eliminação. O endpoint de conteúdo devolve HTTP 410 para imagens restringidas, e a listagem de exemplares de embeddings exclui exemplares ligados a imagens que não estejam ACTIVE. O teste de integração test_restricted_own_store_image_rejects_ocr_writes_and_retry cobre também estes dois limites.

**Limitação identificada na auditoria:** o modelo contém campos para PURGED, purged_at e purge_not_before, mas a API atual não expõe um fluxo de purge definitivo nem foi encontrado um worker que elimine o ficheiro e os dados derivados. Não se deve interpretar a restrição como cumprimento de um pedido de apagamento definitivo.

Um fluxo de purge futuro tem de:
- exigir autorização administrativa e motivo auditável;
- recusar imagens com legal_hold ativo ou ainda dentro do período de retenção;
- serializar a operação com workers e alterações de retenção através do lock da imagem;
- remover o ficheiro apenas depois de validar que o caminho pertence ao diretório da loja;
- eliminar ou anonimizar embeddings de origem, deteções, execuções OCR, evidências, correspondências e fusões;
- preservar o registo mínimo da imagem e os eventos de auditoria, incluindo um evento explícito de purge, sem deixar conteúdo pessoal recuperável;
- ser idempotente e recuperar de falhas entre a remoção do ficheiro e a confirmação transacional.


## Pré-validação administrativa de purge (não destrutiva)

O endpoint `GET /api/v1/shelf-images/{image_id}/retention/purge-eligibility` está limitado a ADMIN e fornece uma pré-validação sem apagar dados. Verifica se a imagem está `RESTRICTED` ou `PENDING_PURGE`, se não existe legal hold, se `purge_not_before` está definido e expirado, se a análise não está em execução e se o ficheiro continua presente num caminho seguro dentro do diretório da loja. Devolve também contagens de deteções, execuções/registos OCR, fusões e exemplares de embeddings associados.

A resposta inclui `eligible`, a lista de `blockers` e `deletion_performed: false`. A elegibilidade é apenas uma pré-condição, não uma autorização para apagar diretamente. A API ainda não implementa o executor de purge. Nenhuma duração de retenção é inferida: `purge_not_before` tem de ser definido por uma política aprovada e aplicada por um fluxo próprio. O endpoint é útil para auditoria operacional, mas não substitui uma operação de purge idempotente com recuperação de falhas entre filesystem e base de dados.


### Agendamento administrativo do purge

Apenas ADMIN pode agendar ou cancelar a data de purge de uma imagem `RESTRICTED`. O agendamento exige uma data futura com fuso horário explícito, uma versão de política (`policy_version`) e uma justificação. A operação grava `purge_not_before`, `retention_policy_version` e a justificação, sem alterar o estado `RESTRICTED` e sem apagar conteúdo. A tabela append-only de eventos regista `PURGE_SCHEDULED`; o cancelamento limpa a data e a versão da política e regista `PURGE_CANCELLED`. Imagens com legal hold, em processamento ou que não estejam `RESTRICTED` não podem ser agendadas. O cancelamento também não restaura a imagem nem remove o legal hold.

Endpoints:
- `POST /api/v1/shelf-images/{image_id}/retention/purge-schedule`
- `POST /api/v1/shelf-images/{image_id}/retention/purge-schedule/cancel`
- `GET /api/v1/shelf-images/{image_id}/retention/purge-eligibility`

A migração `0032_shelf_image_purge_schedule_events` alarga a restrição dos tipos de evento para incluir os dois eventos de agendamento. O executor de purge continua por implementar; a data agendada não dispara qualquer eliminação automática.