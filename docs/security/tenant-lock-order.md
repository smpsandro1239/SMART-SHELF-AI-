# Ordem de autorização e locks por tenant

## Problema

Adquirir um row lock antes de verificar o store scope permite que um utilizador autenticado de outra loja cause contenção sobre recursos que não pode alterar. A resposta final 403 não elimina o impacto de disponibilidade.

## Contrato obrigatório

Para recursos multi-loja:
1. Fazer uma leitura não bloqueante para resolver o store_id.
2. Revalidar a identidade activa e as permissões do actor.
3. Aplicar store scope antes do lock.
4. Adquirir o row lock e refrescar o registo.
5. Revalidar o store scope sobre o estado bloqueado.
6. Executar a operação e auditoria na mesma transacção.

Não usar um lock global como substituto de autorização.

## Helpers

- _lock_authorized_shelf_image: valida a relação imagem → prateleira → zona antes e depois do lock.
- _lock_store_scoped_record: aplica o mesmo padrão a entidades com store_id directo.

## Cobertura

22 handlers são protegidos por estes helpers ou por autorização de recurso equivalente:
- Conteúdo, retenção, deteções, OCR, matching e fusão de evidências de imagens.
- Revisões de SKU e exemplares de embeddings.
- Sessões de captura e upload associado.
- Tarefas de reposição e reconciliação.
- Eventos de paletes.
- Actualização de alertas.

O teste test_store_scoped_lock_handlers_authorize_before_their_first_lock verifica que os handlers usam o helper antes de qualquer lock local. O teste test_store_scoped_record_lock_rejects_foreign_store_before_lock confirma que um actor de outra loja é recusado sem tentar adquirir lock.

## Evidência

No commit 1c0f591:
- API CI: 1413 passed, 1 skipped.
- Quality Gates: 1413 passed, 1 skipped.
- PostgreSQL 16 concurrency/retention smokes: PASS.
- ZAP baseline/API safe-mode: 0 High, 0 Medium, 0 Low.

## Limitações

Esta é uma correcção da ordem de locks e uma cobertura estática dos handlers identificados. Não substitui a auditoria completa BOLA/IDOR por recurso, nem a matriz autenticada endpoint × ADMIN/SUPERVISOR/EMPLOYEE × loja.

## Revalidação — 2026-11-21

No commit a345746, API CI e Quality Gates passaram com 1422 testes aprovados e 1 ignorado. Os 22 handlers abrangidos pela regra de autorização pré-lock continuam cobertos; PostgreSQL 16 smokes e o workflow de segurança também passaram.

## Evidência adicional — matriz de leituras multi-loja (2026-11-23)

- O smoke `postgres_inventory_authorization_smoke.py` cobre 23 rotas GET de vendas, tráfego, forecasting, replenishment, decisões e warehouse com `store_id` da loja estrangeira.
- O actor é um SUPERVISOR autenticado por JWT, associado à loja de origem; as respostas esperadas são HTTP 403. O mesmo script mantém as tentativas de escrita cross-store e verifica que não deixam alterações persistidas.
- A alteração está no commit `40f9456a`; API CI, Quality Gates, Security Scans e Docker Compose ainda aguardam conclusão no SHA.
- Esta evidência não substitui testes de IDs aninhados, todos os papéis/rotas, leitura positiva same-store ou ensaio de volume persistente.
