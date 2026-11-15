"""Sensores: último envio ao portal e espelhos de tensão (para gravar estatísticas)."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory, UnitOfElectricPotential
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from . import FVConfigEntry
from .const import CONF_TENSAO_FASES, DOMAIN, SINAL_ENVIO, VERSAO


def _device(entry: FVConfigEntry) -> DeviceInfo:
    return DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, name="FV Home Energia", manufacturer="FV Home",
                      model="Relatório mensal de energia", sw_version=VERSAO, entry_type=DeviceEntryType.SERVICE,
                      configuration_url="https://app.fvhome.com.br")


async def async_setup_entry(hass: HomeAssistant, entry: FVConfigEntry,
                            add: AddConfigEntryEntitiesCallback) -> None:
    ents: list[SensorEntity] = [UltimoEnvio(entry)]
    for origem in entry.options.get(CONF_TENSAO_FASES, []) or []:
        st = hass.states.get(origem)
        if st is None or st.attributes.get("state_class") != "measurement":
            ents.append(EspelhoTensao(entry, origem))
    add(ents)


class UltimoEnvio(SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "ultimo_envio"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:cloud-upload"

    def __init__(self, entry: FVConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_ultimo_envio"
        self._attr_device_info = _device(entry)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(
            self.hass, SINAL_ENVIO.format(self._entry.entry_id), self.async_write_ha_state))

    @property
    def native_value(self) -> str | None:
        u = self._entry.runtime_data.ultimo
        if not u:
            return None
        return "ok" if u.get("ok") else "erro"

    @property
    def extra_state_attributes(self) -> dict:
        u = self._entry.runtime_data.ultimo or {}
        return {k: v for k, v in u.items() if k != "ok"}


class EspelhoTensao(SensorEntity):
    """Copia um sensor de tensão que não grava estatísticas, para o relatório ter mínima/máxima por hora."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_suggested_display_precision = 1
    _attr_should_poll = False

    def __init__(self, entry: FVConfigEntry, origem: str) -> None:
        self._origem = origem
        self._attr_unique_id = f"{entry.entry_id}_tensao_{origem}"
        self._attr_device_info = _device(entry)
        self._attr_name = f"Tensão {origem.split('.', 1)[-1]}"

    async def async_added_to_hass(self) -> None:
        st = self.hass.states.get(self._origem)
        if st:
            self._attr_name = f"Tensão · {st.name}"
        self._copiar()

        @callback
        def _mudou(event: Event[EventStateChangedData]) -> None:
            self._copiar()
            self.async_write_ha_state()

        self.async_on_remove(async_track_state_change_event(self.hass, [self._origem], _mudou))

    def _copiar(self) -> None:
        st = self.hass.states.get(self._origem)
        try:
            self._attr_native_value = float(st.state) if st else None
            self._attr_available = True
        except (TypeError, ValueError):
            self._attr_native_value = None
            self._attr_available = False
