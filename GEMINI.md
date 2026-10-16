# Regras do Projeto & Memória Persistente — Grafana-Modens

## 1. Identidade do Projeto
- **Repositório Oficial:** `https://github.com/IDhexter/Grafana-Modens.git`
- **Escopo Exclusivo:** Gêmeo Digital de Modems, Roteadores e Links WAN SNMP (`SGS_LINKS_GRAFANA` / `SGS_LINKS`).
- **Isolamento:** Este repositório é exclusivo do projeto de Modems/Links WAN. Nunca misturar arquivos ou imagens do projeto de Switches (`IDhexter/Grafana-Switch`).
- **Dashboard no Grafana:** `[SGS] - Modems & Links WAN (SGS_LINKS)` (`UID: sgs-modems-wan`, Pasta `POC ALEX`, `Folder ID: 136`, versão `v12+`).
- **Script Construtor:** `scripts/build_sgs_modem_twin.py`.

## 2. Arquitetura em Produção (`v12+`)
- **Auto-Discovery Dinâmico (`SGS_LINKS_GRAFANA`):**
  - A função `syncCatalogFromZabbix()` no JavaScript do painel consulta `hostgroup.get`, `host.get` e `item.get` diretamente na API JSON-RPC do Zabbix (`http://10.10.1.26/api_jsonrpc.php`) a cada 45 segundos e ao clicar em `↻ SYNC`.
  - Quando o grupo `SGS_LINKS_GRAFANA` possui hosts ativos, o painel lista **exclusivamente** os ativos desse grupo. Qualquer novo link SNMP inserido pelo NOC em `SGS_LINKS_GRAFANA` aparece automaticamente na dashboard.
  - Enquanto `SGS_LINKS_GRAFANA` estiver vazio ou sem permissão de leitura para o grupo `Read-only` (`usrgrpid: 15`), o painel utiliza automaticamente `SGS_LINKS` (`groupid: 38`, filtrando switches).
- **Chassi 1U 100% Funcional (Zero Estética Falsa):**
  - Gaiola óptica `WAN SFP`, LEDs `PWR`, `PON/LINK`, `INTERNET`, `LOS/ALM` e portas `LAN 1–4` refletem o estado real SNMP do equipamento no Zabbix e permitem clicar para alternar a interface exibida no osciloscópio.
- **Osciloscópio HTML5 Canvas (60 FPS):**
  - Linha guia vertical tracejada no hover, bolinhas amostrais nas curvas, *target halos* luminosos, cápsula HUD flutuante no topo, linha de Percentil 95 (`P95`) e `padLeft = 84`.
