# Registo e rastreabilidade de paletes

## Objetivo da fase

A migração `0015_pallet_rotation_registry` introduz identidade individual de
paletes, políticas de rotação por loja/produto e eventos de auditoria. A
quantidade é sempre expressa na unidade base do produto, não em número de
caixas ou paletes.

## Modelo de dados

### `store_pallets`

Cada linha representa uma palete física identificável:
- loja, produto e nível de embalagem PALLET;
- código único dentro da loja;
- lote e validade;
- quantidade residual em unidade base;
- estado operacional;
- tipo e código da localização;
- datas de criação e atualização.

Estados iniciais: `READY`, `ON_DISPLAY`, `PARTIAL`, `RETURNED`,
`REBUILDING`, `EMPTY` e `QUARANTINED`.

Localizações: `WAREHOUSE`, `PREPARATION`, `SALES_FLOOR` e `OTHER`.
O código de localização é texto livre nesta fase; ainda não existe uma
associação obrigatória a uma localização física validada.

### `pallet_rotation_policies`

Uma política por combinação loja/produto. O limiar é uma proporção entre 0 e 1
(por exemplo, 0.35 significa considerar a troca quando restar 35% ou menos).
A política pode ser desativada sem ser eliminada. O valor 0.5 é apenas o
predefinido inicial, não uma regra universal.

### `pallet_rotation_events`

Histórico de eventos com palete, tipo, origem/destino, quantidade antes/depois,
lote, validade, operador e instante. O primeiro evento criado no registo é
`REGISTERED`. A API não disponibiliza operações para editar ou apagar eventos.

## Endpoints

Todos os endpoints exigem autenticação. A criação e alteração de registos/
políticas exige perfil ADMIN ou SUPERVISOR. O isolamento de loja é aplicado
a utilizadores não administradores.

### Registar uma palete

`POST /api/v1/warehouse/pallets`

Exemplo (substituir IDs e token por valores reais):

```bash
curl -X POST http://localhost:8000/api/v1/warehouse/pallets \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "store_id": 1,
    "product_id": 7,
    "packaging_level_id": 12,
    "pallet_code": "PAL-0001",
    "lot_code": "LOT-2026-11",
    "expiry_date": "2027-06-30",
    "base_quantity": 720,
    "status": "READY",
    "location_type": "WAREHOUSE",
    "location_code": "ARZ-A-01"
  }'
```

A API valida loja, produto ativo, nível de embalagem PALLET pertencente ao
produto e quantidade não superior à capacidade configurada da palete.
O registo cria um evento `REGISTERED`, mas não altera snapshots nem stock
agregado. O código da palete tem de ser único dentro da loja.

### Consultar paletes

`GET /api/v1/warehouse/pallets?store_id=1&product_id=7&status=READY&limit=200`

Filtros `product_id` e `status` são opcionais. O limite é restringido a
500 registos por pedido.

### Configurar política

`POST /api/v1/warehouse/pallet-rotation/policies`

```json
{
  "store_id": 1,
  "product_id": 7,
  "threshold_ratio": 0.35,
  "is_enabled": true
}
```

Consultar políticas:
`GET /api/v1/warehouse/pallet-rotation/policies?store_id=1`

Alterar limiar ou ativação:
`PATCH /api/v1/warehouse/pallet-rotation/policies/{policy_id}`

Exemplo:
```json
{"threshold_ratio": 0.4, "is_enabled": true}
```

A criação exige que o produto tenha um nível de embalagem PALLET ativo. Só
pode existir uma política por loja/produto.

### Consultar histórico

`GET /api/v1/warehouse/pallets/{pallet_id}/events?store_id=1`

O histórico inclui o evento inicial de registo. Nesta fase ainda não existem
endpoints de movimento, alteração de quantidade, troca, retorno ou recomposição.

## Limites e salvaguardas

- Não há atualização de `InventorySnapshot` nem de `WarehouseProductPlacement`.
- Não há reserva automática de uma palete de substituição.
- Não há execução de movimentos físicos.
- O endpoint de registo não confirma que a palete foi contada fisicamente;
  essa confirmação é responsabilidade do operador que regista.
- A localização é texto livre, não uma posição de armazém validada.
- O histórico tem interface apenas de leitura depois do registo, mas a
  imutabilidade absoluta ao nível da base de dados ainda não está garantida
  contra alterações administrativas diretas.
- Ainda não existe validação de compatibilidade de lote para recomposição,
  nem aplicação automática de FEFO/FIFO.
- O estado atual e o histórico não são sincronizados com ERP/WMS externos.

Antes de ativar movimentos operacionais, será necessário criar transições de
estado validadas, bloqueio concorrente/idempotência, confirmação por scan,
controlo de lote/validade, validação de localização e reconciliação com stock
agregado.


## Atualizar o ciclo de vida de uma palete

`POST /api/v1/warehouse/pallets/{pallet_id}/events` regista uma alteração supervisionada
de estado, quantidade ou localização. Requer ADMIN/SUPERVISOR e respeita o
âmbito da loja.

O pedido tem de incluir `expected_status` e `expected_base_quantity`
com os valores atualmente lidos. Se outra operação já tiver alterado a palete,
a API devolve HTTP 409 para evitar que um operador grave uma decisão baseada
num estado desatualizado. Em PostgreSQL, a linha é também bloqueada durante a
transação (`SELECT FOR UPDATE`).

Exemplo de passagem para exposição:

```http
POST /api/v1/warehouse/pallets/15/events
```

```json
{
  "expected_status": "READY",
  "expected_base_quantity": 720,
  "status": "ON_DISPLAY",
  "location_type": "SALES_FLOOR",
  "location_code": "CORREDOR-03",
  "reason": "Palete colocada na exposição após confirmação visual"
}
```

Transições permitidas nesta fase:
- READY -> ON_DISPLAY ou QUARANTINED
- ON_DISPLAY -> PARTIAL, RETURNED ou QUARANTINED
- PARTIAL -> RETURNED, REBUILDING, ON_DISPLAY ou QUARANTINED
- RETURNED -> REBUILDING ou QUARANTINED
- REBUILDING -> READY ou QUARANTINED
- EMPTY -> QUARANTINED
- QUARANTINED é terminal

A quantidade continua expressa na unidade base e tem de respeitar a capacidade
da embalagem PALLET. EMPTY exige zero; os restantes estados exigem quantidade
positiva. A API grava o evento e o estado atual na mesma transação. Não altera
InventorySnapshot, posições de armazém nem stock agregado. A alteração de lote/
validade e a recomposição com mistura de lotes continuam bloqueadas até existir
um fluxo FEFO/FIFO e rastreabilidade próprio.
