# Chaves HMAC de inventários externos

## Objetivo

As assinaturas de inventários novos devem ser isoladas por loja e sistema externo. Uma chave configurada para a loja A não pode validar um inventário da loja B, mesmo que ambas usem o mesmo fornecedor.

A rotação não reescreve snapshots históricos. Cada snapshot conserva o identificador da chave usada na assinatura e a verificação histórica resolve exactamente essa versão.

## Formato de configuração

A variável `ARTIFACT_INVENTORY_HMAC_KEYS_JSON` aceita o formato versionado:

```json
{
  "stores": {
    "12": {
      "object-storage": {
        "active_key_id": "2026-11",
        "keys": {
          "2026-08": "SEGREDO_ANTIGO_COM_PELO_MENOS_32_BYTES",
          "2026-11": "SEGREDO_ACTUAL_COM_PELO_MENOS_32_BYTES"
        }
      }
    },
    "27": {
      "object-storage": {
        "active_key_id": "2026-11",
        "keys": {
          "2026-11": "OUTRO_SEGREDO_INDEPENDENTE_COM_32_BYTES"
        }
      }
    }
  }
}
```

Os identificadores de loja são strings decimais. O identificador do sistema externo tem de corresponder exactamente ao `external_system` registado na integração da loja. Cada segredo tem de possuir pelo menos 32 bytes UTF-8.

O conector envia `key_id` no payload do snapshot e calcula a assinatura com a mesma versão. O identificador entra no payload canónico versão 2, ficando criptograficamente associado à assinatura. A API só aceita para novas ingestões o `active_key_id` configurado para aquela loja e fornecedor.

## Rotação segura

1. Gerar um segredo novo e independente para cada par loja/sistema externo.
2. Adicionar o segredo ao mapa `keys`, mantendo a chave anterior.
3. Alterar `active_key_id` para o novo identificador.
4. Distribuir a nova configuração ao conector e à API de forma coordenada.
5. Confirmar que os novos snapshots são assinados com o novo identificador.
6. Manter as chaves antigas enquanto existirem snapshots históricos que precisem de ser verificados.
7. Remover uma chave antiga apenas após avaliar retenção, auditoria e dependências de todos os snapshots assinados com ela.

A verificação de snapshots persistidos aceita uma chave histórica que continue presente no keyring, mesmo que já não seja a activa. A ingestão nova exige sempre a chave activa. A chave identificada no snapshot é imutável porque a tabela de snapshots é append-only.

## Compatibilidade

A migration `0047_artifact_inventory_key_id` adiciona `key_id` com o valor `legacy` para todos os snapshots já existentes. O valor `legacy` mantém a verificação do formato canónico versão 1 e da configuração histórica plana:

```json
{
  "object-storage": "SEGREDO_LEGADO_COM_PELO_MENOS_32_BYTES"
}
```

Esta compatibilidade é transitória: não oferece isolamento por loja aos snapshots legados. Em `APP_ENV=production`, a API rejeita novas ingestões `legacy` por omissão; para uma janela de migração explicitamente controlada, `ARTIFACT_INVENTORY_ALLOW_LEGACY_INGESTION=true` permite temporariamente esse tráfego. O valor `false` bloqueia-o em qualquer ambiente. Quando a variável não está definida, ambientes não produtivos mantêm compatibilidade e produção aplica o bloqueio. Exact retries de snapshots legados já persistidos continuam idempotentes, e a verificação/leitura histórica não é afectada. As integrações devem migrar para o keyring versionado e deixar de assinar novos inventários no formato legado. Não remover a chave legada enquanto existirem snapshots antigos que dela dependam.

## Limites operacionais

- Não guardar segredos no PostgreSQL, no frontend, no README, em logs ou em commits.
- Injectar a configuração através do gestor de segredos do ambiente de execução.
- Não reutilizar o mesmo segredo entre lojas ou sistemas externos.
- Não registar o segredo nem a configuração completa em mensagens de erro.
- A rotação de configuração deve ser coordenada entre API e conector; não é uma rotação automática nem uma gestão de segredos remota.
- A remoção de uma chave antiga torna os snapshots correspondentes não verificáveis e bloqueia o consumo de artefactos que dependam deles.

## Política de cutover do formato legado

A variável `ARTIFACT_INVENTORY_ALLOW_LEGACY_INGESTION` controla a aceitação de novos snapshots com `key_id="legacy"`. Em produção, o valor por omissão é `false`; fora de produção, a ausência da variável mantém a compatibilidade. Definir explicitamente `true` apenas durante uma janela de transição aprovada e removê-la depois de todos os conectores enviarem um `key_id` versionado. Definir `false` bloqueia o formato legado em qualquer ambiente. A política não invalida snapshots históricos nem impede retries exactos de registos já persistidos.

Sequência recomendada: (1) distribuir keyrings por loja/fornecedor, (2) atualizar conectores para enviar `key_id` activo, (3) observar métricas/logs sem expor segredos, (4) manter o override legado desligado em produção, e (5) remover a configuração plana quando a verificação histórica já não depender dela.

## Validação

A suite `apps/api/tests/test_artifact_inventory_signing.py` inclui cobertura para isolamento entre lojas, associação criptográfica do `key_id`, retenção de chaves antigas para verificação histórica e rejeição de chaves antigas em novas ingestões. A execução de pytest, migration em PostgreSQL 16 e CI deste bloco ainda precisa de confirmação.

## Limites de registo de referências

A API só aceita novas referências de artefactos quando a origem externa correspondente está registada e activa na loja da imagem. A revogação de uma integração impede novas declarações e novas ingestões, sem apagar referências ou snapshots históricos. Relações pai/filho permanecem limitadas à mesma imagem e loja.