"""Lê as estatísticas do Home Assistant e envia o resumo ao portal FV Home."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .const import (
    CONF_AMBIENTES, CONF_BATERIAS, CONF_CASA,
    CONF_POTENCIA_CASA, CONF_SO_CONSUMO, CONF_TEMP_EXTERNA, CONF_TENSAO_FASES,
    CONF_TENSAO_NOMINAL, CONF_TOKEN, CONF_URL, DOMAIN, URL_PADRAO, VERSAO,
)
from .montar import itens_do_painel, meses_do_relatorio, montar_resumo

_LOGGER = logging.getLogger(__name__)


class ErroEnvio(HomeAssistantError):
    """Falha ao montar ou enviar o relatório."""


def _opc(entry: ConfigEntry, chave: str, padrao: Any = None) -> Any:
    return entry.options.get(chave, entry.data.get(chave, padrao))


def stat_tensao(hass: HomeAssistant, entry: ConfigEntry, origem: str) -> str:
    """Sensor de tensão que tem estatísticas: o próprio, ou o espelho criado pela integração."""
    st = hass.states.get(origem)
    if st and st.attributes.get("state_class") == "measurement":
        return origem
    reg = er.async_get(hass)
    espelho = reg.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_tensao_{origem}")
    return espelho or origem


async def _stats(hass: HomeAssistant, ini: datetime, fim: datetime, ids: set[str], periodo: str,
                 tipos: set[str], unidades: dict | None = None) -> dict[str, list[dict]]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return await get_instance(hass).async_add_executor_job(
        statistics_during_period, hass, ini, fim, ids, periodo, unidades, tipos)


async def montar(hass: HomeAssistant, entry: ConfigEntry, mes: str | None = None,
                 parcial: bool = False) -> dict[str, Any]:
    tz = ZoneInfo(hass.config.time_zone)
    agora = dt_util.now(tz)

    if mes:
        mes_ref = mes
    elif parcial:
        mes_ref = agora.strftime("%Y-%m")
    else:
        mes_ref = (agora.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    a, m = int(mes_ref[:4]), int(mes_ref[5:7])
    ini_mes = datetime(a, m, 1, tzinfo=tz)
    fim_mes = datetime(a + (m == 12), 1 if m == 12 else m + 1, 1, tzinfo=tz)
    parcial_ate = None
    if fim_mes > agora:
        if not parcial:
            raise ErroEnvio(f"O mês {mes_ref} ainda não terminou. Use 'parcial' para enviar uma prévia.")
        fim = agora.replace(minute=0, second=0, microsecond=0)
        parcial_ate = fim
    else:
        fim = fim_mes
    meses = meses_do_relatorio(mes_ref)
    ini_3m = datetime(int(meses[0][:4]), int(meses[0][5:7]), 1, tzinfo=tz)

    # fontes do Painel de Energia
    from homeassistant.components.energy.data import async_get_manager
    manager = await async_get_manager(hass)
    itens = itens_do_painel(manager.data)
    if not itens:
        raise ErroEnvio("O Painel de Energia do Home Assistant ainda não tem nenhuma fonte configurada.")
    nomes = {i["stat"]: (hass.states.get(i["stat"]).name if hass.states.get(i["stat"]) else i["stat"]) for i in itens}

    # configurações opcionais (opções da integração)
    # climatização: um item por ambiente com ar-condicionado dedicado (sala, quarto...)
    ambientes = [
        {k: v for k, v in {"nome": a.get("nome"), "climate": a.get("climate"), "potencia": a.get("potencia"),
                           "temp_interna": a.get("temp_interna")}.items() if v}
        for a in (_opc(entry, CONF_AMBIENTES, []) or []) if a.get("potencia")
    ]
    clima_cfg = {"temp_externa": _opc(entry, CONF_TEMP_EXTERNA), "ambientes": ambientes} if ambientes else {}
    try:
        caps = [float(x) for x in str(_opc(entry, CONF_BATERIAS, "5,10")).replace(";", ",").split(",") if x.strip()]
    except ValueError:
        caps = [5.0, 10.0]
    bateria_cfg = {"capacidades_kwh": caps, "profundidade": 0.9, "eficiencia": 0.9,
                   "potencia_casa": _opc(entry, CONF_POTENCIA_CASA)} if caps else {}
    fases = []
    for origem in _opc(entry, CONF_TENSAO_FASES, []) or []:
        st = hass.states.get(origem)
        fases.append({"nome": st.name if st else origem, "stat": stat_tensao(hass, entry, origem)})
    tensao_cfg = {"nominal": int(_opc(entry, CONF_TENSAO_NOMINAL, 127)), "fases": fases} if fases else {}

    kwh = {"energy": "kWh"}
    ids_todos = {i["stat"] for i in itens}
    ids_hora = {i["stat"] for i in itens if i["papel"] != "aparelho"}
    st_mes, st_hora, st_media, st_max, st_tensao = await asyncio.gather(
        _stats(hass, ini_3m, fim, ids_todos, "month", {"change"}, kwh),
        _stats(hass, ini_mes, fim, ids_hora, "hour", {"change"}, kwh),
        _stats(hass, ini_mes, fim, {clima_cfg.get("temp_externa")}
               | {a.get(k) for a in clima_cfg.get("ambientes", []) for k in ("potencia", "temp_interna")},
               "hour", {"mean"}),
        _stats(hass, ini_mes, fim, {bateria_cfg.get("potencia_casa")}, "hour", {"max"}),
        _stats(hass, ini_mes, fim, {f["stat"] for f in fases}, "hour", {"min", "max", "mean"}),
    )

    return montar_resumo(
        casa=_opc(entry, CONF_CASA) or hass.config.location_name, mes_ref=mes_ref, meses=meses, itens=itens,
        nomes=nomes, st_mes=st_mes, st_hora=st_hora, st_media=st_media, st_max=st_max, st_tensao=st_tensao,
        tz=tz, agora=agora, medidor_so_consumo=bool(_opc(entry, CONF_SO_CONSUMO, False)),
        clima_cfg=clima_cfg, bateria_cfg=bateria_cfg, tensao_cfg=tensao_cfg, parcial_ate=parcial_ate,
        origem=f"fvhome_energia {VERSAO}",
    )


async def enviar_json(hass: HomeAssistant, url: str, token: str, dados: dict, tentativas: int = 3) -> tuple[int, Any]:
    sessao = async_get_clientsession(hass)
    espera = [0, 60, 600]
    ultimo: tuple[int, Any] = (0, "sem resposta")
    for n in range(tentativas):
        if espera[min(n, 2)]:
            await asyncio.sleep(espera[min(n, 2)])
        try:
            async with sessao.post(url, json=dados, timeout=aiohttp.ClientTimeout(total=30),
                                   headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}) as r:
                try:
                    corpo = await r.json(content_type=None)
                except ValueError:
                    corpo = (await r.text())[:300]
                ultimo = (r.status, corpo)
                if r.status in (200, 201):
                    return ultimo
                if r.status in (401, 403, 422):
                    return ultimo   # repetir não resolve
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            ultimo = (0, str(err))
        _LOGGER.warning("FV Home: tentativa %s de envio falhou: %s", n + 1, ultimo)
    return ultimo


async def enviar(hass: HomeAssistant, entry: ConfigEntry, mes: str | None = None, parcial: bool = False,
                 tentativas: int = 3) -> dict[str, Any]:
    dados = await montar(hass, entry, mes, parcial)
    url = entry.data.get(CONF_URL) or URL_PADRAO
    status, corpo = await enviar_json(hass, url, entry.data[CONF_TOKEN], dados, tentativas)
    eh = dados["estat_hora"]
    import json
    return {
        "ok": status in (200, 201), "mes": dados["mes_relatorio"], "parcial_ate": dados["parcial_ate"],
        "portal_status": status, "portal_resposta": corpo, "quando": dt_util.now().isoformat(timespec="seconds"),
        "consumo_casa": dados["totais_por_mes"].get(dados["mes_relatorio"], {}).get("consumo_casa"),
        "sensores": {"energia": len(dados["detalhe"]), "hora_energia": len(eh["energia"]),
                     "clima": len(eh["media"]), "tensao": len(eh["tensao"])},
        "tamanho_kb": round(len(json.dumps(dados)) / 1024),
    }
