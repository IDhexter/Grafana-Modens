# 📘 Manual Operacional NOC & Arquitetura Técnica — Gêmeo Digital Modems WAN (`v12`)

Este documento descreve o funcionamento técnico e operacional da dashboard **`[SGS] - Modems & Links WAN (SGS_LINKS)`** (`UID: sgs-modems-wan`), projetada para monitoramento em tempo real dos links de internet corporativos e modems/roteadores SNMP.

---

## 1. Fluxo Operacional para o NOC: Adicionando Novos Links Automaticamente

A dashboard possui um motor de **Auto-Discovery em Tempo Real** executado diretamente no navegador do operador. Não é necessário editar o Grafana nem executar scripts quando um novo link entra em operação.

### Passo a Passo no Zabbix:
1. **Criação/Permissão do Grupo `SGS_LINKS_GRAFANA` (Configuração Única pelo Admin):**
   - No Zabbix (`http://10.10.1.26`), crie o grupo de hosts **`SGS_LINKS_GRAFANA`** (ou como subgrupo `SGS_LINKS/SGS_LINKS_GRAFANA`).
   - Em *Users → User groups → Read-only → Permissions*, garanta que o grupo de usuários **`Read-only`** tenha permissão **`Read` (Leitura)** sobre o grupo `SGS_LINKS_GRAFANA`.
2. **Inclusão de Novo Link pelo NOC:**
   - Cadastre o modem/roteador com interface SNMP e associe o template SNMP de rede (com descoberta de interfaces `net.if.*` e `icmpping*`).
   - Adicione o host ao grupo **`SGS_LINKS_GRAFANA`**.
   - **Pronto!** Em até **45 segundos** (ou imediatamente clicando no botão **`↻ SYNC`** no canto superior direito da dashboard), o novo link aparecerá automaticamente:
     - No seletor **`🌐 LINK`**;
     - Na contagem das **Pílulas de Operadora** (`VIVO`, `ALGAR`, `VEGANET`, `DESKTOP`, `STARLINK`, etc.);
     - No **Ranking de Consumo em Tempo Real** no canto inferior direito.

> **Observação sobre Hosts Recém-Criados (Aguardando LLD):**  
> Caso o técnico do NOC acabe de colocar o host no grupo `SGS_LINKS_GRAFANA` e o Zabbix ainda não tenha finalizado o primeiro ciclo de *Low-Level Discovery (LLD)* das interfaces SNMP, o host **já aparece imediatamente na lista da dashboard** com a porta sinalizada como `AGUARDANDO DESCOBERTA SNMP (LLD)...`. Assim que o Zabbix descobrir as interfaces, elas passam a exibir o tráfego automaticamente.

---

## 2. Anatomia do Chassi Físico 1U (100% Funcional em Produção)

Nenhum LED ou porta da dashboard é meramente decorativo. Todos os indicadores respondem aos itens SNMP e ICMP reais do Zabbix:

| Componente no Chassi | Item Zabbix Associado | Comportamento Visual e Interação |
| :--- | :--- | :--- |
| **Pílula `IP: x.x.x.x 📋`** | `interface.ip` (SNMP prioritário) | Clique para copiar o IP imediatamente para a área de transferência (`✓ COPIADO!`). |
| **Pílula `LATÊNCIA` / `PERDA`** | `icmppingsec` / `icmppingloss` | Exibe a latência em `ms` (destaca em âmbar se `> 80ms`) e a perda de pacotes em `%`. |
| **Gaiola Óptica `WAN SFP`** | Interface WAN Primária (`interfaces[0]`) | Brilho laser ciano ativo; **clicar** seleciona a interface WAN principal no osciloscópio. |
| **LED `PWR`** | `host.status == 0` | Verde esmeralda sólido indicando equipamento ativo no Zabbix. |
| **LED `PON/LINK`** | Status da WAN Primária | Verde esmeralda sólido; **clicar** foca o osciloscópio na porta WAN principal. |
| **LED `INTERNET`** | `net.if.in` + `net.if.out` (WAN) | Pisca dinamicamente (*traffic flicker*) acelerando conforme o tráfego (`> 20 Mbps` = rápido). |
| **LED `LOS/ALM`** | `icmpping` / `icmppingloss` | Apagado quando íntegro (`0%` perda); **Âmbar** se perda `> 5%`; **Vermelho piscante** se host `OFFLINE`. |
| **Portas `LAN 1` a `LAN 4`** | Interfaces LAN secundárias (`CNX_LAN`, `Gi0/1`, `eth2`, etc.) | Conectores RJ45 com pinos dourados e LED próprio. Portas reais conectadas ficam acesas e **clicáveis** (exibindo o gráfico daquela LAN). Portas sem interface SNMP ficam esmaecidas (`35%` opacidade). |

---

## 3. KPIs Estatísticos e Osciloscópio de 60 FPS

1. **Download Atual (`⬇ RX`) & Upload Atual (`⬆ TX`)**:
   - Exibem a última leitura em tempo real, barra de proporção em relação ao pico da janela, além da **Média** e do **Pico** daquela direção.
2. **Pico Máximo na Janela (`ÀS HH:MM`)**:
   - Identifica o maior pico registrado no período selecionado (`1H`, `3H`, `6H`, `12H`, `24H` ou `7D`) e informa o minuto exato em que ocorreu.
3. **Percentil 95 (`P95 WAN`)**:
   - Calcula estatisticamente o **Percentil 95** das amostras do período (métrica padrão de telecomunicações para dimensionamento de capacidade descartando os 5% de rajadas atípicas) e traça a **Linha P95** tracejada em âmbar no osciloscópio.
4. **Inspeção no Osciloscópio (Hover & Zoom)**:
   - **Hover:** Linha vertical tracejada, bolinhas amostrais nas curvas, auréolas luminosas (*target halos*) e cápsula flutuante superior com `[ HH:MM:SS | ● In | ● Out | Total ]`.
   - **Zoom:** Arraste o mouse horizontalmente sobre qualquer anomalia para dar zoom temporal; dê duplo clique ou clique em `↺ RESET ZOOM` para voltar.
   - **Toggles de Série:** Clique nos botões `Download (Inbound)`, `Upload (Outbound)` ou `Linha P95` para isolar curvas específicas.
