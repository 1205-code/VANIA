#!/usr/bin/env python3
"""Monitor de providências pós-parecer.

Fonte da verdade: clientes/<slug>/ficha.yaml. Este script NÃO altera a ficha;
ele calcula prazos, status derivados, conferência de pagamentos e semáforo, e
gera a Ficha de Controle em Markdown no formato da skill.

Uso:
  python3 monitor/monitor.py painel [--hoje AAAA-MM-DD]
  python3 monitor/monitor.py ficha <slug> [--hoje AAAA-MM-DD] [--salvar]
  python3 monitor/monitor.py lembretes <slug> [--hoje AAAA-MM-DD]
  python3 monitor/monitor.py novo <slug>
"""
import argparse
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dias_uteis import eh_util, somar_uteis, uteis_entre  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
CLIENTES = RAIZ / "clientes"
MODELO = CLIENTES / "_MODELO"
CALENDARIO = RAIZ / "base" / "calendario_normativo.yaml"

STATUS = {"PENDENTE", "EM ANDAMENTO", "INFORMADO SEM PROVA", "CONCLUÍDO",
          "ATRASADO", "BLOQUEADO", "CANCELADO"}
FECHADOS = {"CONCLUÍDO", "CANCELADO"}
RESPONSAVEIS = {"ESCRITÓRIO", "CLIENTE", "CONTABILIDADE"}
# Origem válida da guia por órgão do acordo (skill, regras 4 e Conferência)
ORIGEM_VALIDA = {
    "PGFN": {"REGULARIZE"},
    "RFB": {"E-CAC", "PORTAL DE SERVIÇOS"},
    "SIMPLES": {"PORTAL DO SIMPLES"},
}
COMPROVANTES_INVALIDOS = {"AGENDAMENTO", "EM PROCESSAMENTO", "BOLETO SEM AUTENTICAÇÃO", "PRINT SEM AUTENTICAÇÃO"}
ALERTAS_VERMELHOS = {"NOTIFICAÇÃO DE RESCISÃO", "EXCLUSÃO", "BLOQUEIO JUDICIAL", "INTIMAÇÃO", "TERMO DE EXCLUSÃO DO SIMPLES"}
ORDEM_SEMAFORO = {"VERDE": 0, "AMARELO": 1, "VERMELHO": 2}


# ---------------------------------------------------------------- utilidades
def _data(v):
    if v in (None, ""):
        return None
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v))


def _dinheiro(v):
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v).replace("R$", "").replace(" ", ""))
    except InvalidOperation:
        raise ValueError(f"valor monetário inválido: {v!r} (use ponto decimal, ex.: \"1234.56\")")


def _br(d):
    return d.strftime("%d/%m/%Y") if d else "-"


def _reais(v):
    if v is None:
        return "-"
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def _digitos(s):
    return re.sub(r"\D", "", str(s or ""))


def _norm(s):
    return str(s or "").strip().upper().replace("ESCRITORIO", "ESCRITÓRIO").replace("CONCLUIDO", "CONCLUÍDO")


def _cel(v):
    return str(v if v not in (None, "") else "-").replace("|", "/").replace("\n", " ")


# ---------------------------------------------------------------- análise
@dataclass
class Analise:
    ficha: dict
    hoje: date
    tarefas: list = field(default_factory=list)
    pagamentos: list = field(default_factory=list)
    vermelhos: list = field(default_factory=list)
    amarelos: list = field(default_factory=list)
    erros: list = field(default_factory=list)

    @property
    def semaforo(self):
        if self.vermelhos:
            return "VERMELHO"
        if self.amarelos:
            return "AMARELO"
        return "VERDE"

    @property
    def proximo_fatal(self):
        abertas = [t for t in self.tarefas if t["status_efetivo"] not in FECHADOS and t["fatal"]]
        return min(abertas, key=lambda t: t["fatal"], default=None)


def carregar(slug):
    p = CLIENTES / slug / "ficha.yaml"
    if not p.exists():
        raise SystemExit(f"Ficha não encontrada: {p}")
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def analisar(ficha, hoje):
    a = Analise(ficha=ficha, hoje=hoje)
    cli = ficha.get("cliente") or {}
    locais = [_data(x) for x in ficha.get("feriados_locais") or []]

    for campo in ("razao_social", "cnpj"):
        if not cli.get(campo):
            a.erros.append(f"cliente.{campo} não preenchido")

    # --- tarefas
    brutas = ficha.get("tarefas") or []
    ids = [t.get("id") for t in brutas]
    for dup in {i for i in ids if ids.count(i) > 1}:
        a.erros.append(f"ID de tarefa duplicado: {dup}")

    for t in brutas:
        tid = t.get("id", "?")
        st = _norm(t.get("status") or "PENDENTE")
        resp = _norm(t.get("responsavel"))
        if st not in STATUS:
            a.erros.append(f"{tid}: status inválido {t.get('status')!r}")
        if resp not in RESPONSAVEIS:
            a.erros.append(f"{tid}: responsável deve ser um só entre {sorted(RESPONSAVEIS)} (recebido {t.get('responsavel')!r})")
        fatal = _data(t.get("prazo_fatal"))
        interno = _data(t.get("prazo_interno"))
        if fatal and not interno:
            interno = somar_uteis(fatal, -5, locais)
        if fatal and t.get("tipo") == "pagamento" and interno and interno >= fatal:
            a.erros.append(f"{tid}: pagamento com prazo interno no prazo fatal; regra é nunca pagar no último dia útil")
        if fatal and not eh_util(fatal, locais):
            a.amarelos.append(f"{tid}: prazo fatal {_br(fatal)} cai em dia não útil; conferir a regra de prorrogação na norma (pagamento: antecipar)")

        ev = t.get("evidencia_recebida") or {}
        efetivo = st
        if st == "CONCLUÍDO" and not (ev.get("arquivo") and ev.get("data")):
            efetivo = "INFORMADO SEM PROVA"
            a.erros.append(f"{tid}: marcado CONCLUÍDO sem evidência datada (arquivo + data); tratado como INFORMADO SEM PROVA")
        if efetivo not in FECHADOS:
            deps = [d for d in (t.get("depende_de") or [])]
            pend = [d for d in deps if _norm(next((x.get("status") for x in brutas if x.get("id") == d), "PENDENTE")) not in FECHADOS]
            for d in deps:
                if d not in ids:
                    a.erros.append(f"{tid}: depende de {d}, que não existe")
            if fatal and fatal < hoje:
                efetivo = "ATRASADO"
            elif pend and efetivo == "PENDENTE":
                efetivo = "BLOQUEADO"
        a.tarefas.append({**t, "id": tid, "responsavel": resp, "fatal": fatal, "interno": interno,
                          "status_efetivo": efetivo, "status_informado": st, "evidencia": ev})

        if efetivo in FECHADOS:
            continue
        if fatal:
            uteis = uteis_entre(hoje, fatal, locais)
            if uteis <= 5:
                quando = f"vencido há {-uteis} dia(s) útil(eis)" if uteis < 0 else (
                    "vence HOJE" if uteis == 0 else f"vence em {uteis} dia(s) útil(eis)")
                a.vermelhos.append(f"{tid} {t.get('providencia')}: prazo fatal {_br(fatal)} ({quando}) sem evidência")
            elif (fatal - hoje).days <= 15:
                a.amarelos.append(f"{tid} {t.get('providencia')}: prazo fatal {_br(fatal)} em {(fatal - hoje).days} dias")
            if interno and interno < hoje and fatal >= hoje:
                a.amarelos.append(f"{tid}: prazo interno {_br(interno)} já passou")
        if efetivo == "INFORMADO SEM PROVA":
            a.amarelos.append(f"{tid}: informado sem prova; pedir documento ({t.get('evidencia_exigida') or 'evidência'})")
        if t.get("nao_retorno") and efetivo not in FECHADOS:
            a.amarelos.append(f"{tid}: PONTO DE NÃO RETORNO pendente; exige PARE e confirmação expressa do advogado")

    # --- acordos
    acordos = {str(x.get("numero")): x for x in ficha.get("acordos") or []}
    for num, ac in acordos.items():
        org = _norm(ac.get("orgao"))
        if org not in ORIGEM_VALIDA:
            a.erros.append(f"acordo {num}: órgão deve ser PGFN, RFB ou SIMPLES")
        atras = int(ac.get("atrasadas") or 0)
        if atras:
            a.vermelhos.append(f"acordo {num} ({org}): {atras} prestação(ões) em atraso. Emitir guia nova HOJE; não deixar chegar à 3ª")
        pv = _data(ac.get("proximo_vencimento"))
        if pv and pv < hoje:
            a.vermelhos.append(f"acordo {num}: próximo vencimento {_br(pv)} já passou e a ficha não foi atualizada; conferir no sistema (R11/R4/R5)")
        elif pv and (pv - hoje).days <= 15:
            a.amarelos.append(f"acordo {num}: prestação vence em {_br(pv)}; guia enviada ao cliente?")
        sit = _norm(ac.get("situacao") or "ATIVO")
        if sit not in {"ATIVO", "QUITADO"}:
            a.vermelhos.append(f"acordo {num}: situação {sit}")

    # --- pagamentos
    cnpj = _digitos(cli.get("cnpj"))
    for p in ficha.get("pagamentos") or []:
        motivos, pend = [], []
        ac = acordos.get(str(p.get("acordo")))
        org = _norm(ac.get("orgao")) if ac else None
        origem = _norm(p.get("origem_guia"))
        if not ac:
            motivos.append(f"acordo {p.get('acordo')!r} não cadastrado")
        elif origem not in ORIGEM_VALIDA.get(org, set()):
            motivos.append(f"origem da guia {origem or '?'} inválida para {org} (exigido: {', '.join(sorted(ORIGEM_VALIDA[org]))})")
        if _digitos(p.get("cnpj_pagador")) != cnpj:
            motivos.append(f"CNPJ do comprovante ({p.get('cnpj_pagador') or 'não informado'}) diverge do cliente")
        try:
            vg, vp = _dinheiro(p.get("valor_guia")), _dinheiro(p.get("valor_pago"))
        except ValueError as e:
            vg = vp = None
            motivos.append(str(e))
        if vg is None or vp is None:
            motivos.append("valor da guia ou valor pago ausente")
        elif vp < vg:
            motivos.append(f"pago a menor ({_reais(vp)} < {_reais(vg)}): prestação paga a menor é prestação não paga")
        elif vp > vg:
            motivos.append(f"pago a maior ({_reais(vp)} > {_reais(vg)}): excedente vai para as seguintes; levar ao advogado")
        dp, venc = _data(p.get("data_pagamento")), _data(p.get("vencimento"))
        if not dp or not venc:
            motivos.append("data do pagamento ou vencimento da guia ausente")
        elif dp > venc:
            motivos.append(f"pago em {_br(dp)}, após o 'pagar até' {_br(venc)}")
        tipo = _norm(p.get("tipo_comprovante"))
        if tipo in COMPROVANTES_INVALIDOS or not p.get("autenticacao"):
            motivos.append("sem autenticação bancária definitiva (agendamento/processamento não comprova)")
        if not motivos and not p.get("baixa_no_sistema"):
            dias = uteis_entre(dp, hoje, locais)
            if dias > 10:
                motivos.append(f"sem baixa no sistema {dias} dias úteis após o pagamento: divergência, verificar no portal")
            else:
                pend.append("aguardando baixa no sistema; pedir print do SISPAR/parcelamento na próxima sessão")
        resultado = "REPROVADO: " + "; ".join(motivos) if motivos else ("APROVADO, sem baixa" if pend else "APROVADO")
        a.pagamentos.append({**p, "_vg": vg, "_vp": vp, "_dp": dp, "_venc": venc, "_res": resultado})
        ref = f"pagamento {p.get('referencia') or p.get('guia')}"
        if motivos:
            (a.vermelhos if venc and venc <= hoje else a.amarelos).append(f"{ref}: {resultado}")
        elif pend:
            a.amarelos.append(f"{ref}: {pend[0]}")

    # --- alertas avulsos (notificações, bloqueios)
    for al in ficha.get("alertas") or []:
        if al.get("resolvido"):
            continue
        tipo = _norm(al.get("tipo"))
        msg = f"{tipo}: {al.get('descricao', '')} (ciência {_br(_data(al.get('data_ciencia')))}, prazo {_br(_data(al.get('prazo_fatal')))})"
        (a.vermelhos if tipo in ALERTAS_VERMELHOS else a.amarelos).append(msg)

    # --- acessos e obrigações permanentes
    ac = ficha.get("acessos") or {}
    proc = _data(ac.get("procuracao_ecac_ate"))
    if not proc:
        a.amarelos.append("procuração e-CAC: vigência não informada (pergunta de abertura 1)")
    elif proc < hoje:
        a.vermelhos.append(f"procuração e-CAC vencida em {_br(proc)}: escritório sem acesso (R1b)")
    elif (proc - hoje).days <= 30:
        a.amarelos.append(f"procuração e-CAC vence em {_br(proc)}: pedir renovação (R1b)")
    if not ac.get("email_regularize"):
        a.amarelos.append("e-mail do Regularize não conferido: a notificação de rescisão vai só para ele (Edital PGDAU 6/2026, art. 22, § 1º)")
    if not any(t.get("permanente") for t in brutas):
        a.erros.append("faltam as obrigações permanentes (correntes em 90 dias, FGTS, e-mail Regularize, Caixa Postal); copiar do _MODELO")

    return a


# ---------------------------------------------------------------- saída
def render_ficha(a: Analise) -> str:
    f, cli, ac = a.ficha, a.ficha.get("cliente") or {}, a.ficha.get("acessos") or {}
    cont = ac.get("contador") or {}
    prox = a.proximo_fatal
    motivo = (a.vermelhos or a.amarelos or ["sem pendência crítica"])[0]
    L = [
        f"# CONTROLE DE PROVIDÊNCIAS: {cli.get('razao_social', '?')} (CNPJ {cli.get('cnpj', '?')})",
        f"Parecer de referência: {_br(_data(cli.get('parecer_data')))} | Advogado responsável: {cli.get('advogado') or '-'} | Última atualização: {a.hoje.isoformat()}",
        f"Acessos: procuração e-CAC vigente até {_br(_data(ac.get('procuracao_ecac_ate')))} | e-mail Regularize: {ac.get('email_regularize') or 'NÃO CONFERIDO'} | Contador: {cont.get('nome') or '-'}, {cont.get('contato') or '-'}",
        "",
        "## Painel",
        f"Semáforo geral: {a.semaforo}  Motivo: {motivo}",
        f"Próximo prazo fatal: {_br(prox['fatal']) + ' ' + prox['id'] + ' ' + str(prox.get('providencia')) if prox else '-'}",
        "",
    ]
    if a.vermelhos or a.amarelos:
        L.append("### Alertas")
        L += [f"- VERMELHO: {x}" for x in a.vermelhos] + [f"- AMARELO: {x}" for x in a.amarelos]
        L.append("")
    if a.erros:
        L.append("### Inconsistências da ficha (corrigir no ficha.yaml)")
        L += [f"- {x}" for x in a.erros]
        L.append("")
    L += ["## Tarefas",
          "| ID | Providência | Resp. | Portal/Local | Prazo interno | Prazo fatal | Depende de | Não retorno? | Evidência exigida | Status | Evidência recebida | Fundamento |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for t in sorted(a.tarefas, key=lambda t: (t["status_efetivo"] in FECHADOS, t["fatal"] or date.max)):
        st = t["status_efetivo"] + (f" (informado: {t['status_informado']})" if t["status_efetivo"] != t["status_informado"] else "")
        ev = t["evidencia"]
        evs = f"{ev.get('arquivo')} ({_br(_data(ev.get('data')))})" if ev.get("arquivo") else "-"
        L.append("| " + " | ".join(_cel(x) for x in [
            t["id"], t.get("providencia"), t["responsavel"], t.get("portal"), _br(t["interno"]), _br(t["fatal"]),
            ", ".join(t.get("depende_de") or []) or "-", "SIM" if t.get("nao_retorno") else "não",
            t.get("evidencia_exigida"), st, evs, t.get("fundamento")]) + " |")
    L += ["", "## Acordos e parcelamentos ativos",
          "| Acordo/Nº | Órgão | Modalidade | Data adesão | Nº prestações | Pagas | Em aberto | Atrasadas | Próx. vencimento | Valor da guia (fonte) |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for x in f.get("acordos") or []:
        L.append("| " + " | ".join(_cel(v) for v in [
            x.get("numero"), x.get("orgao"), x.get("modalidade"), _br(_data(x.get("data_adesao"))), x.get("n_prestacoes"),
            x.get("pagas"), x.get("em_aberto"), x.get("atrasadas"), _br(_data(x.get("proximo_vencimento"))),
            f"{_reais(_dinheiro(x.get('valor_guia')))} ({x.get('fonte_valor') or 'SEM FONTE'})" if x.get("valor_guia") else "-"]) + " |")
    L += ["", "## Pagamentos conferidos",
          "| Data pgto | Guia (nº documento) | Referência (prestação) | Valor guia | Valor pago | Vencimento | Origem da guia | Resultado da conferência | Baixa no sistema? |",
          "|---|---|---|---|---|---|---|---|---|"]
    for p in a.pagamentos:
        L.append("| " + " | ".join(_cel(v) for v in [
            _br(p["_dp"]), p.get("guia"), p.get("referencia"), _reais(p["_vg"]), _reais(p["_vp"]), _br(p["_venc"]),
            p.get("origem_guia"), p["_res"], "sim" if p.get("baixa_no_sistema") else "não"]) + " |")
    L += ["", "## Histórico"]
    L += [f"- {_data(h.get('data')).isoformat()}: {h.get('evento')}" for h in sorted(f.get("historico") or [], key=lambda h: _data(h.get("data")))]
    return "\n".join(L) + "\n"


def calendario_proximo(hoje, dias=45):
    if not CALENDARIO.exists():
        return [], None
    c = yaml.safe_load(CALENDARIO.read_text(encoding="utf-8"))
    out = []
    for e in c.get("eventos") or []:
        ini, fim = _data(e["data"]), _data(e.get("ate")) or _data(e["data"])
        if fim >= hoje and ini <= hoje + timedelta(days=dias):
            out.append((ini, e))
    return sorted(out, key=lambda x: x[0]), _data(c.get("conferido_em"))


def slugs():
    return sorted(p.name for p in CLIENTES.iterdir() if p.is_dir() and not p.name.startswith("_") and (p / "ficha.yaml").exists())


def cmd_painel(hoje):
    print(f"# PAINEL DE PROVIDÊNCIAS em {_br(hoje)}\n")
    linhas = []
    for s in slugs():
        a = analisar(carregar(s), hoje)
        linhas.append((ORDEM_SEMAFORO[a.semaforo], a, s))
    if not linhas:
        print("Nenhum cliente cadastrado. Use: python3 monitor/monitor.py novo <slug>\n")
    else:
        print("| Semáforo | Cliente | Próximo prazo fatal | Motivo principal | Inconsistências |\n|---|---|---|---|---|")
        for _, a, s in sorted(linhas, key=lambda x: (-x[0], (x[1].proximo_fatal or {}).get("fatal") or date.max)):
            p = a.proximo_fatal
            print(f"| {a.semaforo} | {s} | {_br(p['fatal']) + ' ' + p['id'] if p else '-'} | "
                  f"{_cel((a.vermelhos or a.amarelos or ['-'])[0])} | {len(a.erros)} |")
        print()
    ev, conf = calendario_proximo(hoje)
    print(f"## Calendário normativo (próximos 45 dias; conferido em {_br(conf)})")
    if conf and (hoje - conf).days > 7:
        print(f"ATENÇÃO: calendário conferido há {(hoje - conf).days} dias. Reconferir prorrogações antes de usar.")
    for d, e in ev:
        print(f"- {_br(d)}{' a ' + _br(_data(e['ate'])) if e.get('ate') else ''}{' ' + e['hora'] if e.get('hora') else ''}: {e['evento']} ({e['fonte']})")


def cmd_ficha(slug, hoje, salvar):
    a = analisar(carregar(slug), hoje)
    md = render_ficha(a)
    if salvar:
        destino = CLIENTES / slug / "fichas"
        destino.mkdir(exist_ok=True)
        arq = destino / f"{hoje.isoformat()}_{slug.upper()}_Controle-Providencias.md"
        arq.write_text(md, encoding="utf-8")
        print(f"Ficha salva em {arq.relative_to(RAIZ)}", file=sys.stderr)
    print(md)
    return 1 if a.erros else 0


def cmd_lembretes(slug, hoje):
    ficha = carregar(slug)
    locais = [_data(x) for x in ficha.get("feriados_locais") or []]
    print(f"Lembretes sugeridos (D-5 úteis do prazo fatal) para {slug}. Criar só com aceite do advogado.")
    for t in analisar(ficha, hoje).tarefas:
        if t["status_efetivo"] in FECHADOS or not t["fatal"]:
            continue
        d5 = somar_uteis(t["fatal"], -5, locais)
        marca = " (já passou: avisar hoje)" if d5 < hoje else ""
        print(f"- {_br(d5)}{marca}: {t['id']} {t.get('providencia')} | fatal {_br(t['fatal'])} | {t['responsavel']}")


def cmd_novo(slug):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug):
        raise SystemExit("slug: só minúsculas, números e hífen (ex.: metalurgica-silva)")
    dest = CLIENTES / slug
    if dest.exists():
        raise SystemExit(f"{dest} já existe")
    shutil.copytree(MODELO, dest)
    print(f"Criado {dest.relative_to(RAIZ)}. Preencha ficha.yaml a partir do parecer e rode: python3 monitor/monitor.py ficha {slug}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("comando", choices=["painel", "ficha", "lembretes", "novo"])
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--hoje", type=date.fromisoformat, default=date.today())
    ap.add_argument("--salvar", action="store_true")
    a = ap.parse_args(argv)
    if a.comando != "painel" and not a.slug:
        ap.error("informe o slug do cliente")
    if a.comando == "painel":
        cmd_painel(a.hoje)
    elif a.comando == "ficha":
        return cmd_ficha(a.slug, a.hoje, a.salvar)
    elif a.comando == "lembretes":
        cmd_lembretes(a.slug, a.hoje)
    else:
        cmd_novo(a.slug)
    return 0


if __name__ == "__main__":
    sys.exit(main())
