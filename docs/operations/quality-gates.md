# Quality gates e validação contínua

## Workflow

O workflow `.github/workflows/smart-shelf-quality.yml` executa em cada push para `main`, em pull requests dirigidos a `main` e por execução manual.

### Backend API

1. Instala Python 3.12.
2. Instala as dependências de `apps/api/requirements.txt`.
3. Compila os módulos da aplicação com `python -m compileall -q app`.
4. Executa a suite completa com `python -m pytest -q`.

### Frontend

1. Instala Node.js 22.
2. Instala as dependências declaradas em `apps/web/package.json`.
3. Executa `npm run build`, que inclui a verificação TypeScript (`tsc -b`) e o build Vite.

O workflow não precisa de segredos de produção: as verificações usam configuração de teste e não se ligam a serviços externos.

## Execução local

Backend:

```bash
cd apps/api
python -m pip install -r requirements.txt
python -m compileall -q app
python -m pytest -q
```

Frontend:

```bash
cd apps/web
npm install
npm run build
```

## Critério de aceitação

- Não considerar uma alteração validada apenas porque foi publicada.
- Confirmar que os jobs do GitHub Actions terminaram com sucesso.
- Corrigir falhas antes de integrar novas alterações que dependam do comportamento afetado.
- Preservar testes de regressão para regras de negócio e limites operacionais.
- Não usar dados de produção, credenciais reais ou movimentação física em testes.

## Limitações conhecidas

O workflow verifica compilação e testes unitários/integrados já presentes no repositório. Não substitui testes end-to-end com POS/ERP/WMS, validação de modelos de visão computacional, testes de carga, análise de dependências dedicada nem um piloto físico em loja. O frontend é compilado, mas ainda não tem uma suite de testes de componentes dedicada.


## Salvaguardas de evidência de inventário

A avaliação de risco de rutura exige histórico diário completo e um snapshot de inventário recente. Um snapshot com data futura é rejeitado como `FUTURE_INVENTORY`: não é convertido artificialmente numa idade zero. Quantidades booleanas também são rejeitadas, em vez de serem convertidas em 0/1.

O planeador de paletes ignora candidatos que não sejam objetos de mapeamento e contabiliza-os como excluídos, sem interromper a avaliação dos restantes candidatos. Estas regras são cobertas por testes de regressão.

## Pallet planning and historical evidence validation

- Hourly pallet profiles must contain 24 mapping rows, one per hour. Non-mapping rows are rejected as invalid evidence rather than causing an unhandled attribute error.
- Sales and traffic coverage counts must be actual integers; booleans, decimal values and numeric strings are not accepted as observation counts.
- Residual pallet quantities cannot be booleans. This prevents Python's boolean-to-number coercion from turning `True` into one unit of stock.
- The hourly-profile bridge validates its time-window parameters before processing candidates, including when the candidate list or profile map is empty.
- Malformed pallet candidates are retained only as explicitly unknown evidence and do not interrupt processing of valid candidates.
- Daily sales history accepts calendar dates only. Datetime values are rejected to avoid mixed date/datetime comparisons and ambiguous business-day assignment.
- All these paths remain read-only. Planning evidence and recommendations never authorize physical stock movement.

## HTTP pallet portfolio input guards

- Historical portfolio query parameters (`current_hour`, `days`, `duration_hours`, `minimum_observed_days`, and `limit`) must be actual integers within their documented ranges; booleans and fractional values are rejected.
- Cost/time inputs and operator-supplied demand values must be finite, non-negative numeric values. Boolean values are rejected explicitly instead of being interpreted as 0 or 1.
- The operator-input portfolio endpoint no longer truncates fractional limits with `int(limit)`; the requested limit must already be an integer.
- Invalid input is rejected with HTTP 422 before portfolio database work proceeds. Both portfolio endpoints remain read-only.
