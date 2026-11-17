"""FV Home Energia: envia o resumo mensal do Painel de Energia ao portal FV Home."""
from __future__ import annotations

import logging
import zlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_time_change, async_track_time_interval
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.typing import ConfigType

from .coletor import ErroEnvio, enviar
from .const import CONF_ENVIO_AUTOMATICO, CONF_STATUS_ONLINE, DOMAIN, SERVICO_ENVIAR, SINAL_ENVIO
from .status import INTERVALO_STATUS, avisar_online

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR, Platform.BUTTON]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class DadosFV:
    ultimo: dict[str, Any] = field(default_factory=dict)


type FVConfigEntry = ConfigEntry[DadosFV]


async def executar(hass: HomeAssistant, entry: FVConfigEntry, mes: str | None = None,
                   parcial: bool = False, tentativas: int = 3) -> dict[str, Any]:
    """Monta, envia e guarda o resultado (mostrado no sensor 'Último envio')."""
    try:
        res = await enviar(hass, entry, mes, parcial, tentativas)
    except ErroEnvio as err:
        res = {"ok": False, "erro": str(err), "mes": mes, "portal_status": None}
    except Exception as err:  # noqa: BLE001 - registrar qualquer falha no sensor
        _LOGGER.exception("FV Home: erro ao montar o relatório")
        res = {"ok": False, "erro": f"{type(err).__name__}: {err}", "mes": mes, "portal_status": None}
    entry.runtime_data.ultimo = res
    async_dispatcher_send(hass, SINAL_ENVIO.format(entry.entry_id))
    if not res.get("ok"):
        from homeassistant.components import persistent_notification
        persistent_notification.async_create(
            hass, f"Mês {res.get('mes')}: {res.get('erro') or res.get('portal_resposta')}",
            title="FV Home · falha ao enviar o relatório de energia", notification_id=f"{DOMAIN}_falha")
    return res


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async def servico(call: ServiceCall) -> ServiceResponse:
        entradas = hass.config_entries.async_loaded_entries(DOMAIN)
        if not entradas:
            raise ServiceValidationError("A integração FV Home Energia não está configurada.")
        mes = call.data.get("mes") or None
        res = {}
        for e in entradas:
            res[e.title] = await executar(hass, e, mes, call.data.get("parcial", False), tentativas=1)
        return res if len(res) > 1 else next(iter(res.values()))

    hass.services.async_register(
        DOMAIN, SERVICO_ENVIAR, servico,
        schema=vol.Schema({vol.Optional("mes"): vol.Any(None, "", cv.matches_regex(r"^\d{4}-(0[1-9]|1[0-2])$")),
                           vol.Optional("parcial", default=False): cv.boolean}),
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: FVConfigEntry) -> bool:
    entry.runtime_data = DadosFV()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # envio automático no dia 1, às 6h e um minuto fixo por instalação (espalha a carga no portal)
    minuto = zlib.crc32(entry.entry_id.encode()) % 60

    @callback
    def _agendado(agora: datetime) -> None:
        if agora.day == 1 and entry.options.get(CONF_ENVIO_AUTOMATICO, True):
            hass.async_create_background_task(executar(hass, entry), f"{DOMAIN}_envio_mensal")

    entry.async_on_unload(async_track_time_change(hass, _agendado, hour=6, minute=minuto, second=0))

    # "casa online": avisa o portal a cada 5 min (o painel marca offline após 15 min sem aviso)
    if entry.options.get(CONF_STATUS_ONLINE, True):
        async def _status(_agora: datetime | None = None) -> None:
            await avisar_online(hass, entry)

        @callback
        def _ao_iniciar(_hass: HomeAssistant) -> None:
            # 1 min depois de ligar: dá tempo dos sensores saírem de "desconhecido"
            entry.async_on_unload(async_call_later(hass, 60, _status))

        entry.async_on_unload(async_at_started(hass, _ao_iniciar))
        entry.async_on_unload(async_track_time_interval(hass, _status, INTERVALO_STATUS, name=f"{DOMAIN}_status"))
    entry.async_on_unload(entry.add_update_listener(_recarregar))
    return True


async def _recarregar(hass: HomeAssistant, entry: FVConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: FVConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
