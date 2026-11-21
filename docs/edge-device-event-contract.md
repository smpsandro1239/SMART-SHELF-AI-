# Contrato de eventos Edge AI — versão 1

## Estado e âmbito

O módulo `apps/api/app/edge_event_contract.py` implementa validação local do envelope, validação por tipo de evento, serialização canónica, fingerprint, chave de idempotência e classificação de sequência.

**Ainda não implementa** registo/autenticação de dispositivos, endpoint de ingestão, persistência inbox/outbox, cursores duráveis, acknowledgements, sincronização de imagens ou reconciliação multi-loja. Estes elementos exigem desenho de BD, migração, autorização e testes de concorrência antes de activar ingestão real.

## Envelope comum

Cada mensagem contém:

- `schema_version`: inteiro literal `1`.
- `event_id`: UUID estável, gerado uma única vez no dispositivo e reutilizado em todas as tentativas.
- `event_type`: um dos tipos v1 listados abaixo.
- `device_id`: identificador ASCII estável do dispositivo (1–120 caracteres).
- `store_id`: ID positivo da loja à qual o dispositivo está registado.
- `shelf_id`: ID positivo quando o evento se refere a uma prateleira; caso contrário `null`.
- `sequence_number`: contador monotónico positivo por dispositivo, sem reutilização.
- `occurred_at`: timestamp ISO-8601 com fuso horário explícito.
- `payload`: objecto JSON específico do tipo, limitado a 64 KiB, profundidade 12, 1000 elementos por colecção e strings até 4096 caracteres.

Exemplo de heartbeat:

```json
{
  "schema_version": 1,
  "event_id": "9b7c4b34-7a89-4f93-a2a7-55a8a9e8b17d",
  "event_type": "DEVICE_HEARTBEAT",
  "device_id": "edge-gateway-01",
  "store_id": 12,
  "shelf_id": null,
  "sequence_number": 42,
  "occurred_at": "2026-11-21T14:00:00Z",
  "payload": {
    "firmware_version": "1.4.2",
    "battery_pct": 87.5,
    "network_status": "ONLINE"
  }
}
```

## Tipos de evento

| Tipo | `shelf_id` | Payload obrigatório |
|---|---:|---|
| `DEVICE_HEARTBEAT` | `null` | campos opcionais permitidos: `firmware_version`, `battery_pct`, `network_status`, `storage_free_bytes`; pelo menos um |
| `SHELF_CAPTURED` | obrigatório | `capture_id` UUID, `image_sha256`, `width`, `height`, `media_type` |
| `SHELF_OBSERVATION` | obrigatório | `capture_id` UUID, `model_version`, `observations[]` |
| `TASK_ACKNOWLEDGED` | `null` | `task_id`, `task_version`, `action` (`ACCEPTED`, `STARTED`, `COMPLETED`) |

Cada observação visual contém exactamente `label`, `confidence` (0–1) e `bbox` normalizada `[x_min, y_min, x_max, y_max]`. O contrato não aceita quantidade de stock como resultado de visão. Uma observação é evidência, não uma mutação de inventário.

Os bytes de imagem não devem ser incorporados no envelope. A captura e o transporte de media devem usar fluxo separado, com autenticação, limites de tamanho, retenção, verificação de hash e referência de armazenamento autorizada.

## Idempotência e ordenação

1. O servidor autentica o dispositivo e confirma a associação dispositivo–loja antes de confiar em `device_id` ou `store_id`.
2. Calcula SHA-256 do JSON canónico (chaves ordenadas, separadores compactos) e procura a chave `edge:{sha256(device_id)}:{event_id}`.
3. Se já existir o mesmo evento e o fingerprint coincidir, responde como replay idempotente sem repetir efeitos.
4. Se o mesmo ID chegar com conteúdo diferente, rejeita como conflito e regista incidente de integridade.
5. Para um evento novo, compara `sequence_number` com o cursor durável:
   - `NEXT`: próximo número esperado; elegível para ingestão transaccional.
   - `GAP`: existe uma lacuna; guardar em inbox pendente e não aplicar efeitos fora de ordem.
   - `STALE`: sequência antiga não reconhecida como replay; colocar em quarentena/rejeitar e reconciliar.
6. A pesquisa de replay tem precedência sobre a classificação de sequência: um retry legítimo de evento já aceite não deve ser rejeitado como sequência antiga.

O módulo actual apenas classifica e calcula fingerprints; não guarda cursor, não decide estado persistente e não confirma entrega.

## Outbox local e confirmação do servidor

O agente Edge deverá manter uma outbox durável em armazenamento local:

- Persistir evento, UUID, sequência, fingerprint e estado antes de tentar enviar.
- Reutilizar exactamente o mesmo envelope em retries; nunca criar novo UUID ou sequência para uma repetição.
- Usar backoff exponencial com jitter e limites de fila/armazenamento.
- Eliminar ou marcar como entregue apenas após acknowledgement do servidor emitido depois do commit durável.
- Preservar eventos pendentes durante reinícios e falhas de conectividade.
- Transferir imagens separadamente e manter o hash ligado ao evento de captura.

No servidor, inbox, registo de idempotência, cursor por dispositivo e evento de auditoria devem ser confirmados na mesma transacção. Eventos fora de ordem não podem avançar o cursor nem provocar efeitos laterais.

## Segurança e isolamento

- A identidade do dispositivo tem de ser autenticada por credencial individual (por exemplo mTLS ou assinatura de pedido com chave pública registada); `device_id` no JSON não é autenticação.
- O servidor resolve a loja a partir do registo do dispositivo e compara com o `store_id` declarado; nunca permite que o cliente escolha livremente o tenant.
- Validar autorização sobre `shelf_id` e `task_id` na mesma loja antes de associar entidades.
- Aplicar quotas por dispositivo, tamanho de lote, relógio, frequência e armazenamento.
- Guardar `received_at` no servidor separadamente de `occurred_at`; timestamps do dispositivo não são fonte de verdade para ordenação.
- Nunca converter `SHELF_OBSERVATION` directamente em stock ou rutura. A evidência passa pelo consenso, confiança, planograma e revisão humana definidos pelo domínio.

## Critérios de aceitação para a fase de ingestão

- Replay idêntico não duplica eventos nem efeitos.
- Reutilização de event ID com conteúdo diferente gera conflito auditável.
- Sequência em falta é retida sem avançar cursor nem executar side effects.
- Dispositivo de uma loja não publica eventos para outra loja.
- Reinício do dispositivo não perde outbox nem reutiliza sequência.
- API/worker indisponível não causa perda de eventos confirmados localmente.
- Retenção de imagens e metadados é aplicada independentemente e de forma auditável.
