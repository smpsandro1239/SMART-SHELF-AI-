# Segurança e privacidade

## Princípios

O produto deve ser orientado a produtos e prateleiras, não a pessoas. Privacidade e segurança devem ser requisitos de arquitetura desde o início.

## Restrições de conceção

- Não implementar reconhecimento facial.
- Não recolher áudio.
- Não identificar clientes.
- Não criar métricas individuais de produtividade de trabalhadores.
- Evitar captar pessoas; aplicar máscaras/zonas de exclusão quando tecnicamente possível.
- Preferir processamento local e transmissão de eventos/metadados em vez de vídeo contínuo.
- Definir retenção limitada e eliminação verificável.
- Restringir acesso por função, loja e necessidade operacional.

## Avaliação antes do piloto

A utilização de videovigilância existente para uma finalidade adicional exige análise jurídica e de privacidade própria. Avaliar RGPD, Lei n.º 58/2019, regras laborais aplicáveis, necessidade de AIPD/DPIA, sinalização, fundamento jurídico, transparência, contratos e responsabilidades entre entidades. Obter validação dos responsáveis de proteção de dados e assessoria jurídica antes de ativar câmaras.

## Segurança técnica

- TLS em trânsito e encriptação em repouso quando aplicável.
- Segredos fora do Git.
- Autenticação forte e autorização por função.
- Auditoria de operações sensíveis.
- Atualizações e inventário de dispositivos.
- Validação de payloads e limites de upload.
- Backups testados e política de recuperação.
- Dependências e licenças verificadas.

Este documento é uma orientação técnica inicial, não um parecer jurídico.
