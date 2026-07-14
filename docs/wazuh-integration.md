# Wazuh Integration

SPECTRE forwards **threats and periodic summaries** (never raw frames) to Wazuh as RFC 5424 syslog.

## Wire format

```
<186>1 2026-07-09T02:17:02.055Z spectre spectre - THREAT [32473@spectre band="5GHz" rule="evil_twin" bssid="00:00:5E:00:53:06" ssid="ExampleNet" severity="critical"] {"kind":"threat","ts":...,"rule":"evil_twin","severity":"critical","rank":1,"title":"Evil twin: 'ExampleNet' from unexpected BSSID 00:00:5E:00:53:06","band":"5GHz","bssid":"...","ssid":"ExampleNet","src":null,"detail":{...}}
```

- **PRI** = `local7 (23) × 8 + syslog severity`. Severity is mapped from the threat (see
  [detection-rules.md](detection-rules.md)); e.g. `<186>` = crit, `<190>` = summary/info.
- **app-name** = `spectre` (configurable), **MSGID** = `THREAT` or `SUMMARY`.
- **STRUCTURED-DATA** carries `band` / `rule` / `bssid` / `ssid` / `severity` for quick filtering.
- **MSG** is a compact JSON object Wazuh can decode natively (`kind`, `rule`, `severity`, `title`,
  `band`, `bssid`, `ssid`, `detail`).

## Receiving it

On the Wazuh manager, accept remote syslog from the sensor (`/var/ossec/etc/ossec.conf`):

```xml
<remote>
  <connection>syslog</connection>
  <port>514</port>
  <protocol>udp</protocol>
  <allowed-ips>10.0.0.10</allowed-ips>
</remote>
```

Point SPECTRE at the manager in **Settings** (or `.env`): `WAZUH_HOST=10.0.0.20`,
`WAZUH_PORT=514`, `WAZUH_PROTO=udp` (use `tcp` for guaranteed delivery across network segments).

## Decoder — `/var/ossec/etc/decoders/spectre_decoder.xml`

```xml
<decoder name="spectre">
  <program_name>spectre</program_name>
</decoder>

<!-- Pull the fields we care about straight out of the JSON body. -->
<decoder name="spectre-fields">
  <parent>spectre</parent>
  <regex offset="after_parent">"rule":"(\w+)".+"severity":"(\w+)".+"title":"([^"]+)"</regex>
  <order>spectre.rule,spectre.severity,spectre.title</order>
</decoder>

<decoder name="spectre-band">
  <parent>spectre</parent>
  <regex>band="([^"]+)"</regex>
  <order>spectre.band</order>
</decoder>
```

## Rules — `/var/ossec/etc/rules/spectre_rules.xml`

```xml
<group name="spectre,wireless,">
  <rule id="100600" level="3">
    <decoded_as>spectre</decoded_as>
    <description>SPECTRE: wireless sensor event</description>
  </rule>

  <rule id="100601" level="12">
    <if_sid>100600</if_sid>
    <field name="spectre.severity">critical</field>
    <description>SPECTRE: $(spectre.title)</description>
    <mitre><id>T1557</id></mitre> <!-- Adversary-in-the-Middle (evil twin) -->
  </rule>

  <rule id="100602" level="10">
    <if_sid>100600</if_sid>
    <field name="spectre.severity">high</field>
    <description>SPECTRE: $(spectre.title)</description>
    <mitre><id>T1499</id></mitre> <!-- Endpoint DoS (deauth flood) -->
  </rule>

  <rule id="100603" level="7">
    <if_sid>100600</if_sid>
    <field name="spectre.severity">medium</field>
    <description>SPECTRE: $(spectre.title)</description>
  </rule>

  <rule id="100604" level="4">
    <if_sid>100600</if_sid>
    <field name="spectre.severity">low</field>
    <description>SPECTRE: $(spectre.title)</description>
  </rule>
</group>
```

Restart the manager (`systemctl restart wazuh-manager`) and test with
`/var/ossec/bin/wazuh-logtest`, pasting a captured line.

> **Version note:** RFC 5424 predecoding varies across Wazuh versions. The regex decoders above key
> off the JSON body (the most stable part) rather than the syslog header, so they work regardless of
> how the manager predecodes the 5424 frame. On Wazuh ≥ 4.x you can alternatively use the
> `JSON_Decoder` plugin if you strip the structured-data element first.

_Author: gurvinny · Project: SPECTRE_
