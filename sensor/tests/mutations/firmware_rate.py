"""Firmware line rate: the literal the tools and the simulator are held to."""
TARGET = "../firmware/spectre-sniffer/main/app_main.c"
TESTS = "tests/test_flash_tool.py"

MUTATIONS = [
    ("rate-from-ignored-kconfig",
     "#define UART_BAUD 921600 ", "#define UART_BAUD CONFIG_ESP_CONSOLE_UART_BAUDRATE ",
     "test_firmware_rate_is_the_tool_default"),
    ("rate-drifts-from-tools",
     "#define UART_BAUD 921600 ", "#define UART_BAUD 460800 ",
     "test_firmware_rate_is_the_tool_default"),
]
SURVIVORS = {}
