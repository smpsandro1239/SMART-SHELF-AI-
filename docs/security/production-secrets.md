# Production secrets: generation, storage and rotation

## Required application secrets

Production API and worker processes require two distinct values:

- `JWT_SECRET_KEY`: signs and verifies access tokens.
- `BOOTSTRAP_ADMIN_KEY`: authorizes the one-time creation of the first administrator.

Both values must contain at least 32 characters, contain no whitespace, avoid placeholder/development markers, and differ from one another. Use independently generated random values; do not derive one from the other.

## Generate

Generate each value independently with a cryptographically secure random generator:

```bash
openssl rand -hex 32
openssl rand -hex 32
```

Each command produces 256 bits of random material encoded as 64 hexadecimal characters. Run the command twice and assign one output to each secret.

Do not commit generated values, paste them into issue trackers, or place them in frontend variables such as `VITE_*`.

## Store and deploy

### Vercel

Set `APP_ENV=production`, `JWT_SECRET_KEY`, `BOOTSTRAP_ADMIN_KEY`, and a least-privilege runtime `DATABASE_URL` in the Vercel project's server-side Environment Variables. The URL must authenticate as the application runtime role, never as the database/migration owner. Configure Production and Preview independently; do not expose secrets to the browser. Redeploy after changing a value.

### Docker Compose

The Compose API and worker now receive `APP_ENV`, `JWT_SECRET_KEY`, and `BOOTSTRAP_ADMIN_KEY` from the host environment. For production, provide all three through the deployment platform's secret/environment injection and set `APP_ENV=production`. Do not rely on the development defaults in `.env.example` or the Compose file. Keep the file containing actual values outside version control with restrictive permissions, or use a dedicated secret manager.

The API and worker must receive the same JWT and bootstrap values because both import the validated application settings. PostgreSQL uses two separate identities: `APP_DB_USER`/`APP_DB_PASSWORD` are the least-privilege runtime credentials for API/worker; `POSTGRES_USER`/`POSTGRES_PASSWORD` are reserved for the migration owner and the explicitly invoked ONNX release-registration profile. Never inject the owner credentials into API or worker containers. The runtime role has DML on operational tables but only SELECT on `vision_model_release_states` and `vision_model_release_events`.

## First administrator bootstrap

1. Deploy with a strong `BOOTSTRAP_ADMIN_KEY` already configured.
2. Call `POST /api/v1/auth/bootstrap` once, sending that value in the `X-Bootstrap-Key` header over HTTPS.
3. Confirm the first administrator can sign in.
4. Rotate `BOOTSTRAP_ADMIN_KEY` to a fresh random value and redeploy. The endpoint remains one-time: once any user exists it returns HTTP 409, even with the correct key.
5. Keep a strong configured value after bootstrap because production configuration validation still requires it; never replace it with an empty value or a placeholder.

The API serializes concurrent bootstrap attempts in PostgreSQL with a transaction-scoped advisory lock. Only one concurrent request can create the first administrator; the other receives HTTP 409.

## Rotation

### JWT signing key

The application currently supports one active JWT signing key, not an overlapping key ring. Rotation therefore invalidates all outstanding access tokens:

1. Generate a new random value.
2. Update `JWT_SECRET_KEY` in the deployment secret store for every API instance.
3. Roll out/restart all API instances as one coordinated deployment.
4. Require users to sign in again and monitor authentication failures.

Do not run a mixed deployment where instances use different JWT secrets; tokens minted by one instance would fail on another.

### Bootstrap key

Generate a new value, update the secret store, and redeploy. Since bootstrap is one-time, rotating this value after the first administrator exists does not change existing accounts or access tokens.

### Database credentials

Rotate `APP_DB_PASSWORD` for the runtime role independently from `POSTGRES_PASSWORD` for the migration owner. Update the database role and the corresponding secret-store values in a coordinated rollout. API and worker use only `APP_DB_USER`/`APP_DB_PASSWORD`; the `migrate` service and one-shot `register-model-release` profile use the owner credentials. The Compose `provision-runtime-role` one-shot service runs before migrations on each deployment and reconciles existing volumes as well as fresh databases. After changing credentials, run `docker compose run --rm provision-runtime-role` explicitly when an immediate reconciliation is required; coordinate API/worker restarts with password rotation.

## Operational controls

- Restrict secret-store access to deployment operators and the minimum required automation.
- Keep separate secrets for development, Preview, and Production.
- Never log secret values or include them in diagnostic output.
- Replace any secret that was committed, pasted into a ticket/chat, or exposed in a build log; deleting the visible copy is not sufficient.
- Record rotation date and owner in the organization's secret manager, not in this repository.
