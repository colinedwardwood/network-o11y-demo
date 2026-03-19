#!/usr/bin/env python3
"""
Generate Grafana dashboard JSON files for the network-o11y-demo.

Run:  python3 grafana/dashboards.py

Metric names verified against live Prometheus data:

SNMP (Grafana Alloy integrations/snmp):
  job label:     integrations/snmp/<device>   (e.g. integrations/snmp/spine1)
  ifDescr:       ethernet-1/1 format
  Names follow standard snmp_exporter / IF-MIB conventions (ifHCInOctets, etc.)

gNMI (gnmic → Alloy relabeling → Prometheus):
  job:           integrations/gnmi
  source:        device name  (spine1, leaf1, …)
  interface_name: ethernet-1/1
  neighbor_peer_address: BGP peer IP

  gnmic generates long YANG-path metric names; Alloy's prometheus.relabel
  "netbox_enrich_gnmi" renames them to short srl_* names following
  https://prometheus.io/docs/practices/naming/:

    srl_iface_{in,out}_octets              — interface byte counters
    srl_iface_{in,out}_error_packets       — interface error counters
    srl_iface_{in,out}_discarded_packets   — interface discard counters
    srl_iface_{in,out}_packets             — interface packet counters
    srl_iface_carrier_transitions          — link flap counter

    srl_bgp_neighbor_established_transitions      — BGP session flap counter
    srl_bgp_neighbor_afi_safi_received_routes     — routes received per AFI/SAFI
    srl_bgp_neighbor_afi_safi_active_routes       — active routes per AFI/SAFI
    srl_bgp_neighbor_afi_safi_sent_routes         — routes advertised
    srl_bgp_neighbor_peer_as                      — remote AS number
    srl_bgp_neighbor_received_messages_total_notifications
    srl_bgp_neighbor_sent_messages_total_notifications

    srl_cpu_total_average_1                — 1-min CPU utilization %
    srl_cpu_total_average_5                — 5-min CPU utilization %
    srl_memory_free                        — free memory bytes
    srl_memory_utilization                 — memory utilization %
    srl_memory_physical                    — total physical memory bytes
"""

import json, os

OUT_DIR = os.path.join(os.path.dirname(__file__), "dashboards")
TAGS    = ["network-o11y-demo"]
SCHEMA  = 41

# ── Metric name constants ──────────────────────────────────────────────────────

# SNMP job selectors
# SR Linux SNMP series use job=integrations/snmp/<device> with no shared label;
# filter by job regex to select only fabric devices.
SNMP_ALL = 'job=~"integrations/snmp/(spine|leaf).*"'
SNMP_SRL = SNMP_ALL  # alias kept for compatibility

# gNMI interface stats — renamed from gnmic YANG-path names by Alloy relabeling
IFACE_IN       = "srl_iface_in_octets"
IFACE_OUT      = "srl_iface_out_octets"
IFACE_IN_ERR   = "srl_iface_in_error_packets"
IFACE_OUT_ERR  = "srl_iface_out_error_packets"
IFACE_IN_DISC  = "srl_iface_in_discarded_packets"
IFACE_OUT_DISC = "srl_iface_out_discarded_packets"
IFACE_IN_PKT   = "srl_iface_in_packets"
IFACE_OUT_PKT  = "srl_iface_out_packets"
IFACE_CARRIER  = "srl_iface_carrier_transitions"

# gNMI BGP metrics
BGP_ESTAB      = "srl_bgp_neighbor_established_transitions"
BGP_RX_ROUTES  = "srl_bgp_neighbor_afi_safi_received_routes"
BGP_ACT_ROUTES = "srl_bgp_neighbor_afi_safi_active_routes"
BGP_SENT_ROUTES= "srl_bgp_neighbor_afi_safi_sent_routes"
BGP_PEER_AS    = "srl_bgp_neighbor_peer_as"

# gNMI system resources
CPU_TOTAL_1    = "srl_cpu_total_average_1"
CPU_TOTAL_5    = "srl_cpu_total_average_5"
MEM_FREE       = "srl_memory_free"
MEM_UTIL       = "srl_memory_utilization"
MEM_PHYSICAL   = "srl_memory_physical"


# ── Dashboard header HTML ─────────────────────────────────────────────────────
# Each dashboard gets a full-width "About this Dashboard" row + HTML text panel
# injected at the top.  Content lives here so regenerating dashboards.py
# preserves the headers.  See with_header() below.

HEADER_H = 5   # height of the about text panel in grid units

ABOUT_HTML = {
    "network-topology": """\
<div style="padding:10px 16px;font-size:14px;line-height:1.65;">
<p style="margin:0 0 8px 0;">
  <strong>Network O11y — Network Overview</strong> shows the live state of a Nokia SR Linux
  2-spine / 3-leaf Clos fabric. The animated topology map colours each link by utilisation,
  and the inventory table lists every device's role, interfaces, and current alarm state.
</p>
<p style="margin:0;">
  <strong>Telemetry pipeline:</strong>
  Interface counters (in/out octets, oper-state) are collected every 60 s by
  <strong>Grafana Alloy via SNMP v2c</strong> and stored in Prometheus.
  Device metadata (hostname, role, site) is pulled from <strong>NetBox</strong> and
  joined as metric labels during ingestion. Syslog events from each switch are
  forwarded over <strong>UDP 6514</strong> to Alloy's Loki receiver and stored in
  Grafana Cloud Loki.
</p>
</div>""",

    "device-details": """\
<div style="padding:10px 16px;font-size:14px;line-height:1.65;">
<p style="margin:0 0 8px 0;">
  <strong>Network O11y — Device Details</strong> is a per-device drill-down for a single
  SR Linux switch. Select a node with the <em>Device</em> variable above. Panels cover
  CPU and memory utilisation, per-interface traffic rates and errors, BGP neighbour state,
  and a live syslog event feed from the device.
</p>
<p style="margin:0;">
  <strong>Telemetry pipeline:</strong>
  CPU, memory, and BGP metrics come from <strong>gNMI streaming telemetry</strong> — gnmic
  subscribes to each SR Linux gNMI endpoint, exports the data as Prometheus metrics, and
  Alloy scrapes them every 30 s. Interface traffic counters are collected separately by
  Alloy via <strong>SNMP v2c</strong> polling (60 s interval). Syslog events are forwarded
  by the SR Linux rsyslog daemon over <strong>UDP 6514</strong> directly to Alloy's Loki
  receiver (ClusterIP), then shipped to Grafana Cloud Loki.
</p>
</div>""",

    "bgp-status": """\
<div style="padding:10px 16px;font-size:14px;line-height:1.65;">
<p style="margin:0 0 8px 0;">
  <strong>Network O11y — BGP Session Status</strong> gives a fabric-wide view of every BGP
  neighbour relationship across the Clos fabric. Panels show session state, established /
  reset transition counts, advertised and received route counts, and BGP message-rate
  activity per peer.
</p>
<p style="margin:0;">
  <strong>Telemetry pipeline:</strong>
  All metrics come from <strong>gNMI streaming telemetry</strong>. gnmic subscribes to
  <code>/network-instance[name=default]/protocols/bgp/neighbor/...</code> on each SR Linux
  node and exports the data as labelled Prometheus metrics. Grafana Alloy scrapes the gnmic
  <code>/metrics</code> endpoint every 30 s and ships the data to Grafana Cloud.
</p>
</div>""",

    "interface-health": """\
<div style="padding:10px 16px;font-size:14px;line-height:1.65;">
<p style="margin:0 0 8px 0;">
  <strong>Network O11y — Interface Health</strong> surfaces operational state, throughput,
  and error counters for every interface on every switch in the fabric. Use the
  <em>Device</em> and <em>Interface</em> variables to narrow the view.
</p>
<p style="margin:0;">
  <strong>Telemetry pipeline:</strong>
  All metrics are collected via <strong>SNMP v2c</strong> polling by Grafana Alloy every
  60 s. Standard IF-MIB OIDs are queried:
  <code>ifOperStatus</code>, <code>ifHCInOctets</code>, <code>ifHCOutOctets</code>,
  <code>ifInErrors</code>, <code>ifOutErrors</code>, <code>ifInDiscards</code>,
  <code>ifOutDiscards</code>. Interface labels (device name, role, site) are enriched from
  <strong>NetBox</strong> via Alloy's relabelling pipeline before ingestion into Prometheus.
</p>
</div>""",

    "traffic-flows": """\
<div style="padding:10px 16px;font-size:14px;line-height:1.65;">
<p style="margin:0 0 8px 0;">
  <strong>Network O11y — Fabric Traffic</strong> shows per-interface ingress and egress byte
  and packet rates across the entire fabric, plus fabric-wide aggregate totals. Use the
  <em>Device</em> variable to focus on a single switch.
</p>
<p style="margin:0;">
  <strong>Telemetry pipeline:</strong>
  Interface statistics are collected via <strong>gNMI streaming telemetry</strong>. gnmic
  subscribes to <code>/interface[name=*]/statistics/</code> on each SR Linux node and
  exports in/out octet and packet counters as Prometheus metrics. Grafana Alloy scrapes
  the gnmic endpoint every 30 s and forwards data to Grafana Cloud.
</p>
</div>""",

    "traffic-sankey": """\
<div style="padding:10px 16px;font-size:14px;line-height:1.65;">
<p style="margin:0 0 8px 0;">
  <strong>Network O11y — Traffic Sankey</strong> visualises directional traffic volumes
  between the spine and leaf layers of the Clos fabric as an interactive Sankey diagram.
  Link widths are proportional to egress byte rate.
</p>
<p style="margin:0;">
  <strong>Telemetry pipeline:</strong>
  Egress byte counters are collected via <strong>SNMP v2c</strong> polling by Grafana Alloy
  (60 s interval, IF-MIB <code>ifHCOutOctets</code>). PromQL
  <code>label_replace()</code> expressions map interface names to connected peer devices,
  enabling the flow-based visualisation.
</p>
</div>""",
}


# ── Panel helpers ──────────────────────────────────────────────────────────────

def _ds(kind="prometheus"):
    uid = "${datasource}" if kind == "prometheus" else "${loki_datasource}"
    return {"type": kind, "uid": uid}


def row(title, y, collapsed=False):
    return {
        "id": None, "type": "row", "title": title,
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
        "collapsed": collapsed, "panels": [],
    }


def timeseries(title, targets, x, y, w=12, h=8, unit="", decimals=None,
               stacked=False, legend_calcs=None, thresholds=None, ds_type="prometheus"):
    legend = legend_calcs or ["lastNotNull", "max", "mean"]
    field_defaults = {
        "unit": unit,
        "custom": {
            "lineWidth": 1, "fillOpacity": 8 if stacked else 4,
            "showPoints": "never", "spanNulls": True,
            "stacking": {"mode": "normal" if stacked else "none", "group": "A"},
        },
    }
    if decimals is not None:
        field_defaults["decimals"] = decimals
    if thresholds:
        field_defaults["thresholds"] = thresholds
    return {
        "id": None, "type": "timeseries", "title": title,
        "datasource": _ds(ds_type),
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "fieldConfig": {"defaults": field_defaults, "overrides": []},
        "options": {
            "tooltip": {"mode": "multi", "sort": "desc"},
            "legend": {"displayMode": "table", "placement": "bottom", "calcs": legend},
        },
        "targets": targets,
    }


def stat(title, targets, x, y, w=6, h=4, unit="", color_mode="thresholds",
         thresholds=None, reduce="lastNotNull", ds_type="prometheus",
         text_mode="auto", graph_mode="area", option_color_mode="background"):
    th = thresholds or {
        "mode": "absolute",
        "steps": [{"color": "green", "value": None}, {"color": "red", "value": 80}],
    }
    return {
        "id": None, "type": "stat", "title": title,
        "datasource": _ds(ds_type),
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "fieldConfig": {
            "defaults": {
                "unit": unit, "thresholds": th,
                "color": {"mode": color_mode},
            },
            "overrides": [],
        },
        "options": {
            "reduceOptions": {"calcs": [reduce], "fields": "", "values": False},
            "colorMode": option_color_mode, "graphMode": graph_mode,
            "justifyMode": "auto", "orientation": "auto", "textMode": text_mode,
        },
        "targets": targets,
    }


def table(title, targets, x, y, w=24, h=10, overrides=None, ds_type="prometheus",
          transformations=None, sort_by=None):
    return {
        "id": None, "type": "table", "title": title,
        "datasource": _ds(ds_type),
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "fieldConfig": {"defaults": {}, "overrides": overrides or []},
        "options": {
            "footer": {"show": False, "reducer": ["sum"]},
            "showHeader": True, "sortBy": sort_by or [], "cellHeight": "sm",
        },
        "targets": targets,
        "transformations": transformations or [],
    }


def logs_panel(title, targets, x, y, w=24, h=8):
    return {
        "id": None, "type": "logs", "title": title,
        "datasource": _ds("loki"),
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "options": {
            "dedupStrategy": "none", "enableLogDetails": True,
            "prettifyLogMessage": False, "showLabels": False,
            "showTime": True, "sortOrder": "Descending", "wrapLogMessage": False,
        },
        "targets": targets,
    }


def state_timeline(title, targets, x, y, w=24, h=5, value_mappings=None):
    return {
        "id": None, "type": "state-timeline", "title": title,
        "datasource": _ds(),
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "fieldConfig": {
            "defaults": {
                "custom": {"lineWidth": 0, "fillOpacity": 90},
                "mappings": value_mappings or [
                    {"type": "value", "options": {
                        "1": {"text": "up",   "color": "green", "index": 0},
                        "2": {"text": "down", "color": "red",   "index": 1},
                    }},
                ],
            },
            "overrides": [],
        },
        "options": {
            "alignValue": "left", "fillGapsWith": None,
            "legend": {"displayMode": "list", "placement": "bottom"},
            "tooltip": {"mode": "single", "sort": "none"},
            "rowHeight": 0.9, "showValue": "auto",
        },
        "targets": targets,
    }


def gauge(title, targets, x, y, w=6, h=4, unit="%", min_val=0, max_val=100,
          ds_type="prometheus"):
    return {
        "id": None, "type": "gauge", "title": title,
        "datasource": _ds(ds_type),
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "fieldConfig": {
            "defaults": {
                "unit": unit, "min": min_val, "max": max_val,
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"color": "green", "value": None},
                        {"color": "yellow", "value": 70},
                        {"color": "red",    "value": 90},
                    ],
                },
            },
            "overrides": [],
        },
        "options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "orientation": "auto"},
        "targets": targets,
    }


def text_panel(title, content, x, y, w=24, h=6, mode="markdown"):
    return {
        "id": None, "type": "text", "title": title,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "options": {"content": content, "mode": mode},
    }


def button_panel(title, button_text, url, x, y, w=5, h=5, variant="primary"):
    """volkovlabs-form-panel — custom button using Business Forms.

    Requires the 'Business Forms' plugin (volkovlabs-form-panel) to be
    installed on the Grafana instance.  On click the button executes
    customCode which uses fetch() to POST to `url`.  Grafana interpolates
    dashboard variables (e.g. ${controller_url}) inside customCode before
    the JavaScript runs, so the URL is resolved at click time.

    Uses context.grafana.notifySuccess / notifyError for in-dashboard feedback.
    """
    # Grafana interpolates ${...} variables in option strings before rendering,
    # so the URL reference is resolved at runtime in the browser.
    custom_code = (
        f"fetch('{url}', {{method: 'POST'}})"
        f"  .then(function(r) {{ return r.json(); }})"
        f"  .then(function() {{ context.grafana.notifySuccess(['{button_text}', 'Command sent successfully.']); }})"
        f"  .catch(function(e) {{ context.grafana.notifyError(['{button_text}', 'Error: ' + e.message]); }});"
    )
    return {
        "id": None,
        "type": "volkovlabs-form-panel",
        "title": title,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "datasource": None,
        "targets": [],
        "fieldConfig": {"defaults": {}, "overrides": []},
        "options": {
            "sync": False,
            "elements": [
                {
                    "uid": button_text.lower().replace(" ", "-"),
                    "id": button_text.lower().replace(" ", "-"),
                    "title": "",
                    "type": "button",
                    "buttonLabel": button_text,
                    "customCode": custom_code,
                    "icon": "",
                    "size": "lg",
                    "variant": variant,
                    "foregroundColor": "",
                    "backgroundColor": "",
                    "show": "form",
                    "labelWidth": 10,
                    "width": None,
                    "tooltip": "",
                    "section": "",
                    "unit": "",
                    "value": "",
                }
            ],
            "submit": {"confirm": False},
            "resetAction": {"confirm": False},
            "saveDefault": {"confirm": False},
            "layout": {"variant": "single"},
            "buttonGroup": {"orientation": "center"},
        },
    }


def with_header(panels: list, key: str) -> list:
    """Prepend an 'About this Dashboard' row + HTML text panel to panels.

    The About row must contain exactly one panel (the text panel).  In Grafana,
    a non-collapsed row visually owns every panel until the next row panel.  If
    the first content panel is not a row, we insert a silent separator row right
    after the text panel so the About row cannot absorb any content panels.

    All existing panels are shifted down accordingly.
    """
    html = ABOUT_HTML[key]
    needs_separator = panels and panels[0].get("type") != "row"
    # Total shift: row(1) + text(HEADER_H) + optional separator row(1)
    shift = 1 + HEADER_H + (1 if needs_separator else 0)
    for p in panels:
        p["gridPos"]["y"] += shift

    header = [
        {
            "id": None, "type": "row",
            "title": "About this Dashboard",
            "gridPos": {"h": 1, "w": 24, "x": 0, "y": 0},
            "collapsed": False, "panels": [],
        },
        {
            "id": None, "type": "text", "title": "",
            "gridPos": {"h": HEADER_H, "w": 24, "x": 0, "y": 1},
            "datasource": None,
            "fieldConfig": {"defaults": {}, "overrides": []},
            "options": {
                "code": {
                    "language": "plaintext",
                    "showLineNumbers": False,
                    "showMiniMap": False,
                },
                "content": html,
                "mode": "html",
            },
            "pluginVersion": "10.0.0",
            "transparent": True,
        },
    ]
    if needs_separator:
        header.append({
            "id": None, "type": "row",
            "title": "",
            "gridPos": {"h": 1, "w": 24, "x": 0, "y": 1 + HEADER_H},
            "collapsed": False, "panels": [],
        })
    return header + panels


def flow_panel(title, targets, x, y, w, h, svg_url, panel_config_url, site_config_url=""):
    """andrewbmchugh-flow-panel — live topology weathermap."""
    options = {
        "animationControlEnabled": True,
        "animationsEnabled": True,
        "highlighterEnabled": True,
        "panZoomEnabled": True,
        "timeSliderEnabled": True,
        "testDataEnabled": False,
        "svg": svg_url,
        "panelConfig": panel_config_url,
    }
    if site_config_url:
        options["siteConfig"] = site_config_url
    return {
        "id": None,
        "type": "andrewbmchugh-flow-panel",
        "title": title,
        "datasource": _ds(),
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "options": options,
        "targets": targets,
    }


def sankey_panel(title, targets, x, y, w=24, h=12, transformations=None):
    """netsage-sankey-panel — flow diagram.

    Requires table-format data with string columns as flow path nodes and one
    numeric column as the flow value.  Always pass instant=True, format='table'
    targets and an 'organize' transformation to drop the Time column.
    """
    return {
        "id": None,
        "type": "netsage-sankey-panel",
        "title": title,
        "datasource": _ds(),
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "fieldConfig": {"defaults": {}, "overrides": []},
        "options": {
            "linkColor": "multi",
            "nodeColor": "#7EB26D",
            "nodeWidth": 20,
            "nodePadding": 10,
            "layoutIterations": 32,
        },
        "targets": targets,
        "transformations": transformations or [],
    }


# ── Target helpers ────────────────────────────────────────────────────────────

def _t(expr, legend="", ref="A", ds_type="prometheus"):
    return {
        "datasource": _ds(ds_type),
        "expr": expr,
        "legendFormat": legend,
        "refId": ref,
        "editorMode": "code",
        "range": True,
        "instant": False,
    }


def _t_inst(expr, legend="", ref="A", fmt=""):
    """Instant query — for stat/table panels.

    Pass fmt='table' for table panels so Prometheus returns label columns
    instead of a single series column named by the full label set.
    """
    t = {
        "datasource": _ds(),
        "expr": expr,
        "legendFormat": legend,
        "refId": ref,
        "editorMode": "code",
        "range": False,
        "instant": True,
    }
    if fmt:
        t["format"] = fmt
    return t


def _loki(query, legend="", ref="A"):
    return {
        "datasource": _ds("loki"),
        "expr": query,
        "legendFormat": legend,
        "refId": ref,
    }


# ── Variable helpers ──────────────────────────────────────────────────────────

_DS_DEFAULTS = {
    "prometheus": "grafanacloud-networko11ydev-prom",
    "loki":       "grafanacloud-networko11ydev-logs",
}


def ds_var(name="datasource", label="Prometheus", kind="prometheus"):
    default_uid = _DS_DEFAULTS.get(kind, "")
    return {
        "name": name, "type": "datasource", "label": label,
        "query": kind, "refresh": 1,
        "current": {
            "selected": True,
            "text": default_uid,
            "value": default_uid,
        },
        "hide": 0,
        "includeAll": False, "multi": False, "options": [],
    }


def query_var(name, label, query, multi=True, include_all=True,
              all_value=None, regex="", refresh=2, hide=0):
    v = {
        "name": name, "type": "query", "label": label,
        "datasource": _ds(),
        "query": {"query": query, "refId": "StandardVariableQuery"},
        "refresh": refresh, "regex": regex, "sort": 1,
        "multi": multi, "includeAll": include_all,
        "current": {}, "hide": hide, "options": [],
    }
    if all_value:
        v["allValue"] = all_value
    return v


def const_var(name, label, value, hide=0):
    """Constant variable — a fixed string editable from the dashboard header."""
    return {
        "name": name, "type": "constant", "label": label,
        "query": value,
        "current": {"value": value, "text": value, "selected": False},
        "hide": hide,
        "options": [],
    }


# ── Panel ID assignment ───────────────────────────────────────────────────────

def number_panels(panels):
    for i, p in enumerate(panels, start=1):
        if p.get("id") is None:
            p["id"] = i
    return panels


# ── Dashboard wrapper ─────────────────────────────────────────────────────────

def dashboard(uid, title, panels, variables, description="", refresh="30s"):
    return {
        "uid": uid, "title": title, "description": description,
        "tags": TAGS, "schemaVersion": SCHEMA, "version": 0,
        "refresh": refresh,
        "time": {"from": "now-1h", "to": "now"},
        "timepicker": {}, "timezone": "browser", "editable": True,
        "graphTooltip": 1, "links": [],
        "panels": number_panels(panels),
        "templating": {"list": variables},
        "annotations": {"list": []},
        "fiscalYearStartMonth": 0,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Dashboard 1 — Interface Health (SNMP)
# ═══════════════════════════════════════════════════════════════════════════════

def dash_interface_health():
    BASE  = f'{SNMP_ALL}'
    DFILT = f'job=~"integrations/snmp/$device"'
    IFACE = 'ifDescr=~"$interface"'
    ALL      = f'{BASE}, {DFILT}'
    ALLIFACE = f'{BASE}, {DFILT}, {IFACE}'

    panels = [
        stat("Interfaces Up", [_t_inst(
            f'count(ifOperStatus{{{ALL}}} == 1)', "Up",
        )], x=0, y=0, w=4, h=4, unit="none",
            thresholds={"mode": "absolute", "steps": [{"color": "green", "value": None}]}),

        stat("Interfaces Down", [_t_inst(
            f'count(ifOperStatus{{{ALL}}} == 2) or vector(0)', "Down",
        )], x=4, y=0, w=4, h=4, unit="none",
            thresholds={"mode": "absolute", "steps": [
                {"color": "green", "value": None}, {"color": "red", "value": 1}]}),

        stat("SR Linux Devices Polled", [_t_inst(
            f'count(count by (job) (ifHCInOctets{{{BASE}}}))', "Devices",
        )], x=8, y=0, w=4, h=4, unit="none", color_mode="fixed",
            thresholds={"mode": "absolute", "steps": [{"color": "blue", "value": None}]}),

        stat("Total Interfaces", [_t_inst(
            f'count(ifHCInOctets{{{ALL}}})', "Interfaces",
        )], x=12, y=0, w=4, h=4, unit="none", color_mode="fixed",
            thresholds={"mode": "absolute", "steps": [{"color": "blue", "value": None}]}),

        stat("Avg Input Error Rate", [_t_inst(
            f'avg(rate(ifInErrors{{{ALL}}}[$__rate_interval]))', "Errors/s",
        )], x=16, y=0, w=4, h=4, unit="reqps",
            thresholds={"mode": "absolute", "steps": [
                {"color": "green", "value": None}, {"color": "yellow", "value": 0.01},
                {"color": "red", "value": 1}]}),

        stat("Avg Discard Rate", [_t_inst(
            f'avg(rate(ifInDiscards{{{ALL}}}[$__rate_interval]))', "Discards/s",
        )], x=20, y=0, w=4, h=4, unit="reqps",
            thresholds={"mode": "absolute", "steps": [
                {"color": "green", "value": None}, {"color": "yellow", "value": 0.01},
                {"color": "red", "value": 1}]}),

        row("Traffic", y=4),

        timeseries("Inbound Traffic (bits/s)", [_t(
            f'rate(ifHCInOctets{{{ALLIFACE}}}[$__rate_interval]) * 8',
            "{{source}} {{ifDescr}}",
        )], x=0, y=5, w=12, h=9, unit="bps"),

        timeseries("Outbound Traffic (bits/s)", [_t(
            f'rate(ifHCOutOctets{{{ALLIFACE}}}[$__rate_interval]) * 8',
            "{{source}} {{ifDescr}}",
        )], x=12, y=5, w=12, h=9, unit="bps"),

        row("Errors & Discards", y=14),

        timeseries("Input Errors (per sec)", [_t(
            f'rate(ifInErrors{{{ALLIFACE}}}[$__rate_interval])',
            "{{source}} {{ifDescr}}",
        )], x=0, y=15, w=12, h=8, unit="reqps"),

        timeseries("Output Errors (per sec)", [_t(
            f'rate(ifOutErrors{{{ALLIFACE}}}[$__rate_interval])',
            "{{source}} {{ifDescr}}",
        )], x=12, y=15, w=12, h=8, unit="reqps"),

        timeseries("Input Discards (per sec)", [_t(
            f'rate(ifInDiscards{{{ALLIFACE}}}[$__rate_interval])',
            "{{source}} {{ifDescr}}",
        )], x=0, y=23, w=12, h=8, unit="reqps"),

        timeseries("Output Discards (per sec)", [_t(
            f'rate(ifOutDiscards{{{ALLIFACE}}}[$__rate_interval])',
            "{{source}} {{ifDescr}}",
        )], x=12, y=23, w=12, h=8, unit="reqps"),

        row("Interface Details", y=31),

        # Single merged table — max by (source, ifDescr) drops all the extra SNMP
        # label columns (ifIndex, ifName, job, instance…) so the merge produces
        # clean device / interface / value columns.
        table("Interface Details", [
            _t_inst(f'max by (source, ifDescr) (ifOperStatus{{{ALLIFACE}}})',
                    ref="A", fmt="table"),
            _t_inst(f'max by (source, ifDescr) (rate(ifHCInOctets{{{ALLIFACE}}}[5m]) * 8)',
                    ref="B", fmt="table"),
            _t_inst(f'max by (source, ifDescr) (rate(ifHCOutOctets{{{ALLIFACE}}}[5m]) * 8)',
                    ref="C", fmt="table"),
        ], x=0, y=32, w=24, h=12,
            transformations=[
                {"id": "merge", "options": {}},
                {"id": "organize", "options": {
                    "excludeByName": {"Time": True},
                    "indexByName": {
                        "source":   0,
                        "ifDescr":  1,
                        "Value #A": 2,
                        "Value #B": 3,
                        "Value #C": 4,
                    },
                    "renameByName": {
                        "source":   "Device",
                        "ifDescr":  "Interface",
                        "Value #A": "Oper State",
                        "Value #B": "In (bps)",
                        "Value #C": "Out (bps)",
                    },
                }},
            ],
            overrides=[
                {"matcher": {"id": "byName", "options": "Device"},
                 "properties": [{"id": "custom.width", "value": 120}]},
                {"matcher": {"id": "byName", "options": "Interface"},
                 "properties": [{"id": "custom.width", "value": 150}]},
                {"matcher": {"id": "byName", "options": "Oper State"},
                 "properties": [
                     {"id": "mappings", "value": [{"type": "value", "options": {
                         "1": {"text": "up",   "color": "green", "index": 0},
                         "2": {"text": "down", "color": "red",   "index": 1},
                     }}]},
                     {"id": "custom.cellOptions", "value": {"type": "color-background"}},
                     {"id": "custom.width", "value": 110},
                 ]},
                {"matcher": {"id": "byName", "options": "In (bps)"},
                 "properties": [{"id": "unit", "value": "bps"}]},
                {"matcher": {"id": "byName", "options": "Out (bps)"},
                 "properties": [{"id": "unit", "value": "bps"}]},
            ],
            sort_by=[{"displayName": "Device", "desc": False}]),

        row("Interface Status", y=44),

        # State timeline shows physical interfaces only (sub-interfaces like
        # ethernet-1/1.0 are excluded by the interface variable's all_value regex).
        state_timeline("Interface Operational State", [_t(
            f'max by (source, ifDescr) (ifOperStatus{{{ALLIFACE}}})',
            "{{source}} {{ifDescr}}",
        )], x=0, y=45, w=24, h=24),

        # ── Interface Event Logs ─────────────────────────────────────────────
        row("Interface Event Logs", y=69),

        # Link state changes, SFP/optics events, autoneg, remote fault, and
        # BFD-triggered events — explains the "why" behind every transition
        # visible in the state timeline above.
        logs_panel("Interface Events — ${device}", [
            _loki('{job="syslog/srl", hostname=~"$device"} |~ "(?i)interface|link.state|carrier|oper.state|ethernet|sfp|transceiver|autoneg|remote.fault|bfd"'),
        ], x=0, y=70, w=24, h=10),
    ]

    variables = [
        ds_var("datasource", "Prometheus"),
        ds_var("loki_datasource", "Loki", "loki"),
        # Single-select device — "All" removed to keep panel row counts manageable.
        query_var("device", "Device",
                  f'label_values(ifHCInOctets{{{SNMP_ALL}}}, job)',
                  multi=False, include_all=False,
                  regex="integrations/snmp/(.*)"),
        # Interface dropdown — sub-interfaces (ethernet-1/1.0 etc.) excluded both
        # from the list (regex) and from the default "All" regex (all_value).
        # This halves the visible row count compared to showing every sub-interface.
        query_var("interface", "Interface",
                  f'label_values(ifHCInOctets{{{SNMP_ALL}, job=~"integrations/snmp/$device"}}, ifDescr)',
                  all_value="[^.]+",
                  regex="^[^.]+$"),
    ]

    return dashboard(
        uid="net-o11y-iface-health",
        title="Network O11y — Interface Health",
        panels=with_header(panels, "interface-health"), variables=variables,
        description="Per-device per-interface SNMP traffic, errors, discards, and oper state.",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Dashboard 2 — BGP Session Status (gNMI)
# ═══════════════════════════════════════════════════════════════════════════════

def _bgp_table_xforms():
    """Shared merge + organize transformations for BGP neighbor tables."""
    return [
        {"id": "merge", "options": {}},
        {"id": "organize", "options": {
            "excludeByName": {"Time": True},
            "indexByName": {
                "source":                0,
                "neighbor_peer_address": 1,
                "Value #A":              2,
                "Value #B":              3,
                "Value #C":              4,
                "Value #D":              5,
                "Value #E":              6,
                "Value #F":              7,
            },
            "renameByName": {
                "source":                "Device",
                "neighbor_peer_address": "Peer IP",
                "Value #A":              "Status",
                "Value #B":              "Flaps",
                "Value #C":              "Peer AS",
                "Value #D":              "Rx Prefixes",
                "Value #E":              "Active Prefixes",
                "Value #F":              "Tx Prefixes",
            },
        }},
    ]


def _bgp_table_overrides():
    """Shared field overrides for BGP neighbor tables."""
    return [
        # Status: value mappings + colored background
        {"matcher": {"id": "byName", "options": "Status"},
         "properties": [
             {"id": "mappings", "value": [
                 {"type": "value",
                  "options": {"0": {"text": "Down", "color": "red", "index": 0}}},
                 {"type": "range",
                  "options": {"from": 1, "to": 99999,
                              "result": {"text": "Up", "color": "green", "index": 1}}},
             ]},
             {"id": "custom.cellOptions", "value": {"type": "color-background"}},
         ]},
        # Flaps: threshold coloring
        {"matcher": {"id": "byName", "options": "Flaps"},
         "properties": [
             {"id": "thresholds", "value": {
                 "mode": "absolute",
                 "steps": [{"color": "green", "value": None},
                           {"color": "yellow", "value": 1},
                           {"color": "red", "value": 5}],
             }},
             {"id": "custom.cellOptions", "value": {"type": "color-background"}},
         ]},
    ]


def dash_bgp_status():
    GNMI  = 'job="integrations/gnmi"'
    DEV   = f'{GNMI}, source=~"$device"'
    # The gNMI path maps to afi_safi_afi_safi_name (double prefix) with values
    # ipv4-unicast, ipv6-unicast, evpn.
    IPV4  = 'afi_safi_afi_safi_name="ipv4-unicast"'

    BGP_RX_MSG   = "srl_bgp_neighbor_received_messages_total_messages"
    BGP_TX_MSG   = "srl_bgp_neighbor_sent_messages_total_messages"
    BGP_RX_UPD   = "srl_bgp_neighbor_received_messages_total_updates"
    BGP_TX_UPD   = "srl_bgp_neighbor_sent_messages_total_updates"
    BGP_RX_NOT   = "srl_bgp_neighbor_received_messages_total_notifications"
    BGP_TX_NOT   = "srl_bgp_neighbor_sent_messages_total_notifications"
    BGP_LOCAL_AS = "srl_bgp_neighbor_local_as_as_number"
    BGP_HOLD     = "srl_bgp_neighbor_timers_negotiated_hold_time"

    panels = [
        row("Session Health", y=0),

        stat("BGP Sessions", [_t_inst(
            f'count({BGP_ESTAB}{{{DEV}}})', "Sessions",
        )], x=0, y=1, w=4, h=4, unit="none", color_mode="fixed",
            thresholds={"mode": "absolute", "steps": [{"color": "blue", "value": None}]}),

        stat("Sessions Up (ever established)", [_t_inst(
            f'count({BGP_ESTAB}{{{DEV}}} >= 1) or vector(0)', "Up",
        )], x=4, y=1, w=4, h=4, unit="none",
            thresholds={"mode": "absolute", "steps": [
                {"color": "red", "value": None}, {"color": "green", "value": 1}]}),

        stat("IPv4 Neighbors Exchanging Routes", [_t_inst(
            f'count({BGP_RX_ROUTES}{{{DEV}, {IPV4}}} > 0) or vector(0)', "Active",
        )], x=8, y=1, w=4, h=4, unit="none",
            thresholds={"mode": "absolute", "steps": [
                {"color": "red", "value": None}, {"color": "green", "value": 1}]}),

        stat("Total IPv4 Received Routes", [_t_inst(
            f'sum({BGP_RX_ROUTES}{{{DEV}, {IPV4}}})', "Routes",
        )], x=12, y=1, w=4, h=4, unit="none",
            thresholds={"mode": "absolute", "steps": [
                {"color": "red", "value": None}, {"color": "green", "value": 1}]}),

        stat("Total IPv4 Active Routes", [_t_inst(
            f'sum({BGP_ACT_ROUTES}{{{DEV}, {IPV4}}})', "Active",
        )], x=16, y=1, w=4, h=4, unit="none", color_mode="fixed",
            thresholds={"mode": "absolute", "steps": [{"color": "green", "value": None}]}),

        stat("Session Flaps (last hour)", [_t_inst(
            f'sum(increase({BGP_ESTAB}{{{DEV}}}[1h])) or vector(0)', "Flaps",
        )], x=20, y=1, w=4, h=4, unit="none",
            thresholds={"mode": "absolute", "steps": [
                {"color": "green", "value": None}, {"color": "yellow", "value": 1},
                {"color": "red", "value": 3}]}),

        row("Underlay Sessions", y=5),

        table("Underlay BGP (Link IPs — exchange loopback reachability)", [
            _t_inst(f'sum by (source, neighbor_peer_address) ({BGP_ESTAB}{{source=~"$device", {GNMI}, neighbor_peer_address=~"192[.]168[.].*"}})',
                    ref="A", fmt="table"),
            _t_inst(f'clamp_min(sum by (source, neighbor_peer_address) ({BGP_ESTAB}{{source=~"$device", {GNMI}, neighbor_peer_address=~"192[.]168[.].*"}}) - 1, 0)',
                    ref="B", fmt="table"),
            _t_inst(f'sum by (source, neighbor_peer_address) ({BGP_PEER_AS}{{source=~"$device", {GNMI}, neighbor_peer_address=~"192[.]168[.].*"}})',
                    ref="C", fmt="table"),
            _t_inst(f'sum by (source, neighbor_peer_address) ({BGP_RX_ROUTES}{{source=~"$device", {GNMI}, neighbor_peer_address=~"192[.]168[.].*", {IPV4}}})',
                    ref="D", fmt="table"),
            _t_inst(f'sum by (source, neighbor_peer_address) ({BGP_ACT_ROUTES}{{source=~"$device", {GNMI}, neighbor_peer_address=~"192[.]168[.].*", {IPV4}}})',
                    ref="E", fmt="table"),
            _t_inst(f'sum by (source, neighbor_peer_address) ({BGP_SENT_ROUTES}{{source=~"$device", {GNMI}, neighbor_peer_address=~"192[.]168[.].*", {IPV4}}})',
                    ref="F", fmt="table"),
        ], x=0, y=6, w=24, h=8,
            transformations=_bgp_table_xforms(),
            overrides=_bgp_table_overrides()),

        row("Overlay Sessions", y=14),

        table("Overlay BGP (Loopback IPs — EVPN / tenant routes)", [
            _t_inst(f'sum by (source, neighbor_peer_address) ({BGP_ESTAB}{{source=~"$device", {GNMI}, neighbor_peer_address=~"10[.].*"}})',
                    ref="A", fmt="table"),
            _t_inst(f'clamp_min(sum by (source, neighbor_peer_address) ({BGP_ESTAB}{{source=~"$device", {GNMI}, neighbor_peer_address=~"10[.].*"}}) - 1, 0)',
                    ref="B", fmt="table"),
            _t_inst(f'sum by (source, neighbor_peer_address) ({BGP_PEER_AS}{{source=~"$device", {GNMI}, neighbor_peer_address=~"10[.].*"}})',
                    ref="C", fmt="table"),
            _t_inst(f'sum by (source, neighbor_peer_address) ({BGP_RX_ROUTES}{{source=~"$device", {GNMI}, neighbor_peer_address=~"10[.].*", {IPV4}}})',
                    ref="D", fmt="table"),
            _t_inst(f'sum by (source, neighbor_peer_address) ({BGP_ACT_ROUTES}{{source=~"$device", {GNMI}, neighbor_peer_address=~"10[.].*", {IPV4}}})',
                    ref="E", fmt="table"),
            _t_inst(f'sum by (source, neighbor_peer_address) ({BGP_SENT_ROUTES}{{source=~"$device", {GNMI}, neighbor_peer_address=~"10[.].*", {IPV4}}})',
                    ref="F", fmt="table"),
        ], x=0, y=15, w=24, h=8,
            transformations=_bgp_table_xforms(),
            overrides=_bgp_table_overrides()),

        row("IPv4 Route Counts", y=23),

        timeseries("IPv4 Received Routes per Neighbor", [_t(
            f'{BGP_RX_ROUTES}{{{DEV}, {IPV4}}}',
            "{{source}} → {{neighbor_peer_address}}",
        )], x=0, y=24, w=12, h=8, unit="none",
            legend_calcs=["lastNotNull", "max"]),

        timeseries("IPv4 Active Routes per Neighbor", [_t(
            f'{BGP_ACT_ROUTES}{{{DEV}, {IPV4}}}',
            "{{source}} → {{neighbor_peer_address}}",
        )], x=12, y=24, w=12, h=8, unit="none",
            legend_calcs=["lastNotNull", "max"]),

        row("Session Stability & Message Activity", y=32),

        timeseries("BGP Updates Received (rate/s)", [_t(
            f'rate({BGP_RX_UPD}{{{DEV}}}[$__rate_interval])',
            "{{source}} → {{neighbor_peer_address}}",
        )], x=0, y=33, w=12, h=8, unit="reqps",
            legend_calcs=["lastNotNull", "max"]),

        timeseries("BGP Updates Sent (rate/s)", [_t(
            f'rate({BGP_TX_UPD}{{{DEV}}}[$__rate_interval])',
            "{{source}} → {{neighbor_peer_address}}",
        )], x=12, y=33, w=12, h=8, unit="reqps",
            legend_calcs=["lastNotNull", "max"]),

        timeseries("BGP Messages Received (rate/s)", [
            _t(f'rate({BGP_RX_MSG}{{{DEV}}}[$__rate_interval])',
               "{{source}} → {{neighbor_peer_address}}", ref="A"),
        ], x=0, y=41, w=12, h=8, unit="reqps",
            legend_calcs=["lastNotNull", "mean"]),

        timeseries("Established Transitions (cumulative)", [
            _t(f'{BGP_ESTAB}{{{DEV}}}',
               "{{source}} → {{neighbor_peer_address}}", ref="A"),
        ], x=12, y=41, w=12, h=8, unit="none",
            legend_calcs=["lastNotNull"],
            thresholds={"mode": "absolute", "steps": [
                {"color": "green", "value": None}]}),

        # ── BGP Event Logs ───────────────────────────────────────────────────
        row("BGP Event Logs", y=49),

        # BGP NOTIFICATION messages, session state changes, and policy events
        # land here — gives the "why" behind every flap shown in the charts above.
        logs_panel("BGP Events — ${device}", [
            _loki('{job="syslog/srl", hostname=~"$device"} |~ "(?i)bgp|neighbor|notification|hold.timer|open.message|session"'),
        ], x=0, y=50, w=24, h=10),
    ]

    variables = [
        ds_var("datasource", "Prometheus"),
        ds_var("loki_datasource", "Loki", "loki"),
        query_var("device", "Device",
                  f'label_values({BGP_ESTAB}{{job="integrations/gnmi"}}, source)',
                  all_value=".*"),
    ]

    return dashboard(
        uid="net-o11y-bgp-status",
        title="Network O11y — BGP Session Status",
        panels=with_header(panels, "bgp-status"), variables=variables,
        description="BGP neighbor health, route counts, and message activity "
                    "from gNMI streaming telemetry across the SR Linux Clos fabric.",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Dashboard 3 — Fabric Traffic (gNMI interface bytes — replaces NetFlow)
# ═══════════════════════════════════════════════════════════════════════════════

def dash_traffic_flows():
    GNMI = 'job="integrations/gnmi"'
    DEV  = f'{GNMI}, source=~"$device"'
    INTF = f'{DEV}, interface_name=~"$interface"'

    panels = [
        stat("Total Fabric In (last 5m)", [_t_inst(
            f'sum(increase({IFACE_IN}{{{GNMI}}}[5m])) * 8', "Bits",
        )], x=0, y=0, w=6, h=4, unit="bits", color_mode="fixed",
            thresholds={"mode": "absolute", "steps": [{"color": "blue", "value": None}]}),

        stat("Total Fabric Out (last 5m)", [_t_inst(
            f'sum(increase({IFACE_OUT}{{{GNMI}}}[5m])) * 8', "Bits",
        )], x=6, y=0, w=6, h=4, unit="bits", color_mode="fixed",
            thresholds={"mode": "absolute", "steps": [{"color": "blue", "value": None}]}),

        stat("Active Interfaces", [_t_inst(
            f'count({IFACE_IN}{{{GNMI}}})', "Interfaces",
        )], x=12, y=0, w=6, h=4, unit="none", color_mode="fixed",
            thresholds={"mode": "absolute", "steps": [{"color": "blue", "value": None}]}),

        stat("Active Devices", [_t_inst(
            f'count(count by (source) ({IFACE_IN}{{{GNMI}}}))', "Devices",
        )], x=18, y=0, w=6, h=4, unit="none", color_mode="fixed",
            thresholds={"mode": "absolute", "steps": [{"color": "blue", "value": None}]}),

        row("Interface Traffic Rates", y=4),

        timeseries("Inbound (bits/s) — by interface", [_t(
            f'rate({IFACE_IN}{{{INTF}}}[$__rate_interval]) * 8',
            "{{source}} {{interface_name}} in",
        )], x=0, y=5, w=12, h=9, unit="bps"),

        timeseries("Outbound (bits/s) — by interface", [_t(
            f'rate({IFACE_OUT}{{{INTF}}}[$__rate_interval]) * 8',
            "{{source}} {{interface_name}} out",
        )], x=12, y=5, w=12, h=9, unit="bps"),

        row("Top Talkers", y=14),

        timeseries("Top 5 Interfaces by Inbound bps", [_t(
            f'topk(5, rate({IFACE_IN}{{{GNMI}}}[$__rate_interval]) * 8)',
            "{{source}} {{interface_name}}",
        )], x=0, y=15, w=12, h=9, unit="bps"),

        timeseries("Top 5 Interfaces by Outbound bps", [_t(
            f'topk(5, rate({IFACE_OUT}{{{GNMI}}}[$__rate_interval]) * 8)',
            "{{source}} {{interface_name}}",
        )], x=12, y=15, w=12, h=9, unit="bps"),

        row("Packet Rates", y=24),

        timeseries("Inbound Packets/s", [_t(
            f'rate({IFACE_IN_PKT}{{{INTF}}}[$__rate_interval])',
            "{{source}} {{interface_name}} in",
        )], x=0, y=25, w=12, h=8, unit="pps"),

        timeseries("Outbound Packets/s", [_t(
            f'rate({IFACE_OUT_PKT}{{{INTF}}}[$__rate_interval])',
            "{{source}} {{interface_name}} out",
        )], x=12, y=25, w=12, h=8, unit="pps"),

        row("Errors & Discards", y=33),

        timeseries("Input Errors (per sec)", [_t(
            f'rate({IFACE_IN_ERR}{{{INTF}}}[$__rate_interval])',
            "{{source}} {{interface_name}}",
        )], x=0, y=34, w=12, h=8, unit="reqps"),

        timeseries("Input Discards (per sec)", [_t(
            f'rate({IFACE_IN_DISC}{{{INTF}}}[$__rate_interval])',
            "{{source}} {{interface_name}}",
        )], x=12, y=34, w=12, h=8, unit="reqps"),
    ]

    variables = [
        ds_var("datasource", "Prometheus"),
        query_var("device", "Device",
                  f'label_values({IFACE_IN}{{job="integrations/gnmi"}}, source)',
                  all_value=".*"),
        query_var("interface", "Interface",
                  f'label_values({IFACE_IN}{{job="integrations/gnmi", source=~"$device"}}, interface_name)',
                  all_value=".*"),
    ]

    return dashboard(
        uid="net-o11y-traffic-flows",
        title="Network O11y — Fabric Traffic",
        panels=with_header(panels, "traffic-flows"), variables=variables,
        description="gNMI interface byte/packet rates per SR Linux device and interface.",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Dashboard 4b — Device Details (drill-down from Network Overview)
# ═══════════════════════════════════════════════════════════════════════════════

def dash_device_details():
    GNMI     = 'job="integrations/gnmi"'
    DEV      = f'{GNMI}, source=~"$device"'
    SNMP_DEV = 'job="integrations/snmp/$device"'

    panels = [
        # ── Top stat row ────────────────────────────────────────────────────
        # avg by (source) collapses duplicate series that arise when Prometheus
        # retains old (pre-enrichment) and new (post-enrichment) label sets.
        stat("CPU %", [_t_inst(f'avg by (source) ({CPU_TOTAL_1}{{{DEV}}})', "CPU")],
             x=0, y=0, w=6, h=4, unit="percent",
             thresholds={"mode": "absolute", "steps": [
                 {"color": "green", "value": None},
                 {"color": "yellow", "value": 50},
                 {"color": "red", "value": 80}]}),

        stat("Memory %", [_t_inst(f'avg by (source) ({MEM_UTIL}{{{DEV}}})', "Memory")],
             x=6, y=0, w=6, h=4, unit="percent",
             thresholds={"mode": "absolute", "steps": [
                 {"color": "green", "value": None},
                 {"color": "yellow", "value": 60},
                 {"color": "red", "value": 85}]}),

        stat("BGP Sessions Up", [_t_inst(
            f'count(sum by (source, neighbor_peer_address) ({BGP_ESTAB}{{{DEV}}}) >= 1)'
            f' or vector(0)', "Sessions")],
             x=12, y=0, w=6, h=4, unit="none",
             thresholds={"mode": "absolute", "steps": [
                 {"color": "red", "value": None},
                 {"color": "green", "value": 1}]}),

        stat("Uptime", [_t_inst(
            f'max(sysUpTime{{{SNMP_DEV}}} / 100)', "Uptime")],
             x=18, y=0, w=6, h=4, unit="dtdurations", color_mode="fixed",
             thresholds={"mode": "absolute", "steps": [{"color": "blue", "value": None}]}),

        # ── System Info stat panels ──────────────────────────────────────────
        # textMode="name" renders the legend string (the extracted label value)
        # as the panel's displayed value rather than the raw numeric 1.
        stat("Model", [_t_inst(
            f'group by (source, model) ('
            f'label_replace(sysDescr{{{SNMP_DEV}}},'
            f' "model", "$1", "sysDescr", "SRLinux-[^ ]+ (7220 IXR-[A-Z0-9]+).*"))',
            "{{model}}")],
            x=0, y=4, w=8, h=3,
            text_mode="name", graph_mode="none", option_color_mode="value",
            color_mode="fixed",
            thresholds={"mode": "absolute", "steps": [{"color": "#ccccdc", "value": None}]}),

        stat("OS Version", [_t_inst(
            f'group by (source, os_ver) ('
            f'label_replace(sysDescr{{{SNMP_DEV}}},'
            f' "os_ver", "$1", "sysDescr", "(SRLinux-v[0-9]+[.][0-9]+[.][0-9]+).*"))',
            "{{os_ver}}")],
            x=8, y=4, w=8, h=3,
            text_mode="name", graph_mode="none", option_color_mode="value",
            color_mode="fixed",
            thresholds={"mode": "absolute", "steps": [{"color": "#ccccdc", "value": None}]}),

        stat("Role", [_t_inst(
            f'group by (source, role) ({CPU_TOTAL_1}{{{DEV}}})',
            "{{role}}")],
            x=16, y=4, w=8, h=3,
            text_mode="name", graph_mode="none", option_color_mode="value",
            color_mode="fixed",
            thresholds={"mode": "absolute", "steps": [{"color": "#ccccdc", "value": None}]}),

        # ── CPU ─────────────────────────────────────────────────────────────
        row("CPU", y=7),

        timeseries("CPU Utilization %", [
            _t(f'avg by (source) ({CPU_TOTAL_1}{{{DEV}}})', "1-min avg", ref="A"),
            _t(f'avg by (source) ({CPU_TOTAL_5}{{{DEV}}})', "5-min avg", ref="B"),
        ], x=0, y=8, w=24, h=8, unit="percent",
            thresholds={"mode": "absolute", "steps": [
                {"color": "green", "value": None},
                {"color": "yellow", "value": 50},
                {"color": "red", "value": 80}]}),

        # ── Memory ──────────────────────────────────────────────────────────
        row("Memory", y=16),

        timeseries("Memory Utilization %", [
            _t(f'avg by (source) ({MEM_UTIL}{{{DEV}}})', "Utilization %"),
        ], x=0, y=17, w=12, h=8, unit="percent",
            thresholds={"mode": "absolute", "steps": [
                {"color": "green", "value": None},
                {"color": "yellow", "value": 60},
                {"color": "red", "value": 85}]}),

        timeseries("Memory Free", [
            _t(f'avg by (source) ({MEM_FREE}{{{DEV}}})', "Free"),
        ], x=12, y=17, w=12, h=8, unit="decbytes"),

        # ── Interface Traffic ────────────────────────────────────────────────
        row("Interface Traffic", y=25),

        timeseries("Inbound (bps) — per interface", [
            _t(f'rate(ifHCInOctets{{{SNMP_DEV}}}[$__rate_interval]) * 8',
               "{{ifDescr}}"),
        ], x=0, y=26, w=12, h=9, unit="bps"),

        timeseries("Outbound (bps) — per interface", [
            _t(f'rate(ifHCOutOctets{{{SNMP_DEV}}}[$__rate_interval]) * 8',
               "{{ifDescr}}"),
        ], x=12, y=26, w=12, h=9, unit="bps"),

        # ── Syslog ──────────────────────────────────────────────────────────
        row("Syslog", y=35),

        logs_panel("Device Logs — ${device}", [
            _loki('{job="syslog/srl", hostname=~"$device"}'),
        ], x=0, y=36, w=24, h=12),
    ]

    variables = [
        ds_var("datasource", "Prometheus"),
        ds_var("loki_datasource", "Loki", "loki"),
        # Single-select, no All option — this is a per-device drill-down.
        query_var("device", "Device",
                  f'label_values({CPU_TOTAL_1}{{job="integrations/gnmi"}}, source)',
                  multi=False, include_all=False),
    ]

    return dashboard(
        uid="net-o11y-device-details",
        title="Network O11y — Device Details",
        panels=with_header(panels, "device-details"), variables=variables,
        description="Per-device drill-down: CPU, memory, interface traffic, and BGP session health.",
    )



# ═══════════════════════════════════════════════════════════════════════════════
# Dashboard 6 — Network Topology (FlowPlugin weathermap + live stats)
# ═══════════════════════════════════════════════════════════════════════════════

def dash_network_topology():
    GNMI     = 'job="integrations/gnmi"'
    SNMP     = SNMP_ALL
    SNMP_SRC = f'{SNMP}, source!=""'   # only new-label series (source set by Alloy fix)
    IPV4     = 'afi_safi_afi_safi_name="ipv4-unicast"'

    SRL_REPO  = "https://raw.githubusercontent.com/srl-labs/srl-telemetry-lab/refs/heads/flow_panel/configs/grafana/flow_panels"
    SVG_URL   = f"{SRL_REPO}/topology.svg"
    PANEL_URL = f"{SRL_REPO}/st_topopanel.yml"
    SITE_URL  = f"{SRL_REPO}/siteconfig.yml"

    def _short_iface(expr, src_label="ifDescr"):
        """Add iface_short label: ethernet-1/1 → e1-1."""
        return (
            f'label_replace({expr},'
            f' "iface_short", "e$1-$2", "{src_label}", "ethernet-(\\\\d+)/(\\\\d+)")'
        )

    # FlowPlugin expects these legend key formats (from topopanel.yml):
    #   oper-state:<device>:<iface_short>
    #   <device>:<iface_short>:out
    #   <device>:<iface_short>:in
    # SNMP now carries "source" = device name (e.g. "spine1") after Alloy relabel fix.
    # ifOperStatus: 1=up → 1 (green), 2=down → 0 (red) via (2 - value)
    oper_state_expr = _short_iface(f'(2 - ifOperStatus{{{SNMP_SRC}}})')
    out_expr        = _short_iface(f'rate(ifHCOutOctets{{{SNMP_SRC}}}[$__rate_interval]) * 8')
    in_expr         = _short_iface(f'rate(ifHCInOctets{{{SNMP_SRC}}}[$__rate_interval]) * 8')

    panels = [
        # ── FlowPlugin live weathermap ────────────────────────────────────────
        flow_panel(
            title="Fabric Map",
            targets=[
                _t(oper_state_expr, "oper-state:{{source}}:{{iface_short}}", ref="A"),
                _t(out_expr,        "{{source}}:{{iface_short}}:out",         ref="B"),
                _t(in_expr,         "{{source}}:{{iface_short}}:in",          ref="C"),
            ],
            x=0, y=0, w=16, h=18,
            svg_url=SVG_URL,
            panel_config_url=PANEL_URL,
            site_config_url=SITE_URL,
        ),

        # ── Right-hand stats column ───────────────────────────────────────────
        stat("BGP Sessions Up", [_t_inst(
            f'count(avg by (source, neighbor_peer_address) ({BGP_ESTAB}{{{GNMI}}}) >= 1)',
            "Sessions",
        )], x=16, y=0, w=4, h=3, unit="none", color_mode="fixed",
            thresholds={"mode": "absolute", "steps": [{"color": "blue", "value": None}]}),

        stat("Session Flaps (1h)", [_t_inst(
            f'sum(increase({BGP_ESTAB}{{{GNMI}}}[1h])) or vector(0)', "Flaps",
        )], x=20, y=0, w=4, h=3, unit="none",
            thresholds={"mode": "absolute", "steps": [
                {"color": "green", "value": None},
                {"color": "yellow", "value": 1},
                {"color": "red", "value": 3}]}),

        stat("IPv4 Active Routes", [_t_inst(
            f'sum({BGP_ACT_ROUTES}{{{GNMI}, {IPV4}}})', "Routes",
        )], x=16, y=3, w=8, h=3, unit="none",
            thresholds={"mode": "absolute", "steps": [
                {"color": "red", "value": None}, {"color": "green", "value": 1}]}),

        stat("Interfaces Up", [_t_inst(
            f'count(ifOperStatus{{{SNMP_SRC}}} == 1)', "Up",
        )], x=16, y=6, w=4, h=3, unit="none",
            thresholds={"mode": "absolute", "steps": [
                {"color": "red", "value": None}, {"color": "green", "value": 1}]}),

        stat("Interfaces Down", [_t_inst(
            f'count(ifOperStatus{{{SNMP_SRC}}} == 2) or vector(0)', "Down",
        )], x=20, y=6, w=4, h=3, unit="none",
            thresholds={"mode": "absolute", "steps": [
                {"color": "green", "value": None}, {"color": "red", "value": 1}]}),

        stat("Fabric Rx", [_t_inst(
            f'sum(rate(ifHCInOctets{{{SNMP_SRC}}}[5m])) * 8', "bps",
        )], x=16, y=9, w=4, h=3, unit="bps", color_mode="fixed",
            thresholds={"mode": "absolute", "steps": [{"color": "blue", "value": None}]}),

        stat("Fabric Tx", [_t_inst(
            f'sum(rate(ifHCOutOctets{{{SNMP_SRC}}}[5m])) * 8', "bps",
        )], x=20, y=9, w=4, h=3, unit="bps", color_mode="fixed",
            thresholds={"mode": "absolute", "steps": [{"color": "blue", "value": None}]}),

        stat("Devices Online", [_t_inst(
            f'count(count by (source) ({CPU_TOTAL_1}{{{GNMI}}}))', "Devices",
        )], x=16, y=12, w=4, h=3, unit="none", color_mode="fixed",
            thresholds={"mode": "absolute", "steps": [{"color": "blue", "value": None}]}),

        stat("Avg CPU", [_t_inst(
            f'avg(avg by (source) ({CPU_TOTAL_1}{{{GNMI}}}))', "CPU",
        )], x=20, y=12, w=4, h=3, unit="percent",
            thresholds={"mode": "absolute", "steps": [
                {"color": "green", "value": None},
                {"color": "yellow", "value": 50},
                {"color": "red", "value": 80}]}),

        stat("Min Device Uptime", [_t_inst(
            f'min(max by (source) (sysUpTime{{{SNMP_SRC}}} / 100))', "Uptime",
        )], x=16, y=15, w=8, h=3, unit="dtdurations", color_mode="fixed",
            thresholds={"mode": "absolute", "steps": [{"color": "blue", "value": None}]}),

        # ── Per-device table — full fleet details ─────────────────────────────
        row("Network Devices", y=18),

        table("Network Devices", [
            # A: BGP sessions per device
            _t_inst(
                f'count by (source) (avg by (source, neighbor_peer_address) ({BGP_ESTAB}{{{GNMI}}}) >= 1)',
                ref="A", fmt="table"),
            # B: BGP flaps last hour
            _t_inst(
                f'sum by (source) (increase({BGP_ESTAB}{{{GNMI}}}[1h]))',
                ref="B", fmt="table"),
            # C: Interfaces up
            _t_inst(
                f'count by (source) (ifOperStatus{{{SNMP_SRC}}} == 1)',
                ref="C", fmt="table"),
            # D: Aggregate Rx bps
            _t_inst(
                f'sum by (source) (rate(ifHCInOctets{{{SNMP_SRC}}}[5m]) * 8)',
                ref="D", fmt="table"),
            # E: Aggregate Tx bps
            _t_inst(
                f'sum by (source) (rate(ifHCOutOctets{{{SNMP_SRC}}}[5m]) * 8)',
                ref="E", fmt="table"),
            # F: Role label (value excluded, label kept for column)
            _t_inst(
                f'sum by (source, role) ('
                f'  label_replace(label_replace({CPU_TOTAL_1}{{{GNMI}}},'
                f'    "role", "Spine", "source", "spine.*"),'
                f'    "role", "Leaf",  "source", "leaf.*"))',
                ref="F", fmt="table"),
            # G: CPU utilization %
            _t_inst(f'avg by (source) ({CPU_TOTAL_1}{{{GNMI}}})',
                    ref="G", fmt="table"),
            # H: Memory utilization %
            _t_inst(f'avg by (source) ({MEM_UTIL}{{{GNMI}}})',
                    ref="H", fmt="table"),
            # I: Model + OS version from sysDescr (Value #I excluded; labels kept)
            _t_inst(
                f'group by (source, model, os_ver) ('
                f'  label_replace('
                f'    label_replace('
                f'      sysDescr{{{SNMP_SRC}}},'
                f'      "os_ver", "$1", "sysDescr", "(SRLinux-v[0-9]+[.][0-9]+[.][0-9]+).*"'
                f'    ),'
                f'    "model", "$1", "sysDescr", "SRLinux-[^ ]+ (7220 IXR-[A-Z0-9]+).*"'
                f'  )'
                f')',
                ref="I", fmt="table"),
            # J: Uptime in seconds (sysUpTime is centiseconds)
            _t_inst(f'max by (source) (sysUpTime{{{SNMP_SRC}}} / 100)',
                    ref="J", fmt="table"),
        ], x=0, y=19, w=24, h=9,
            sort_by=[{"displayName": "Role", "desc": False}],
            transformations=[
                {"id": "merge", "options": {}},
                {"id": "organize", "options": {
                    "excludeByName": {"Time": True, "Value #F": True, "Value #I": True},
                    "indexByName": {
                        "source":   0,
                        "role":     1,
                        "model":    2,
                        "os_ver":   3,
                        "Value #J": 4,
                        "Value #G": 5,
                        "Value #H": 6,
                        "Value #A": 7,
                        "Value #B": 8,
                        "Value #C": 9,
                        "Value #D": 10,
                        "Value #E": 11,
                    },
                    "renameByName": {
                        "source":   "Device",
                        "role":     "Role",
                        "model":    "Model",
                        "os_ver":   "OS Version",
                        "Value #A": "BGP Sessions",
                        "Value #B": "BGP Flaps (1h)",
                        "Value #C": "Interfaces Up",
                        "Value #D": "Rx bps",
                        "Value #E": "Tx bps",
                        "Value #G": "CPU %",
                        "Value #H": "Memory %",
                        "Value #J": "Uptime",
                    },
                }},
            ],
            overrides=[
                {"matcher": {"id": "byName", "options": "Device"},
                 "properties": [
                     {"id": "custom.width", "value": 230},
                     {"id": "links", "value": [{
                         "title": "Open Device Details",
                         "url": "/d/net-o11y-device-details?var-device=${__data.fields.Device}&${__url_time_range}",
                         "targetBlank": False,
                     }]}]},
                {"matcher": {"id": "byName", "options": "Role"},
                 "properties": [{"id": "custom.width", "value": 78}]},
                {"matcher": {"id": "byName", "options": "Model"},
                 "properties": [{"id": "custom.width", "value": 130}]},
                {"matcher": {"id": "byName", "options": "OS Version"},
                 "properties": [{"id": "custom.width", "value": 150}]},
                {"matcher": {"id": "byName", "options": "Uptime"},
                 "properties": [
                     {"id": "unit", "value": "dtdurations"},
                     {"id": "decimals", "value": 0},
                     {"id": "custom.width", "value": 102},
                 ]},
                {"matcher": {"id": "byName", "options": "CPU %"},
                 "properties": [
                     {"id": "unit", "value": "percent"},
                     {"id": "thresholds", "value": {"mode": "absolute", "steps": [
                         {"color": "green", "value": None},
                         {"color": "yellow", "value": 50},
                         {"color": "red", "value": 80},
                     ]}},
                     {"id": "custom.cellOptions", "value": {"type": "color-background"}},
                     {"id": "custom.width", "value": 111},
                 ]},
                {"matcher": {"id": "byName", "options": "Memory %"},
                 "properties": [
                     {"id": "unit", "value": "percent"},
                     {"id": "thresholds", "value": {"mode": "absolute", "steps": [
                         {"color": "green", "value": None},
                         {"color": "yellow", "value": 60},
                         {"color": "red", "value": 85},
                     ]}},
                     {"id": "custom.cellOptions", "value": {"type": "color-background"}},
                     {"id": "custom.width", "value": 100},
                 ]},
                {"matcher": {"id": "byName", "options": "BGP Sessions"},
                 "properties": [
                     {"id": "decimals", "value": 0},
                     {"id": "thresholds", "value": {"mode": "absolute", "steps": [
                         {"color": "red", "value": None},
                         {"color": "green", "value": 1},
                     ]}},
                     {"id": "custom.cellOptions", "value": {"type": "color-background"}},
                     {"id": "custom.width", "value": 110},
                 ]},
                {"matcher": {"id": "byName", "options": "BGP Flaps (1h)"},
                 "properties": [
                     {"id": "decimals", "value": 0},
                     {"id": "thresholds", "value": {"mode": "absolute", "steps": [
                         {"color": "green", "value": None},
                         {"color": "yellow", "value": 1},
                         {"color": "red", "value": 3},
                     ]}},
                     {"id": "custom.cellOptions", "value": {"type": "color-background"}},
                     {"id": "custom.width", "value": 139},
                 ]},
                {"matcher": {"id": "byName", "options": "Interfaces Up"},
                 "properties": [
                     {"id": "decimals", "value": 0},
                     {"id": "custom.width", "value": 110},
                 ]},
                {"matcher": {"id": "byName", "options": "Rx bps"},
                 "properties": [
                     {"id": "unit", "value": "bps"},
                     {"id": "custom.width", "value": 100},
                 ]},
                {"matcher": {"id": "byName", "options": "Tx bps"},
                 "properties": [
                     {"id": "unit", "value": "bps"},
                     {"id": "custom.width", "value": 100},
                 ]},
            ]),
    ]

    # Append the fleet-wide event stream after the device table (y=19+9=28).
    panels += [
        row("Fabric Event Stream", y=28),

        # WARNING/ERROR/CRITICAL messages across all fabric devices — acts as a
        # live NOC feed so problems on any device are visible without drilling in.
        logs_panel("Recent Fabric Events (warn / error / critical)", [
            _loki('{job="syslog/srl"} | severity =~ "warning|error|critical|Warning|Error|Critical"'),
        ], x=0, y=29, w=24, h=12),
    ]

    variables = [
        ds_var("datasource", "Prometheus"),
        ds_var("loki_datasource", "Loki", "loki"),
    ]

    return dashboard(
        uid="net-o11y-topology",
        title="Network O11y — Network Overview",
        panels=with_header(panels, "network-topology"), variables=variables,
        description="Live Clos fabric map with fabric-wide health metrics and a full per-device inventory table.",
        refresh="30s",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Dashboard 7 — Traffic Sankey (netsage-sankey-panel)
# ═══════════════════════════════════════════════════════════════════════════════

def _sankey_target(expr, ref="A"):
    """Instant table-format target required by netsage-sankey-panel."""
    return {
        "datasource": _ds(),
        "expr": expr,
        "legendFormat": "",
        "refId": ref,
        "editorMode": "code",
        "range": False,
        "instant": True,
        "format": "table",
    }


def _hide_time_xform(rename=None):
    """Transformation that drops Time, orders source→destination→value, and renames columns.

    indexByName uses original (pre-rename) field names. Prometheus returns labels
    alphabetically so 'destination' would precede 'source' without explicit ordering.
    """
    renaming = rename or {}
    return [
        {
            "id": "organize",
            "options": {
                "excludeByName": {"Time": True},
                "indexByName": {
                    "source":      0,
                    "destination": 1,
                    "Value":       2,
                },
                "renameByName": renaming,
            },
        }
    ]


def dash_traffic_sankey():
    """Traffic Sankey dashboard.

    The netsage-sankey-panel needs TABLE data where:
      - string columns define the Sankey path nodes (left → right)
      - one numeric column defines the flow width

    Uses SNMP ifHCOutOctets (verified working) instead of gNMI interface metrics.
    label_replace extracts device name from the job label suffix.

    Fabric topology (from NetBox / clab config):
      spine1/2 : ethernet-1/1 → leaf1
      spine1/2 : ethernet-1/2 → leaf2
      spine1/2 : ethernet-1/3 → leaf3
      leaf uplinks: ethernet-1/49 → spine1, ethernet-1/50 → spine2
    """
    SNMP_SPINE = 'job=~"integrations/snmp/spine.*"'
    SNMP_LEAF  = 'job=~"integrations/snmp/leaf.*"'
    # Extracts device name (spine1, leaf1, …) from job into "source" label.
    _src = '"source", "$1", "job", "integrations/snmp/(.*)"'

    def _spine_to_leaf():
        """Spine outbound → leaf: source=spine, destination=leaf."""
        return (
            f'sum by (source, destination) ('
            f'  label_replace('
            f'    label_replace('
            f'      label_replace('
            f'        label_replace('
            f'          rate(ifHCOutOctets{{{SNMP_SPINE}, ifDescr=~"ethernet-1/[123]"}}[$__rate_interval]) * 8,'
            f'          {_src}'
            f'        ),'
            f'        "destination", "leaf1", "ifDescr", "ethernet-1/1"'
            f'      ),'
            f'      "destination", "leaf2", "ifDescr", "ethernet-1/2"'
            f'    ),'
            f'    "destination", "leaf3", "ifDescr", "ethernet-1/3"'
            f'  )'
            f')'
        )

    def _leaf_to_spine():
        """Leaf uplinks outbound → spine: source=leaf, destination=spine.

        ethernet-1/49 connects to spine1, ethernet-1/50 connects to spine2.
        """
        return (
            f'sum by (source, destination) ('
            f'  label_replace('
            f'    label_replace('
            f'      label_replace('
            f'        rate(ifHCOutOctets{{{SNMP_LEAF}, ifDescr=~"ethernet-1/(49|50)"}}[$__rate_interval]) * 8,'
            f'        {_src}'
            f'      ),'
            f'      "destination", "spine1", "ifDescr", "ethernet-1/49"'
            f'    ),'
            f'    "destination", "spine2", "ifDescr", "ethernet-1/50"'
            f'  )'
            f')'
        )

    def _aggregate_spine_leaf():
        """Total traffic in both directions for each spine-leaf pair.

        Adds spine→leaf outbound (spine downlinks) and leaf→spine outbound (leaf uplinks)
        using + on(source, destination). Both sides relabeled source=spine, destination=leaf
        so the 6 pairs (2 spines × 3 leaves) align correctly.
        """
        spine_out = (
            f'sum by (source, destination) ('
            f'  label_replace('
            f'    label_replace('
            f'      label_replace('
            f'        label_replace('
            f'          rate(ifHCOutOctets{{{SNMP_SPINE}, ifDescr=~"ethernet-1/[123]"}}[$__rate_interval]) * 8,'
            f'          {_src}'
            f'        ),'
            f'        "destination", "leaf1", "ifDescr", "ethernet-1/1"'
            f'      ),'
            f'      "destination", "leaf2", "ifDescr", "ethernet-1/2"'
            f'    ),'
            f'    "destination", "leaf3", "ifDescr", "ethernet-1/3"'
            f'  )'
            f')'
        )
        leaf_out_relabeled = (
            f'sum by (source, destination) ('
            f'  label_replace('
            f'    label_replace('
            f'      label_replace('
            f'        label_replace('
            f'          rate(ifHCOutOctets{{{SNMP_LEAF}, ifDescr=~"ethernet-1/(49|50)"}}[$__rate_interval]) * 8,'
            f'          {_src}'
            f'        ),'
            f'        "destination", "$1", "source", "(leaf.*)"'
            f'      ),'
            f'      "source", "spine1", "ifDescr", "ethernet-1/49"'
            f'    ),'
            f'    "source", "spine2", "ifDescr", "ethernet-1/50"'
            f'  )'
            f')'
        )
        return f'({spine_out}) + on(source, destination) ({leaf_out_relabeled})'

    def _leaf_to_client():
        """Leaf downlink (ethernet-1/1) → client: source=leaf, destination=client."""
        return (
            f'sum by (source, destination) ('
            f'  label_replace('
            f'    label_replace('
            f'      label_replace('
            f'        label_replace('
            f'          rate(ifHCOutOctets{{{SNMP_LEAF}, ifDescr="ethernet-1/1"}}[$__rate_interval]) * 8,'
            f'          {_src}'
            f'        ),'
            f'        "destination", "client1", "source", "leaf1"'
            f'      ),'
            f'      "destination", "client2", "source", "leaf2"'
            f'    ),'
            f'    "destination", "client3", "source", "leaf3"'
            f'  )'
            f')'
        )

    # Full-fabric: union of spine→leaf and leaf→client flows.
    # Two separate queries in one panel; Grafana merges them into a single table
    # which the Sankey plugin renders as a multi-hop flow.
    rename_src_dst = {"source": "Source", "destination": "Destination", "Value": "bps"}

    panels = [
        row("Spine ↔ Leaf Traffic", y=0),

        sankey_panel(
            "Spine → Leaf",
            targets=[_sankey_target(_spine_to_leaf())],
            x=0, y=1, w=12, h=14,
            transformations=_hide_time_xform(rename_src_dst),
        ),

        sankey_panel(
            "Leaf → Spine",
            targets=[_sankey_target(_leaf_to_spine())],
            x=12, y=1, w=12, h=14,
            transformations=_hide_time_xform(rename_src_dst),
        ),

        sankey_panel(
            "Spine ↔ Leaf (Aggregate)",
            targets=[_sankey_target(_aggregate_spine_leaf())],
            x=0, y=15, w=24, h=14,
            transformations=_hide_time_xform(),
        ),

    ]

    variables = [ds_var("datasource", "Prometheus")]

    return dashboard(
        uid="net-o11y-traffic-sankey",
        title="Network O11y — Traffic Sankey",
        panels=with_header(panels, "traffic-sankey"), variables=variables,
        description=(
            "Sankey flow diagrams of SR Linux Clos fabric traffic. "
            "Uses label_replace() to map gNMI interface names to connected device names."
        ),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Dashboard 7 — Landing Page
# ═══════════════════════════════════════════════════════════════════════════════

_LANDING_LINKS_HTML = """\
<div style="padding:14px 20px; font-size:14px; line-height:1.8; display:flex; gap:48px; flex-wrap:wrap;">

  <div>
    <div style="font-weight:700; font-size:13px; text-transform:uppercase; letter-spacing:.06em; margin-bottom:6px;">Repository</div>
    <a href="https://github.com/grafana/network-o11y-demo" target="_blank"
       style="color:#6e9fff;">grafana/network-o11y-demo</a><br>
    <a href="https://github.com/grafana/network-o11y-demo/blob/main/README.md" target="_blank"
       style="color:#6e9fff;">README — setup &amp; architecture</a>
  </div>

  <div>
    <div style="font-weight:700; font-size:13px; text-transform:uppercase; letter-spacing:.06em; margin-bottom:6px;">Blog Series — Network Observability Without the Lock-in</div>
    <a href="https://github.com/grafana/network-o11y-demo/blob/main/blog/10_drafts/blog-post-01-the-case.md" target="_blank" style="color:#6e9fff;">Post 1: The Case Against SolarWinds</a><br>
    <a href="https://github.com/grafana/network-o11y-demo/blob/main/blog/10_drafts/blog-post-02-the-stack.md" target="_blank" style="color:#6e9fff;">Post 2: The Open Network Observability Stack</a><br>
    <a href="https://github.com/grafana/network-o11y-demo/blob/main/blog/10_drafts/blog-post-03-the-lab.md" target="_blank" style="color:#6e9fff;">Post 3: Building the Lab</a><br>
    <a href="https://github.com/grafana/network-o11y-demo/blob/main/blog/10_drafts/blog-post-04-netbox.md" target="_blank" style="color:#6e9fff;">Post 4: NetBox as Your Source of Truth</a><br>
    <a href="https://github.com/grafana/network-o11y-demo/blob/main/blog/10_drafts/blog-post-05-grafana.md" target="_blank" style="color:#6e9fff;">Post 5: Observability with Grafana</a><br>
    <a href="https://github.com/grafana/network-o11y-demo/blob/main/blog/10_drafts/blog-post-06-ansible.md" target="_blank" style="color:#6e9fff;">Post 6: Config Management with Ansible</a><br>
    <a href="https://github.com/grafana/network-o11y-demo/blob/main/blog/10_drafts/blog-post-07-migration.md" target="_blank" style="color:#6e9fff;">Post 7: Migration Guide</a>
  </div>

  <div>
    <div style="font-weight:700; font-size:13px; text-transform:uppercase; letter-spacing:.06em; margin-bottom:6px;">Stack</div>
    Grafana Cloud &nbsp;·&nbsp; Prometheus &nbsp;·&nbsp; Loki<br>
    Grafana Alloy &nbsp;·&nbsp; gnmic &nbsp;·&nbsp; ktranslate<br>
    Nokia SR Linux &nbsp;·&nbsp; NetBox &nbsp;·&nbsp; Ansible<br>
    AWS EKS &nbsp;·&nbsp; Clabbernetes
  </div>

</div>
"""

_LANDING_DEMO_HTML = """\
<div style="padding:14px 20px; font-size:13.5px; line-height:1.75;">

  <p style="margin:0 0 10px 0; font-size:15px; font-weight:600;">
    The SolarWinds Alternative — Live Demo Script
  </p>

  <p style="margin:0 0 14px 0; color:#aaa;">
    This environment runs a Nokia SR Linux Clos fabric (2 spines, 3 leaves, 3 Linux clients)
    entirely monitored with open-source tooling — Grafana, Prometheus, Loki, Alloy, gnmic,
    and NetBox. No per-node licensing. No proprietary agents. No vendor lock-in.
  </p>

  <ol style="margin:0; padding-left:20px; display:flex; flex-direction:column; gap:8px;">
    <li>Set the time range to <strong>Last 15 minutes</strong> (top-right).</li>
    <li>
      Open <strong>NetBox</strong> — the inventory source of truth for this demo.<br>
      <span style="color:#aaa; font-size:12px;">
        If you haven't already, clone the repo and set up the SSH tunnel:
      </span>
      <pre style="margin:6px 0 0 0; padding:8px 12px; background:#1a1a2e; border-radius:4px; font-size:11.5px; line-height:1.7; overflow-x:auto;"># Prerequisites (one-time):
#   1. AWS CLI v2: https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html
#   2. SSM plugin: https://docs.aws.amazon.com/systems-manager/latest/userguide/
#                  session-manager-working-with-install-plugin.html
#   3. Configure your Grafana AWS credentials: aws configure

git clone https://github.com/grafana/network-o11y-demo
cd network-o11y-demo
bash scripts/access.sh   # auto-detects SSM — no SSH key needed</pre>
      <span style="color:#aaa; font-size:12px;">
        Then navigate to
        <a href="http://localhost:8080" target="_blank" style="color:#6e9fff;">http://localhost:8080</a>
        (login: <code>admin</code> / <code>admin</code>).
        Show the device list — every device has a role (<code>spine</code>, <code>leaf</code>, <code>client</code>),
        a site, and a platform. These labels flow automatically into every Prometheus metric via the
        netbox-sd adapter — no manual tagging in the collector.
      </span>
    </li>
    <li>
      Open <strong>BGP Status</strong> — confirm all 6 eBGP sessions are green.<br>
      <span style="color:#aaa; font-size:12px;">
        SolarWinds equivalent: NPM BGP MIB polling (5-min minimum granularity, no log correlation).
      </span>
    </li>
    <li>
      Open <strong>Interface Health</strong> — both spines are active, traffic is balanced.<br>
      <span style="color:#aaa; font-size:12px;">
        Filter by <code>device_role=spine</code> — that label came from NetBox automatically. SolarWinds
        requires manually maintained node groups to achieve the same filtering.
      </span>
    </li>
    <li>
      Click <strong style="color:#f87171;">Stop Spine 1</strong> on the right →<br>
      <span style="color:#aaa; font-size:12px;">
        This scales the spine1 Kubernetes deployment to 0 replicas, simulating a total node failure.
      </span>
    </li>
    <li>
      Return to <strong>BGP Status</strong> — sessions to spine1 will flip red within seconds.<br>
      Traffic reconverges to spine2 automatically (watch Interface Health).
    </li>
    <li>
      Open <strong>Device Details → spine2</strong> — check the syslog panel for NOTIFICATION messages.<br>
      <span style="color:#aaa; font-size:12px;">
        Metrics and logs in the same dashboard, same time window. SolarWinds needs a separate Log Analyzer product for this.
      </span>
    </li>
    <li>
      Click <strong style="color:#4ade80;">Start Spine 1</strong> on the right →<br>
      BGP reconverges. Typical recovery: &lt; 30 seconds.
    </li>
    <li>
      Point out the <strong>Network Topology</strong> dashboard — live link utilisation overlaid on
      the Clos diagram, animated. SolarWinds equivalent: Network Atlas (static maps, no live overlay).
    </li>
  </ol>

</div>
"""


def dash_landing_page():
    CTRL = "${controller_url}"

    panels = [
        # ── Row 1: Announcements and Information ──────────────────────────────
        {
            "id": None, "type": "row",
            "title": "Announcements and Information",
            "gridPos": {"h": 1, "w": 24, "x": 0, "y": 0},
            "collapsed": False, "panels": [],
        },
        {
            "id": None, "type": "text", "title": "",
            "gridPos": {"h": 8, "w": 24, "x": 0, "y": 1},
            "datasource": None,
            "fieldConfig": {"defaults": {}, "overrides": []},
            "options": {
                "code": {
                    "language": "plaintext",
                    "showLineNumbers": False,
                    "showMiniMap": False,
                },
                "content": _LANDING_LINKS_HTML,
                "mode": "html",
            },
            "pluginVersion": "10.0.0",
            "transparent": True,
        },

        # ── Row 2: Demo Block ─────────────────────────────────────────────────
        {
            "id": None, "type": "row",
            "title": "Demo Block",
            "gridPos": {"h": 1, "w": 24, "x": 0, "y": 9},
            "collapsed": False, "panels": [],
        },
        {
            "id": None, "type": "text", "title": "",
            "gridPos": {"h": 14, "w": 14, "x": 0, "y": 10},
            "datasource": None,
            "fieldConfig": {"defaults": {}, "overrides": []},
            "options": {
                "code": {
                    "language": "plaintext",
                    "showLineNumbers": False,
                    "showMiniMap": False,
                },
                "content": _LANDING_DEMO_HTML,
                "mode": "html",
            },
            "pluginVersion": "10.0.0",
            "transparent": True,
        },
        button_panel(
            title="",
            button_text="Stop Spine 1",
            url=f"{CTRL}/spine/spine1/stop",
            x=14, y=10, w=10, h=5,
            variant="destructive",
        ),
        button_panel(
            title="",
            button_text="Start Spine 1",
            url=f"{CTRL}/spine/spine1/start",
            x=14, y=15, w=10, h=5,
            variant="primary",
        ),
    ]

    return dashboard(
        uid="landing-page",
        title="00 Network O11y Landing Page",
        panels=panels,
        variables=[
            const_var(
                name="controller_url",
                label="Spine Controller URL",
                value="http://REPLACE_WITH_LB_HOSTNAME",
            ),
        ],
        description=(
            "Landing page for the Network O11y demo. "
            "Links, announcements, and a live demo script for the SolarWinds alternative story."
        ),
        refresh="",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Write JSON files
# ═══════════════════════════════════════════════════════════════════════════════

DASHBOARDS = [
    ("landing-page",       dash_landing_page),
    ("interface-health",   dash_interface_health),
    ("bgp-status",         dash_bgp_status),
    ("traffic-flows",      dash_traffic_flows),
    ("device-details",     dash_device_details),
    ("network-topology",   dash_network_topology),
    ("traffic-sankey",     dash_traffic_sankey),
]


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for name, fn in DASHBOARDS:
        dash = fn()
        path = os.path.join(OUT_DIR, f"{name}.json")
        with open(path, "w") as f:
            json.dump(dash, f, indent=2)
        print(f"  wrote {path}  (panels: {len(dash['panels'])})")
    print(f"\nGenerated {len(DASHBOARDS)} dashboards → {OUT_DIR}/")


if __name__ == "__main__":
    main()
