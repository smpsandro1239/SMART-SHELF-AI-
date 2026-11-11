# Arquitetura — visão geral

## Componentes lógicos

### 1. Recolha
Fontes previstas: câmaras fixas, câmara instalada no robô existente (se tecnicamente suportada) e telemóveis. Cada evento deve identificar loja, dispositivo, localização, instante e origem.

### 2. Edge
Agente de captura, validação de qualidade, filtragem de privacidade, inferência local quando adequada e buffer persistente para períodos sem conectividade. A captura deve ser seletiva e proporcional à finalidade.

### 3. Plataforma Cloud
- API FastAPI.
- PostgreSQL para dados operacionais e auditoria.
- Serviços de visão, inventário, previsão e tarefas.
- Integrações autenticadas com POS/ERP/WMS, mediante autorização.
- Observabilidade, controlo de acessos e gestão de versões.

### 4. Interfaces
Dashboard Angular para supervisão e PWA para observação, consulta e confirmação de tarefas.

## Fluxo operacional proposto

1. Um dispositivo autorizado recolhe uma imagem de uma prateleira.
2. O Edge valida qualidade e aplica as medidas de privacidade configuradas.
3. O serviço de visão produz deteções e estado estimado com confiança.
4. A plataforma associa a observação à loja/prateleira/produto.
5. O serviço de inventário consulta a última informação disponível e indica a sua idade.
6. O serviço de previsão estima procura e risco de rutura.
7. O motor de regras calcula prioridade e quantidade sugerida.
8. Se existir stock de retaguarda elegível, é proposta/criada uma tarefa segundo as regras aprovadas.
9. Se não existir stock, é criada uma ocorrência alternativa.
10. O operador confirma a ação; o resultado alimenta métricas e melhoria do sistema.

## Integração com robô

A compatibilidade não está confirmada. Antes de qualquer modificação, recolher fabricante, modelo, SDK/API, interfaces físicas, alimentação, documentação de segurança e autorização do fabricante. ROS 2 não deve ser presumido.

## Comunicação

- REST/HTTPS para operações e consultas.
- MQTT para eventos e estado de dispositivos, se necessário.
- Não transportar imagens em bruto em tópicos MQTT; usar armazenamento/transferência segura e referências autenticadas.
- Mensagens devem suportar identificadores idempotentes, timestamps e reprocessamento controlado.

## Resiliência

- Buffer local com limites e política de retenção.
- Reenvio com backoff e idempotência.
- Monitorização de dispositivos offline.
- Separação entre falha de visão, falha de inventário e falha de comunicação.
- Registo da origem e da versão do modelo em todas as deteções.
