# Auditoria de isolamento multi-loja — evidência derivada de imagens

**Estado:** auditoria parcial; não constitui aprovação de segurança para produção.

## Âmbito desta ronda

Foram revistos os handlers e as regras de autorização de:

- sessões de captura e upload de imagens;
- conteúdo binário, deteções, OCR, fusão de evidência e revisões humanas;
- fila de revisão e respetivos contadores;
- exemplares de embeddings e matching;
- candidatos de treino derivados de revisões humanas;
- relatório de avaliação SKU revisto por humanos;
- histórico e operações de retenção.

A análise considerou o middleware JWT, as regras por perfil, a resolução da loja através de prateleira/zona e os filtros aplicados às consultas.

## Regras de isolamento observadas

1. Um utilizador não ADMIN só pode consultar ou alterar recursos associados à sua loja.
2. O acesso ao conteúdo de uma imagem verifica a loja antes de verificar o estado de retenção.
3. Imagens que não estejam em estado `ACTIVE` não podem alimentar leitura operacional, revisão, matching ou curadoria de treino.
4. O catálogo de produtos é global por decisão arquitetural; a associação SKU–prateleira continua limitada pela loja.
5. Os endpoints de revisão de evidência e de gestão de datasets exigem perfil de supervisor ou administrador através do middleware.
6. A avaliação SKU aceita um filtro de loja para ADMIN; um SUPERVISOR fica limitado à própria loja e recebe 403 quando tenta indicar outra loja.
7. Candidatos de treino são filtrados pela loja da imagem de origem para utilizadores não ADMIN.

## Regressões adicionadas

O ficheiro `apps/api/tests/test_training_candidates.py` inclui agora testes de integração para:

- supervisor de outra loja não receber candidatos de treino;
- supervisor da loja de origem continuar a receber os seus candidatos;
- supervisor não conseguir consultar a avaliação SKU de uma loja estrangeira;
- supervisor não conseguir carregar imagens para prateleiras de outra loja, sem criar registo nem ficheiro;
- avaliação SKU sem filtro explícito usar automaticamente a loja do supervisor.

Os testes usam um ator de teste injetado no helper de resolução de utilizador. O middleware de autenticação é deliberadamente ignorado em `APP_ENV=test`; estes testes validam a autorização dentro dos handlers e não substituem testes HTTP com JWT real em ambiente de integração.

## Separação de funções na aprovação de exemplares

A revisão de embeddings passou a impedir a autoaprovação por SUPERVISOR. O criador recebe HTTP 403 ao tentar aprovar/rejeitar o próprio exemplar; um segundo SUPERVISOR da mesma loja pode rever e ADMIN mantém a capacidade de revisão. A regra é verificada por teste de regressão no handler. Esta salvaguarda reduz o risco de um único utilizador introduzir uma referência e torná-la elegível para matching sem revisão independente.

## Decisões e limitações

- Não foi alterada a política do catálogo global.
- Não foi introduzida purga física nem eliminação de evidência derivada.
- Não se considerou suficiente a análise estática para fechar a auditoria.
- A auditoria completa ainda requer cobertura de todos os endpoints, execução dos testes em PostgreSQL, revisão dos acessos administrativos e verificação do worker e de caminhos indiretos.
- Antes de produção, deve existir uma matriz explícita de permissões por método/rota/perfil e testes de integração com tokens reais para ADMIN, SUPERVISOR e EMPLOYEE.

## Critério para fechar a tarefa

A tarefa só pode ser marcada como concluída quando a matriz de rotas estiver coberta, os testes cross-store passarem em CI com PostgreSQL e não existirem caminhos indiretos que revelem dados de outra loja ou evidência com retenção restrita.
