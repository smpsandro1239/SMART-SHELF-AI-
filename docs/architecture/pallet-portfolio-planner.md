# Planeamento global de rotação de paletes

O módulo `app/pallet_portfolio.py` agrega decisões consultivas para várias
paletes numa única lista operacional. Não substitui o motor individual
`pallet_rotation.py` nem o planeador de janelas históricas.

## Regras de prioridade

1. **INTERIM_REPLENISHMENT** — o residual não cobre o consumo esperado até à
   próxima janela de baixa afluência; proteger primeiro o nível de serviço.
2. **SWAP_PALLET** — apenas quando existe palete substituta, capacidade de
   retaguarda confirmada, tráfego elevado, residual abaixo do limiar e a troca
   poupa tempo de mão de obra.
3. **PREPARE_REPLACEMENT / REVIEW_BACKROOM** — falta uma condição operacional;
   não assumir disponibilidade.
4. **REPLENISH_CURRENT** — manter reposição convencional ou repor na janela
   atualmente calma.
5. **REVIEW_DATA** — tráfego desconhecido.

Dentro da prioridade, o planeador ordena pela poupança estimada e pelo ID da
palete para garantir resultados determinísticos.

## Contrato de segurança

- O motor recebe candidatos já selecionados e validados pelo chamador.
- Dados numéricos ausentes ou inválidos excluem o candidato; não são imputados.
- IDs repetidos são excluídos depois da primeira ocorrência.
- A resposta declara `automatic_stock_movement_allowed=false`.
- Não reserva paletes, não cria tarefas, não atualiza estados ou inventário.
- Os minutos são estimativas fornecidas pelo chamador; não são medição real.

## Integração pendente

A camada API ainda tem de recolher candidatos por loja, ligar cada palete à
política ativa, embalagem PALLET, perfil de procura e janela histórica, validar
capacidade real da localização e aplicar isolamento por loja/role. Até essa
integração, este módulo é uma unidade pura de decisão e não disponibiliza um
endpoint público.
