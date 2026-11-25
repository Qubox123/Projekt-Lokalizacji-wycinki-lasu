# MODEL_DIR: katalog wyniku train.py z chainsaw_model_data.h i feature_config.h
set(MODEL_DIR "${CMAKE_CURRENT_LIST_DIR}/../../out_unified_v2" CACHE PATH "katalog modelu")

idf_component_register(SRCS "main.cpp" "features.cpp" "audio_in.cpp"
                       INCLUDE_DIRS "." "${MODEL_DIR}"
                       PRIV_REQUIRES driver esp_timer espressif__esp-tflite-micro)
