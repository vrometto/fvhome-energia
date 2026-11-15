"""Monta o resumo mensal de energia no formato que o portal FV Home espera.

Este módulo não importa nada do Home Assistant: recebe as estatísticas já lidas
e devolve um dicionário. Assim a lógica pode ser testada fora do HA e fica igual
à do script ``script.fvhome_relatorio_energia`` (versão em YAML).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, tzinfo
from typing import Any

PAPEIS_HORA = ("rede_importada", "rede_exportada", "solar", "bateria_descarga", "bateria_carga")
ORDEM_ALERTAS = ("parou", "falha_intermitente", "comecou", "nunca_mediu")


def itens_do_painel(prefs: dict[str, Any] | None) -> list[dict[str, str]]:
    """Converte a configuração do Painel de Energia do HA em itens com papel.

    Aceita o formato atual (uma entrada de rede por sensor, com ``stat_energy_from``
    e ``stat_energy_to``) e o antigo (``flow_from``/``flow_to``).
    """
    itens: list[dict[str, str]] = []
    if not prefs:
        return itens

    def add(papel: str, stat: str | None, nome: str | None = None) -> None:
        if stat:
            itens.append({"papel": papel, "nome": nome or "", "stat": stat})

    for fonte in prefs.get("energy_sources") or []:
        tipo = fonte.get("type")
        nome = fonte.get("name")
        if tipo == "grid":
            add("rede_importada", fonte.get("stat_energy_from"), nome)
            add("rede_exportada", fonte.get("stat_energy_to"), nome)
            for f in fonte.get("flow_from") or []:
                add("rede_importada", f.get("stat_energy_from"), f.get("name"))
            for f in fonte.get("flow_to") or []:
                add("rede_exportada", f.get("stat_energy_to"), f.get("name"))
        elif tipo == "solar":
            add("solar", fonte.get("stat_energy_from"), nome)
        elif tipo == "battery":
            add("bateria_descarga", fonte.get("stat_energy_from"), nome)
            add("bateria_carga", fonte.get("stat_energy_to"), nome)
    for dev in prefs.get("device_consumption") or []:
        add("aparelho", dev.get("stat_consumption"), dev.get("name"))
    return itens


def _ts(v: Any) -> float:
    """Início da linha de estatística em segundos (aceita float, ms ou datetime)."""
    if isinstance(v, datetime):
        return v.timestamp()
    v = float(v)
    return v / 1000 if v > 1e11 else v


def _mes_local(v: Any, tz: tzinfo) -> str:
    return datetime.fromtimestamp(_ts(v), tz).strftime("%Y-%m")


def _r(v: float | None, n: int) -> float | None:
    return None if v is None else round(float(v), n)


def montar_resumo(
    *,
    casa: str,
    mes_ref: str,
    meses: list[str],
    itens: list[dict[str, str]],
    nomes: dict[str, str],
    st_mes: dict[str, list[dict]],
    st_hora: dict[str, list[dict]],
    st_media: dict[str, list[dict]],
    st_max: dict[str, list[dict]],
    st_tensao: dict[str, list[dict]],
    tz: tzinfo,
    agora: datetime,
    medidor_so_consumo: bool,
    clima_cfg: dict,
    bateria_cfg: dict,
    tensao_cfg: dict,
    parcial_ate: datetime | None = None,
    origem: str = "",
) -> dict[str, Any]:
    # --- valor por sensor e por mês
    detalhe = []
    for it in itens:
        rows = st_mes.get(it["stat"], [])
        por_mes: dict[str, float | None] = {c: None for c in meses}
        for r in rows:
            c = _mes_local(r["start"], tz)
            if c in por_mes and r.get("change") is not None:
                por_mes[c] = round(float(r["change"]), 2)
        detalhe.append({
            "papel": it["papel"],
            "nome": it.get("nome") or nomes.get(it["stat"]) or it["stat"],
            "statistic_id": it["stat"],
            "por_mes": por_mes,
        })

    # --- alertas (sensor parou, começou, nunca mediu...)
    alertas, vistos = [], set()
    for l in detalhe:
        sid = l["statistic_id"]
        if sid in vistos:
            continue
        vistos.add(sid)
        f = [(l["por_mes"][c] or 0) > 0.5 for c in meses]
        if not any(f):
            alertas.append({"tipo": "nunca_mediu", "nome": l["nome"], "statistic_id": sid,
                            "texto": f"{l['nome']}: sem leitura no período (porta vazia ou sensor sem uso?)"})
        elif not all(f):
            ultimo = len(f) - 1 - f[::-1].index(True)
            primeiro = f.index(True)
            if ultimo < len(f) - 1:
                alertas.append({"tipo": "parou", "nome": l["nome"], "statistic_id": sid,
                                "texto": f"{l['nome']}: PAROU de medir em {meses[ultimo + 1]} — verificar"})
            elif primeiro > 0:
                alertas.append({"tipo": "comecou", "nome": l["nome"], "statistic_id": sid,
                                "texto": f"{l['nome']}: começou a medir em {meses[primeiro]} (sensor novo ou religado)"})
            else:
                alertas.append({"tipo": "falha_intermitente", "nome": l["nome"], "statistic_id": sid,
                                "texto": f"{l['nome']}: sem leitura em parte do período — verificar"})
    alertas.sort(key=lambda a: ORDEM_ALERTAS.index(a["tipo"]))

    aparelhos = {l["nome"]: l["por_mes"] for l in detalhe if l["papel"] == "aparelho"}

    # --- totais por mês, consumo da casa e saldo solar
    totais: dict[str, dict[str, float]] = {}
    for c in meses:
        t: dict[str, float] = {}
        for l in detalhe:
            v = l["por_mes"][c]
            if v is not None:
                t[l["papel"]] = round(t.get(l["papel"], 0) + v, 2)
        if medidor_so_consumo:
            t["consumo_casa"] = t.get("rede_importada", 0)
            t.pop("rede_exportada", None)
        elif "solar" in t or "rede_exportada" in t:
            t["consumo_casa"] = round(t.get("rede_importada", 0) + t.get("solar", 0) + t.get("bateria_descarga", 0)
                                      - t.get("rede_exportada", 0) - t.get("bateria_carga", 0), 2)
        if "solar" in t and "consumo_casa" in t:
            t["saldo_solar"] = round(t["solar"] - t["consumo_casa"], 2)
        totais[c] = t

    # --- estatísticas por hora
    energia: dict[str, dict] = {}
    for papel in PAPEIS_HORA:
        soma: dict[int, float] = defaultdict(float)
        achou = False
        for sid in {it["stat"] for it in itens if it["papel"] == papel}:
            for r in st_hora.get(sid, []):
                if r.get("change") is None:
                    continue
                soma[int(_ts(r["start"]))] += float(r["change"])
                achou = True
        if achou:
            ts = sorted(soma)
            energia[papel] = {"t": ts, "v": [round(soma[k], 4) for k in ts]}

    def serie(rows: list[dict], campo: str, n: int) -> dict:
        rows = [r for r in rows if r.get(campo) is not None]
        return {"t": [int(_ts(r["start"])) for r in rows], "v": [round(float(r[campo]), n) for r in rows]}

    media = {k: serie(v, "mean", 2) for k, v in st_media.items() if v}
    maximo = {k: serie(v, "max", 1) for k, v in st_max.items() if v}
    tensao = {}
    for k, rows in st_tensao.items():
        rows = [r for r in rows if r.get("mean") is not None]
        if rows:
            tensao[k] = {"t": [int(_ts(r["start"])) for r in rows],
                         "min": [_r(r.get("min"), 1) for r in rows],
                         "max": [_r(r.get("max"), 1) for r in rows],
                         "mean": [_r(r.get("mean"), 1) for r in rows]}

    resumo = {
        "casa": casa,
        "gerado_em": agora.isoformat(timespec="seconds"),
        "fuso": str(tz),
        "unidade": "kWh",
        "mes_relatorio": mes_ref,
        "parcial_ate": parcial_ate.isoformat() if parcial_ate else None,
        "meses": meses,
        "totais_por_mes": totais,
        "aparelhos": aparelhos,
        "alertas": alertas,
        "detalhe": detalhe,
        "estat_hora": {"por": "papel", "energia": energia, "media": media, "max": maximo, "tensao": tensao},
        "config_extras": {"medidor_so_consumo": medidor_so_consumo, "clima": clima_cfg,
                          "bateria": bateria_cfg, "tensao": tensao_cfg},
    }
    if origem:
        resumo["origem"] = origem
    return resumo


def meses_do_relatorio(mes_ref: str) -> list[str]:
    """Mês do relatório + 2 anteriores, do mais antigo para o mais novo."""
    a, m = int(mes_ref[:4]), int(mes_ref[5:7])
    out = []
    for k in (2, 1, 0):
        mm, aa = m - k, a
        if mm <= 0:
            mm, aa = mm + 12, a - 1
        out.append(f"{aa:04d}-{mm:02d}")
    return out
