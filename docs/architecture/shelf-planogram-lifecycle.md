# Planogramas versionados de prateleira

## Objectivo e limite de domínio

Um planograma descreve a disposição esperada dos produtos numa prateleira física. A geometria é normalizada relativamente à imagem/calibração e cada célula pode referenciar um SKU esperado. Um planograma não representa quantidades em profundidade, stock de retaguarda, reservas nem stock contabilístico.

A comparação visual continua a ser consultiva. Não cria movimentos de inventário, tarefas ou encomendas.

## Modelo e ciclo de vida

As migrations `0067_shelf_planograms` e `0068_shelf_planogram_expected_facings` criam e evoluem:

- `shelf_planograms`: versão sequencial por prateleira, estado, origem de calibração e metadados de criação/ativação/retirada.
- `shelf_planogram_cells`: código, posição na grelha, bounding box normalizada, SKU esperado opcional e `expected_facings` opcional.

Cada prateleira pode ter no máximo uma versão `ACTIVE`. As transições permitidas são:

```text
DRAFT -> ACTIVE -> RETIRED
```

A ativação de uma versão nova retira a anterior na mesma transação. Versões ativadas não podem ser eliminadas nem ter as células alteradas. As células de um `DRAFT` podem ser substituídas atomicamente através de `PUT /api/v1/planograms/{planogram_id}/cells`. Depois da ativação, os triggers impedem alterações às células.

As versões e células têm constraints e triggers PostgreSQL/SQLite para identidade imutável, sequência por prateleira, transições de estado, SKU elegível, geometria não degenerada/não sobreposta e preservação do histórico. A ativação usa também um índice único parcial para impedir duas versões ativas na mesma prateleira.

## Calibração

A origem pode ser:

- `MANUAL`: não referencia imagem.
- `IMAGE`: exige imagem da mesma prateleira, estado de retenção `ACTIVE` e SHA-256 correspondente.

A criação e ativação revalidam a imagem e o SKU esperado. A retirada não exige que a imagem continue `ACTIVE`: é importante conseguir retirar um planograma cujo artefacto de calibração tenha sido posteriormente restringido. A identidade da imagem e o digest continuam a ser verificados.

## API HTTP

Todas as rotas exigem Bearer JWT e perfil `ADMIN` ou `SUPERVISOR`. O supervisor só acede a prateleiras da sua loja; o administrador pode operar entre lojas. `EMPLOYEE` não tem acesso a estas rotas.

| Método | Rota | Comportamento |
|---|---|---|
| POST | `/api/v1/shelves/{shelf_id}/planograms` | Criar uma nova versão `DRAFT` com todas as células |
| GET | `/api/v1/shelves/{shelf_id}/planograms` | Listar histórico por versão descendente; aceita `limit` e `offset` |
| GET | `/api/v1/shelves/{shelf_id}/planograms/active` | Obter a versão ativa; devolve `null` quando não existe |
| PUT | `/api/v1/planograms/{planogram_id}/cells` | Substituir atomicamente as células de uma versão DRAFT |
| POST | `/api/v1/planograms/{planogram_id}/activate` | Ativar a versão e retirar a anterior |
| POST | `/api/v1/planograms/{planogram_id}/retire` | Retirar a versão ativa sem apagar histórico |

Exemplo de criação:

```json
{
  "calibration_source": "MANUAL",
  "cells": [
    {
      "cell_code": "A1",
      "row_index": 0,
      "column_index": 0,
      "x_min": 0.0,
      "y_min": 0.0,
      "x_max": 0.5,
      "y_max": 1.0,
      "expected_product_id": 42,
      "expected_facings": 3
    }
  ]
}
```

Para calibração por imagem, enviar `calibration_source: "IMAGE"`, `calibration_image_id` e `calibration_image_sha256`. `expected_facings` é opcional, positivo e exige SKU esperado. Cada célula tem coordenadas em `[0,1]), largura/altura positivas, código único e posição de grelha única. Um SKU esperado tem de estar ativo e atribuído à mesma prateleira.

Os motivos de ativação/retirada são obrigatórios (3–500 caracteres). Conflitos de ciclo de vida/concorrência devolvem HTTP 409; dados inválidos devolvem 422; prateleira/planograma inexistente devolve 404; perfil ou loja não autorizados devolvem 403.

## Garantias e limitações atuais

- A camada HTTP e o serviço de domínio validam perfil e âmbito da loja; não dependem apenas do middleware.
- As operações de escrita são transacionais e tratam conflitos de constraints como 409.
- A migration mantém equivalência de guards entre PostgreSQL e SQLite.
- A eliminação em cascata de células de um rascunho é permitida; células de versões ativas/retiradas permanecem protegidas.
- Não existe ainda endpoint de edição de rascunhos, endpoint de comparação, interface React, ligação ao worker de visão ou calibração com imagens reais.
- `expected_facings` está persistido, mas a contagem observada ainda precisa de calibração e integração no worker.
- A deteção visual de espaços vazios/facings não altera inventário contabilístico.

## Validação CI

No commit `3d9f338e5bdf50a9674f53d05da1ad99e23faa01`:

- [API CI](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44560333697): PostgreSQL 16, migrações e **1334 testes aprovados, 1 ignorado e 1 aviso**.
- [Quality Gates](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44560333600): compilação Python, suite API e build TypeScript/produção Web aprovados.
- [Docker Compose smoke](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44560333624): stack de demonstração aprovada.

O aviso restante é a depreciação externa `anyio.abc.BlockingPortal` emitida pelo Starlette TestClient.


## Migration 0068 — expected facings e edição de rascunhos

A migration `0068_shelf_planogram_expected_facings` adiciona `expected_facings INTEGER NULL` a cada célula. A regra é `NULL` ou valor positivo associado a `expected_product_id`. PostgreSQL impõe CHECK constraint; SQLite impõe triggers para INSERT e UPDATE.

O endpoint `PUT /api/v1/planograms/{planogram_id}/cells` substitui o conjunto completo de células de um rascunho. A operação valida o conjunto inteiro antes de apagar, bloqueia imagem de calibração, prateleira e planograma pela ordem global definida, revalida SKUs e executa DELETE + INSERT na mesma transação. Se qualquer validação ou trigger falhar, a transação é revertida e as células anteriores permanecem.

A rota devolve 409 se o planograma já não estiver em DRAFT. A ativação e edição competem pelo mesmo lock da prateleira/planograma, evitando que a substituição de células ultrapasse a transição para ACTIVE.
