# VANIA: Monitor de Providências Pós-Parecer

Controle da execução de pareceres de passivo fiscal federal (PGFN, RFB, Simples Nacional):
tarefas, prazos em dias úteis, conferência de comprovantes, semáforo de risco e roteiros de portal.

- Instruções de operação: [`CLAUDE.md`](CLAUDE.md)
- Skill: [`.claude/skills/acompanhamento-providencias-fiscais/SKILL.md`](.claude/skills/acompanhamento-providencias-fiscais/SKILL.md)
- Normas de base e calendário normativo: [`base/`](base/)
- Motor: [`monitor/`](monitor/) (Python 3 + PyYAML)
- Modelo de ficha: [`clientes/_MODELO/ficha.yaml`](clientes/_MODELO/ficha.yaml)

Dados de cliente não são versionados enquanto o repositório for público (ver `.gitignore`).
