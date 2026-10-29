# Monitor de Providências Pós-Parecer

Este repositório executa a skill `acompanhamento-providencias-fiscais`
(`.claude/skills/acompanhamento-providencias-fiscais/SKILL.md`). Ela vale integralmente,
inclusive as 10 regras invioláveis. Este arquivo só define ONDE fica o estado e QUEM calcula.

## Divisão de trabalho

- **Claude**: lê parecer e documentos, classifica, confere o conteúdo, extrai os dados para a
  ficha, escreve Boletim, roteiros de tela e mensagens.
- **Motor (`monitor/monitor.py`)**: dias úteis, prazo interno (fatal menos 5 dias úteis),
  ATRASADO e BLOQUEADO, conferência numérica de pagamento (valor centavo a centavo, data,
  origem da guia, CNPJ, autenticação, baixa), semáforo. Nunca calcular isso de cabeça; se o
  motor e o raciocínio divergirem, investigar antes de entregar.
- **Advogado**: clica, assina, confirma. Pontos de não retorno só com "confirmo" escrito.

## Estado

- Fonte da verdade: `clientes/<slug>/ficha.yaml`. A Ficha em Markdown é gerada, nunca editada à mão.
- Documentos recebidos: salvar em `clientes/<slug>/documentos/` com o padrão
  `AAAA-MM-DD_CLIENTE_TIPO.pdf` e registrar na ficha (`evidencia_recebida`, `pagamentos`, `historico`).
- Calendário normativo: `base/calendario_normativo.yaml`. Reconferir prorrogações e atualizar
  `conferido_em` antes de usar uma data (regra 8). O painel avisa se a conferência tem mais de 7 dias.
- Normas de base: `base/`. Norma prevalece sobre o Manual Técnico.

## Comandos

```bash
python3 monitor/monitor.py painel                  # todos os clientes + calendário dos próximos 45 dias
python3 monitor/monitor.py novo <slug>             # Fase 0: cria a pasta a partir de clientes/_MODELO
python3 monitor/monitor.py ficha <slug> --salvar   # gera a Ficha; código 1 se houver inconsistência
python3 monitor/monitor.py lembretes <slug>        # datas D-5 úteis para tarefas agendadas
python3 -m unittest discover -s monitor            # testes do motor
```

## Roteiro por sessão

1. **Cliente novo (Fase 0):** `novo <slug>`; ler o parecer; desdobrar cada recomendação em tarefas
   atômicas no `ficha.yaml` (um responsável, um portal, um prazo); manter as obrigações permanentes
   P01 a P04; fazer as 5 perguntas de abertura num bloco só; rodar `ficha --salvar`; entregar Ficha e
   mensagens de alinhamento; oferecer lembretes (`lembretes`) e só criar com aceite.
2. **Documento ou pergunta (Fase 1):** triagem, conferência pelo checklist da skill, atualizar
   `ficha.yaml` + `historico`, rodar `ficha --salvar`, entregar o Boletim no formato da skill com a
   Ficha gerada.
3. **Início do mês (Fase 2):** `painel`, depois a rotina mensal da skill para cada cliente.

Inconsistência apontada pelo motor (exit 1) se corrige no `ficha.yaml` antes de entregar o Boletim.

## Sigilo

O repositório é público. `clientes/*` está no `.gitignore`: nunca commitar dado de cliente,
nunca usar `git add -f` em `clientes/`. Nunca pedir senha, PIN de certificado ou código de autenticação.
