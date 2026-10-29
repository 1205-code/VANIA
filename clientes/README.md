# Clientes

Uma pasta por cliente: `clientes/<slug>/`, criada com `python3 monitor/monitor.py novo <slug>`.

```
clientes/<slug>/
  ficha.yaml      fonte da verdade (editar aqui)
  documentos/     parecer, comprovantes, relatórios, prints (AAAA-MM-DD_CLIENTE_TIPO.pdf)
  fichas/         Fichas de Controle geradas (AAAA-MM-DD_CLIENTE_Controle-Providencias.md)
```

**Sigilo:** enquanto o repositório for público, estas pastas ficam fora do git (ver `.gitignore`)
e se perdem quando a sessão na nuvem é encerrada. Para persistir o histórico, torne o repositório
privado e remova o bloqueio no `.gitignore`.
