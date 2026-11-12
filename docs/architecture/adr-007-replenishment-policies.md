# ADR-007 — Separar reposição de prateleira e reaprovisionamento de stock

**Estado:** aceite para a primeira versão do motor de políticas  
**Data:** 12-11-2026

## Contexto

A análise comparativa de soluções externas identificou dois problemas de negócio distintos:
1. **Shelf refill:** mover unidades da retaguarda para uma posição de exposição.
2. **Stock replenishment:** transferir ou comprar unidades para repor o inventário projetado.

Odoo e ERPNext usam níveis de reposição, stock projetado, entradas previstas, reservas, prazos e múltiplos de embalagem. Projetos de monitorização visual demonstram deteção de facings, reconhecimento SKU, planograma e consenso temporal.

## Decisão

O SMART SHELF AI mantém dois cálculos independentes:
- `suggest_shelf_refill`: calcula a diferença entre quantidade observada na prateleira e o alvo, limita a quantidade sugerida ao stock disponível na retaguarda e bloqueia sugestões quando a observação é antiga, pouco fiável ou o inventário é desconhecido.
- `suggest_purchase_reorder`: calcula stock projetado à data de receção (`on_hand + incoming - reserved - demand_until_receipt`), compara-o com o ponto de encomenda e propõe quantidade até ao nível máximo, respeitando quantidade mínima e múltiplos de embalagem.

Ambos são cálculos determinísticos e não executam movimentos de stock nem criam encomendas. A revisão humana continua obrigatória no fluxo inicial.

## Consequências

- Não confundir deteção visual de espaço vazio com rutura no armazém.
- Não calcular uma encomenda a fornecedor apenas com fotografia da prateleira.
- A integração futura deve fornecer stock, reservas, entradas, consumo previsto, lead time, unidade de medida, MOQ e múltiplo.
- O modelo visual deve devolver quantidade observada por SKU apenas quando a identidade estiver suficientemente confirmada; caso contrário, manter UNKNOWN.
- A política de visão deverá usar persistência temporal e deduplicação para reduzir alertas transitórios.
- Os cálculos estão isolados em `apps/api/app/replenishment_policy.py` para permitir testes sem base de dados e futura integração por serviço.

## Referências

- [REA externa — soluções comparadas](../reverse-engineering/external-solutions.md)
- [Odoo Reordering Rules](https://www.odoo.com/documentation/18.0/applications/inventory_and_mrp/inventory/warehouses_storage/replenishment/reordering_rules.html)
- [ERPNext Automatic Reordering](https://docs.frappe.io/erpnext/auto-creation-of-material-request)
