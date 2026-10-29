"""Testes do motor. Rodar: python3 -m unittest discover -s monitor"""
import copy
import unittest
from datetime import date
from pathlib import Path

import yaml

import monitor as m
from dias_uteis import pascoa, somar_uteis, ultimo_util_do_mes, uteis_entre

HOJE = date(2026, 10, 29)

BASE = {
    "cliente": {"razao_social": "Exemplo Ltda", "cnpj": "11.222.333/0001-81"},
    "acessos": {"procuracao_ecac_ate": "2027-06-30", "email_regularize": "fiscal@exemplo.com"},
    "tarefas": [
        {"id": "P01", "providencia": "Correntes 90 dias", "responsavel": "CONTABILIDADE", "permanente": True, "status": "EM ANDAMENTO"},
    ],
    "acordos": [{"numero": "123", "orgao": "PGFN", "atrasadas": 0, "proximo_vencimento": "2026-11-30"}],
}


def f(**extra):
    d = copy.deepcopy(BASE)
    for k, v in extra.items():
        d[k] = d.get(k, []) + v if isinstance(v, list) else v
    return d


def pg(**k):
    p = {"acordo": "123", "referencia": "01", "origem_guia": "REGULARIZE", "cnpj_pagador": "11222333000181",
         "valor_guia": "1000.00", "valor_pago": "1000.00", "vencimento": "2026-10-30",
         "data_pagamento": "2026-10-28", "autenticacao": True, "baixa_no_sistema": True}
    p.update(k)
    return p


class DiasUteis(unittest.TestCase):
    def test_pascoa(self):
        self.assertEqual(pascoa(2026), date(2026, 4, 5))
        self.assertEqual(pascoa(2027), date(2027, 3, 28))

    def test_ultimos_uteis(self):
        self.assertEqual(ultimo_util_do_mes(2026, 10), date(2026, 10, 30))
        self.assertEqual(ultimo_util_do_mes(2026, 11), date(2026, 11, 30))
        self.assertEqual(ultimo_util_do_mes(2026, 12), date(2026, 12, 30))  # 31/12 sem expediente
        self.assertEqual(ultimo_util_do_mes(2027, 1), date(2027, 1, 29))

    def test_finados_e_consciencia_negra(self):
        # 30/10 (sex) + 1 útil pula fim de semana e Finados (seg 02/11)
        self.assertEqual(somar_uteis(date(2026, 10, 30), 1), date(2026, 11, 3))
        self.assertEqual(somar_uteis(date(2026, 11, 19), 1), date(2026, 11, 23))
        self.assertEqual(uteis_entre(date(2026, 10, 29), date(2026, 11, 5)), 4)
        self.assertEqual(uteis_entre(date(2026, 11, 5), date(2026, 10, 29)), -4)

    def test_feriado_local(self):
        self.assertEqual(somar_uteis(date(2026, 12, 7), 1, [date(2026, 12, 8)]), date(2026, 12, 9))


class Tarefas(unittest.TestCase):
    def test_concluido_sem_prova_rebaixa(self):
        a = m.analisar(f(tarefas=[{"id": "T1", "providencia": "x", "responsavel": "CLIENTE", "status": "CONCLUÍDO"}]), HOJE)
        t = next(t for t in a.tarefas if t["id"] == "T1")
        self.assertEqual(t["status_efetivo"], "INFORMADO SEM PROVA")
        self.assertTrue(a.erros)

    def test_prazo_interno_5_uteis(self):
        a = m.analisar(f(tarefas=[{"id": "T1", "providencia": "x", "responsavel": "CLIENTE", "prazo_fatal": "2026-11-30"}]), HOJE)
        self.assertEqual(next(t for t in a.tarefas if t["id"] == "T1")["interno"], date(2026, 11, 23))

    def test_vermelho_ate_5_uteis_e_atrasado(self):
        a = m.analisar(f(tarefas=[{"id": "T1", "providencia": "entrada", "responsavel": "CLIENTE", "prazo_fatal": "2026-10-30"},
                                  {"id": "T2", "providencia": "velha", "responsavel": "CLIENTE", "prazo_fatal": "2026-10-20"}]), HOJE)
        self.assertEqual(a.semaforo, "VERMELHO")
        self.assertEqual(next(t for t in a.tarefas if t["id"] == "T2")["status_efetivo"], "ATRASADO")

    def test_bloqueado_por_dependencia(self):
        a = m.analisar(f(tarefas=[{"id": "T1", "providencia": "a", "responsavel": "ESCRITÓRIO", "prazo_fatal": "2027-01-29"},
                                  {"id": "T2", "providencia": "b", "responsavel": "ESCRITÓRIO", "prazo_fatal": "2027-01-29", "depende_de": ["T1"]}]), HOJE)
        self.assertEqual(next(t for t in a.tarefas if t["id"] == "T2")["status_efetivo"], "BLOQUEADO")

    def test_dois_responsaveis_e_erro(self):
        a = m.analisar(f(tarefas=[{"id": "T1", "providencia": "a", "responsavel": "CLIENTE/CONTABILIDADE"}]), HOJE)
        self.assertTrue(any("responsável" in e for e in a.erros))


class Pagamentos(unittest.TestCase):
    def res(self, **k):
        return m.analisar(f(pagamentos=[pg(**k)]), HOJE).pagamentos[0]["_res"]

    def test_aprovado(self):
        self.assertEqual(self.res(), "APROVADO")

    def test_centavo_a_menor(self):
        self.assertIn("pago a menor", self.res(valor_pago="999.99"))

    def test_darf_sicalc_em_transacao_pgfn(self):
        self.assertIn("origem da guia", self.res(origem_guia="SICALC"))

    def test_agendamento(self):
        self.assertIn("autenticação", self.res(tipo_comprovante="AGENDAMENTO"))

    def test_apos_vencimento(self):
        self.assertIn("após", self.res(data_pagamento="2026-10-31"))

    def test_cnpj_divergente(self):
        self.assertIn("CNPJ", self.res(cnpj_pagador="99.999.999/0001-99"))

    def test_sem_baixa_apos_duas_semanas(self):
        self.assertIn("sem baixa", self.res(data_pagamento="2026-10-01", vencimento="2026-10-30", baixa_no_sistema=False))


class Acordos(unittest.TestCase):
    def test_uma_atrasada_e_vermelho(self):
        d = f()
        d["acordos"][0]["atrasadas"] = 1
        self.assertEqual(m.analisar(d, HOJE).semaforo, "VERMELHO")

    def test_modelo_valido(self):
        d = yaml.safe_load((Path(m.MODELO) / "ficha.yaml").read_text(encoding="utf-8"))
        a = m.analisar(d, HOJE)
        self.assertEqual({e for e in a.erros if "permanentes" in e}, set())
        m.render_ficha(a)


if __name__ == "__main__":
    unittest.main()
