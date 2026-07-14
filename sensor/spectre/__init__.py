"""SPECTRE — Signal Processing & Electromagnetic Threat Reconnaissance Engine.

A self-hosted wireless intrusion-detection sensor: ingests JSON frame
observations from ESP32-C5 sniffer boards over UART, detects WiFi attacks,
serves a real-time API/WebSocket for the web console, and forwards threats
plus periodic summaries to Wazuh via RFC 5424 syslog.

Author: gurvinny
Project: SPECTRE
"""

__version__ = "0.1.0"
