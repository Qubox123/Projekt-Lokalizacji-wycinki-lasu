"""Mały DS-CNN (depthwise-separable CNN) na log-mel spektrogram 49x40.

Ok. 10 tys. parametrów -> ok. 20 KB po kwantyzacji int8. Używa tylko operacji
wspieranych przez TFLite Micro i przyspieszanych przez ESP-NN
(CONV_2D, DEPTHWISE_CONV_2D, MEAN, FULLY_CONNECTED, LOGISTIC).
"""

import keras
from keras import layers

import config as C


def _ds_block(x, filters, stride):
    x = layers.DepthwiseConv2D(3, strides=stride, padding="same", use_bias=False)(x)
    x = layers.BatchNormalization()(x)
    x = layers.ReLU()(x)
    x = layers.Conv2D(filters, 1, use_bias=False)(x)
    x = layers.BatchNormalization()(x)
    return layers.ReLU()(x)


def build_model(mel_mean, mel_var, width=16):
    inp = keras.Input(shape=(C.N_FRAMES, C.N_MELS, 1), name="log_mel")
    # Normalizacja per pasmo mel wbudowana w model - na ESP32 podajemy surowy log-mel
    x = layers.Normalization(axis=2, mean=mel_mean, variance=mel_var)(inp)
    x = layers.Conv2D(width, 3, strides=2, padding="same", use_bias=False)(x)   # 25x20
    x = layers.BatchNormalization()(x)
    x = layers.ReLU()(x)
    x = _ds_block(x, 2 * width, 1)
    x = _ds_block(x, 2 * width, 2)   # 13x10
    x = _ds_block(x, 4 * width, 2)   # 7x5
    x = _ds_block(x, 4 * width, 1)
    x = layers.GlobalAveragePooling2D()(x)
    x = layers.Dropout(0.2)(x)
    out = layers.Dense(1, activation="sigmoid", name="p_chainsaw")(x)
    return keras.Model(inp, out, name="chainsaw_dscnn")
