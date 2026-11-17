"""Sinal de "casa online": avisa o portal FV Home a cada 5 minutos.

Se o portal ficar 15 minutos sem receber o aviso, a casa aparece como offline
no painel da FV Home (internet caiu, Home Assistant travou, falta de energia…).
Vai só: versão do HA, versão desta integração, total de entidades e quantas
estão indisponíveis. Nenhum estado, nome de dispositivo ou dado de consumo.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, __version__ as HA_VERSAO
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_TOKEN, CONF_URL, URL_PADRAO, VERSAO

_LOGGER = logging.getLogger(__name__)

INTERVALO_STATUS = timedelta(minutes=5)


def url_status(url_relatorio: str | None) -> str:
    """https://…/api/relatorio  →  https://…/api/status"""
    base = (url_relatorio or URL_PADRAO).strip().rstrip("/")
    if base.endswith("/relatorio"):
        base = base[: -len("/relatorio")]
    return base + "/status"


def montar_status(hass: HomeAssistant) -> dict[str, Any]:
    estados = hass.states.async_all()
    return {
        "ha_versao": HA_VERSAO,
        "integracao": VERSAO,
        "entidades": len(estados),
        "indisponiveis": sum(1 for s in estados if s.state == STATE_UNAVAILABLE),
    }


async def avisar_online(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Manda o sinal. Falha não gera alerta: o próprio silêncio é o que o portal mede."""
    url = url_status(entry.data.get(CONF_URL))
    try:
        async with async_get_clientsession(hass).post(
                url, json=montar_status(hass),
                headers={"Authorization": f"Bearer {entry.data[CONF_TOKEN]}", "Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status == 401:
                _LOGGER.warning("FV Home: o portal recusou o token ao avisar que a casa está online (token revogado?)")
            elif r.status >= 400:
                _LOGGER.debug("FV Home: aviso de status respondeu %s", r.status)
            return r.status < 400
    except (aiohttp.ClientError, TimeoutError) as err:
        _LOGGER.debug("FV Home: sem conexão para avisar o portal (%s)", err)
        return False
