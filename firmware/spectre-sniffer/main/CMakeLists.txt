idf_component_register(
    SRCS "app_main.c" "core/dot11.c" "core/ie.c" "core/jsonw.c" "core/line.c"
         "core/cfg.c" "core/apcache.c"
    INCLUDE_DIRS "core"
    PRIV_REQUIRES esp_wifi esp_event nvs_flash esp_driver_uart esp_driver_tsens esp_ringbuf
                  esp_timer esp_app_format)
target_compile_options(${COMPONENT_LIB} PRIVATE -Wall -Wextra -Werror)
