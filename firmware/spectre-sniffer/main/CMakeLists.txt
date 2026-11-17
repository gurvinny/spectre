idf_component_register(
    SRCS "app_main.c" "core/dot11.c" "core/ie.c" "core/jsonw.c" "core/line.c"
         "core/cfg.c" "core/apcache.c" "core/ringacct.c"
    INCLUDE_DIRS "core"
    PRIV_REQUIRES esp_wifi esp_event nvs_flash esp_driver_uart esp_driver_usb_serial_jtag esp_driver_tsens esp_ringbuf
                  esp_timer esp_app_format)
target_compile_options(${COMPONENT_LIB} PRIVATE -Wall -Wextra -Werror)
# The link choice reads the USB-Serial-JTAG connection monitor, which IDF links
# only while the USB console is on; link it regardless so a console change
# cannot leave the board silently on UART.
target_link_libraries(${COMPONENT_LIB} INTERFACE "-u usb_serial_jtag_connection_monitor_include")
