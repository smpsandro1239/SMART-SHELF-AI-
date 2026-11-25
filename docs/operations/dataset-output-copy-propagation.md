# Propagação de governação para cópias, caches e backups

## Estado

Contrato operacional documentado. Não existe ainda integração com object storage, CDN, cache distribuída, backup provider ou arquivo externo. Não existe inventário de cópias externas completo; por isso, nenhum sistema pode afirmar que uma restrição ou legal hold foi propagado para cópias não registadas.

## Regra de segurança

A publicação original e as relações pai → derivado são a fonte de linhagem conhecida. Uma operação de cópia/export/cache/backup tem de consultar a fronteira de consumo governado antes de ler os bytes e registar a cópia antes de a disponibilizar. Uma cópia sem identidade verificável, sem linhagem ou sem estado de inventário conhecido é considerada não elegível para servir.

## Contrato mínimo para futuros adapters

Cada cópia materializada deve ter um registo imutável com:

- publicação(ões) de origem e cadeia de linhagem;
- tipo de destino: CACHE, EXPORT, BACKUP, REPLICA, OBJECT_STORAGE ou REPORT;
- sistema/provedor e identificador opaco do objecto (nunca credenciais ou URLs assinadas);
- SHA-256, tamanho, instante de criação e última atestação;
- estado: PRESENT, MISSING, UNKNOWN, INVALID ou DISPOSITION_PENDING;
- versão do adapter e evidência da última verificação.

A identidade de destino não deve ser usada como substituto do digest. O inventário deve ser append-only, com eventos de descoberta, verificação, invalidação, restauro e disposição; correcções devem ser novos eventos, não updates destrutivos.

## Propagação de restrições e legal holds

- A aplicação de uma restrição/hold deve invalidar de forma síncrona as capacidades de leitura de caches e exports controlados pela aplicação.
- Se a invalidação imediata de um destino não puder ser confirmada, o adapter deve falhar fechado e recusar servir esse destino.
- Backups imutáveis não podem ser alterados para simular propagação. Devem receber uma anotação de governação no catálogo e ficar bloqueados no processo de restauro/recuperação até revalidarem a cadeia de origem.
- Um restauro deve reconstruir primeiro o estado de governação actual, verificar inventário e linhagem, e só depois disponibilizar o conteúdo.
- Inventário ausente, desactualizado, incompleto ou com estado UNKNOWN bloqueia consumo e impede declarar cobertura completa.
- O TTL de cache, por si só, não é mecanismo de propagação nem prova de eliminação.

## Matriz de cobertura mínima antes de produção

| Destino | Registo obrigatório | Bloqueio em restrição/hold | Verificação em restore/serve |
|---|---|---|---|
| Cache local/distribuída | ID de chave + digest + origem | Invalidar; recusar se falhar | Sim |
| Export/relatório | ID do artefacto + digest + origem | Revogar acesso e marcar bloqueado | Sim |
| Object storage | Bucket lógico + key opaca + version ID + digest | Negar GET/cópia; marcar versão | Sim |
| Réplica | Identidade da réplica + watermark | Bloquear leitura até sincronizar | Sim |
| Backup imutável | ID do backup + manifesto de conteúdos | Registar hold; não alterar backup | Gate obrigatório antes de restore |
| Cópia offline | Manifesto assinado + cadeia de origem | Marcar não elegível; bloquear reimportação | Sim |

## Disposição física

Não executar DELETE, lifecycle expiration, purge de bucket, limpeza de cache ou expiração de backup com base apenas na idade. A disposição exige política aprovada, inventário completo, evidência de cada destino, aprovação independente, janela de recuperação e reconciliação pós-operação. Até lá, preservar bytes e bloquear acessos não autorizados.
