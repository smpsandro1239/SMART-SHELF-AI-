# Âmbito do produto

## Problema a resolver

A disponibilidade na prateleira pode divergir do stock registado. A observação visual ajuda a detetar sinais de baixa disponibilidade, mas não substitui o inventário nem confirma, por si só, a quantidade física total.

## Utilizadores e intervenientes

- Operadores de loja e equipas de reposição.
- Responsáveis de secção/loja.
- Equipas de inventário e aprovisionamento.
- Equipas técnicas responsáveis por infraestrutura, dados e dispositivos.
- Responsáveis de privacidade e segurança.

## Capacidades pretendidas

1. Registar lojas, zonas, corredores, prateleiras e produtos.
2. Registar câmaras, dispositivos móveis e robôs autorizados.
3. Receber observações de imagem com timestamp, origem, qualidade e versão do modelo.
4. Classificar o estado observado: NORMAL, LOW_STOCK, EMPTY, MISPLACED, DAMAGED, UNKNOWN ou OCCLUDED.
5. Associar deteções a produtos e localizações, incluindo confiança.
6. Consultar snapshots de inventário e reservas através de integração autorizada.
7. Estimar procura por produto e período.
8. Calcular risco e hora provável de rutura.
9. Recomendar quantidade e prioridade de reposição.
10. Criar, agrupar, atribuir e concluir tarefas.
11. Registar exceções e trilho de auditoria.
12. Disponibilizar dashboard e experiência móvel.

## Regras de negócio críticas

- A observação da câmara representa uma estimativa da disponibilidade visível, não o stock total.
- O stock de retaguarda tem de vir de uma fonte de inventário identificada e com timestamp.
- Se não houver stock disponível para reposição, criar uma ocorrência para inventário/aprovisionamento, não uma tarefa de reposição impossível.
- Recomendações automáticas devem ser explicáveis e auditáveis.
- A decisão final e os fluxos operacionais devem ser validados com a loja piloto.

## Estados de observação propostos

- NORMAL
- LOW_STOCK
- EMPTY
- MISPLACED
- DAMAGED
- UNKNOWN
- OCCLUDED

## Fora do âmbito inicial

- Reconhecimento facial ou identificação de clientes.
- Gravação ou análise de áudio.
- Avaliação individual de desempenho de trabalhadores.
- Controlo autónomo de navegação do robô sem autorização do fabricante.
- Escrita automática em ERP/POS sem integração formal e aprovação.

## Dados ainda necessários

- Catálogo e identificadores dos produtos.
- Mapa e localização das prateleiras.
- Histórico de vendas e ruturas.
- Snapshots de stock e reservas.
- Calendário de promoções e horários.
- Especificações do fabricante/modelo do robô.
- Inventário de câmaras e permissões de utilização.
