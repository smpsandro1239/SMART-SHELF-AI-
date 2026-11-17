# SMART SHELF AI — Roadmap

## Prioridade atual: demo vertical de 10 minutos

- [x] Criar provider mock determinístico compatível com `VisionProvider`.
- [x] Criar seed idempotente com loja Demo Store Braga, três prateleiras, quinze produtos, três perfis, snapshots e política de frescura.
- [x] Gerar imagem sintética local sem dados pessoais ou fotografia de terceiros.
- [ ] Ligar a captura do frontend à criação de sessão e ao upload.
- [ ] Ligar a deteção a uma revisão humana de SKU e à criação de observação.
- [ ] Tornar o percurso recomendação → aprovação → tarefa → execução → reconciliação navegável sem terminal.
- [ ] Adicionar testes de integração ponta-a-ponta em PostgreSQL.
- [ ] Validar instalação limpa com Docker Compose, worker, API e frontend.
- [ ] Capturar screenshots do percurso completo.

## Fora do âmbito desta fase

- Integrações POS, ERP ou WMS reais.
- Treino ou inferência de modelos de visão production-grade.
- Rotação de paletes, slotting, picking ou previsão avançada.

## Regras de conclusão

Só marcar uma tarefa como concluída quando existir implementação e evidência de teste/build. Um provider mock não é um modelo de IA treinado; um seed não é inventário real; uma reconciliação local não equivale a integração com um sistema externo.
