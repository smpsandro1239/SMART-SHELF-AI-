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
