import os
import sys
import json
import time
import requests
from dotenv import load_dotenv

load_dotenv('.env')

ZABBIX_URL = os.getenv('ZABBIX_URL', 'http://10.10.1.26/api_jsonrpc.php')
ZABBIX_TOKEN = os.getenv('ZABBIX_TOKEN')
GRAFANA_URL = os.getenv('GRAFANA_URL', 'http://10.10.1.25:3000')
GRAFANA_USER = os.getenv('GRAFANA_USER', 'admin')
GRAFANA_PASSWORD = os.getenv('GRAFANA_PASSWORD', 'admin')

DASHBOARD_TITLE = "[SGS] - Modems & Links WAN (SGS_LINKS)"
DASHBOARD_UID = "sgs-modems-wan"
TARGET_FOLDER_ID = 136  # POC ALEX
TARGET_GROUP_NAME = "SGS_LINKS_GRAFANA"
FALLBACK_GROUP_NAME = "SGS_LINKS"
FALLBACK_GROUP_ID = "38"

print(f"=== INICIANDO BUILD DO GÊMEO DIGITAL DE MODEMS/LINKS SGS ===")
print(f"Zabbix: {ZABBIX_URL}")
print(f"Grafana: {GRAFANA_URL} (Pasta ID: {TARGET_FOLDER_ID})")

headers = {'Authorization': f'Bearer {ZABBIX_TOKEN}', 'Content-Type': 'application/json-rpc'}

# 1. Procurar pelo grupo prioritário SGS_LINKS_GRAFANA (ou fallback para SGS_LINKS)
print(f"1. Verificando grupo dinâmico '{TARGET_GROUP_NAME}' no Zabbix...")
r_groups = requests.post(ZABBIX_URL, json={
    'jsonrpc': '2.0',
    'method': 'hostgroup.get',
    'params': {
        'search': {'name': 'SGS_LINKS'},
        'output': ['groupid', 'name']
    },
    'id': 1
}, headers=headers).json()

discovered_groups = r_groups.get('result', [])
target_group = None
fallback_group = None

for g in discovered_groups:
    gname = g['name'].upper()
    if gname == TARGET_GROUP_NAME or gname.endswith('/' + TARGET_GROUP_NAME):
        target_group = g
    elif gname == FALLBACK_GROUP_NAME or g['groupid'] == FALLBACK_GROUP_ID:
        fallback_group = g

active_group_id = FALLBACK_GROUP_ID
active_group_name = FALLBACK_GROUP_NAME
is_dedicated_group = False

if target_group:
    # Verificar se há hosts dentro do grupo SGS_LINKS_GRAFANA
    r_check_hosts = requests.post(ZABBIX_URL, json={
        'jsonrpc': '2.0',
        'method': 'host.get',
        'params': {
            'groupids': target_group['groupid'],
            'output': ['hostid', 'status']
        },
        'id': 2
    }, headers=headers).json()
    active_target_hosts = [h for h in r_check_hosts.get('result', []) if h.get('status') == '0']
    if len(active_target_hosts) > 0:
        active_group_id = target_group['groupid']
        active_group_name = target_group['name']
        is_dedicated_group = True
        print(f"   [OK] Grupo dedicado '{active_group_name}' (ID: {active_group_id}) ativo com {len(active_target_hosts)} hosts!")
    else:
        print(f"   [INFO] Grupo '{target_group['name']}' encontrado (ID: {target_group['groupid']}), porém ainda sem hosts ativos. Usando '{FALLBACK_GROUP_NAME}' como base inicial.")
else:
    print(f"   [INFO] Grupo '{TARGET_GROUP_NAME}' ainda não visível/criado para a API. Usando '{FALLBACK_GROUP_NAME}' (ID: {FALLBACK_GROUP_ID}) como catálogo inicial.")
    print(f"   [INFO] Assim que '{TARGET_GROUP_NAME}' for criado e populado no Zabbix, o navegador descobrirá os novos links automaticamente em tempo real!")

# 2. Obter todos os hosts do grupo selecionado
print(f"2. Consultando hosts do grupo '{active_group_name}' (ID: {active_group_id})...")
r_hosts = requests.post(ZABBIX_URL, json={
    'jsonrpc': '2.0',
    'method': 'host.get',
    'params': {
        'groupids': active_group_id,
        'output': ['hostid', 'name', 'status', 'description'],
        'selectInterfaces': ['ip', 'port', 'type', 'available'],
        'selectParentTemplates': ['name']
    },
    'id': 3
}, headers=headers).json()

hosts = [h for h in r_hosts.get('result', []) if h['status'] == '0']
print(f"Encontrados {len(hosts)} hosts ativos no grupo {active_group_name}.")

# 3. Obter itens de tráfego (net.if) e ICMP para os hosts
print("3. Consultando itens de tráfego (net.if) e ICMP...")
host_ids = [h['hostid'] for h in hosts]

items = []
icmp_items = []
if host_ids:
    r_items = requests.post(ZABBIX_URL, json={
        'jsonrpc': '2.0',
        'method': 'item.get',
        'params': {
            'hostids': host_ids,
            'search': {'key_': 'net.if.'},
            'output': ['itemid', 'hostid', 'name', 'key_', 'lastvalue', 'units', 'value_type', 'status']
        },
        'id': 4
    }, headers=headers).json()
    items = [i for i in r_items.get('result', []) if i['status'] == '0']

    r_icmp = requests.post(ZABBIX_URL, json={
        'jsonrpc': '2.0',
        'method': 'item.get',
        'params': {
            'hostids': host_ids,
            'search': {'key_': 'icmp'},
            'output': ['itemid', 'hostid', 'name', 'key_', 'lastvalue', 'units', 'value_type']
        },
        'id': 5
    }, headers=headers).json()
    icmp_items = r_icmp.get('result', [])

print(f"Encontrados {len(items)} itens net.if ativos e {len(icmp_items)} itens ICMP.")

ISP_LIST = ["VIVO", "ALGAR", "VEGANET", "DESKTOP", "STARLINK", "HUGHESNET", "EMBRATEL", "CLARO", "OI", "NET", "EVOLNET", "GT CONECT", "DBT"]

def detect_isp(name_str):
    u = (name_str or "").upper()
    for op in ISP_LIST:
        if op in u:
            return op
    return "TELECOM"

hosts_catalog = []

for h in hosts:
    # No grupo fallback SGS_LINKS filtramos switches; no grupo dedicado SGS_LINKS_GRAFANA respeitamos 100% o que o NOC colocar
    if not is_dedicated_group and 'switch' in h['name'].lower():
        continue

    hid = h['hostid']
    h_items = [i for i in items if i['hostid'] == hid]

    if not is_dedicated_group and not h_items:
        continue

    ifaces_map = {}
    for it in h_items:
        k = it['key_']
        idx = None
        if '[' in k and ']' in k:
            param = k.split('[')[1].split(']')[0]
            if '.' in param:
                idx = param.split('.')[-1]
            else:
                idx = param
        else:
            idx = it['name']

        if idx not in ifaces_map:
            raw_name = it['name']
            clean_name = raw_name
            if 'Interface ' in raw_name:
                clean_name = raw_name.split('Interface ')[1].split(':')[0].strip()
            elif ':' in raw_name:
                clean_name = raw_name.split(':')[0].strip()

            ifaces_map[idx] = {
                'id': idx,
                'name': clean_name,
                'rawName': it['name'],
                'inItem': None,
                'outItem': None,
                'errorsItem': None,
                'discardsItem': None,
                'speed': 1000000000,
                'status': 1
            }

        try:
            lv = float(it['lastvalue']) if it.get('lastvalue') is not None else 0.0
        except Exception:
            lv = 0.0

        if 'net.if.in[' in k:
            ifaces_map[idx]['inItem'] = {
                'itemid': it['itemid'],
                'key': k,
                'valueType': it['value_type'],
                'lastvalue': lv
            }
        elif 'net.if.out[' in k:
            ifaces_map[idx]['outItem'] = {
                'itemid': it['itemid'],
                'key': k,
                'valueType': it['value_type'],
                'lastvalue': lv
            }
        elif 'errors' in k:
            ifaces_map[idx]['errorsItem'] = it['itemid']
        elif 'discards' in k:
            ifaces_map[idx]['discardsItem'] = it['itemid']

    valid_ifaces = [ifdata for ifdata in ifaces_map.values() if ifdata['inItem'] or ifdata['outItem']]

    if not valid_ifaces:
        if is_dedicated_group:
            # Se está no grupo SGS_LINKS_GRAFANA mas o LLD SNMP acabou de ser criado e ainda não descobriu as interfaces
            valid_ifaces = [{
                'id': 'pending_lld',
                'name': 'AGUARDANDO DESCOBERTA SNMP (LLD)...',
                'rawName': 'Aguardando LLD',
                'inItem': None,
                'outItem': None,
                'errorsItem': None,
                'discardsItem': None,
                'speed': 1000000000,
                'status': 1
            }]
        else:
            continue

    def iface_priority(x):
        score = 0
        name_upper = x['name'].upper()
        if 'WAN' in name_upper or 'INTERNET' in name_upper or 'LINK' in name_upper:
            score += 100000000
        in_val = x['inItem']['lastvalue'] if x['inItem'] else 0
        out_val = x['outItem']['lastvalue'] if x['outItem'] else 0
        score += (in_val + out_val)
        return score

    valid_ifaces.sort(key=iface_priority, reverse=True)

    h_name = h['name']
    isp = detect_isp(h_name)

    ifaces_list = h.get('interfaces', [])
    # Priorizar interface SNMP (type 2) se existir
    snmp_if = next((i for i in ifaces_list if str(i.get('type')) == '2'), None)
    chosen_if = snmp_if or (ifaces_list[0] if ifaces_list else {})
    ip = chosen_if.get('ip', 'N/A')

    h_icmp = [i for i in icmp_items if i['hostid'] == hid]
    ping_item = next((i['itemid'] for i in h_icmp if 'icmpping[' in i['key_'] or i['key_'] == 'icmpping'), None)
    sec_item = next((i['itemid'] for i in h_icmp if 'icmppingsec' in i['key_']), None)
    loss_item = next((i['itemid'] for i in h_icmp if 'icmppingloss' in i['key_']), None)

    ping_val = next((float(i['lastvalue']) for i in h_icmp if ('icmpping[' in i['key_'] or i['key_'] == 'icmpping') and i.get('lastvalue') is not None), 1.0)
    sec_val = next((float(i['lastvalue']) for i in h_icmp if 'icmppingsec' in i['key_'] and i.get('lastvalue') is not None), 0.0)
    loss_val = next((float(i['lastvalue']) for i in h_icmp if 'icmppingloss' in i['key_'] and i.get('lastvalue') is not None), 0.0)

    total_in = sum((x['inItem']['lastvalue'] if x['inItem'] else 0) for x in valid_ifaces)
    total_out = sum((x['outItem']['lastvalue'] if x['outItem'] else 0) for x in valid_ifaces)

    hosts_catalog.append({
        'hostid': hid,
        'name': h_name,
        'isp': isp,
        'ip': ip,
        'templates': [t['name'] for t in h.get('parentTemplates', [])],
        'interfaces': valid_ifaces,
        'pingItem': ping_item,
        'secItem': sec_item,
        'lossItem': loss_item,
        'pingVal': ping_val,
        'secVal': sec_val,
        'lossVal': loss_val,
        'totalIn': total_in,
        'totalOut': total_out,
        'totalTraffic': total_in + total_out
    })

hosts_catalog.sort(key=lambda x: x['name'])
print(f"Total de {len(hosts_catalog)} modems/links catalogados com sucesso!")

catalog_json = json.dumps(hosts_catalog, ensure_ascii=False)
initial_group_meta = json.dumps({
    "groupName": active_group_name,
    "groupId": active_group_id,
    "isDedicated": is_dedicated_group,
    "targetGroupName": TARGET_GROUP_NAME,
    "fallbackGroupName": FALLBACK_GROUP_NAME,
    "fallbackGroupId": FALLBACK_GROUP_ID
}, ensure_ascii=False)

# 4. Construir o HTML, CSS e JavaScript do Business Text
print("4. Construindo componentes da UI aprimorada (HTML, CSS, JS)...")

html_content = r"""
<div class="sgs-modem-container">
  <!-- Top Navigation & Auto-Discovery Bar -->
  <div class="sgs-top-bar">
    <div class="sgs-brand-block">
      <span class="sgs-status-orb" id="sgs-orb-status"></span>
      <div class="sgs-brand-text">
        <div class="sgs-title-row">
          <span class="sgs-title-main">SGS WAN GATEWAY & MODEM TWIN</span>
          <span class="sgs-group-pill" id="sgs-group-badge" title="Grupo Zabbix monitorado em tempo real via Auto-Discovery">
            ⚡ AUTO-DISCOVERY: CARREGANDO...
          </span>
        </div>
        <span class="sgs-title-sub" id="sgs-sync-status">
          Sincronização dinâmica Zabbix JSON-RPC • Tudo no grupo SGS_LINKS_GRAFANA entra automaticamente
        </span>
      </div>
    </div>

    <div class="sgs-selectors-group">
      <div class="sgs-search-wrap" id="sgs-search-mount">
        <span class="sgs-search-icon">🔍</span>
        <!-- Input injetado via JS para passar pelo sanitizador DOMPurify do Grafana -->
      </div>

      <div class="sgs-field">
        <label><span class="sgs-icon">🌐</span> LINK (<span id="sgs-host-count">0</span>):</label>
        <select id="sgs-host-select" class="sgs-select">
          <!-- Injetado dinamicamente -->
        </select>
      </div>

      <div class="sgs-field">
        <label><span class="sgs-icon">🔌</span> PORTA:</label>
        <select id="sgs-iface-select" class="sgs-select sgs-select-iface">
          <!-- Injetado dinamicamente -->
        </select>
      </div>

      <div class="sgs-time-pill-group">
        <button class="sgs-time-pill" data-sec="3600">1H</button>
        <button class="sgs-time-pill" data-sec="10800">3H</button>
        <button class="sgs-time-pill active" data-sec="21600">6H</button>
        <button class="sgs-time-pill" data-sec="43200">12H</button>
        <button class="sgs-time-pill" data-sec="86400">24H</button>
        <button class="sgs-time-pill" data-sec="604800">7D</button>
      </div>

      <button id="sgs-sync-btn" class="sgs-btn-refresh" title="Sincronizar Novos Links do Grupo SGS_LINKS_GRAFANA & Atualizar Telemetria">
        <span class="sgs-spin-icon" id="sgs-spin-icon">↻</span> SYNC
      </button>
    </div>
  </div>

  <!-- Quick ISP Filter Pills Bar -->
  <div class="sgs-filter-bar">
    <div class="sgs-filter-left">
      <span class="sgs-filter-label">FILTRO POR OPERADORA:</span>
      <div class="sgs-isp-pills" id="sgs-isp-pills">
        <!-- Pílulas geradas dinamicamente (TODOS, VIVO, ALGAR, VEGANET...) -->
      </div>
    </div>
    <div class="sgs-filter-right">
      <span class="sgs-aggregate-stat" id="sgs-aggregate-stat">
        Banda Agregada do Grupo: <b style="color:#00e676">⬇ --</b> • <b style="color:#a855f7">⬆ --</b>
      </span>
    </div>
  </div>

  <!-- Physical Chassis of the Modem / ONT / Router -->
  <div class="sgs-chassis-wrap">
    <div class="sgs-chassis">
      <!-- Metallic Bevel Top -->
      <div class="sgs-chassis-top-bevel">
        <span class="sgs-chassis-model" id="sgs-chassis-model">HIGH-CAPACITY SNMP WAN GATEWAY • TELEMETRIA L2/L3</span>
        <div class="sgs-vent-slots">
          <span></span><span></span><span></span><span></span><span></span>
          <span></span><span></span><span></span><span></span><span></span>
          <span></span><span></span><span></span><span></span>
        </div>
      </div>

      <!-- Main Faceplate -->
      <div class="sgs-faceplate">
        <!-- Device Info Left -->
        <div class="sgs-device-badge">
          <div class="sgs-badge-row">
            <span class="sgs-isp-tag" id="sgs-isp-badge">VIVO</span>
            <span class="sgs-hostid-tag" id="sgs-hostid-badge">ID: --</span>
          </div>
          <div class="sgs-dev-name" id="sgs-dev-name">SELECIONE UM LINK</div>
          <div class="sgs-dev-meta">
            <span class="sgs-meta-pill copyable" id="sgs-dev-ip" title="Clique para copiar o endereço IP">IP: -- 📋</span>
            <span class="sgs-meta-pill" id="sgs-dev-ping">LATÊNCIA: --</span>
            <span class="sgs-meta-pill" id="sgs-dev-loss">PERDA: 0%</span>
            <span class="sgs-meta-pill online" id="sgs-dev-health">STATUS: ONLINE</span>
          </div>
        </div>

        <!-- Center: Authentic Optical SFP/PON + LED Matrix + 4x RJ45 LAN Ports -->
        <div class="sgs-led-cluster">
          <!-- Optical PON / SFP Cage -->
          <div class="sgs-sfp-unit sgs-clickable-wan" id="sgs-btn-sfp-wan" title="Porta Óptica WAN / Uplink (Clique para inspecionar no osciloscópio)">
            <div class="sgs-sfp-cage" id="sgs-sfp-cage">
              <div class="sgs-sfp-inner">
                <span class="sgs-sfp-laser"></span>
              </div>
            </div>
            <span class="sgs-led-label">WAN SFP</span>
          </div>

          <div class="sgs-led-separator"></div>

          <!-- Status LEDs -->
          <div class="sgs-led-unit" title="Alimentação Elétrica do Equipamento (Host Ativo)">
            <div class="sgs-led sgs-led-pwr sgs-led-green" id="sgs-led-pwr"></div>
            <span class="sgs-led-label">PWR</span>
          </div>
          <div class="sgs-led-unit sgs-clickable-wan" id="sgs-btn-wan-pon" title="Sincronismo Óptico / Link WAN (Clique para ver no osciloscópio)">
            <div class="sgs-led sgs-led-pon sgs-led-green" id="sgs-led-pon"></div>
            <span class="sgs-led-label">PON/LINK</span>
          </div>
          <div class="sgs-led-unit sgs-clickable-wan" id="sgs-btn-wan-net" title="Tráfego de Dados WAN (Clique para ver no osciloscópio)">
            <div class="sgs-led sgs-led-wan sgs-led-cyan sgs-led-flicker" id="sgs-led-wan"></div>
            <span class="sgs-led-label">INTERNET</span>
          </div>
          <div class="sgs-led-unit" title="Alarme de Perda de Sinal / Pacotes (LOS / Packet Loss)">
            <div class="sgs-led" id="sgs-led-los"></div>
            <span class="sgs-led-label">LOS/ALM</span>
          </div>

          <div class="sgs-led-separator"></div>

          <!-- LAN 1 to 4 Ports (Mini Receptacles with Dynamic LEDs) -->
          <div class="sgs-lan-ports" id="sgs-lan-ports">
            <div class="sgs-lan-unit" id="sgs-lan-unit-0" data-slot="0">
              <div class="sgs-mini-rj45" id="sgs-rj45-0">
                <div class="sgs-rj45-pins"><i></i><i></i><i></i><i></i></div>
              </div>
              <div class="sgs-led sgs-led-lan" id="sgs-led-lan0"></div>
              <span class="sgs-led-label" id="sgs-label-lan0">LAN 1</span>
            </div>
            <div class="sgs-lan-unit" id="sgs-lan-unit-1" data-slot="1">
              <div class="sgs-mini-rj45" id="sgs-rj45-1">
                <div class="sgs-rj45-pins"><i></i><i></i><i></i><i></i></div>
              </div>
              <div class="sgs-led sgs-led-lan" id="sgs-led-lan1"></div>
              <span class="sgs-led-label" id="sgs-label-lan1">LAN 2</span>
            </div>
            <div class="sgs-lan-unit" id="sgs-lan-unit-2" data-slot="2">
              <div class="sgs-mini-rj45" id="sgs-rj45-2">
                <div class="sgs-rj45-pins"><i></i><i></i><i></i><i></i></div>
              </div>
              <div class="sgs-led sgs-led-lan" id="sgs-led-lan2"></div>
              <span class="sgs-led-label" id="sgs-label-lan2">LAN 3</span>
            </div>
            <div class="sgs-lan-unit" id="sgs-lan-unit-3" data-slot="3">
              <div class="sgs-mini-rj45" id="sgs-rj45-3">
                <div class="sgs-rj45-pins"><i></i><i></i><i></i><i></i></div>
              </div>
              <div class="sgs-led sgs-led-lan" id="sgs-led-lan3"></div>
              <span class="sgs-led-label" id="sgs-label-lan3">LAN 4</span>
            </div>
          </div>
        </div>

        <!-- Right Quick Meter & Inventory -->
        <div class="sgs-chassis-right">
          <div class="sgs-speed-pill-box">
            <div class="sgs-speed-row">
              <span class="sgs-dir-icon in">⬇ RX:</span>
              <span class="sgs-speed-val" id="sgs-quick-in">0.00 Mb/s</span>
            </div>
            <div class="sgs-speed-row">
              <span class="sgs-dir-icon out">⬆ TX:</span>
              <span class="sgs-speed-val" id="sgs-quick-out">0.00 Mb/s</span>
            </div>
          </div>
          <div class="sgs-chassis-actions">
            <button id="sgs-btn-drawer" class="sgs-btn-info" title="Abrir Gaveta de Inventário SNMP & Detalhes do Grupo">
              ℹ️ INVENTÁRIO
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- 5 Enhanced KPI Cards Grid -->
  <div class="sgs-kpi-grid">
    <div class="sgs-kpi-card sgs-kpi-in">
      <div class="sgs-kpi-header">
        <span class="sgs-kpi-title">DOWNLOAD ATUAL (IN)</span>
        <span class="sgs-kpi-badge in">⬇ RX</span>
      </div>
      <div class="sgs-kpi-val" id="sgs-kpi-in-val">--</div>
      <div class="sgs-kpi-bar-bg"><div class="sgs-kpi-bar-fill in" id="sgs-kpi-in-bar" style="width:0%"></div></div>
      <div class="sgs-kpi-sub" id="sgs-kpi-in-sub">Média: -- • Pico: --</div>
    </div>

    <div class="sgs-kpi-card sgs-kpi-out">
      <div class="sgs-kpi-header">
        <span class="sgs-kpi-title">UPLOAD ATUAL (OUT)</span>
        <span class="sgs-kpi-badge out">⬆ TX</span>
      </div>
      <div class="sgs-kpi-val" id="sgs-kpi-out-val">--</div>
      <div class="sgs-kpi-bar-bg"><div class="sgs-kpi-bar-fill out" id="sgs-kpi-out-bar" style="width:0%"></div></div>
      <div class="sgs-kpi-sub" id="sgs-kpi-out-sub">Média: -- • Pico: --</div>
    </div>

    <div class="sgs-kpi-card">
      <div class="sgs-kpi-header">
        <span class="sgs-kpi-title">PICO MÁXIMO NA JANELA</span>
        <span class="sgs-kpi-badge peak" id="sgs-kpi-peak-time">MAX</span>
      </div>
      <div class="sgs-kpi-val" id="sgs-kpi-peak-val">--</div>
      <div class="sgs-kpi-bar-bg"><div class="sgs-kpi-bar-fill peak" id="sgs-kpi-peak-bar" style="width:100%"></div></div>
      <div class="sgs-kpi-sub" id="sgs-kpi-peak-sub">⬆ Pico Upload: --</div>
    </div>

    <div class="sgs-kpi-card">
      <div class="sgs-kpi-header">
        <span class="sgs-kpi-title">PERCENTIL 95 & MÉDIA</span>
        <span class="sgs-kpi-badge avg">P95 WAN</span>
      </div>
      <div class="sgs-kpi-val" id="sgs-kpi-avg-val">--</div>
      <div class="sgs-kpi-bar-bg"><div class="sgs-kpi-bar-fill avg" id="sgs-kpi-avg-bar" style="width:0%"></div></div>
      <div class="sgs-kpi-sub" id="sgs-kpi-avg-sub">Média In: -- | Out: --</div>
    </div>

    <div class="sgs-kpi-card">
      <div class="sgs-kpi-header">
        <span class="sgs-kpi-title">QUALIDADE & SAÚDE WAN</span>
        <span class="sgs-kpi-badge status" id="sgs-kpi-health-badge">SAUDÁVEL</span>
      </div>
      <div class="sgs-kpi-val" id="sgs-kpi-health-val">100% UP</div>
      <div class="sgs-kpi-bar-bg"><div class="sgs-kpi-bar-fill health" id="sgs-kpi-health-bar" style="width:100%"></div></div>
      <div class="sgs-kpi-sub" id="sgs-kpi-health-sub">Latência: -- • Perda: 0%</div>
    </div>
  </div>

  <!-- Main Oscilloscope Section -->
  <div class="sgs-chart-card">
    <div class="sgs-chart-header">
      <div class="sgs-chart-title-wrap">
        <span class="sgs-chart-title">OSCILOSCÓPIO DE TRÁFEGO WAN EM TEMPO REAL</span>
        <span class="sgs-chart-sub" id="sgs-chart-sub">Interface: --</span>
      </div>
      <div class="sgs-chart-legend">
        <button class="sgs-leg-btn active" id="sgs-toggle-in" title="Clique para exibir/ocultar curva de Download">
          <i class="leg-in"></i> Download (Inbound)
        </button>
        <button class="sgs-leg-btn active" id="sgs-toggle-out" title="Clique para exibir/ocultar curva de Upload">
          <i class="leg-out"></i> Upload (Outbound)
        </button>
        <button class="sgs-leg-btn active" id="sgs-toggle-p95" title="Clique para exibir/ocultar linha de referência Percentil 95">
          <i class="leg-p95"></i> Linha P95
        </button>
        <button id="sgs-btn-reset-zoom" class="sgs-btn-reset-zoom" style="display:none;">↺ RESET ZOOM</button>
        <span class="sgs-chart-hint">✦ passe o mouse p/ inspecionar • arraste p/ zoom</span>
      </div>
    </div>

    <!-- Canvas container with drag-to-zoom and tooltip HUD -->
    <div class="sgs-canvas-wrap" id="sgs-canvas-wrap">
      <!-- Floating Interactive Tooltip HUD like the Switch -->
      <div id="sgs-canvas-tooltip" class="sgs-canvas-tooltip" style="display: none;">
        <span id="sgs-tt-time" class="sgs-tt-time">--:--:--</span>
        <span class="sgs-tt-in"><span class="sgs-tt-dot in"></span>In: <span id="sgs-tt-in-val">0 bps</span></span>
        <span class="sgs-tt-out"><span class="sgs-tt-dot out"></span>Out: <span id="sgs-tt-out-val">0 bps</span></span>
        <span class="sgs-tt-total">Total: <span id="sgs-tt-total-val">0 bps</span></span>
      </div>
      <canvas id="sgs-traffic-canvas"></canvas>
    </div>
  </div>

  <!-- Bottom Grid: Interfaces & Live Group Leaderboard -->
  <div class="sgs-bottom-grid">
    <!-- Left: Interfaces Table -->
    <div class="sgs-panel-box sgs-iface-box">
      <div class="sgs-panel-header">
        <span>INTERFACES DETECTADAS NO ATIVO SELECIONADO</span>
        <span class="sgs-panel-badge" id="sgs-iface-count">0 interfaces</span>
      </div>
      <div class="sgs-table-wrap">
        <table class="sgs-table">
          <thead>
            <tr>
              <th>Interface</th>
              <th>Papel</th>
              <th>Status</th>
              <th>⬇ Download (In)</th>
              <th>⬆ Upload (Out)</th>
              <th>Ação</th>
            </tr>
          </thead>
          <tbody id="sgs-iface-tbody">
            <!-- Populado dinamicamente -->
          </tbody>
        </table>
      </div>
    </div>

    <!-- Right: Live Group Ranking / All Discovered Links -->
    <div class="sgs-panel-box sgs-top-links-box">
      <div class="sgs-panel-header">
        <span id="sgs-ranking-title">RANKING DE CONSUMO EM TEMPO REAL (TODOS OS LINKS)</span>
        <span class="sgs-panel-badge live" id="sgs-ranking-count">LIVE</span>
      </div>
      <div class="sgs-top-links-list" id="sgs-top-links-list">
        <!-- Populado dinamicamente -->
      </div>
    </div>
  </div>

  <!-- Slide-out Inventory Drawer -->
  <div class="sgs-drawer" id="sgs-drawer" style="display:none;">
    <div class="sgs-drawer-content">
      <div class="sgs-drawer-header">
        <span class="sgs-drawer-title">INVENTÁRIO DO ATIVO & AUTO-DISCOVERY ZABBIX</span>
        <button id="sgs-drawer-close" class="sgs-drawer-close">✕ FECHAR</button>
      </div>
      <div class="sgs-drawer-body" id="sgs-drawer-body">
        <!-- Populado dinamicamente -->
      </div>
    </div>
  </div>
</div>
"""

css_styles = r"""
.sgs-modem-container {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  color: #e2e8f0;
  background: #060a11;
  padding: 14px 16px;
  border-radius: 8px;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* Top Control Bar */
.sgs-top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: linear-gradient(180deg, #0f172a 0%, #0b111e 100%);
  border: 1px solid #1e293b;
  border-radius: 8px;
  padding: 10px 16px;
  box-shadow: 0 4px 14px rgba(0,0,0,0.5);
  flex-wrap: wrap;
  gap: 10px;
}
.sgs-brand-block {
  display: flex;
  align-items: center;
  gap: 10px;
}
.sgs-status-orb {
  width: 11px;
  height: 11px;
  border-radius: 50%;
  background: #00e676;
  box-shadow: 0 0 10px #00e676;
  display: inline-block;
  flex-shrink: 0;
  animation: sgsOrbPulse 2s infinite ease-in-out;
}
@keyframes sgsOrbPulse {
  0% { transform: scale(0.9); opacity: 0.8; }
  50% { transform: scale(1.15); opacity: 1; box-shadow: 0 0 16px #00e676; }
  100% { transform: scale(0.9); opacity: 0.8; }
}
.sgs-brand-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.sgs-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.sgs-title-main {
  font-size: 13px;
  font-weight: 800;
  letter-spacing: 0.6px;
  color: #f8fafc;
}
.sgs-group-pill {
  font-size: 9.5px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 12px;
  background: rgba(0, 230, 118, 0.14);
  color: #00e676;
  border: 1px solid rgba(0, 230, 118, 0.35);
  font-family: monospace;
  letter-spacing: 0.3px;
}
.sgs-group-pill.fallback {
  background: rgba(56, 189, 248, 0.14);
  color: #38bdf8;
  border-color: rgba(56, 189, 248, 0.35);
}
.sgs-title-sub {
  font-size: 10px;
  color: #64748b;
  letter-spacing: 0.2px;
}

.sgs-selectors-group {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.sgs-search-wrap {
  position: relative;
  display: flex;
  align-items: center;
}
.sgs-search-icon {
  position: absolute;
  left: 9px;
  font-size: 11px;
  pointer-events: none;
  opacity: 0.75;
  z-index: 2;
}
.sgs-search-input {
  background: #131b2e !important;
  border: 1px solid #25334d !important;
  border-radius: 5px !important;
  color: #f1f5f9 !important;
  font-size: 11px !important;
  height: 30px !important;
  line-height: 18px !important;
  padding: 4px 10px 4px 26px !important;
  width: 175px !important;
  outline: none !important;
  box-sizing: border-box !important;
  transition: all 0.2s ease;
}
.sgs-search-input::placeholder {
  color: #64748b !important;
}
.sgs-search-input:focus {
  border-color: #00b0ff !important;
  box-shadow: 0 0 8px rgba(0, 176, 255, 0.35) !important;
  width: 210px !important;
}

.sgs-field {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 10.5px;
  color: #94a3b8;
  font-weight: 700;
}
.sgs-select {
  background: #131b2e url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%2338bdf8' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E") no-repeat right 8px center !important;
  appearance: none !important;
  -webkit-appearance: none !important;
  -moz-appearance: none !important;
  color: #38bdf8 !important;
  border: 1px solid #25334d !important;
  border-radius: 5px !important;
  height: 30px !important;
  min-height: 30px !important;
  line-height: 18px !important;
  padding: 4px 26px 4px 10px !important;
  font-size: 11px !important;
  font-weight: 600 !important;
  outline: none !important;
  cursor: pointer !important;
  box-sizing: border-box !important;
  transition: all 0.2s ease;
  min-width: 225px;
  max-width: 310px;
}
.sgs-select option {
  background: #0f172a;
  color: #f1f5f9;
}
.sgs-select.sgs-select-iface {
  min-width: 155px;
  max-width: 215px;
}
.sgs-select:hover, .sgs-select:focus {
  border-color: #00b0ff !important;
  box-shadow: 0 0 8px rgba(0, 176, 255, 0.4) !important;
}
.sgs-time-pill-group {
  display: flex;
  background: #131b2e;
  border: 1px solid #25334d;
  border-radius: 5px;
  overflow: hidden;
  height: 30px;
  box-sizing: border-box;
}
.sgs-time-pill {
  background: transparent;
  color: #94a3b8;
  border: none;
  padding: 0 9px;
  font-size: 10.5px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.15s ease;
}
.sgs-time-pill:hover {
  color: #f8fafc;
  background: #1e293b;
}
.sgs-time-pill.active {
  background: #00b0ff;
  color: #050b14;
}
.sgs-btn-refresh {
  background: #162238;
  color: #38bdf8;
  border: 1px solid #293d5e;
  border-radius: 5px;
  height: 30px;
  padding: 0 11px;
  cursor: pointer;
  font-size: 10.5px;
  font-weight: 800;
  display: flex;
  align-items: center;
  gap: 5px;
  box-sizing: border-box;
  transition: all 0.2s ease;
}
.sgs-btn-refresh:hover {
  background: #00b0ff;
  color: #050b14;
  border-color: #00b0ff;
  box-shadow: 0 0 10px rgba(0, 176, 255, 0.5);
}
@keyframes sgsSpin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}
.sgs-spinning .sgs-spin-icon {
  display: inline-block;
  animation: sgsSpin 0.8s linear infinite;
}

/* Quick ISP Filter Bar */
.sgs-filter-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #0b111d;
  border: 1px solid #172236;
  border-radius: 6px;
  padding: 6px 14px;
  flex-wrap: wrap;
  gap: 10px;
}
.sgs-filter-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.sgs-filter-label {
  font-size: 9.5px;
  font-weight: 800;
  color: #64748b;
  letter-spacing: 0.6px;
}
.sgs-isp-pills {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.sgs-isp-pill {
  background: #131c2e;
  border: 1px solid #22304a;
  color: #94a3b8;
  font-size: 9.5px;
  font-weight: 700;
  padding: 3px 9px;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.sgs-isp-pill:hover {
  color: #f8fafc;
  border-color: #38bdf8;
}
.sgs-isp-pill.active {
  background: rgba(0, 176, 255, 0.2);
  color: #38bdf8;
  border-color: #00b0ff;
  box-shadow: 0 0 8px rgba(0, 176, 255, 0.3);
}
.sgs-aggregate-stat {
  font-size: 10.5px;
  color: #94a3b8;
  font-family: monospace;
}

/* Modem / ONT Physical Chassis */
.sgs-chassis-wrap {
  width: 100%;
}
.sgs-chassis {
  background: linear-gradient(180deg, #172033 0%, #0b111c 100%);
  border: 1px solid #263552;
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.6), inset 0 1px 0 rgba(255,255,255,0.08);
  overflow: hidden;
}
.sgs-chassis-top-bevel {
  background: #0f1624;
  border-bottom: 1px solid #1c2840;
  padding: 4px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.sgs-chassis-model {
  font-size: 8.5px;
  font-weight: 700;
  color: #475569;
  letter-spacing: 1px;
  font-family: monospace;
}
.sgs-vent-slots {
  display: flex;
  gap: 4px;
}
.sgs-vent-slots span {
  width: 14px;
  height: 2.5px;
  background: #06090e;
  border-radius: 1px;
}
.sgs-faceplate {
  padding: 10px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: nowrap;
}
@media (max-width: 1050px) {
  .sgs-faceplate { flex-wrap: wrap; }
}
.sgs-device-badge {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 220px;
  flex-shrink: 1;
}
.sgs-badge-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.sgs-isp-tag {
  display: inline-block;
  font-size: 9.5px;
  font-weight: 800;
  letter-spacing: 0.8px;
  padding: 2px 8px;
  border-radius: 3px;
  background: #660099;
  color: #ffffff;
  box-shadow: 0 0 8px rgba(102, 0, 153, 0.6);
}
.sgs-hostid-tag {
  font-size: 9px;
  color: #64748b;
  background: #0d1422;
  border: 1px solid #1e293b;
  padding: 1px 6px;
  border-radius: 3px;
  font-family: monospace;
}
.sgs-dev-name {
  font-size: 13px;
  font-weight: 800;
  color: #f8fafc;
  letter-spacing: 0.3px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sgs-dev-meta {
  display: flex;
  gap: 5px;
  flex-wrap: wrap;
}
.sgs-meta-pill {
  font-size: 9.5px;
  color: #cbd5e1;
  background: #0f172a;
  padding: 2px 6px;
  border-radius: 3px;
  border: 1px solid #1e293b;
  font-family: monospace;
  transition: all 0.15s ease;
}
.sgs-meta-pill.copyable {
  cursor: pointer;
}
.sgs-meta-pill.copyable:hover {
  border-color: #38bdf8;
  color: #38bdf8;
}
.sgs-meta-pill.online {
  color: #00e676;
  border-color: rgba(0, 230, 118, 0.35);
  background: rgba(0, 230, 118, 0.08);
}

/* LED Cluster & SFP Optical Port */
.sgs-led-cluster {
  display: flex;
  align-items: center;
  gap: 11px;
  background: #080d16;
  padding: 7px 14px;
  border-radius: 6px;
  border: 1px solid #192438;
  box-shadow: inset 0 2px 6px rgba(0,0,0,0.85);
  flex-shrink: 0;
}
.sgs-sfp-unit {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
}
.sgs-sfp-cage {
  width: 24px;
  height: 14px;
  background: #141c2b;
  border: 1px solid #475569;
  border-radius: 2px;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: inset 0 1px 3px #000;
}
.sgs-sfp-inner {
  width: 16px;
  height: 8px;
  background: #090d14;
  border: 1px solid #00b0ff;
  border-radius: 1px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.sgs-sfp-laser {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #00b0ff;
  box-shadow: 0 0 6px #00b0ff;
}

.sgs-led-unit {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}
.sgs-led {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #263246;
  box-shadow: inset 0 1px 2px rgba(0,0,0,0.8);
  transition: all 0.2s ease;
}
.sgs-led-green {
  background: #00e676;
  box-shadow: 0 0 8px #00e676, inset 0 1px 1px rgba(255,255,255,0.6);
}
.sgs-led-cyan {
  background: #00b0ff;
  box-shadow: 0 0 8px #00b0ff, inset 0 1px 1px rgba(255,255,255,0.6);
}
.sgs-led-red {
  background: #ef4444;
  box-shadow: 0 0 8px #ef4444;
}
.sgs-led-amber {
  background: #f59e0b;
  box-shadow: 0 0 8px #f59e0b;
}
@keyframes sgsFlicker {
  0% { opacity: 1; filter: drop-shadow(0 0 3px currentColor); }
  15% { opacity: 0.22; }
  30% { opacity: 0.95; filter: drop-shadow(0 0 5px currentColor); }
  55% { opacity: 0.28; }
  75% { opacity: 1; filter: drop-shadow(0 0 4px currentColor); }
  90% { opacity: 0.25; }
  100% { opacity: 1; }
}
.sgs-led-flicker {
  animation: sgsFlicker 0.4s infinite cubic-bezier(0.4, 0, 0.6, 1);
}
.sgs-led-label {
  font-size: 8.5px;
  font-weight: 700;
  color: #64748b;
  letter-spacing: 0.4px;
  white-space: nowrap;
}
.sgs-led-separator {
  width: 1px;
  height: 26px;
  background: #1e293b;
}

/* LAN Mini Receptacles */
.sgs-lan-ports {
  display: flex;
  gap: 7px;
}
.sgs-lan-unit {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  padding: 3px 5px;
  border-radius: 4px;
  transition: all 0.2s ease;
  user-select: none;
}
.sgs-lan-unit.clickable {
  cursor: pointer;
}
.sgs-lan-unit.clickable:hover {
  background: rgba(255, 255, 255, 0.08);
}
.sgs-lan-unit.selected {
  background: rgba(0, 176, 255, 0.2);
  box-shadow: 0 0 8px rgba(0, 176, 255, 0.5);
}
.sgs-clickable-wan {
  cursor: pointer;
  padding: 3px 5px;
  border-radius: 4px;
  transition: all 0.2s ease;
  user-select: none;
}
.sgs-clickable-wan:hover {
  background: rgba(255, 255, 255, 0.08);
}
.sgs-clickable-wan.selected {
  background: rgba(0, 176, 255, 0.2);
  box-shadow: 0 0 8px rgba(0, 176, 255, 0.5);
}
.sgs-mini-rj45 {
  width: 18px;
  height: 12px;
  background: #141b27;
  border: 1px solid #334155;
  border-radius: 2px;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: inset 0 1px 3px rgba(0,0,0,0.8);
  transition: all 0.2s ease;
}
.sgs-mini-rj45.active {
  border-color: #00e676;
}
.sgs-mini-rj45.selected {
  border-color: #00b0ff;
  box-shadow: 0 0 8px #00b0ff;
}
.sgs-rj45-pins {
  display: flex;
  gap: 1.5px;
}
.sgs-rj45-pins i {
  width: 1px;
  height: 4px;
  background: #ffd700;
  display: inline-block;
}

/* Chassis Right Info & Button */
.sgs-chassis-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}
.sgs-speed-pill-box {
  background: #080d16;
  border: 1px solid #1a253a;
  border-radius: 5px;
  padding: 5px 10px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 122px;
}
.sgs-speed-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  font-size: 11px;
  font-family: monospace;
}
.sgs-dir-icon.in { color: #00e676; font-weight: 700; }
.sgs-dir-icon.out { color: #a855f7; font-weight: 700; }
.sgs-speed-val { color: #f8fafc; font-weight: 700; }
.sgs-btn-info {
  background: #131b2e;
  border: 1px solid #25334d;
  color: #38bdf8;
  font-size: 10px;
  font-weight: 700;
  padding: 8px 11px;
  border-radius: 5px;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
}
.sgs-btn-info:hover {
  background: #00b0ff;
  color: #050b14;
  border-color: #00b0ff;
  box-shadow: 0 0 10px rgba(0, 176, 255, 0.5);
}

/* KPI Cards Grid */
.sgs-kpi-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
}
@media (max-width: 1100px) {
  .sgs-kpi-grid { grid-template-columns: repeat(auto-fit, minmax(185px, 1fr)); }
}
.sgs-kpi-card {
  background: #0d131f;
  border: 1px solid #1e293b;
  border-radius: 7px;
  padding: 11px 14px;
  display: flex;
  flex-direction: column;
  gap: 5px;
  box-shadow: 0 3px 8px rgba(0,0,0,0.35);
}
.sgs-kpi-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.sgs-kpi-title {
  font-size: 9.5px;
  font-weight: 800;
  color: #94a3b8;
  letter-spacing: 0.5px;
}
.sgs-kpi-badge {
  font-size: 9px;
  font-weight: 800;
  padding: 1px 6px;
  border-radius: 3px;
  font-family: monospace;
}
.sgs-kpi-badge.in { background: rgba(0, 230, 118, 0.15); color: #00e676; }
.sgs-kpi-badge.out { background: rgba(168, 85, 247, 0.15); color: #a855f7; }
.sgs-kpi-badge.peak { background: rgba(245, 158, 11, 0.15); color: #f59e0b; }
.sgs-kpi-badge.avg { background: rgba(56, 189, 248, 0.15); color: #38bdf8; }
.sgs-kpi-badge.status { background: rgba(16, 185, 129, 0.15); color: #10b981; }
.sgs-kpi-val {
  font-size: 19px;
  font-weight: 800;
  color: #f8fafc;
  letter-spacing: -0.4px;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", monospace;
}
.sgs-kpi-in .sgs-kpi-val { color: #00e676; }
.sgs-kpi-out .sgs-kpi-val { color: #a855f7; }
.sgs-kpi-bar-bg {
  width: 100%;
  height: 4px;
  background: #162032;
  border-radius: 2px;
  overflow: hidden;
}
.sgs-kpi-bar-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.35s ease;
}
.sgs-kpi-bar-fill.in { background: linear-gradient(90deg, #00b0ff, #00e676); }
.sgs-kpi-bar-fill.out { background: linear-gradient(90deg, #6366f1, #a855f7); }
.sgs-kpi-bar-fill.peak { background: linear-gradient(90deg, #f59e0b, #ef4444); }
.sgs-kpi-bar-fill.avg { background: linear-gradient(90deg, #0284c7, #38bdf8); }
.sgs-kpi-bar-fill.health { background: #10b981; }
.sgs-kpi-sub {
  font-size: 10px;
  color: #64748b;
  font-family: monospace;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Oscilloscope Chart */
.sgs-chart-card {
  background: #0d131f;
  border: 1px solid #1e293b;
  border-radius: 8px;
  padding: 12px 16px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.4);
  display: flex;
  flex-direction: column;
  gap: 9px;
}
.sgs-chart-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
}
.sgs-chart-title {
  font-size: 12px;
  font-weight: 800;
  color: #f8fafc;
  letter-spacing: 0.6px;
}
.sgs-chart-sub {
  font-size: 11px;
  color: #38bdf8;
  margin-left: 8px;
  font-family: monospace;
}
.sgs-chart-legend {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.sgs-leg-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 10.5px;
  color: #64748b;
  font-weight: 700;
  background: #131c2e;
  border: 1px solid #1e293b;
  border-radius: 4px;
  padding: 3px 8px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.sgs-leg-btn.active {
  color: #e2e8f0;
  border-color: #2dd4bf44;
  background: #162238;
}
.sgs-leg-btn i {
  width: 9px;
  height: 9px;
  border-radius: 2px;
  display: inline-block;
}
.sgs-leg-btn i.leg-in { background: #00e676; box-shadow: 0 0 6px #00e676; }
.sgs-leg-btn i.leg-out { background: #a855f7; box-shadow: 0 0 6px #a855f7; }
.sgs-leg-btn i.leg-p95 { background: #f59e0b; border-radius: 0; height: 2px; width: 10px; }
.sgs-btn-reset-zoom {
  background: #1e293b;
  color: #f59e0b;
  border: 1px solid #f59e0b;
  border-radius: 4px;
  padding: 3px 8px;
  font-size: 10.5px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s ease;
}
.sgs-btn-reset-zoom:hover {
  background: #f59e0b;
  color: #050b14;
}
.sgs-canvas-wrap {
  position: relative;
  width: 100%;
  height: 225px;
  background: #080c14;
  border: 1px solid #162032;
  border-radius: 6px;
  overflow: hidden;
  cursor: crosshair;
}
#sgs-traffic-canvas {
  width: 100%;
  height: 100%;
  display: block;
}
.sgs-chart-hint {
  font-size: 9.5px;
  color: #64748b;
  font-family: monospace;
  margin-left: 4px;
}
.sgs-canvas-tooltip {
  position: absolute;
  top: 10px;
  background: rgba(11, 16, 26, 0.96);
  border: 1px solid #00b0ff;
  border-radius: 6px;
  padding: 4px 12px;
  font-size: 11px;
  color: #f8fafc;
  pointer-events: none;
  z-index: 1000;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.9);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  gap: 12px;
  white-space: nowrap;
  width: max-content;
  flex-shrink: 0;
}
.sgs-tt-time {
  color: #94a3b8;
  font-family: monospace;
  font-size: 10.5px;
  border-right: 1px solid #334155;
  padding-right: 8px;
  white-space: nowrap;
  flex-shrink: 0;
}
.sgs-tt-in {
  color: #00e676;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 5px;
  white-space: nowrap;
  flex-shrink: 0;
}
.sgs-tt-out {
  color: #a855f7;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 5px;
  white-space: nowrap;
  flex-shrink: 0;
}
.sgs-tt-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
}
.sgs-tt-dot.in {
  background: #00e676;
  box-shadow: 0 0 6px #00e676;
}
.sgs-tt-dot.out {
  background: #a855f7;
  box-shadow: 0 0 6px #a855f7;
}
.sgs-tt-total {
  color: #ffffff;
  font-weight: 700;
  border-left: 1px solid #334155;
  padding-left: 8px;
  white-space: nowrap;
  flex-shrink: 0;
}

/* Bottom Grid */
.sgs-bottom-grid {
  display: grid;
  grid-template-columns: 1.35fr 1fr;
  gap: 14px;
}
@media (max-width: 960px) {
  .sgs-bottom-grid { grid-template-columns: 1fr; }
}
.sgs-panel-box {
  background: #0d131f;
  border: 1px solid #1e293b;
  border-radius: 8px;
  padding: 12px 14px;
  box-shadow: 0 3px 10px rgba(0,0,0,0.3);
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.sgs-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 10.5px;
  font-weight: 800;
  color: #94a3b8;
  letter-spacing: 0.6px;
}
.sgs-panel-badge {
  font-size: 9.5px;
  background: #1e293b;
  color: #38bdf8;
  padding: 2px 7px;
  border-radius: 3px;
  font-family: monospace;
}
.sgs-panel-badge.live {
  background: rgba(0, 230, 118, 0.18);
  color: #00e676;
}
.sgs-table-wrap {
  overflow-x: auto;
  max-height: 230px;
  overflow-y: auto;
}
.sgs-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
}
.sgs-table th {
  text-align: left;
  color: #64748b;
  padding: 6px 8px;
  border-bottom: 1px solid #1e293b;
  font-weight: 700;
  position: sticky;
  top: 0;
  background: #0d131f;
}
.sgs-table td {
  padding: 6px 8px;
  border-bottom: 1px solid #141c2c;
  color: #cbd5e1;
}
.sgs-table tr:hover td {
  background: #141d2e;
}
.sgs-badge-role {
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 8.5px;
  font-weight: 800;
  font-family: monospace;
}
.sgs-badge-role.wan { background: rgba(0, 176, 255, 0.18); color: #38bdf8; }
.sgs-badge-role.lan { background: rgba(168, 85, 247, 0.18); color: #c084fc; }
.sgs-badge-status {
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 9px;
  font-weight: 700;
}
.sgs-badge-status.up { background: rgba(0, 230, 118, 0.15); color: #00e676; }
.sgs-badge-status.down { background: rgba(239, 68, 68, 0.15); color: #ef4444; }
.sgs-btn-select-if {
  background: #1e293b;
  border: 1px solid #334155;
  color: #38bdf8;
  padding: 2px 8px;
  border-radius: 3px;
  font-size: 9.5px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.15s ease;
}
.sgs-btn-select-if:hover, .sgs-btn-select-if.active {
  background: #00b0ff;
  color: #050b14;
  border-color: #00b0ff;
}

/* Live Links Ranking Leaderboard */
.sgs-top-links-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 230px;
  overflow-y: auto;
  padding-right: 4px;
}
.sgs-top-link-item {
  display: flex;
  flex-direction: column;
  gap: 5px;
  background: #111827;
  border: 1px solid #1f2937;
  border-radius: 6px;
  padding: 7px 10px;
  cursor: pointer;
  transition: all 0.18s ease;
}
.sgs-top-link-item:hover {
  border-color: #38bdf8;
  background: #152238;
}
.sgs-top-link-item.active {
  border-color: #00e676;
  background: rgba(0, 230, 118, 0.07);
  box-shadow: inset 2px 0 0 #00e676;
}
.sgs-top-link-row1 {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.sgs-top-link-name {
  font-size: 11px;
  font-weight: 700;
  color: #f1f5f9;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sgs-top-link-rate {
  font-size: 11.5px;
  font-weight: 800;
  color: #00e676;
  font-family: monospace;
  flex-shrink: 0;
}
.sgs-top-link-row2 {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 9.5px;
  color: #64748b;
  font-family: monospace;
}
.sgs-top-link-bar {
  width: 100%;
  height: 3px;
  background: #1e293b;
  border-radius: 2px;
  overflow: hidden;
}
.sgs-top-link-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, #00b0ff, #00e676);
  border-radius: 2px;
}

/* Slide Drawer */
.sgs-drawer {
  position: fixed;
  top: 0; right: 0; bottom: 0;
  width: 400px;
  background: #0d131f;
  border-left: 1px solid #00b0ff;
  box-shadow: -8px 0 24px rgba(0,0,0,0.85);
  z-index: 99999;
  display: flex;
  flex-direction: column;
}
.sgs-drawer-content {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  height: 100%;
}
.sgs-drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #1e293b;
  padding-bottom: 10px;
}
.sgs-drawer-title {
  font-size: 12px;
  font-weight: 800;
  color: #38bdf8;
}
.sgs-drawer-close {
  background: #1e293b;
  border: 1px solid #334155;
  color: #cbd5e1;
  padding: 3px 8px;
  border-radius: 4px;
  cursor: pointer;
}
.sgs-drawer-close:hover {
  background: #ef4444;
  color: #fff;
}
.sgs-drawer-body {
  font-size: 11px;
  color: #94a3b8;
  line-height: 1.6;
  overflow-y: auto;
}
"""

js_script = r"""
(function() {
  const ZABBIX_URL = "__ZABBIX_URL__";
  const ZABBIX_TOKEN = "__ZABBIX_TOKEN__";
  const INITIAL_CATALOG = __CATALOG_JSON__;
  const GROUP_META = __GROUP_META_JSON__;

  function getEl(id) {
    try {
      if (typeof element !== 'undefined' && element && element.querySelector) {
        const found = element.querySelector('#' + id);
        if (found) return found;
      }
      return document.getElementById(id);
    } catch(e) {
      return document.getElementById(id);
    }
  }

  console.log("[SGS-MODEM-TWIN] Inicializando runtime com Auto-Discovery para SGS_LINKS_GRAFANA...");

  if (window.__SGS_MODEM_TWIN_RUNTIME__) {
    try { window.__SGS_MODEM_TWIN_RUNTIME__.destroy(); } catch(e){}
  }

  // Selecionar inicialmente o link com maior tráfego (ou preservar caso o Grafana tenha re-renderizado)
  const topInitialHost = [...INITIAL_CATALOG].sort((a,b) => (b.totalTraffic || 0) - (a.totalTraffic || 0))[0] || INITIAL_CATALOG[0] || null;
  const prevState = window.__SGS_MODEM_PERSISTED_STATE__ || null;

  const state = {
    allHosts: prevState ? prevState.allHosts : INITIAL_CATALOG,
    filteredHosts: prevState ? prevState.filteredHosts : INITIAL_CATALOG,
    currentHost: prevState ? prevState.currentHost : topInitialHost,
    currentIface: prevState ? prevState.currentIface : (topInitialHost && topInitialHost.interfaces[0]) || null,
    activeGroupName: prevState ? prevState.activeGroupName : GROUP_META.groupName,
    activeGroupId: prevState ? prevState.activeGroupId : GROUP_META.groupId,
    isDedicatedGroup: prevState ? prevState.isDedicatedGroup : GROUP_META.isDedicated,
    lastCatalogSync: prevState ? prevState.lastCatalogSync : new Date(),
    searchQuery: prevState ? prevState.searchQuery : "",
    selectedIsp: prevState ? prevState.selectedIsp : "TODOS",
    timeRangeSec: prevState ? prevState.timeRangeSec : 21600,
    historyIn: prevState ? prevState.historyIn : [],
    historyOut: prevState ? prevState.historyOut : [],
    showIn: true,
    showOut: true,
    showP95: true,
    p95In: prevState ? prevState.p95In : 0,
    pollTimer: null,
    catalogTimer: null,
    zoomStart: null,
    zoomEnd: null,
    isZooming: false,
    dragStartX: null,
    dragCurrentX: null,
    hoveredIdx: null
  };
  window.__SGS_MODEM_PERSISTED_STATE__ = state;

  const ISP_LIST = ["VIVO", "ALGAR", "VEGANET", "DESKTOP", "STARLINK", "HUGHESNET", "EMBRATEL", "CLARO", "OI", "NET", "EVOLNET", "GT CONECT", "DBT"];
  const ISP_COLORS = {
    "VIVO": "#660099",
    "ALGAR": "#00b04f",
    "VEGANET": "#0088cc",
    "DESKTOP": "#ff6600",
    "STARLINK": "#1e293b",
    "HUGHESNET": "#003366",
    "EMBRATEL": "#d6001c",
    "CLARO": "#da291c",
    "OI": "#d97706",
    "NET": "#da291c",
    "EVOLNET": "#00a86b",
    "GT CONECT": "#0284c7",
    "DBT": "#4f46e5",
    "TELECOM": "#2563eb"
  };

  function detectIsp(nameStr) {
    const u = (nameStr || "").toUpperCase();
    for (let i = 0; i < ISP_LIST.length; i++) {
      if (u.includes(ISP_LIST[i])) return ISP_LIST[i];
    }
    return "TELECOM";
  }

  function formatBps(bps) {
    if (bps === null || bps === undefined || isNaN(bps)) return "0 bps";
    const b = Number(bps);
    if (b >= 1000000000) return (b / 1000000000).toFixed(2) + " Gb/s";
    if (b >= 1000000) return (b / 1000000).toFixed(2) + " Mb/s";
    if (b >= 1000) return (b / 1000).toFixed(1) + " Kb/s";
    return b.toFixed(0) + " bps";
  }

  async function zabbixCall(method, params, id = 1) {
    const resp = await fetch(ZABBIX_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        jsonrpc: "2.0",
        method: method,
        params: params,
        auth: ZABBIX_TOKEN,
        id: id
      })
    });
    return await resp.json();
  }

  // =========================================================================
  // AUTO-DISCOVERY EM TEMPO REAL DO GRUPO ZABBIX "SGS_LINKS_GRAFANA"
  // =========================================================================
  async function syncCatalogFromZabbix(manualTrigger = false) {
    const btnSync = getEl("sgs-sync-btn");
    if (btnSync && manualTrigger) btnSync.classList.add("sgs-spinning");

    try {
      // 1. Buscar grupos que contenham SGS_LINKS
      const grpRes = await zabbixCall("hostgroup.get", {
        search: { name: "SGS_LINKS" },
        output: ["groupid", "name"]
      }, 100);

      const groups = grpRes.result || [];
      let targetGrp = null;
      let fallbackGrp = null;

      groups.forEach(g => {
        const up = (g.name || "").toUpperCase();
        if (up === GROUP_META.targetGroupName || up.endsWith("/" + GROUP_META.targetGroupName)) {
          targetGrp = g;
        } else if (up === GROUP_META.fallbackGroupName || g.groupid === GROUP_META.fallbackGroupId) {
          fallbackGrp = g;
        }
      });

      let chosenGroupId = GROUP_META.fallbackGroupId;
      let chosenGroupName = GROUP_META.fallbackGroupName;
      let usingDedicated = false;
      let rawHosts = [];

      // Se SGS_LINKS_GRAFANA existe, verificar os hosts ativos nele
      if (targetGrp) {
        const checkRes = await zabbixCall("host.get", {
          groupids: targetGrp.groupid,
          output: ["hostid", "name", "status", "description"],
          selectInterfaces: ["ip", "port", "type", "available"],
          selectParentTemplates: ["name"]
        }, 101);
        const activeInTarget = (checkRes.result || []).filter(h => h.status === "0");
        if (activeInTarget.length > 0) {
          chosenGroupId = targetGrp.groupid;
          chosenGroupName = targetGrp.name;
          usingDedicated = true;
          rawHosts = activeInTarget;
        }
      }

      // Caso SGS_LINKS_GRAFANA ainda não exista ou esteja vazio, buscar no fallback SGS_LINKS
      if (!usingDedicated) {
        if (fallbackGrp) {
          chosenGroupId = fallbackGrp.groupid;
          chosenGroupName = fallbackGrp.name;
        }
        const fbRes = await zabbixCall("host.get", {
          groupids: chosenGroupId,
          output: ["hostid", "name", "status", "description"],
          selectInterfaces: ["ip", "port", "type", "available"],
          selectParentTemplates: ["name"]
        }, 102);
        rawHosts = (fbRes.result || []).filter(h => h.status === "0");
      }

      if (rawHosts.length === 0) return;

      const hostIds = rawHosts.map(h => h.hostid);

      // 2. Buscar itens net.if e icmp de todos os hosts do grupo em paralelo
      const [itemsRes, icmpRes] = await Promise.all([
        zabbixCall("item.get", {
          hostids: hostIds,
          search: { key_: "net.if." },
          output: ["itemid", "hostid", "name", "key_", "lastvalue", "units", "value_type", "status"]
        }, 103),
        zabbixCall("item.get", {
          hostids: hostIds,
          search: { key_: "icmp" },
          output: ["itemid", "hostid", "name", "key_", "lastvalue", "units", "value_type"]
        }, 104)
      ]);

      const netItems = (itemsRes.result || []).filter(i => i.status === "0");
      const icmpItems = icmpRes.result || [];

      const newCatalog = [];

      rawHosts.forEach(h => {
        if (!usingDedicated && (h.name || "").toLowerCase().includes("switch")) {
          return;
        }
        const hid = h.hostid;
        const hItems = netItems.filter(i => i.hostid === hid);

        if (!usingDedicated && hItems.length === 0) {
          return;
        }

        const ifacesMap = {};
        hItems.forEach(it => {
          const k = it.key_ || "";
          let idx = it.name;
          if (k.includes("[") && k.includes("]")) {
            const param = k.split("[")[1].split("]")[0];
            idx = param.includes(".") ? param.split(".").pop() : param;
          }

          if (!ifacesMap[idx]) {
            let cleanName = it.name || idx;
            if (cleanName.includes("Interface ")) {
              cleanName = cleanName.split("Interface ")[1].split(":")[0].trim();
            } else if (cleanName.includes(":")) {
              cleanName = cleanName.split(":")[0].trim();
            }
            ifacesMap[idx] = {
              id: idx,
              name: cleanName,
              rawName: it.name,
              inItem: null,
              outItem: null,
              errorsItem: null,
              discardsItem: null,
              speed: 1000000000,
              status: 1
            };
          }

          const lv = parseFloat(it.lastvalue);
          const safeLv = isNaN(lv) ? 0 : lv;

          if (k.includes("net.if.in[")) {
            ifacesMap[idx].inItem = {
              itemid: it.itemid,
              key: k,
              valueType: it.value_type,
              lastvalue: safeLv
            };
          } else if (k.includes("net.if.out[")) {
            ifacesMap[idx].outItem = {
              itemid: it.itemid,
              key: k,
              valueType: it.value_type,
              lastvalue: safeLv
            };
          } else if (k.includes("errors")) {
            ifacesMap[idx].errorsItem = it.itemid;
          } else if (k.includes("discards")) {
            ifacesMap[idx].discardsItem = it.itemid;
          }
        });

        let validIfaces = Object.values(ifacesMap).filter(x => x.inItem || x.outItem);
        if (validIfaces.length === 0) {
          if (usingDedicated) {
            validIfaces = [{
              id: "pending_lld",
              name: "AGUARDANDO DESCOBERTA SNMP (LLD)...",
              rawName: "Aguardando LLD",
              inItem: null,
              outItem: null,
              errorsItem: null,
              discardsItem: null,
              speed: 1000000000,
              status: 1
            }];
          } else {
            return;
          }
        }

        validIfaces.sort((a, b) => {
          const score = x => {
            let s = 0;
            const nu = (x.name || "").toUpperCase();
            if (nu.includes("WAN") || nu.includes("INTERNET") || nu.includes("LINK")) s += 100000000;
            const iv = x.inItem ? x.inItem.lastvalue : 0;
            const ov = x.outItem ? x.outItem.lastvalue : 0;
            return s + iv + ov;
          };
          return score(b) - score(a);
        });

        const ifList = h.interfaces || [];
        const snmpIf = ifList.find(i => String(i.type) === "2") || ifList[0] || {};
        const ip = snmpIf.ip || "N/A";

        const hIcmp = icmpItems.filter(i => i.hostid === hid);
        const pingIt = hIcmp.find(i => i.key_ === "icmpping" || (i.key_ || "").includes("icmpping["));
        const secIt = hIcmp.find(i => (i.key_ || "").includes("icmppingsec"));
        const lossIt = hIcmp.find(i => (i.key_ || "").includes("icmppingloss"));

        const totalIn = validIfaces.reduce((acc, x) => acc + (x.inItem ? x.inItem.lastvalue : 0), 0);
        const totalOut = validIfaces.reduce((acc, x) => acc + (x.outItem ? x.outItem.lastvalue : 0), 0);

        newCatalog.push({
          hostid: hid,
          name: h.name,
          isp: detectIsp(h.name),
          ip: ip,
          templates: (h.parentTemplates || []).map(t => t.name),
          interfaces: validIfaces,
          pingItem: pingIt ? pingIt.itemid : null,
          secItem: secIt ? secIt.itemid : null,
          lossItem: lossIt ? lossIt.itemid : null,
          pingVal: pingIt && pingIt.lastvalue !== undefined ? parseFloat(pingIt.lastvalue) : 1,
          secVal: secIt && secIt.lastvalue !== undefined ? parseFloat(secIt.lastvalue) : 0,
          lossVal: lossIt && lossIt.lastvalue !== undefined ? parseFloat(lossIt.lastvalue) : 0,
          totalIn: totalIn,
          totalOut: totalOut,
          totalTraffic: totalIn + totalOut
        });
      });

      newCatalog.sort((a, b) => a.name.localeCompare(b.name));

      state.allHosts = newCatalog;
      state.activeGroupName = chosenGroupName;
      state.activeGroupId = chosenGroupId;
      state.isDedicatedGroup = usingDedicated;
      state.lastCatalogSync = new Date();

      // Preservar host e interface atualmente selecionados se ainda existirem no grupo
      if (state.currentHost) {
        const updatedHost = newCatalog.find(h => h.hostid === state.currentHost.hostid);
        if (updatedHost) {
          state.currentHost = updatedHost;
          if (state.currentIface) {
            const updatedIface = updatedHost.interfaces.find(i => i.id === state.currentIface.id);
            state.currentIface = updatedIface || updatedHost.interfaces[0] || null;
          } else {
            state.currentIface = updatedHost.interfaces[0] || null;
          }
        } else {
          state.currentHost = newCatalog[0] || null;
          state.currentIface = state.currentHost ? state.currentHost.interfaces[0] : null;
        }
      } else {
        state.currentHost = newCatalog[0] || null;
        state.currentIface = state.currentHost ? state.currentHost.interfaces[0] : null;
      }

      updateGroupStatusBanner();
      renderIspFilterPills();
      applyFiltersAndRender();
      updateChassisUI();
      renderInterfacesTable();

    } catch (err) {
      console.error("[SGS-MODEM-TWIN] Erro ao sincronizar catálogo Zabbix:", err);
    } finally {
      if (btnSync && manualTrigger) btnSync.classList.remove("sgs-spinning");
    }
  }

  function updateGroupStatusBanner() {
    const badge = getEl("sgs-group-badge");
    const syncSub = getEl("sgs-sync-status");
    const aggEl = getEl("sgs-aggregate-stat");
    const hhmmss = state.lastCatalogSync.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

    if (badge) {
      if (state.isDedicatedGroup) {
        badge.className = "sgs-group-pill";
        badge.textContent = `🟢 GRUPO ATIVO: ${state.activeGroupName} (${state.allHosts.length} links)`;
      } else {
        badge.className = "sgs-group-pill fallback";
        badge.textContent = `⚡ AUTO-DISCOVERY: ${state.activeGroupName} (${state.allHosts.length} links • Pronto p/ SGS_LINKS_GRAFANA)`;
      }
    }

    if (syncSub) {
      if (state.isDedicatedGroup) {
        syncSub.textContent = `Sincronizado com ${state.activeGroupName} às ${hhmmss} • Novos links SNMP aparecem automaticamente`;
      } else {
        syncSub.textContent = `Últ. Sync: ${hhmmss} • Exibindo ${state.activeGroupName} (Adicione hosts ao grupo SGS_LINKS_GRAFANA no Zabbix para ativar filtro dedicado)`;
      }
    }

    if (aggEl) {
      const sumIn = state.allHosts.reduce((acc, h) => acc + (h.totalIn || 0), 0);
      const sumOut = state.allHosts.reduce((acc, h) => acc + (h.totalOut || 0), 0);
      aggEl.innerHTML = `Tráfego Agregado (${state.allHosts.length} links): <b style="color:#00e676">⬇ ${formatBps(sumIn)}</b> • <b style="color:#a855f7">⬆ ${formatBps(sumOut)}</b>`;
    }
  }

  // Renderizar Pílulas de Filtro de Operadora (ISP)
  function renderIspFilterPills() {
    const container = getEl("sgs-isp-pills");
    if (!container) return;

    const counts = { "TODOS": state.allHosts.length };
    state.allHosts.forEach(h => {
      counts[h.isp] = (counts[h.isp] || 0) + 1;
    });

    const isps = ["TODOS", ...Object.keys(counts).filter(k => k !== "TODOS").sort((a,b) => counts[b] - counts[a])];
    container.innerHTML = "";

    isps.forEach(isp => {
      const btn = document.createElement("button");
      btn.className = "sgs-isp-pill" + (state.selectedIsp === isp ? " active" : "");
      btn.textContent = `${isp} (${counts[isp]})`;
      btn.onclick = () => {
        state.selectedIsp = isp;
        renderIspFilterPills();
        applyFiltersAndRender(true);
      };
      container.appendChild(btn);
    });
  }

  // Aplicar busca por texto + filtro ISP
  function applyFiltersAndRender(autoSelectFirstIfChanged = false) {
    const q = (state.searchQuery || "").trim().toLowerCase();
    state.filteredHosts = state.allHosts.filter(h => {
      const matchIsp = (state.selectedIsp === "TODOS") || (h.isp === state.selectedIsp);
      if (!matchIsp) return false;
      if (!q) return true;
      return (h.name || "").toLowerCase().includes(q) ||
             (h.ip || "").toLowerCase().includes(q) ||
             (h.isp || "").toLowerCase().includes(q);
    });

    const countEl = getEl("sgs-host-count");
    if (countEl) countEl.textContent = state.filteredHosts.length;

    if (autoSelectFirstIfChanged && state.filteredHosts.length > 0) {
      const stillInList = state.currentHost && state.filteredHosts.some(h => h.hostid === state.currentHost.hostid);
      if (!stillInList) {
        selectHost(state.filteredHosts[0]);
      }
    }

    renderHostSelect();
    renderTopLinks();
  }

  // Montar Dropdown de Hosts
  function renderHostSelect() {
    const sel = getEl("sgs-host-select");
    if (!sel) return;
    sel.innerHTML = "";

    const listToUse = state.filteredHosts.length > 0 ? state.filteredHosts : state.allHosts;

    listToUse.forEach(h => {
      const opt = document.createElement("option");
      opt.value = h.hostid;
      opt.textContent = `${h.name} (${h.ip})`;
      if (state.currentHost && state.currentHost.hostid === h.hostid) {
        opt.selected = true;
      }
      sel.appendChild(opt);
    });

    sel.onchange = function(e) {
      const hid = e.target.value;
      const found = state.allHosts.find(x => x.hostid === hid);
      if (found) {
        selectHost(found);
      }
    };
  }

  // Montar Dropdown de Interfaces
  function renderIfaceSelect() {
    const sel = getEl("sgs-iface-select");
    if (!sel || !state.currentHost) return;
    sel.innerHTML = "";
    state.currentHost.interfaces.forEach(iface => {
      const opt = document.createElement("option");
      opt.value = iface.id;
      opt.textContent = iface.name;
      if (state.currentIface && state.currentIface.id === iface.id) {
        opt.selected = true;
      }
      sel.appendChild(opt);
    });

    sel.onchange = function(e) {
      const ifid = e.target.value;
      const found = state.currentHost.interfaces.find(x => x.id === ifid);
      if (found) {
        selectInterface(found);
      }
    };
  }

  // Selecionar Host
  function selectHost(host) {
    state.currentHost = host;
    state.currentIface = host.interfaces[0] || null;
    state.zoomStart = null;
    state.zoomEnd = null;
    const btnReset = getEl("sgs-btn-reset-zoom");
    if (btnReset) btnReset.style.display = "none";

    updateChassisUI();
    renderHostSelect();
    renderIfaceSelect();
    renderInterfacesTable();
    renderTopLinks();

    const sub = getEl("sgs-chart-sub");
    if (sub && state.currentIface) sub.textContent = `Ativo: ${host.name} • Porta: ${state.currentIface.name}`;

    fetchTelemetry();
  }

  // Selecionar Interface
  function selectInterface(iface) {
    state.currentIface = iface;
    state.zoomStart = null;
    state.zoomEnd = null;
    const btnReset = getEl("sgs-btn-reset-zoom");
    if (btnReset) btnReset.style.display = "none";

    const sub = getEl("sgs-chart-sub");
    if (sub && state.currentHost) sub.textContent = `Ativo: ${state.currentHost.name} • Porta: ${iface.name}`;

    const sel = getEl("sgs-iface-select");
    if (sel) sel.value = iface.id;

    renderInterfacesTable();
    updateChassisLEDs();
    fetchTelemetry();
  }

  // Identificar interfaces LAN do Host
  function getHostLanInterfaces(host) {
    if (!host || !host.interfaces) return [];
    const explicitLan = host.interfaces.filter(i => {
      const n = (i.name || "").toUpperCase();
      return n.includes("LAN") && !n.includes("WAN");
    });
    if (explicitLan.length > 0) return explicitLan.slice(0, 4);

    const otherIfaces = host.interfaces.filter((i, idx) => {
      const n = (i.name || "").toUpperCase();
      return !n.includes("WAN") && !n.includes("INTERNET") && idx > 0;
    });
    if (otherIfaces.length > 0) return otherIfaces.slice(0, 4);

    return host.interfaces.slice(1, 5);
  }

  // Atualizar LEDs do Chassi (WAN + SFP + LAN 1 a 4 100% Funcionais)
  function updateChassisLEDs() {
    const host = state.currentHost;
    if (!host) return;

    const wanIface = host.interfaces[0] || null;
    const lanIfaces = getHostLanInterfaces(host);
    const isWanSelected = state.currentIface && wanIface && (state.currentIface.id === wanIface.id);

    ["sgs-btn-sfp-wan", "sgs-btn-wan-pon", "sgs-btn-wan-net"].forEach(id => {
      const el = getEl(id);
      if (el && wanIface) {
        el.classList.toggle("selected", isWanSelected);
        el.title = `Porta WAN Principal: ${wanIface.name}\n✦ Clique para inspecionar a WAN no osciloscópio`;
        el.onclick = () => selectInterface(wanIface);
      }
    });

    // LED LOS/ALM (Alarme de perda de pacote ou host down)
    const ledLos = getEl("sgs-led-los");
    if (ledLos) {
      if (host.pingVal === 0) {
        ledLos.className = "sgs-led sgs-led-red sgs-led-flicker";
      } else if (host.lossVal > 5) {
        ledLos.className = "sgs-led sgs-led-amber";
      } else {
        ledLos.className = "sgs-led";
      }
    }

    for (let slot = 0; slot < 4; slot++) {
      const unit = getEl("sgs-lan-unit-" + slot);
      const rj45 = getEl("sgs-rj45-" + slot);
      const led = getEl("sgs-led-lan" + slot);
      const label = getEl("sgs-label-lan" + slot);
      if (!unit || !rj45 || !led) continue;

      const iface = lanIfaces[slot];
      if (iface) {
        const isSelected = state.currentIface && (state.currentIface.id === iface.id);
        unit.classList.add("clickable");
        unit.classList.toggle("selected", isSelected);
        unit.style.opacity = "1";

        rj45.classList.add("active");
        rj45.classList.toggle("selected", isSelected);

        const inVal = (iface.inItem && iface.inItem.lastvalue) || 0;
        const outVal = (iface.outItem && iface.outItem.lastvalue) || 0;
        const totalBps = inVal + outVal;
        const isUp = iface.status !== 0;

        led.className = "sgs-led sgs-led-lan";
        if (isUp) {
          led.classList.add("sgs-led-green");
          if (totalBps > 0) {
            led.classList.add("sgs-led-flicker");
            led.style.animationDuration = totalBps > 20000000 ? "0.18s" : (totalBps > 2000000 ? "0.35s" : "0.7s");
          } else {
            led.style.animationDuration = "";
          }
        } else {
          led.classList.add("sgs-led-red");
          led.style.animationDuration = "";
        }

        if (label) {
          label.textContent = `LAN ${slot + 1}`;
        }

        unit.title = `LAN ${slot + 1}: ${iface.name}\nStatus: ${isUp ? 'UP (Conectada)' : 'DOWN'}\n⬇ In: ${formatBps(inVal)} | ⬆ Out: ${formatBps(outVal)}\n✦ Clique para abrir esta porta no osciloscópio`;
        unit.onclick = () => selectInterface(iface);
      } else {
        unit.classList.remove("clickable", "selected");
        unit.style.opacity = "0.35";
        unit.title = `LAN ${slot + 1}: Sem interface LAN adicional mapeada no SNMP`;
        rj45.classList.remove("active", "selected");
        led.className = "sgs-led sgs-led-lan";
        led.style.animationDuration = "";
        if (label) label.textContent = `LAN ${slot + 1}`;
        unit.onclick = null;
      }
    }
  }

  // Atualizar UI do Chassi Físico
  function updateChassisUI() {
    if (!state.currentHost) return;
    const h = state.currentHost;

    const elName = getEl("sgs-dev-name");
    if (elName) elName.textContent = h.name;

    const elHostId = getEl("sgs-hostid-badge");
    if (elHostId) elHostId.textContent = `HOSTID: ${h.hostid}`;

    const elModel = getEl("sgs-chassis-model");
    if (elModel) {
      const tpl = (h.templates && h.templates[0]) ? h.templates[0].toUpperCase() : "SNMP GATEWAY";
      elModel.textContent = `${h.isp} WAN GATEWAY • ${tpl} • ${h.interfaces.length} INTERFACES`;
    }

    const elIp = getEl("sgs-dev-ip");
    if (elIp) {
      elIp.textContent = `IP: ${h.ip || "N/A"} 📋`;
      elIp.onclick = () => {
        if (navigator.clipboard && h.ip) {
          navigator.clipboard.writeText(h.ip);
          elIp.textContent = `IP: ${h.ip} ✓ COPIADO!`;
          setTimeout(() => { elIp.textContent = `IP: ${h.ip} 📋`; }, 1500);
        }
      };
    }

    const elIsp = getEl("sgs-isp-badge");
    if (elIsp) {
      elIsp.textContent = h.isp;
      const c = ISP_COLORS[h.isp] || "#2563eb";
      elIsp.style.background = c;
      elIsp.style.boxShadow = `0 0 8px ${c}`;
    }

    const ms = h.secVal ? (h.secVal * 1000).toFixed(1) : null;
    const elPing = getEl("sgs-dev-ping");
    if (elPing) {
      elPing.textContent = ms ? `LATÊNCIA: ${ms} ms` : "LATÊNCIA: --";
      elPing.style.color = (ms && ms > 80) ? "#f59e0b" : "#cbd5e1";
    }

    const loss = h.lossVal ? Number(h.lossVal).toFixed(1) : "0";
    const elLoss = getEl("sgs-dev-loss");
    if (elLoss) {
      elLoss.textContent = `PERDA: ${loss}%`;
      elLoss.style.color = Number(loss) > 0 ? "#f59e0b" : "#cbd5e1";
    }

    const elHealth = getEl("sgs-dev-health");
    if (elHealth) {
      const isUp = h.pingVal !== 0;
      elHealth.textContent = isUp ? "STATUS: ONLINE" : "STATUS: OFFLINE";
      elHealth.className = "sgs-meta-pill " + (isUp ? "online" : "");
    }

    updateChassisLEDs();
    renderDrawerInfo();
  }

  // Renderizar Tabela de Interfaces
  function renderInterfacesTable() {
    const tbody = getEl("sgs-iface-tbody");
    const countBadge = getEl("sgs-iface-count");
    if (!tbody || !state.currentHost) return;

    const ifaces = state.currentHost.interfaces;
    if (countBadge) countBadge.textContent = ifaces.length + " portas";

    tbody.innerHTML = "";
    ifaces.forEach((iface, idx) => {
      const tr = document.createElement("tr");
      const inVal = iface.inItem ? iface.inItem.lastvalue : 0;
      const outVal = iface.outItem ? iface.outItem.lastvalue : 0;
      const isSelected = state.currentIface && state.currentIface.id === iface.id;
      const nameUpper = (iface.name || "").toUpperCase();
      const isWan = idx === 0 || nameUpper.includes("WAN") || nameUpper.includes("INTERNET") || nameUpper.includes("LINK");

      tr.innerHTML = `
        <td style="font-weight: 700; color: ${isSelected ? '#00b0ff' : '#f1f5f9'};">
          ${isSelected ? '▶ ' : ''}${iface.name}
        </td>
        <td><span class="sgs-badge-role ${isWan ? 'wan' : 'lan'}">${isWan ? 'WAN / UPLINK' : 'LAN / LOCAL'}</span></td>
        <td><span class="sgs-badge-status up">UP</span></td>
        <td style="color: #00e676; font-family: monospace; font-weight: 700;">${formatBps(inVal)}</td>
        <td style="color: #a855f7; font-family: monospace; font-weight: 700;">${formatBps(outVal)}</td>
        <td>
          <button class="sgs-btn-select-if ${isSelected ? 'active' : ''}" data-id="${iface.id}">
            ${isSelected ? 'NO GRÁFICO' : 'INSPECIONAR'}
          </button>
        </td>
      `;

      tr.querySelector("button").onclick = function() {
        selectInterface(iface);
      };

      tbody.appendChild(tr);
    });
  }

  // Renderizar Ranking Vivo de Todos os Links do Grupo
  function renderTopLinks() {
    const list = getEl("sgs-top-links-list");
    const countBadge = getEl("sgs-ranking-count");
    if (!list) return;

    const baseList = state.filteredHosts.length > 0 ? state.filteredHosts : state.allHosts;
    const sorted = [...baseList].sort((a, b) => b.totalTraffic - a.totalTraffic);
    const maxTraffic = Math.max(1000000, sorted[0] ? sorted[0].totalTraffic : 1000000);

    if (countBadge) countBadge.textContent = `${sorted.length} ATIVOS LIVE`;
    list.innerHTML = "";

    sorted.forEach((h, idx) => {
      const isCurrent = state.currentHost && state.currentHost.hostid === h.hostid;
      const pct = Math.min(100, Math.max(2, (h.totalTraffic / maxTraffic) * 100));
      const ispColor = ISP_COLORS[h.isp] || "#2563eb";
      const ms = h.secVal ? (h.secVal * 1000).toFixed(0) + "ms" : "OK";

      const item = document.createElement("div");
      item.className = "sgs-top-link-item" + (isCurrent ? " active" : "");
      item.innerHTML = `
        <div class="sgs-top-link-row1">
          <span class="sgs-top-link-name">#${idx + 1} ${h.name}</span>
          <span class="sgs-top-link-rate">${formatBps(h.totalTraffic)}</span>
        </div>
        <div class="sgs-top-link-bar">
          <div class="sgs-top-link-bar-fill" style="width: ${pct.toFixed(1)}%"></div>
        </div>
        <div class="sgs-top-link-row2">
          <span><b style="color:${ispColor}">● ${h.isp}</b> • IP: ${h.ip} • Ping: ${ms}</span>
          <span><span style="color:#00e676">⬇ ${formatBps(h.totalIn)}</span> | <span style="color:#a855f7">⬆ ${formatBps(h.totalOut)}</span></span>
        </div>
      `;
      item.onclick = function() {
        selectHost(h);
      };
      list.appendChild(item);
    });
  }

  // Renderizar Drawer de Inventário + Status Auto-Discovery
  function renderDrawerInfo() {
    const body = getEl("sgs-drawer-body");
    if (!body || !state.currentHost) return;
    const h = state.currentHost;
    const zbxBase = ZABBIX_URL.replace('/api_jsonrpc.php', '');

    body.innerHTML = `
      <div style="margin-bottom: 12px; padding: 12px; background: #131b2e; border: 1px solid #25334d; border-radius: 6px;">
        <div style="font-size: 13px; font-weight: 800; color: #fff;">${h.name}</div>
        <div style="color: #38bdf8; font-size: 11px; margin-top: 3px; font-family: monospace;">
          Zabbix Host ID: ${h.hostid} • Grupo: ${state.activeGroupName}
        </div>
      </div>

      <div style="margin-bottom: 12px; padding: 10px; background: rgba(0, 230, 118, 0.08); border: 1px solid rgba(0, 230, 118, 0.3); border-radius: 6px;">
        <div style="font-weight: 800; color: #00e676; font-size: 11px; margin-bottom: 4px;">
          ⚡ AUTO-DISCOVERY DINÂMICO (SGS_LINKS_GRAFANA)
        </div>
        <div style="font-size: 10.5px; color: #cbd5e1;">
          Esta dashboard consulta a API do Zabbix em tempo real direto pelo navegador.<br>
          Qualquer host SNMP adicionado ao grupo <b>SGS_LINKS_GRAFANA</b> no Zabbix entra automaticamente na lista sem precisar editar o Grafana!
        </div>
      </div>

      <div style="display: flex; flex-direction: column; gap: 8px;">
        <div><b>IP de Gerência / WAN:</b> <span style="font-family:monospace; color:#f8fafc;">${h.ip}</span></div>
        <div><b>Operadora / ISP:</b> ${h.isp}</div>
        <div><b>Interfaces SNMP Ativas:</b> ${h.interfaces.length}</div>
        <div><b>Templates Vinculados:</b>
          <ul style="margin: 4px 0 0 18px; padding: 0; color: #cbd5e1;">
            ${(h.templates && h.templates.length > 0) ? h.templates.map(t => `<li>${t}</li>`).join('') : '<li>SNMP Padrão</li>'}
          </ul>
        </div>
        <div style="margin-top: 12px; display: flex; flex-direction: column; gap: 8px;">
          <a href="${zbxBase}/zabbix.php?action=host.edit&hostid=${h.hostid}" target="_blank"
             style="color: #00b0ff; text-decoration: none; font-weight: 700; background: #162238; padding: 8px 12px; border-radius: 5px; border: 1px solid #293d5e; text-align: center;">
             ↗ Abrir Configuração do Host no Zabbix
          </a>
          <a href="${zbxBase}/zabbix.php?action=latest.view&filter_hostids%5B%5D=${h.hostid}&filter_set=1" target="_blank"
             style="color: #00e676; text-decoration: none; font-weight: 700; background: #112220; padding: 8px 12px; border-radius: 5px; border: 1px solid #1b4332; text-align: center;">
             📊 Ver Dados Recentes (Latest Data) no Zabbix
          </a>
        </div>
      </div>
    `;
  }

  // Buscar Telemetria (Últimos Valores e Histórico)
  async function fetchTelemetry() {
    if (!state.currentHost || !state.currentIface) return;
    const h = state.currentHost;
    const iface = state.currentIface;

    const btnSync = getEl("sgs-sync-btn");
    if (btnSync) btnSync.classList.add("sgs-spinning");

    try {
      const now = Math.floor(Date.now() / 1000);
      const timeFrom = now - state.timeRangeSec;

      // Se a janela for > 24h ou history.get vier vazio, usamos trend.get como fallback
      const useTrends = state.timeRangeSec > 172800;

      // 1. Buscar Ping e Perda se houver item
      if (h.secItem) {
        const pingRes = await zabbixCall("item.get", {
          itemids: [h.secItem, h.lossItem, h.pingItem].filter(Boolean),
          output: ["itemid", "key_", "lastvalue"]
        }, 10);

        (pingRes.result || []).forEach(it => {
          const k = it.key_ || "";
          if (k.includes("icmppingsec")) h.secVal = parseFloat(it.lastvalue) || 0;
          else if (k.includes("icmppingloss")) h.lossVal = parseFloat(it.lastvalue) || 0;
          else if (k.includes("icmpping")) h.pingVal = parseFloat(it.lastvalue);
        });
        updateChassisUI();
      }

      let inData = [];
      let outData = [];

      if (iface.inItem && !useTrends) {
        const inRes = await zabbixCall("history.get", {
          itemids: [iface.inItem.itemid],
          history: parseInt(iface.inItem.valueType) || 3,
          time_from: timeFrom,
          time_till: now,
          sortfield: "clock",
          sortorder: "ASC",
          limit: 650
        }, 11);
        inData = inRes.result || [];
      }

      if (iface.outItem && !useTrends) {
        const outRes = await zabbixCall("history.get", {
          itemids: [iface.outItem.itemid],
          history: parseInt(iface.outItem.valueType) || 3,
          time_from: timeFrom,
          time_till: now,
          sortfield: "clock",
          sortorder: "ASC",
          limit: 650
        }, 12);
        outData = outRes.result || [];
      }

      // Fallback para trend.get caso janela de 7D ou histórico curto
      if (inData.length === 0 && iface.inItem) {
        const trIn = await zabbixCall("trend.get", {
          itemids: [iface.inItem.itemid],
          time_from: timeFrom,
          time_till: now,
          output: ["clock", "value_avg", "value_max"]
        }, 13);
        inData = (trIn.result || []).map(p => ({ clock: p.clock, value: p.value_avg }));
      }

      if (outData.length === 0 && iface.outItem) {
        const trOut = await zabbixCall("trend.get", {
          itemids: [iface.outItem.itemid],
          time_from: timeFrom,
          time_till: now,
          output: ["clock", "value_avg", "value_max"]
        }, 14);
        outData = (trOut.result || []).map(p => ({ clock: p.clock, value: p.value_avg }));
      }

      state.historyIn = inData;
      state.historyOut = outData;

      updateKPIs(inData, outData);
      renderCanvas();

    } catch (err) {
      console.error("[SGS-MODEM-TWIN] Erro ao buscar telemetria:", err);
    } finally {
      if (btnSync) btnSync.classList.remove("sgs-spinning");
    }
  }

  function calcPercentile95(arr) {
    if (!arr || arr.length === 0) return 0;
    const sorted = [...arr].sort((a, b) => a - b);
    const idx = Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95));
    return sorted[idx];
  }

  // Atualizar os 5 Cards de KPI
  function updateKPIs(inData, outData) {
    const h = state.currentHost;
    const curIn = inData.length > 0 ? parseFloat(inData[inData.length - 1].value) : (( state.currentIface && state.currentIface.inItem ) ? state.currentIface.inItem.lastvalue : 0);
    const curOut = outData.length > 0 ? parseFloat(outData[outData.length - 1].value) : (( state.currentIface && state.currentIface.outItem ) ? state.currentIface.outItem.lastvalue : 0);

    // Quick Pill no Chassi
    const qIn = getEl("sgs-quick-in");
    if (qIn) qIn.textContent = formatBps(curIn);
    const qOut = getEl("sgs-quick-out");
    if (qOut) qOut.textContent = formatBps(curOut);

    // Estatísticas In
    let maxIn = 0, maxInClock = 0, sumIn = 0;
    const inVals = [];
    inData.forEach(p => {
      const v = parseFloat(p.value) || 0;
      inVals.push(v);
      if (v > maxIn) { maxIn = v; maxInClock = parseInt(p.clock); }
      sumIn += v;
    });
    const avgIn = inData.length > 0 ? (sumIn / inData.length) : curIn;

    // Estatísticas Out
    let maxOut = 0, sumOut = 0;
    const outVals = [];
    outData.forEach(p => {
      const v = parseFloat(p.value) || 0;
      outVals.push(v);
      if (v > maxOut) maxOut = v;
      sumOut += v;
    });
    const avgOut = outData.length > 0 ? (sumOut / outData.length) : curOut;

    const p95In = calcPercentile95(inVals);
    const p95Out = calcPercentile95(outVals);
    state.p95In = Math.max(p95In, p95Out);

    const refMax = Math.max(maxIn, maxOut, 10000000); // min 10 Mbps ref

    // Card 1: Download Atual
    const kIn = getEl("sgs-kpi-in-val");
    if (kIn) kIn.textContent = formatBps(curIn);
    const kInSub = getEl("sgs-kpi-in-sub");
    if (kInSub) kInSub.textContent = `Média: ${formatBps(avgIn)} • Pico: ${formatBps(maxIn)}`;
    const kInBar = getEl("sgs-kpi-in-bar");
    if (kInBar) kInBar.style.width = Math.min(100, (curIn / refMax) * 100).toFixed(1) + "%";

    // Card 2: Upload Atual
    const kOut = getEl("sgs-kpi-out-val");
    if (kOut) kOut.textContent = formatBps(curOut);
    const kOutSub = getEl("sgs-kpi-out-sub");
    if (kOutSub) kOutSub.textContent = `Média: ${formatBps(avgOut)} • Pico: ${formatBps(maxOut)}`;
    const kOutBar = getEl("sgs-kpi-out-bar");
    if (kOutBar) kOutBar.style.width = Math.min(100, (curOut / refMax) * 100).toFixed(1) + "%";

    // Card 3: Pico Máximo na Janela
    const kPeak = getEl("sgs-kpi-peak-val");
    if (kPeak) kPeak.textContent = formatBps(Math.max(maxIn, maxOut));
    const kPeakSub = getEl("sgs-kpi-peak-sub");
    if (kPeakSub) kPeakSub.textContent = `⬇ In: ${formatBps(maxIn)} | ⬆ Out: ${formatBps(maxOut)}`;
    const kPeakTime = getEl("sgs-kpi-peak-time");
    if (kPeakTime && maxInClock > 0) {
      const d = new Date(maxInClock * 1000);
      kPeakTime.textContent = "ÀS " + d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
    }

    // Card 4: Percentil 95 (P95) & Média
    const kAvg = getEl("sgs-kpi-avg-val");
    if (kAvg) kAvg.textContent = formatBps(state.p95In);
    const kAvgSub = getEl("sgs-kpi-avg-sub");
    if (kAvgSub) kAvgSub.textContent = `Média In: ${formatBps(avgIn)} | Out: ${formatBps(avgOut)}`;
    const kAvgBar = getEl("sgs-kpi-avg-bar");
    if (kAvgBar) kAvgBar.style.width = Math.min(100, (state.p95In / refMax) * 100).toFixed(1) + "%";

    // Card 5: Qualidade & Saúde WAN
    const kHealthVal = getEl("sgs-kpi-health-val");
    const kHealthSub = getEl("sgs-kpi-health-sub");
    const kHealthBadge = getEl("sgs-kpi-health-badge");
    const kHealthBar = getEl("sgs-kpi-health-bar");
    if (h) {
      const ms = h.secVal ? (h.secVal * 1000).toFixed(1) + " ms" : "--";
      const loss = h.lossVal ? Number(h.lossVal).toFixed(1) : "0.0";
      const isOnline = h.pingVal !== 0;

      if (kHealthVal) {
        kHealthVal.textContent = isOnline ? (Number(loss) === 0 ? "100% ÍNTEGRO" : `${(100 - Number(loss)).toFixed(1)}% UP`) : "OFFLINE";
        kHealthVal.style.color = !isOnline ? "#ef4444" : (Number(loss) > 2 ? "#f59e0b" : "#10b981");
      }
      if (kHealthSub) kHealthSub.textContent = `Latência: ${ms} • Perda ICMP: ${loss}%`;
      if (kHealthBadge) {
        kHealthBadge.textContent = !isOnline ? "CRÍTICO" : (Number(loss) > 2 ? "ATENÇÃO" : "SAUDÁVEL");
      }
      if (kHealthBar) {
        kHealthBar.style.width = isOnline ? Math.max(10, 100 - Number(loss)) + "%" : "0%";
      }
    }

    // Ajustar velocidade de cintilação do LED da WAN conforme o tráfego
    const ledWan = getEl("sgs-led-wan");
    if (ledWan) {
      ledWan.style.animationDuration = curIn > 20000000 ? "0.18s" : (curIn > 5000000 ? "0.32s" : "0.65s");
    }

    updateChassisLEDs();
  }

  // Renderizar Gráfico Canvas (Osciloscópio)
  function renderCanvas() {
    const canvas = getEl("sgs-traffic-canvas");
    const wrap = getEl("sgs-canvas-wrap");
    if (!canvas || !wrap) return;

    const rect = wrap.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const w = rect.width;
    const h = rect.height;

    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = w + "px";
    canvas.style.height = h + "px";

    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, w, h);

    const inData = state.historyIn || [];
    const outData = state.historyOut || [];

    if (inData.length === 0 && outData.length === 0) {
      ctx.fillStyle = "#64748b";
      ctx.font = "12px sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("Sem histórico de tráfego retornado no período (ou aguardando descoberta SNMP LLD).", w / 2, h / 2);
      return;
    }

    let filteredIn = inData;
    let filteredOut = outData;
    if (state.zoomStart !== null && state.zoomEnd !== null) {
      filteredIn = inData.filter(p => p.clock >= state.zoomStart && p.clock <= state.zoomEnd);
      filteredOut = outData.filter(p => p.clock >= state.zoomStart && p.clock <= state.zoomEnd);
    }

    const allClocks = [...filteredIn.map(p => parseInt(p.clock)), ...filteredOut.map(p => parseInt(p.clock))];
    const allVals = [
      ...(state.showIn ? filteredIn.map(p => parseFloat(p.value)) : []),
      ...(state.showOut ? filteredOut.map(p => parseFloat(p.value)) : [])
    ];

    if (allClocks.length === 0) return;

    const minTime = Math.min(...allClocks);
    const maxTime = Math.max(...allClocks);
    const maxVal = Math.max(...allVals, 1000);
    const yMax = maxVal * 1.16;

    // padLeft aumentado para 84px para evitar qualquer corte de texto no eixo Y!
    const padLeft = 84;
    const padRight = 22;
    const padTop = 16;
    const padBottom = 28;
    const plotW = w - padLeft - padRight;
    const plotH = h - padTop - padBottom;
    const bottomY = padTop + plotH;
    const timeSpan = Math.max(1, maxTime - minTime);

    // Linhas de Grade Horizontais
    ctx.strokeStyle = "#162032";
    ctx.lineWidth = 1;
    ctx.fillStyle = "#64748b";
    ctx.font = "10px monospace";
    ctx.textAlign = "right";

    const gridLines = 4;
    for (let i = 0; i <= gridLines; i++) {
      const yVal = (yMax / gridLines) * i;
      const yPos = bottomY - (yVal / yMax) * plotH;
      ctx.beginPath();
      ctx.moveTo(padLeft, yPos);
      ctx.lineTo(w - padRight, yPos);
      ctx.stroke();

      ctx.fillText(formatBps(yVal), padLeft - 8, yPos + 3);
    }

    // Linhas de Grade Verticais (Tempo)
    ctx.textAlign = "center";
    const timeSteps = 6;
    for (let i = 0; i <= timeSteps; i++) {
      const t = minTime + (timeSpan / timeSteps) * i;
      const xPos = padLeft + ((t - minTime) / timeSpan) * plotW;

      const d = new Date(t * 1000);
      const hours = String(d.getHours()).padStart(2, '0');
      const mins = String(d.getMinutes()).padStart(2, '0');

      ctx.beginPath();
      ctx.strokeStyle = "#162032";
      ctx.moveTo(xPos, padTop);
      ctx.lineTo(xPos, bottomY);
      ctx.stroke();

      ctx.fillStyle = "#64748b";
      if (state.timeRangeSec >= 86400) {
        const day = String(d.getDate()).padStart(2, '0');
        const mo = String(d.getMonth() + 1).padStart(2, '0');
        ctx.fillText(`${day}/${mo} ${hours}:${mins}`, xPos, h - 8);
      } else {
        ctx.fillText(`${hours}:${mins}`, xPos, h - 8);
      }
    }

    function getX(clock) {
      if (maxTime === minTime) return padLeft + plotW / 2;
      return padLeft + ((clock - minTime) / timeSpan) * plotW;
    }
    function getY(val) {
      return bottomY - (val / yMax) * plotH;
    }

    const inCoords = filteredIn.map(p => ({
      x: getX(parseInt(p.clock)),
      y: getY(parseFloat(p.value)),
      clock: parseInt(p.clock),
      value: parseFloat(p.value)
    }));

    const outCoords = filteredOut.map(p => ({
      x: getX(parseInt(p.clock)),
      y: getY(parseFloat(p.value)),
      clock: parseInt(p.clock),
      value: parseFloat(p.value)
    }));

    function drawSeries(coords, strokeColor, r, g, b) {
      if (!coords || coords.length === 0) return;

      const grad = ctx.createLinearGradient(0, padTop, 0, bottomY);
      grad.addColorStop(0, `rgba(${r}, ${g}, ${b}, 0.28)`);
      grad.addColorStop(1, `rgba(${r}, ${g}, ${b}, 0.0)`);
      ctx.fillStyle = grad;

      ctx.beginPath();
      ctx.moveTo(coords[0].x, bottomY);
      coords.forEach(pt => ctx.lineTo(pt.x, pt.y));
      ctx.lineTo(coords[coords.length - 1].x, bottomY);
      ctx.closePath();
      ctx.fill();

      ctx.strokeStyle = strokeColor;
      ctx.lineWidth = 2.2;
      ctx.lineJoin = "round";
      ctx.beginPath();
      coords.forEach((pt, idx) => {
        if (idx === 0) ctx.moveTo(pt.x, pt.y);
        else ctx.lineTo(pt.x, pt.y);
      });
      ctx.stroke();

      if (coords.length <= 160) {
        coords.forEach((pt, idx) => {
          const isLast = (idx === coords.length - 1);
          ctx.fillStyle = strokeColor;
          ctx.beginPath();
          ctx.arc(pt.x, pt.y, isLast ? 3.5 : 2.2, 0, Math.PI * 2);
          ctx.fill();

          if (isLast && state.hoveredIdx == null) {
            ctx.strokeStyle = `rgba(${r}, ${g}, ${b}, 0.55)`;
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.arc(pt.x, pt.y, 7, 0, Math.PI * 2);
            ctx.stroke();
          }
        });
      } else {
        const lastPt = coords[coords.length - 1];
        ctx.fillStyle = strokeColor;
        ctx.beginPath();
        ctx.arc(lastPt.x, lastPt.y, 3.5, 0, Math.PI * 2);
        ctx.fill();

        if (state.hoveredIdx == null) {
          ctx.strokeStyle = `rgba(${r}, ${g}, ${b}, 0.55)`;
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.arc(lastPt.x, lastPt.y, 7, 0, Math.PI * 2);
          ctx.stroke();
        }
      }
    }

    if (state.showOut) {
      drawSeries(outCoords, "#a855f7", 168, 85, 247);
    }
    if (state.showIn) {
      drawSeries(inCoords, "#00e676", 0, 230, 118);
    }

    // Linha tracejada de Percentil 95 (P95)
    if (state.showP95 && state.p95In > 0 && state.p95In <= yMax) {
      const yP95 = getY(state.p95In);
      ctx.strokeStyle = "rgba(245, 158, 11, 0.65)";
      ctx.lineWidth = 1.2;
      ctx.setLineDash([5, 4]);
      ctx.beginPath();
      ctx.moveTo(padLeft, yP95);
      ctx.lineTo(w - padRight, yP95);
      ctx.stroke();
      ctx.setLineDash([]);

      ctx.fillStyle = "#f59e0b";
      ctx.font = "bold 9.5px monospace";
      ctx.textAlign = "right";
      ctx.fillText(`P95: ${formatBps(state.p95In)}`, w - padRight - 6, Math.max(padTop + 10, yP95 - 4));
    }

    // Hover Crosshair (Barrinha Tracejada) e Target Halos (Bolinhas com Auréola)
    if (state.hoveredIdx !== null) {
      const primaryCoords = inCoords.length > 0 ? inCoords : outCoords;
      if (primaryCoords.length > 0) {
        const hIdx = Math.min(state.hoveredIdx, primaryCoords.length - 1);
        const hoverX = primaryCoords[hIdx].x;

        ctx.strokeStyle = "rgba(255, 255, 255, 0.45)";
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(hoverX, padTop);
        ctx.lineTo(hoverX, bottomY);
        ctx.stroke();
        ctx.setLineDash([]);

        let ptOut = null;
        if (state.showOut && outCoords.length > 0) {
          let minDiff = Infinity;
          outCoords.forEach(p => {
            const d = Math.abs(p.x - hoverX);
            if (d < minDiff) { minDiff = d; ptOut = p; }
          });
        }

        let ptIn = null;
        if (state.showIn && inCoords.length > 0) {
          let minDiff = Infinity;
          inCoords.forEach(p => {
            const d = Math.abs(p.x - hoverX);
            if (d < minDiff) { minDiff = d; ptIn = p; }
          });
        }

        if (ptOut) {
          ctx.fillStyle = "#a855f7";
          ctx.beginPath();
          ctx.arc(hoverX, ptOut.y, 5.5, 0, Math.PI * 2);
          ctx.fill();
          ctx.strokeStyle = "#ffffff";
          ctx.lineWidth = 1.5;
          ctx.stroke();
          ctx.strokeStyle = "rgba(168, 85, 247, 0.65)";
          ctx.lineWidth = 3.5;
          ctx.beginPath();
          ctx.arc(hoverX, ptOut.y, 10, 0, Math.PI * 2);
          ctx.stroke();
        }

        if (ptIn) {
          ctx.fillStyle = "#00e676";
          ctx.beginPath();
          ctx.arc(hoverX, ptIn.y, 5.5, 0, Math.PI * 2);
          ctx.fill();
          ctx.strokeStyle = "#ffffff";
          ctx.lineWidth = 1.5;
          ctx.stroke();
          ctx.strokeStyle = "rgba(0, 230, 118, 0.65)";
          ctx.lineWidth = 3.5;
          ctx.beginPath();
          ctx.arc(hoverX, ptIn.y, 10, 0, Math.PI * 2);
          ctx.stroke();
        }
      }
    }

    if (state.isZooming && state.dragStartX != null && state.dragCurrentX != null) {
      const x1 = Math.max(padLeft, Math.min(state.dragStartX, state.dragCurrentX));
      const x2 = Math.min(w - padRight, Math.max(state.dragStartX, state.dragCurrentX));
      const boxW = Math.max(0, x2 - x1);

      ctx.fillStyle = "rgba(0, 176, 255, 0.22)";
      ctx.fillRect(x1, padTop, boxW, plotH);
      ctx.strokeStyle = "#00b0ff";
      ctx.lineWidth = 1.5;
      ctx.setLineDash([4, 2]);
      ctx.strokeRect(x1, padTop, boxW, plotH);
      ctx.setLineDash([]);
    }
  }

  // Configurar Interatividade de Mouse (Crosshair, Tooltip HUD, Series Toggles e Drag-to-Zoom)
  function setupCanvasEvents() {
    const wrap = getEl("sgs-canvas-wrap");
    const tooltip = getEl("sgs-canvas-tooltip");
    const btnReset = getEl("sgs-btn-reset-zoom");
    if (!wrap) return;

    const btnIn = getEl("sgs-toggle-in");
    const btnOut = getEl("sgs-toggle-out");
    const btnP95 = getEl("sgs-toggle-p95");
    if (btnIn) {
      btnIn.onclick = () => {
        state.showIn = !state.showIn;
        btnIn.classList.toggle("active", state.showIn);
        renderCanvas();
      };
    }
    if (btnOut) {
      btnOut.onclick = () => {
        state.showOut = !state.showOut;
        btnOut.classList.toggle("active", state.showOut);
        renderCanvas();
      };
    }
    if (btnP95) {
      btnP95.onclick = () => {
        state.showP95 = !state.showP95;
        btnP95.classList.toggle("active", state.showP95);
        renderCanvas();
      };
    }

    if (!wrap.__hasResizeObserver && window.ResizeObserver) {
      wrap.__hasResizeObserver = true;
      const ro = new ResizeObserver(() => renderCanvas());
      ro.observe(wrap);
    }

    wrap.onmousemove = function(e) {
      const rect = wrap.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const padLeft = 84, padRight = 22;
      const plotW = rect.width - padLeft - padRight;

      if (state.isZooming) {
        state.dragCurrentX = Math.max(padLeft, Math.min(rect.width - padRight, mouseX));
        if (tooltip) tooltip.style.display = "none";
        renderCanvas();
        return;
      }

      if (mouseX < padLeft || mouseX > rect.width - padRight) {
        if (tooltip) tooltip.style.display = "none";
        if (state.hoveredIdx !== null) {
          state.hoveredIdx = null;
          renderCanvas();
        }
        return;
      }

      const inData = state.historyIn || [];
      const outData = state.historyOut || [];
      if (inData.length === 0 && outData.length === 0) return;

      let filteredIn = inData;
      let filteredOut = outData;
      if (state.zoomStart !== null && state.zoomEnd !== null) {
        filteredIn = inData.filter(p => p.clock >= state.zoomStart && p.clock <= state.zoomEnd);
        filteredOut = outData.filter(p => p.clock >= state.zoomStart && p.clock <= state.zoomEnd);
      }

      const primary = filteredIn.length > 0 ? filteredIn : filteredOut;
      if (primary.length === 0) return;

      const allClocks = [...filteredIn.map(p => parseInt(p.clock)), ...filteredOut.map(p => parseInt(p.clock))];
      const minTime = Math.min(...allClocks);
      const maxTime = Math.max(...allClocks);
      const timeSpan = Math.max(1, maxTime - minTime);

      let bestIdx = 0;
      let minDiff = Infinity;
      primary.forEach((p, idx) => {
        const ptX = (maxTime === minTime) ? (padLeft + plotW / 2) : (padLeft + ((p.clock - minTime) / timeSpan) * plotW);
        const diff = Math.abs(mouseX - ptX);
        if (diff < minDiff) {
          minDiff = diff;
          bestIdx = idx;
        }
      });

      state.hoveredIdx = bestIdx;
      renderCanvas();

      const ptIn = filteredIn.length > 0 ? (filteredIn[bestIdx] || filteredIn[filteredIn.length - 1]) : null;
      const valIn = ptIn ? parseFloat(ptIn.value) : 0;
      const refClock = ptIn ? ptIn.clock : (primary[bestIdx] ? primary[bestIdx].clock : 0);

      let valOut = 0;
      if (filteredOut.length > 0) {
        let minDiffOut = Infinity;
        filteredOut.forEach(p => {
          const diff = Math.abs(p.clock - refClock);
          if (diff < minDiffOut) {
            minDiffOut = diff;
            valOut = parseFloat(p.value);
          }
        });
      }

      const d = new Date(refClock * 1000);
      const hhmmss = d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
      let timeStr = hhmmss;
      if (state.timeRangeSec >= 86400) {
        const day = String(d.getDate()).padStart(2, "0");
        const mo = String(d.getMonth() + 1).padStart(2, "0");
        timeStr = `${day}/${mo} ${hhmmss}`;
      }

      const ttTime = getEl("sgs-tt-time");
      if (ttTime) ttTime.textContent = timeStr;
      const ttIn = getEl("sgs-tt-in-val");
      if (ttIn) ttIn.textContent = formatBps(valIn);
      const ttOut = getEl("sgs-tt-out-val");
      if (ttOut) ttOut.textContent = formatBps(valOut);
      const ttTotal = getEl("sgs-tt-total-val");
      if (ttTotal) ttTotal.textContent = formatBps(valIn + valOut);

      if (tooltip) {
        const hoverX = (maxTime === minTime) ? (padLeft + plotW / 2) : (padLeft + ((refClock - minTime) / timeSpan) * plotW);
        const hoverPct = (hoverX / rect.width) * 100;
        if (hoverPct > 68) {
          tooltip.style.left = "auto";
          tooltip.style.right = "14px";
          tooltip.style.transform = "none";
        } else if (hoverPct < 32) {
          tooltip.style.left = "84px";
          tooltip.style.right = "auto";
          tooltip.style.transform = "none";
        } else {
          tooltip.style.left = hoverPct + "%";
          tooltip.style.right = "auto";
          tooltip.style.transform = "translateX(-50%)";
        }
        tooltip.style.display = "flex";
      }
    };

    wrap.onmouseleave = function() {
      if (tooltip) tooltip.style.display = "none";
      state.hoveredIdx = null;
      if (state.isZooming) {
        state.isZooming = false;
        state.dragStartX = null;
        state.dragCurrentX = null;
      }
      renderCanvas();
    };

    wrap.onmousedown = function(e) {
      if (e.button !== 0) return;
      const rect = wrap.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const padLeft = 84, padRight = 22;
      if (mouseX < padLeft || mouseX > rect.width - padRight) return;

      state.isZooming = true;
      state.dragStartX = mouseX;
      state.dragCurrentX = mouseX;
      if (tooltip) tooltip.style.display = "none";
      renderCanvas();
    };

    wrap.onmouseup = function(e) {
      if (!state.isZooming || state.dragStartX === null) return;
      state.isZooming = false;

      const rect = wrap.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const padLeft = 84, padRight = 22;
      const plotW = rect.width - padLeft - padRight;

      const x1 = Math.max(padLeft, Math.min(state.dragStartX, mouseX));
      const x2 = Math.min(rect.width - padRight, Math.max(state.dragStartX, mouseX));
      state.dragStartX = null;
      state.dragCurrentX = null;

      if (x2 - x1 > 15 && (state.historyIn.length > 0 || state.historyOut.length > 0)) {
        const allClocks = [...state.historyIn.map(p => parseInt(p.clock)), ...state.historyOut.map(p => parseInt(p.clock))];
        const minTime = Math.min(...allClocks);
        const maxTime = Math.max(...allClocks);
        const timeSpan = Math.max(1, maxTime - minTime);

        state.zoomStart = Math.floor(minTime + ((x1 - padLeft) / plotW) * timeSpan);
        state.zoomEnd = Math.ceil(minTime + ((x2 - padLeft) / plotW) * timeSpan);

        if (btnReset) btnReset.style.display = "inline-block";
      }
      renderCanvas();
    };

    wrap.ondblclick = function() {
      state.zoomStart = null;
      state.zoomEnd = null;
      if (btnReset) btnReset.style.display = "none";
      renderCanvas();
    };

    if (btnReset) {
      btnReset.onclick = function() {
        state.zoomStart = null;
        state.zoomEnd = null;
        btnReset.style.display = "none";
        renderCanvas();
      };
    }
  }

  function setupTimeButtons() {
    const btns = document.querySelectorAll(".sgs-time-pill");
    btns.forEach(btn => {
      btn.onclick = function() {
        btns.forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        state.timeRangeSec = parseInt(btn.getAttribute("data-sec")) || 21600;
        state.zoomStart = null;
        state.zoomEnd = null;
        const btnReset = getEl("sgs-btn-reset-zoom");
        if (btnReset) btnReset.style.display = "none";
        fetchTelemetry();
      };
    });
  }

  function setupSearchInput() {
    const mount = getEl("sgs-search-mount");
    if (!mount) return;
    let inp = getEl("sgs-host-search");
    if (!inp) {
      inp = document.createElement("input");
      inp.type = "text";
      inp.id = "sgs-host-search";
      inp.className = "sgs-search-input";
      inp.placeholder = "Filtrar filial, IP ou ISP...";
      inp.autocomplete = "off";
      mount.appendChild(inp);
    }
    inp.value = state.searchQuery || "";
    inp.oninput = function(e) {
      state.searchQuery = e.target.value || "";
      applyFiltersAndRender(true);
    };
  }

  function setupDrawer() {
    const btnOpen = getEl("sgs-btn-drawer");
    const btnClose = getEl("sgs-drawer-close");
    const drawer = getEl("sgs-drawer");
    if (btnOpen && drawer) {
      btnOpen.onclick = () => {
        renderDrawerInfo();
        drawer.style.display = "flex";
      };
    }
    if (btnClose && drawer) {
      btnClose.onclick = () => { drawer.style.display = "none"; };
    }
  }

  function init() {
    updateGroupStatusBanner();
    renderIspFilterPills();
    applyFiltersAndRender(false);
    renderIfaceSelect();
    renderInterfacesTable();
    updateChassisUI();
    setupCanvasEvents();
    setupTimeButtons();
    setupSearchInput();
    setupDrawer();

    const sub = getEl("sgs-chart-sub");
    if (sub && state.currentHost && state.currentIface) {
      sub.textContent = `Ativo: ${state.currentHost.name} • Porta: ${state.currentIface.name}`;
    }

    if (state.historyIn.length > 0 || state.historyOut.length > 0) {
      updateKPIs(state.historyIn, state.historyOut);
      renderCanvas();
    }

    const btnSync = getEl("sgs-sync-btn");
    if (btnSync) {
      btnSync.onclick = async () => {
        await syncCatalogFromZabbix(true);
        await fetchTelemetry();
      };
    }

    window.addEventListener("resize", () => renderCanvas());

    // Polling de telemetria a cada 15 segundos
    state.pollTimer = setInterval(() => {
      if (!document.hidden) fetchTelemetry();
    }, 15000);

    // Auto-Discovery contínuo do grupo SGS_LINKS_GRAFANA a cada 45 segundos
    state.catalogTimer = setInterval(() => {
      if (!document.hidden) syncCatalogFromZabbix(false);
    }, 45000);

    // Sincronizar catálogo ao abrir e buscar telemetria
    fetchTelemetry();
    syncCatalogFromZabbix(false);
  }

  window.__SGS_MODEM_TWIN_RUNTIME__ = {
    destroy: function() {
      if (state.pollTimer) clearInterval(state.pollTimer);
      if (state.catalogTimer) clearInterval(state.catalogTimer);
    }
  };

  setTimeout(init, 50);

})();
"""

js_script = (
    js_script
    .replace("__ZABBIX_URL__", ZABBIX_URL)
    .replace("__ZABBIX_TOKEN__", ZABBIX_TOKEN)
    .replace("__CATALOG_JSON__", catalog_json)
    .replace("__GROUP_META_JSON__", initial_group_meta)
)

clean_lines = [l.strip() for l in html_content.splitlines() if l.strip()]
html_clean = "\n".join(clean_lines)

# 5. Construir o JSON do Dashboard do Grafana
print("5. Montando JSON do Dashboard para o Grafana...")

dashboard_obj = {
    "annotations": { "list": [] },
    "editable": True,
    "fiscalYearStartMonth": 0,
    "graphTooltip": 0,
    "links": [],
    "liveNow": False,
    "panels": [
        {
            "datasource": { "type": "datasource", "uid": "-- Mixed --" },
            "gridPos": { "h": 29, "w": 24, "x": 0, "y": 0 },
            "id": 1,
            "options": {
                "afterRender": js_script,
                "content": html_clean,
                "defaultContent": html_clean,
                "renderMode": "everyRow",
                "styles": css_styles
            },
            "targets": [],
            "title": "",
            "transparent": True,
            "type": "marcusolsson-dynamictext-panel"
        }
    ],
    "refresh": "",
    "schemaVersion": 39,
    "tags": ["sgs", "modem", "wan", "link", "snmp", "sgs_links_grafana"],
    "time": { "from": "now-6h", "to": "now" },
    "timepicker": {},
    "timezone": "browser",
    "title": DASHBOARD_TITLE,
    "uid": DASHBOARD_UID,
    "version": 1
}

full_html = f"{html_content}\n<style>{css_styles}</style>\n<script>{js_script}</script>"

os.makedirs("grafana/dashboards", exist_ok=True)
with open("grafana/dashboards/sgs_modem_wan_twin.html", "w", encoding="utf-8") as f:
    f.write(full_html)

with open("grafana/dashboards/sgs_modem_wan_twin.json", "w", encoding="utf-8") as f:
    json.dump(dashboard_obj, f, indent=2, ensure_ascii=False)

print("Arquivos locais gerados em grafana/dashboards/sgs_modem_wan_twin.*")

# 6. Publicar no Grafana REST API
print(f"6. Publicando no Grafana ({GRAFANA_URL}/api/dashboards/db)...")

try:
    check_r = requests.get(f"{GRAFANA_URL}/api/dashboards/uid/{DASHBOARD_UID}", auth=(GRAFANA_USER, GRAFANA_PASSWORD))
    if check_r.status_code == 200:
        existing = check_r.json()
        dashboard_obj["id"] = existing["dashboard"]["id"]
        dashboard_obj["version"] = existing["dashboard"].get("version", 0) + 1
        print(f"Dashboard existente detectado (ID: {dashboard_obj['id']}). Incrementando versão para {dashboard_obj['version']}...")
except Exception as e:
    print("Novo dashboard será criado.", e)

deploy_payload = {
    "dashboard": dashboard_obj,
    "folderId": TARGET_FOLDER_ID,
    "overwrite": True
}

deploy_r = requests.post(
    f"{GRAFANA_URL}/api/dashboards/db",
    json=deploy_payload,
    auth=(GRAFANA_USER, GRAFANA_PASSWORD),
    headers={"Content-Type": "application/json"}
)

print(f"Status do Deploy: {deploy_r.status_code}")
print(f"Resposta Grafana: {deploy_r.text}")

if deploy_r.status_code == 200:
    res_data = deploy_r.json()
    print("\n[OK] SUCESSO! Dashboard de Modems/Links WAN implantada com sucesso no Grafana:")
    print(f"URL: {GRAFANA_URL}{res_data.get('url')}")
    print(f"UID: {DASHBOARD_UID}")
    print(f"Pasta: POC ALEX (Folder ID: {TARGET_FOLDER_ID})")
else:
    print("\n[FAIL] Falha no deploy no Grafana:", deploy_r.status_code, deploy_r.text)
