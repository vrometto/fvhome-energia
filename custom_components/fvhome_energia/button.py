"""Botões: enviar prévia do mês atual e reenviar o mês anterior."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FVConfigEntry, executar
from .sensor import _device


async def async_setup_entry(hass: HomeAssistant, entry: FVConfigEntry,
                            add: AddConfigEntryEntitiesCallback) -> None:
    add([BotaoEnvio(entry, "enviar_previa", True), BotaoEnvio(entry, "reenviar_mes_anterior", False)])


class BotaoEnvio(ButtonEntity):
    _attr_has_entity_name = True

    def __init__(self, entry: FVConfigEntry, chave: str, parcial: bool) -> None:
        self._entry = entry
        self._parcial = parcial
        self._attr_translation_key = chave
        self._attr_unique_id = f"{entry.entry_id}_{chave}"
        self._attr_icon = "mdi:file-clock" if parcial else "mdi:file-send"
        self._attr_device_info = _device(entry)

    async def async_press(self) -> None:
        await executar(self.hass, self._entry, parcial=self._parcial, tentativas=1)
