# Stack de skills de engenharia — SMART SHELF AI

| Skill | Repositório | Commit fixado | Licença | Função |
|---|---|---|---|---|
| Superpowers | https://github.com/obra/superpowers | `22f0b463e7a5e579904dd6211a520321035526f7` | MIT | Processo de engenharia, TDD, debugging, planeamento e revisão |
| Impeccable | https://github.com/pbakaus/impeccable | `b49177d32788f2dc585c42831d845dacf1ebed2c` | Apache-2.0 | Auditoria e qualidade UX/UI |
| Frontend Design | https://github.com/Ilm-Alan/frontend-design | `f8966e6cc9b90247aa102d71f7e675ec3462b419` | MIT | Direcção visual e composição de novas interfaces |

Todos são submódulos Git em `vendor/`; não são dependências runtime. As licenças e fontes upstream permanecem intactas.

## Inicialização
```bash
git submodule update --init --recursive
```

## Processo
1. Ler contexto e roadmap.
2. Brainstorming apenas quando a intenção/decisão está em aberto.
3. Plano para trabalho multi-etapa.
4. TDD: teste falha, alteração mínima, teste passa.
5. Revisão contra plano, contratos, segurança e efeitos laterais.
6. Verificação fresca dos testes e workflows do SHA exacto.
7. Actualizar documentação/backlog.

## Compatibilidade
Superpowers documenta integração nativa Codex via marketplace; o submódulo torna as fontes versionadas/reproduzíveis, mas não instala plugin global. Worktrees e subagentes só podem ser usados quando o runtime os disponibiliza. Não simular delegação.

## Frontend
Impeccable é a referência principal para critique/audit/polish do sistema actual. Frontend Design complementa em novas superfícies ou redesigns deliberados; as oito âncoras não substituem automaticamente os tokens actuais em `DESIGN.md`.
