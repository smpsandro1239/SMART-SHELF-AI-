# Fusão de evidências para identificação de SKU

O módulo `app.product_evidence_fusion` combina o estado do matching visual
(`ProductMatch`) com o ranking textual (`TextMatch`) e a confiança fornecida
pelo motor OCR (`OCRText`).

## Estados

| Estado | Significado | Ação |
|---|---|---|
| `CONSENSUS` | Visão e OCR propõem o mesmo SKU | Apresentar para confirmação humana |
| `VISUAL_ONLY` | Só a visão tem candidato decisivo | Apresentar candidato com ressalva |
| `TEXT_ONLY` | Só o OCR tem candidato suficientemente fiável | Revisão humana obrigatória |
| `CONFLICT` | Visão e OCR propõem SKUs diferentes | Bloquear associação automática e rever |
| `AMBIGUOUS` | Evidência relevante tem candidatos próximos | Rever manualmente |
| `UNKNOWN` | Nenhuma fonte fornece candidato utilizável | Manter sem SKU |

## Regras e segurança

- A confiança OCR mínima é configurável (por omissão, 0,65); não é uma
  probabilidade universal nem substitui calibração por motor/loja/câmara.
- Similaridade de cosseno e semelhança textual não são diretamente comparáveis.
  Por isso, o módulo não faz média dos scores nem os apresenta como probabilidade.
- Uma divergência entre dois sinais decisivos produz `CONFLICT`, sem escolher
  arbitrariamente um dos produtos.
- Mesmo `CONSENSUS` produz apenas uma sugestão. Não aprova exemplares, não
  altera `product_id` persistido, não cria movimentos e não atualiza stock.
- A implementação não chama OCR nem gera embeddings; recebe resultados dos
  providers. A integração com o worker fica deliberadamente separada até existir
  um provider OCR real e avaliação com imagens anotadas.

## Validação necessária antes de produção

Avaliar por SKU e por variante, incluindo embalagens refletoras, texto parcial,
OCR com caracteres confundidos, produtos visualmente semelhantes, produtos
ausentes do catálogo e diferentes distâncias/ângulos. Medir precisão por estado,
taxa de conflito, cobertura e falsos matches. Manter separação por loja/sessão
entre referências, validação e teste final.
