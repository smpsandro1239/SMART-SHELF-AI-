# Auditoria de planos de consulta PostgreSQL

## Objectivo

Recolher planos reais para as consultas de listagem de imagens, deteções, evidência OCR, eventos de retenção e fila de revisão SKU. A auditoria permite decidir com evidência se são necessários índices, alterações à ordenação ou paginação por cursor.

O script não altera dados nem schema. Executa `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON, TIMING OFF)` dentro de uma transacção PostgreSQL `READ ONLY`. Cada consulta tem timeout configurável (por omissão, 15 segundos) e o script confirma que a imagem indicada pertence à loja indicada.

## Preparação recomendada

- Preferir uma réplica de leitura ou staging com estatísticas e volume representativos.
- Evitar executar em horas de pico: `EXPLAIN ANALYZE` executa efectivamente os SELECTs e consome CPU/I/O, apesar de não escrever dados.
- Actualizar estatísticas da base de dados através do procedimento operacional normal antes da medição; o script não executa `VACUUM` nem `ANALYZE` automaticamente.
- Usar um `store_id` e um `image_id` existentes na mesma loja.
- Não copiar planos para tickets públicos se incluírem nomes internos de tabelas, índices ou informação operacional sensível.

## Execução

A partir da raiz do repositório:

```bash
cd apps/api
export PYTHONPATH=.
export DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE'
python scripts/postgres_image_query_plan_audit.py \
  --store-id 12 \
  --image-id 345 \
  --statement-timeout-ms 15000 \
  > /tmp/smart-shelf-image-query-plans.json
```

O comando requer PostgreSQL. Em SQLite termina sem executar consultas. O resultado JSON contém, para cada consulta, o plano, estimativas, linhas reais, tempo total e buffers. Um erro de timeout ou de ligação é reportado como auditoria incompleta; não deve ser interpretado como falha funcional da API.

## Consultas incluídas

1. Imagens activas da loja, ordenadas por `created_at DESC, id DESC`.
2. Detecções de uma imagem, ordenadas por ID.
3. Correspondências OCR, ligadas às execuções OCR da imagem.
4. Regiões de evidência OCR, ligadas às execuções OCR da imagem.
5. Eventos de retenção, ordenados cronologicamente com ID como desempate.
6. Fila de revisão SKU, incluindo a subconsulta correlacionada que compara a data da última revisão humana com a evidência fundida.

Os SELECTs são representativos das rotas actuais, não um benchmark de carga. A consulta da fila projecta apenas IDs para reduzir o volume de leitura, mantendo os joins, filtros, ordenação e limite relevantes para o plano.

## Critérios de análise

Para cada plano, registar:

- `Planning Time` e `Execution Time`.
- `Actual Rows` versus `Plan Rows` em cada nó.
- `Shared Hit Blocks` e `Shared Read Blocks`.
- `Seq Scan` em tabelas que crescem com as imagens/deteções/evidências.
- `Sort` ou `Incremental Sort`, incluindo método e memória/disco.
- `Rows Removed by Filter`.
- Loops da subconsulta de revisão mais recente.
- Diferença entre custo estimado e execução real.

Não adicionar índices apenas porque aparece um `Seq Scan` num ambiente pequeno. Confirmar cardinalidade, selectividade, frequência de escrita, tamanho do índice e o efeito em consultas relacionadas. Comparar antes/depois no mesmo conjunto representativo e preservar o plano original como evidência.

## Limitações actuais

- O CI usa uma base de dados efémera e pequena; não fornece evidência de desempenho com volume de produção.
- O script não gera dados sintéticos em ambientes partilhados, não altera estatísticas e não cria índices.
- A execução com dados representativos continua a depender de acesso autorizado a staging ou a uma réplica.