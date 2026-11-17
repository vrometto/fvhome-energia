# FV Home Energia

Integração para Home Assistant que envia, todo dia 1, o resumo de energia da casa ao portal
[FV Home](https://fvhome.com.br). Lá ele vira um relatório mensal com consumo, geração solar,
aparelhos, dia típico, simulação de bateria, clima e qualidade da tensão.

## O que precisa

* Home Assistant 2025.1 ou mais novo.
* **Painel de Energia configurado** (Configurações → Painéis → Energia), com pelo menos o consumo da rede.
  Solar, bateria e aparelhos que estiverem lá entram sozinhos no relatório.
* Um **token** do portal FV Home (começa com `fvh_`).

## Instalação

**HACS:** HACS → ⋮ → Repositórios personalizados → cole o endereço deste repositório (categoria *Integração*) → instale **FV Home Energia** → reinicie.

**Manual:** copie a pasta `custom_components/fvhome_energia` para `/config/custom_components/` e reinicie.

Depois: Configurações → Dispositivos e serviços → Adicionar integração → **FV Home Energia** → cole o token.

## Opções (todas opcionais)

Em **Configurar** na integração: sensores de tensão por fase (seção *Qualidade da energia*, faixas da ANEEL),
potência da casa (análise de bateria), temperatura externa e **ambientes de climatização** (um por ar-condicionado: nome, potência, temperatura do cômodo).
Se um sensor de tensão não grava estatísticas, a integração cria uma cópia que grava.

## Uso

* Envio automático no dia 1, por volta das 6h.
* Botões **Enviar prévia do mês atual** e **Reenviar mês anterior** no dispositivo *FV Home Energia*.
* Ação `fvhome_energia.enviar_relatorio` (`mes`, `parcial`), que devolve o resultado.
* Sensor **Último envio** mostra se deu certo e a resposta do portal.
* **Casa online e saúde da medição:** a cada 5 minutos a integração avisa o portal que o Home Assistant está no ar
  e se os sensores usados no relatório (Painel de Energia, tensão, potência, climatização) estão medindo.
  Se o aviso parar por 15 minutos, a FV Home vê a casa como *offline*; se um sensor do relatório ficar sem leitura,
  ela vê qual é e corrige antes que o relatório do mês saia com buraco. Dá para desligar em **Configurar → Opções gerais**.

Nada sai do Home Assistant além do resumo de energia do mês e, no aviso de casa online, a versão do HA,
a versão da integração e o nome dos sensores do relatório que estiverem sem leitura — nenhum valor medido nem outros dispositivos.
O token fica só nesta instalação.
