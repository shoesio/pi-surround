CC ?= cc
CFLAGS ?= -O3 -Wall -Wextra -Werror -fPIC
OUT ?= ../build/native

all: $(OUT)/libwiredmix.so $(OUT)/liblate_gain.so

$(OUT):
	mkdir -p $(OUT)

$(OUT)/libwiredmix.so: wired_dsp.c | $(OUT)
	$(CC) $(CFLAGS) -shared -o $@ $< -lm

$(OUT)/liblate_gain.so: late_gain.c | $(OUT)
	$(CC) $(CFLAGS) -shared -o $@ $< -lm

.PHONY: all
