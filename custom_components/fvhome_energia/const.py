"""Constantes da integração FV Home Energia."""
DOMAIN = "fvhome_energia"
VERSAO = "0.3.0"

URL_PADRAO = "https://app.fvhome.com.br/api/relatorio"

CONF_URL = "url"
CONF_TOKEN = "token"
CONF_CASA = "casa"
CONF_SO_CONSUMO = "medidor_so_consumo"
CONF_TENSAO_NOMINAL = "tensao_nominal"
CONF_TENSAO_FASES = "tensao_fases"
CONF_TEMP_EXTERNA = "temp_externa"
CONF_AMBIENTES = "ambientes"          # climatização: [{nome, potencia, temp_interna, climate}]
CONF_POTENCIA_CASA = "potencia_casa"
CONF_BATERIAS = "baterias_kwh"
CONF_ENVIO_AUTOMATICO = "envio_automatico"
CONF_STATUS_ONLINE = "status_online"      # avisar o portal a cada 5 min (casa online no painel)

SERVICO_ENVIAR = "enviar_relatorio"
SINAL_ENVIO = f"{DOMAIN}_envio_{{}}"   # formatado com o entry_id
