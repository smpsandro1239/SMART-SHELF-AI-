# Curadoria de candidatos para aprendizagem supervisionada

## Endpoint

`GET /api/v1/training-candidates/reviewed`

Parâmetros opcionais: `product_id`, `limit` e `offset`. O endpoint é apenas de leitura e está limitado a ADMIN/SUPERVISOR; os supervisores ficam confinados à sua loja.

## Elegibilidade

- Só considera a última decisão humana por deteção.
- `CONFIRMED` e `CORRECTED` com produto selecionado e ativo podem originar candidatos.
- `REJECTED` exclui a deteção; uma rejeição posterior também invalida uma confirmação anterior.
- Uma imagem já registada como exemplar para o mesmo produto é omitida, independentemente do estado desse exemplar.
- A decisão humana não aprova automaticamente o exemplar visual nem cria embeddings.

Cada resultado inclui a caixa delimitadora normalizada, hash da imagem e uma chave de agrupamento por imagem. Todas as crops da mesma imagem têm de permanecer no mesmo split para evitar leakage. O modelo atual ainda não possui um identificador explícito de sessão de captura; por isso, esta chave é uma garantia mínima por imagem, não uma garantia por sessão. Não se deve atribuir um split final de treino/validação/teste até existir metadado de sessão e uma política de separação temporal/por sessão.

## Limitações deliberadas

O endpoint não transfere imagens, não cria crops, não calcula embeddings, não treina modelos e não modifica inventário. A utilização de imagens operacionais requer autorização, política de retenção e validação de direitos/privacidade. Os embeddings continuam a ser registados separadamente como `PENDING` e só entram no matching após aprovação independente.
