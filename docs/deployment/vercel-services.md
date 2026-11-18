# Deploy do SMART SHELF AI na Vercel (Multi-Service)

## Objetivo e serviços publicados

O repositório contém duas aplicações que podem ser construídas separadamente:

| Serviço | Diretório | Framework | Exposição pública |
|---|---|---|---|
| `web` | `apps/web` | Vite / React | `/` — todas as rotas que não correspondem à API |
| `api` | `apps/api` | FastAPI / Python | `/api/*`, `/health` e `/health/ready` |

A configuração está em `/vercel.json`. O serviço `api` recebe o caminho original, incluindo o prefixo `/api`; isto corresponde às rotas existentes `/api/v1/...` da FastAPI. O frontend usa URLs relativas `/api/...`, pelo que ambos partilham o mesmo domínio.

### Bindings entre serviços

Não foi configurado nenhum binding. A aplicação web é executada no browser e chama a API através do caminho público do mesmo domínio; não existe uma chamada servidor-a-servidor entre estes dois serviços que justifique um binding. A API também não chama o frontend.

O worker de inferência, PostgreSQL e armazenamento persistente de imagens **não são serviços Vercel nesta configuração**.

## Requisitos antes de utilizar a API

A Vercel não fornece automaticamente uma base de dados PostgreSQL nem armazenamento persistente para este repositório. Antes de utilizar endpoints que consultam ou alteram dados:

1. Disponibilizar uma instância PostgreSQL externa compatível com SQLAlchemy/psycopg.
2. Configurar as seguintes variáveis no projecto Vercel, para Production e Preview conforme necessário:
   - `APP_ENV=production`
   - `DATABASE_URL`: URL SQLAlchemy PostgreSQL, por exemplo com o esquema `postgresql+psycopg://`.
   - `JWT_SECRET_KEY`: segredo aleatório exclusivo, com pelo menos 32 caracteres.
   - `BOOTSTRAP_ADMIN_KEY`: segredo aleatório exclusivo, com pelo menos 32 caracteres.
3. Executar as migrações Alembic contra essa base de dados antes de usar a API. A migração não é executada automaticamente durante o build:
   ```bash
   cd apps/api
   DATABASE_URL="postgresql+psycopg://..." alembic upgrade head
   ```
4. Não colocar segredos em `vercel.json`, no frontend, no Git ou em variáveis `VITE_*`.

O endpoint `/health/ready` só responde `200` quando consegue consultar PostgreSQL e todas as heads Alembic declaradas no código estão aplicadas. Uma base de dados vazia ou com migrações desatualizadas responde `503`; aplicar as migrações antes de considerar a API pronta.

A configuração de CORS não é necessária para as chamadas normais do frontend, porque usa o mesmo domínio e os rewrites da Vercel. Se a API vier a ser consumida a partir de outro domínio, configurar `CORS_ALLOWED_ORIGINS` com as origens explícitas.

## Segredos e primeiro administrador

A validação de configuração de produção exige `APP_ENV=production`, um `JWT_SECRET_KEY` e um `BOOTSTRAP_ADMIN_KEY` distintos, aleatórios, sem espaços e com pelo menos 32 caracteres. A configuração Multi-Service deve receber estes valores como variáveis de ambiente server-side; nunca os inclua em `vercel.json`, no frontend ou no repositório.

Para gerar e rodar os segredos, incluindo a consequência da rotação JWT para sessões activas, consultar [Production secrets: generation, storage and rotation](../security/production-secrets.md).

O Docker Compose local também aceita `APP_ENV`, `JWT_SECRET_KEY` e `BOOTSTRAP_ADMIN_KEY` para a API e o worker. Os valores por omissão são apenas de desenvolvimento; não são uma configuração de produção válida.

## Limitações funcionais que permanecem

- **PostgreSQL:** externo e sujeito aos limites/termos do respetivo fornecedor.
- **Migrações:** têm de ser executadas explicitamente contra a base de dados de destino.
- **Imagens:** a API grava atualmente em disco local (`IMAGE_STORAGE_PATH`). O sistema de ficheiros de uma Function Vercel não é armazenamento persistente partilhado; não utilizar uploads como armazenamento duradouro até existir uma integração com object storage.
- **Uploads:** as Functions Vercel têm um limite de payload de 4,5 MB. O limite actual da aplicação pode ser superior; uploads maiores podem receber HTTP 413.
- **Worker:** `apps/api/app/vision_worker.py` é um processo de polling contínuo e não é iniciado pela configuração Multi-Service. O processamento de imagens pendentes não ficará operacional apenas com este deploy.
- **Modelos:** não existe um modelo de visão real treinado/configurado no repositório. O deploy não cria essa capacidade.
- **Docker Compose:** continua a ser o ambiente local e de CI; a Vercel não executa o ficheiro `docker-compose.yml` como uma stack integral.

Assim, esta configuração permite publicar o frontend e disponibilizar a API FastAPI no mesmo domínio, mas não equivale a alojar toda a plataforma com persistência de imagens e inferência contínua.

## Build do frontend e desenvolvimento local

O frontend usa `VITE_API_BASE_URL` como override opcional. Se estiver vazio, chama `/api/...` no mesmo domínio. Em desenvolvimento, o Vite encaminha `/api` para `http://127.0.0.1:8000`; basta iniciar a API na porta 8000 e o frontend na porta 5173.

Build do frontend:

```bash
cd apps/web
npm install
npm run build
```

## Configuração na Vercel

1. Importar `smpsandro1239/SMART-SHELF-AI-` a partir do GitHub, branch `main`.
2. Selecionar a configuração de **Multi-Service** (não definir `apps/web` como Root Directory do projecto).
3. Confirmar o framework `Services` e que a Vercel reconhece os serviços `api` e `web` definidos no `vercel.json`.
4. Configurar as variáveis de ambiente da API descritas acima antes de testar endpoints de dados.
5. Fazer Deploy e validar primeiro `/health`, depois `/health/ready` (depois de configurar PostgreSQL) e finalmente o frontend.

O plano Hobby é destinado a utilização pessoal e não comercial. Consultar os limites e condições actuais da Vercel antes de utilizar o projecto num contexto comercial.
