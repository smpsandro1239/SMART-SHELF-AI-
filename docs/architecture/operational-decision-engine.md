# Motor central de decisão operacional

## Objetivo

O `operational_decision_engine` é uma camada de domínio independente da base de dados. Normaliza evidência de quatro áreas — observação da prateleira, inventário, previsão de procura e tarefas existentes — e devolve uma decisão explicável para um par produto/localização.

## Estados de decisão

- `INSUFFICIENT_EVIDENCE`: não há evidência suficiente para avaliar.
- `MONITOR`: a evidência não justifica ação.
- `ACTION_RECOMMENDED`: existe sinal fiável de atenção visual ou risco de a procura prevista exceder o inventário disponível.
- `ALREADY_IN_PROGRESS`: existe uma tarefa ativa; não deve ser criada uma duplicação.

## Regras de segurança e qualidade

1. Datas têm de incluir fuso horário; evidência fora da janela de validade não é usada para disparar uma recomendação.
2. Observações visuais só contam quando a confiança atinge o limiar configurado.
3. Inventário em falta nunca é interpretado como zero.
4. A quantidade sugerida só é calculada quando existem inventário e previsão recentes.
5. A previsão é uma estimativa e não uma venda confirmada.
6. Uma recomendação nunca executa movimentos de stock nem cria tarefas. Exige aprovação humana.
7. A resposta inclui proveniência, idade, confiança e avisos para permitir auditoria.

## Contrato de integração

O módulo recebe dicionários normalizados e devolve um objeto serializável. A camada API deve obter os registos no âmbito da loja autorizada, converter os modelos para o contrato e persistir a recomendação/auditoria através do fluxo existente. Não deve aceitar IDs de outra loja nem contornar as permissões atuais.

## Limitações deliberadas

O motor não calcula disponibilidade física real a partir de uma fotografia, não substitui contagens de inventário, não corrige previsões sem dados históricos e não assume integração POS/ERP. As paletes são apenas uma possível estratégia operacional a jusante, não uma regra do motor central.
