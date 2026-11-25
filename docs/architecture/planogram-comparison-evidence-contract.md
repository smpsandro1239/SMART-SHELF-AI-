# Contrato de evidência para comparações de planograma

Estado: **proposta técnica conservadora — não implementada**
Data: 2026-11-19
Âmbito: comparação entre uma captura de prateleira concluída e uma versão ativa de planograma.

## 1. Decisão imediata

A comparação permanece on-demand, read-only e sem escrita na base de dados. Não criar ainda tabela de resultados, snapshots automáticos no worker, exports ou efeitos operacionais.

A persistência só pode avançar depois de aprovadas a política de retenção/derivados, o modelo de revisão humana e a semântica de idempotência descritos abaixo. O fingerprint SHA-256 atual identifica uma representação canónica; não é assinatura digital, prova de origem nem autorização para conservar os dados.

## 2. Identidade de uma evidência

Uma ocorrência persistida deverá ter identidade própria e imutável, separada do digest do conteúdo. A chave lógica mínima para deduplicação deverá considerar:

- loja, prateleira e captura (shelf_image_id);
- SHA-256 da captura, validado sob lock;
- ID e versão imutável do planograma ativo, incluindo identidade da calibração (MANUAL ou imagem + ID + SHA-256);
- versão do esquema da comparação;
- identidade exacta do pipeline de inferência: provider, versão do modelo de deteção e, quando aplicável, versão do modelo de embeddings/SKU matching e configuração relevante;
- digest do snapshot canónico completo.

Não usar apenas image_id + planogram_id: uma reexecução do modelo ou mudança de algoritmo pode produzir evidência diferente. Não usar apenas o digest como chave primária. A idempotência deve ser explícita e limitada à mesma identidade de pipeline e ao mesmo snapshot.

## 3. Conteúdo mínimo do snapshot

O snapshot imutável deverá conter, em JSON canónico versionado:

- identificadores da loja, prateleira, captura e respectivos SHA-256;
- timestamp de captura e timestamp de conclusão da análise;
- versão do planograma e todas as células usadas na comparação (geometria, SKU esperado e facings);
- origem e identidade/digest da calibração;
- versões exactas dos modelos e configuração/versão do algoritmo de associação;
- deteções efectivamente usadas, com ID e atributos relevantes (classe, confiança, bounding box, SKU atribuído e estado de matching);
- resultado por célula, incluindo estado, contagens, deteções associadas e métricas;
- versão do esquema, instante de cálculo e digest SHA-256.

Não depender exclusivamente de FKs para reconstruir o passado: hoje as deteções podem ser eliminadas em cascata com a captura e referências a produtos podem ser anuladas. Se a política aprovar persistência, o snapshot terá de preservar os valores necessários para interpretar o resultado sem reter a imagem original. A cópia do snapshot é, por si, um derivado governado e tem de herdar retenção, legal hold, autorização e linhagem da captura.

## 4. Imutabilidade e revisão humana

- Registos de evidência são append-only: sem UPDATE/DELETE da evidência, snapshot ou digest por caminhos aplicacionais.
- Correções de SKU, validações, rejeições e decisões de revisão são eventos separados, append-only, com actor, timestamp, decisão, motivo e referência à evidência/deteção.
- Uma revisão nunca reescreve o resultado original nem altera retroactivamente o snapshot.
- Uma nova execução cria nova evidência ligada à anterior por relação explícita (reprocessamento/substituição), sem apagar o histórico.
- O estado de revisão é uma projecção derivada dos eventos, não uma mutação do conteúdo probatório.

## 5. Retenção, revogação e linhagem

A evidência não pode tornar-se uma via indirecta para contornar a retenção da captura. Antes de persistir, é necessária política aprovada que defina:

1. se a evidência derivada pode sobreviver à purga dos bytes da captura;
2. quais os campos permitidos no snapshot e quais são dados pessoais/comerciais;
3. como se herdam RESTRICTED, PENDING_PURGE, PURGED e legal_hold;
4. como se propagam restrições a exports, caches, backups, réplicas e object storage;
5. se existe retenção diferenciada para evidência, revisão e auditoria;
6. como se prova a conclusão de uma purga sem apagar indevidamente a trilha de auditoria.

Até existir decisão, bloquear criação/consumo de snapshots persistidos para capturas não ACTIVE e manter a comparação apenas no endpoint existente, sob os locks e verificações de retenção já implementados. Não inferir que guardar apenas IDs ou hashes torna os derivados anónimos ou isentos de retenção.

## 6. Concorrência e ordem de locks

Qualquer futuro escritor deverá reutilizar a ordem global já aplicada pela comparação:

1. bloquear captura e imagem de calibração por ID crescente;
2. bloquear prateleira;
3. bloquear e revalidar a versão ativa do planograma;
4. revalidar estado da captura, estado de análise, SHA-256, versão do planograma e elegibilidade de todas as fontes;
5. calcular/validar a identidade e inserir evidência e evento de auditoria na mesma transacção.

A versão ativa pode mudar entre a descoberta inicial e a aquisição dos locks: nesse caso, abortar com conflito e exigir nova execução. Não manter locks PostgreSQL durante inferência, cópia de ficheiros, chamadas externas ou outras operações I/O longas. Um worker futuro deverá separar preparação de cálculo da curta transacção de revalidação/publicação e usar fencing/idempotência para impedir workers obsoletos.

## 7. Fronteira operacional

Uma comparação ou revisão visual nunca altera directamente inventário contabilístico, cria movimentos de stock, aprova reposições ou cria tarefas. Qualquer consequência operacional futura exige fluxo separado, permissões específicas, revisão humana válida e evidência fresca revalidada no momento da decisão.

## 8. Critérios de aceitação antes da migration

- Política de retenção/derivados e legal hold aprovada pelo responsável do produto e jurídico/privacidade.
- Esquema de snapshot versionado e teste de canonicalização/digest com fixtures estáveis.
- Definição de idempotência, reprocessamento e unicidade concorrente.
- Triggers/constraints append-only em PostgreSQL e SQLite, se ambos continuarem suportados.
- Smoke PostgreSQL com duas sessões para concorrência entre persistência, mudança de planograma e restrição da captura.
- Testes de isolamento multi-loja, autorização, legal hold, purga e propagação a derivados.
- Procedimento de exportação, retenção, purga e recuperação documentado.
- CI completa antes de qualquer integração do worker.

## 9. Lacunas que permanecem abertas

A versão actual de deteções não é uma identidade imutável do pipeline: a captura guarda model_version, as deteções guardam model_version e embedding_model_version, mas não existe ainda manifesto completo e imutável de configuração/inferência para a comparação. A revisão SKU existente é append-only, mas a comparação actual usa os campos de deteção persistidos; a regra de precedência entre detecção original e revisão humana tem de ser especificada antes de congelar snapshots. Estas lacunas impedem uma migration prematura.