# Fronteiras dos consumidores de datasets

## Objectivo

Distinguir ferramentas de inspecção e preparação de datasets de operações que efectivamente autorizam e iniciam treino ou inferência. A presença de uma release, de um relatório COCO válido ou de uma revisão visual não constitui, isoladamente, autorização operacional.

## Inventário dos caminhos inspeccionados

| Componente | Operação | Efeito / dados | Gate operacional |
|---|---|---|---|
| `app.coco_dataset` | Valida estrutura COCO e, opcionalmente, existência de ficheiros | Leitura local; não cria cópias nem inicia processos externos | Não é um consumidor autorizado; validação estrutural apenas |
| `app.coco_review` | Gera galeria HTML offline | Escreve HTML que referencia os ficheiros originais por caminhos relativos; não copia imagens | Não é aprovação nem autorização de treino |
| `app.dataset_diff` | Compara manifestos e anotações COCO | Escreve relatório JSON agregado; não lê pixels nem copia imagens | Comparação documental, não autorização |
| `app.dataset_quality` / `app.dataset_audit` | Analisa qualidade e separação de splits | Relatórios e métricas; sem execução de treino | Gate de qualidade, não autorização isolada |
| `app.dataset_review` | Valida registos de revisão visual/humana | Confirma estrutura, hashes e decisão declarada; não autentica a identidade do revisor | Evidência de revisão, não autenticação |
| `app.dataset_approval` | Combina registo de release, proveniência, COCO, qualidade e revisão | Produz decisão de aprovação; para imagens internas bloqueia imagem/prateleira/zona no fim das verificações | Gate de aprovação; não lança consumidor |
| `app.dataset_release` | Cria registo determinístico de release | Escreve JSON imutável com fingerprint, manifestos e proveniência | Pode criar release técnica/candidata; não equivale a aprovação nem a treino |
| `app.dataset_execution` | Invoca um processo local síncrono | Cria release ligada à aprovação e mantém a sessão/locks até o processo terminar | **Única fronteira inspeccionada que inicia um consumidor externo de datasets e exige o gate completo** |

## Invariantes do fluxo síncrono

1. O processo só arranca depois de `run_release_gate` devolver `APPROVED` sem erros.
2. O modo (`training` ou `inference`), o SHA-256 do registo de aprovação e o SHA-256 do relatório do gate entram na identidade da release.
3. O processo recebe os identificadores e hashes de aprovação em variáveis de ambiente `SMART_SHELF_DATASET_APPROVAL_*`.
4. Para fontes internas, a sessão PostgreSQL é aberta antes do gate; os locks de imagem/prateleira/zona são adquiridos no final das verificações de ficheiros e mantidos durante a criação da release e o processo síncrono.
5. O processo é invocado com `shell=False`; o timeout é opcional e, quando definido, tem de ser positivo.
6. A sessão é revertida/fechada no `finally`, libertando os locks após o consumidor terminar ou falhar.

## Limites identificados

- A galeria HTML pode revelar nomes de ficheiros e permite visualizar imagens enquanto o utilizador tem acesso ao directório local. Não tem autenticação, autorização multi-loja nem integração com a política operacional de retenção; deve ser tratada como ferramenta local de revisão controlada.
- Os relatórios de diff/qualidade e os registos de release podem conter metadados derivados. A sua localização, cópia, backup e prazo de conservação ainda não estão ligados a um registo central de artefactos.
- A revisão declarada em ficheiro não autentica o revisor. A identidade e a autorização legal/técnica têm de ser verificadas por um processo de aprovação externo ou por uma futura API de revisão autenticada.
- `dataset_release` continua deliberadamente disponível para criar releases técnicas/candidatas. Só `dataset_execution` liga a aprovação ao arranque do consumidor.
- Um consumidor pode destacar processos, enviar dados para uma fila, lançar jobs cloud ou copiar dados antes de terminar. O processo pai não consegue manter os locks nem impedir esses efeitos laterais depois de sair.
- O contrato de proveniência inclui relações pai/filho por ficheiro, mas não existe ainda um catálogo global de artefactos internos com herança de retenção, inventário de destinos, revogação e prova de eliminação.
- Não foi identificado um executor de treino real no repositório. O comando é fornecido pelo operador; o CI valida o wrapper e processos de teste, não treino de um modelo real.

## Próxima implementação segura

Antes de aceitar treino remoto/destacado, implementar um protocolo persistente de execução com:
- identidade imutável do job (fingerprint da release, hashes de aprovação, modo e idempotency key);
- fontes internas normalizadas e ligadas por FK à imagem original, com hash e loja esperados;
- claim atómico com `FOR UPDATE SKIP LOCKED`, proprietário, expiração e contador de fencing monotónico;
- heartbeat e conclusão condicionados por proprietário, token e lease ainda válido;
- revalidação de estado `ACTIVE`, ausência de legal hold, hash e linhagem das fontes em cada fronteira de autorização;
- auditoria append-only de criação, claim, renovação, revogação, falha e conclusão;
- publicação do resultado apenas após validação do token de fencing actual;
- smoke PostgreSQL com dois workers, takeover após expiração, worker antigo a tentar heartbeat/concluir, e restrição/legal hold concorrentes.

**Não assumir que heartbeat frequente, por si só, impede um worker de continuar a ler dados localmente depois de perder o lease.** Para retenção forte, cada leitura de artefacto e cada publicação têm de passar por um serviço de acesso controlado; cópias locais e caches têm de ser inventariadas e revogáveis. Não activar purge físico enquanto esta cobertura não existir.
