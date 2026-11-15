"""Configuração pela interface: token do portal e, nas opções, os sensores extras."""
from __future__ import annotations

import hashlib
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector as sel
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_AMBIENTES, CONF_BATERIAS, CONF_CASA, CONF_ENVIO_AUTOMATICO,
    CONF_POTENCIA_CASA, CONF_SO_CONSUMO, CONF_TEMP_EXTERNA,
    CONF_TENSAO_FASES, CONF_TENSAO_NOMINAL, CONF_TOKEN, CONF_URL, DOMAIN, URL_PADRAO,
)


async def _testar(hass, url: str, token: str) -> tuple[str | None, str | None]:
    """Confere o token no portal. Devolve (nome da casa no portal, erro)."""
    ping = url.rsplit("/relatorio", 1)[0] + "/ping"
    try:
        async with async_get_clientsession(hass).get(
                ping, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status == 401:
                return None, "token_invalido"
            if r.status == 200:
                j = await r.json(content_type=None)
                return (j or {}).get("cliente"), None
            return None, None   # portal sem /ping: segue sem confirmar o nome
    except (aiohttp.ClientError, TimeoutError):
        return None, "sem_conexao"


class FluxoFVHome(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, entrada: dict[str, Any] | None = None) -> ConfigFlowResult:
        erros: dict[str, str] = {}
        if entrada is not None:
            token = entrada[CONF_TOKEN].strip()
            url = (entrada.get(CONF_URL) or URL_PADRAO).strip()
            await self.async_set_unique_id(hashlib.sha256(token.encode()).hexdigest()[:16])
            self._abort_if_unique_id_configured()
            from homeassistant.components.energy.data import async_get_manager
            manager = await async_get_manager(self.hass)
            if not (manager.data or {}).get("energy_sources") and not (manager.data or {}).get("device_consumption"):
                erros["base"] = "sem_painel_energia"
            else:
                nome_portal, erro = await _testar(self.hass, url, token)
                if erro:
                    erros["base"] = erro
                else:
                    casa = entrada.get(CONF_CASA) or nome_portal or self.hass.config.location_name
                    return self.async_create_entry(
                        title=f"FV Home · {casa}",
                        data={CONF_TOKEN: token, CONF_URL: url, CONF_CASA: casa},
                        options={CONF_ENVIO_AUTOMATICO: True, CONF_BATERIAS: "5,10", CONF_TENSAO_NOMINAL: "127"},
                    )
        esquema = vol.Schema({
            vol.Required(CONF_TOKEN): sel.TextSelector(sel.TextSelectorConfig(type=sel.TextSelectorType.PASSWORD)),
            vol.Optional(CONF_CASA): str,
            vol.Optional(CONF_URL, default=URL_PADRAO): sel.TextSelector(sel.TextSelectorConfig(type=sel.TextSelectorType.URL)),
        })
        return self.async_show_form(step_id="user", data_schema=esquema, errors=erros)

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return OpcoesFVHome()


def _ent(dominio: str, classe: str | None = None, multiplo: bool = False) -> sel.EntitySelector:
    filtro = sel.EntityFilterSelectorConfig(domain=dominio, device_class=classe) if classe \
        else sel.EntityFilterSelectorConfig(domain=dominio)
    return sel.EntitySelector(sel.EntitySelectorConfig(filter=filtro, multiple=multiplo))


class OpcoesFVHome(OptionsFlow):
    """Menu: opções gerais, ambientes de climatização (adicionar/remover) e salvar."""

    def __init__(self) -> None:
        self._op: dict[str, Any] | None = None

    @property
    def op(self) -> dict[str, Any]:
        if self._op is None:
            self._op = dict(self.config_entry.options)
            self._op[CONF_AMBIENTES] = [dict(a) for a in self._op.get(CONF_AMBIENTES, []) or []]
        return self._op

    async def async_step_init(self, entrada: dict[str, Any] | None = None) -> ConfigFlowResult:
        amb = self.op[CONF_AMBIENTES]
        menu = ["geral", "ambiente_novo"] + (["ambiente_remover"] if amb else []) + ["salvar"]
        nomes = ", ".join(a["nome"] for a in amb) or "nenhum"
        return self.async_show_menu(step_id="init", menu_options=menu, description_placeholders={"ambientes": nomes})

    async def async_step_geral(self, entrada: dict[str, Any] | None = None) -> ConfigFlowResult:
        erros: dict[str, str] = {}
        if entrada is not None:
            caps = str(entrada.get(CONF_BATERIAS, "")).replace(";", ",")
            try:
                [float(x) for x in caps.split(",") if x.strip()]
            except ValueError:
                erros[CONF_BATERIAS] = "baterias_invalidas"
            if not erros:
                for k in (CONF_TENSAO_FASES, CONF_POTENCIA_CASA, CONF_TEMP_EXTERNA):
                    self.op.pop(k, None)   # campo apagado no formulário = remover
                self.op.update(entrada)
                return await self.async_step_init()
        o = self.op
        sug = lambda k: {"suggested_value": o.get(k)}  # noqa: E731
        esquema = vol.Schema({
            vol.Optional(CONF_ENVIO_AUTOMATICO, default=o.get(CONF_ENVIO_AUTOMATICO, True)): bool,
            vol.Optional(CONF_SO_CONSUMO, default=o.get(CONF_SO_CONSUMO, False)): bool,
            vol.Optional(CONF_TENSAO_NOMINAL, default=str(o.get(CONF_TENSAO_NOMINAL, "127"))): sel.SelectSelector(
                sel.SelectSelectorConfig(options=["127", "220"], mode=sel.SelectSelectorMode.LIST)),
            vol.Optional(CONF_TENSAO_FASES, description=sug(CONF_TENSAO_FASES)): _ent("sensor", "voltage", True),
            vol.Optional(CONF_POTENCIA_CASA, description=sug(CONF_POTENCIA_CASA)): _ent("sensor", "power"),
            vol.Optional(CONF_BATERIAS, default=o.get(CONF_BATERIAS, "5,10")): str,
            vol.Optional(CONF_TEMP_EXTERNA, description=sug(CONF_TEMP_EXTERNA)): _ent("sensor", "temperature"),
        })
        return self.async_show_form(step_id="geral", data_schema=esquema, errors=erros)

    async def async_step_ambiente_novo(self, entrada: dict[str, Any] | None = None) -> ConfigFlowResult:
        erros: dict[str, str] = {}
        if entrada is not None:
            nome = entrada["nome"].strip()
            if any(a["nome"].lower() == nome.lower() for a in self.op[CONF_AMBIENTES]):
                erros["nome"] = "ambiente_repetido"
            else:
                self.op[CONF_AMBIENTES].append({"nome": nome, **{k: v for k, v in entrada.items() if k != "nome" and v}})
                return await self.async_step_init()
        esquema = vol.Schema({
            vol.Required("nome"): str,
            vol.Required("potencia"): _ent("sensor", "power"),
            vol.Optional("temp_interna"): _ent("sensor", "temperature"),
            vol.Optional("climate"): _ent("climate"),
        })
        return self.async_show_form(step_id="ambiente_novo", data_schema=esquema, errors=erros)

    async def async_step_ambiente_remover(self, entrada: dict[str, Any] | None = None) -> ConfigFlowResult:
        if entrada is not None:
            tirar = set(entrada.get("remover", []))
            self.op[CONF_AMBIENTES] = [a for a in self.op[CONF_AMBIENTES] if a["nome"] not in tirar]
            return await self.async_step_init()
        nomes = [a["nome"] for a in self.op[CONF_AMBIENTES]]
        esquema = vol.Schema({vol.Optional("remover", default=[]): sel.SelectSelector(
            sel.SelectSelectorConfig(options=nomes, multiple=True, mode=sel.SelectSelectorMode.LIST))})
        return self.async_show_form(step_id="ambiente_remover", data_schema=esquema)

    async def async_step_salvar(self, entrada: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_create_entry(data=self.op)
