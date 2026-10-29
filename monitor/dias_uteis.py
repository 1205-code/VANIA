"""Calendário de dias úteis para prazos fiscais e pagamentos bancários.

Critério CONSERVADOR: além dos feriados nacionais, trata como não úteis os
dias sem expediente bancário ao público (segunda e terça de Carnaval, Quarta de
Cinzas até o meio-dia, Corpus Christi, 24/12 e 31/12). Considerar não útil um dia
que na verdade é útil só antecipa o prazo; o contrário pode perder o prazo.
Feriados estaduais e municipais do cliente entram por `feriados_locais` na ficha.
"""
from datetime import date, timedelta
from functools import lru_cache


def pascoa(ano: int) -> date:
    # Algoritmo de Meeus/Jones/Butcher (calendário gregoriano)
    a = ano % 19
    b, c = divmod(ano, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = ((h + l - 7 * m + 114) % 31) + 1
    return date(ano, mes, dia)


@lru_cache(maxsize=None)
def feriados(ano: int) -> dict:
    p = pascoa(ano)
    return {
        date(ano, 1, 1): "Confraternização Universal",
        p - timedelta(days=48): "Carnaval (segunda, sem expediente bancário)",
        p - timedelta(days=47): "Carnaval (terça, sem expediente bancário)",
        p - timedelta(days=46): "Quarta-feira de Cinzas (expediente parcial)",
        p - timedelta(days=2): "Paixão de Cristo",
        date(ano, 4, 21): "Tiradentes",
        date(ano, 5, 1): "Dia do Trabalho",
        p + timedelta(days=60): "Corpus Christi (ponto facultativo)",
        date(ano, 9, 7): "Independência",
        date(ano, 10, 12): "Nossa Senhora Aparecida",
        date(ano, 11, 2): "Finados",
        date(ano, 11, 15): "Proclamação da República",
        date(ano, 11, 20): "Consciência Negra (Lei 14.759/2023)",
        date(ano, 12, 24): "Véspera de Natal (sem expediente bancário relevante)",
        date(ano, 12, 25): "Natal",
        date(ano, 12, 31): "Sem expediente bancário ao público",
    }


def eh_util(d: date, locais=()) -> bool:
    return d.weekday() < 5 and d not in feriados(d.year) and d not in set(locais)


def somar_uteis(d: date, n: int, locais=()) -> date:
    """Anda n dias úteis a partir de d (n negativo volta). O dia d não conta."""
    passo = 1 if n >= 0 else -1
    restantes = abs(n)
    while restantes:
        d += timedelta(days=passo)
        if eh_util(d, locais):
            restantes -= 1
    return d


def uteis_entre(inicio: date, fim: date, locais=()) -> int:
    """Dias úteis em (inicio, fim]; negativo se fim < inicio."""
    if fim == inicio:
        return 0
    sinal = 1 if fim > inicio else -1
    a, b = sorted((inicio, fim))
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        if eh_util(d, locais):
            n += 1
    return sinal * n


def ultimo_util_do_mes(ano: int, mes: int, locais=()) -> date:
    prox = date(ano + (mes == 12), mes % 12 + 1, 1)
    d = prox - timedelta(days=1)
    while not eh_util(d, locais):
        d -= timedelta(days=1)
    return d


def util_anterior_ou_igual(d: date, locais=()) -> date:
    while not eh_util(d, locais):
        d -= timedelta(days=1)
    return d
