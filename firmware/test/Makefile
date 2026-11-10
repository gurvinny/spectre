# Host build of the firmware's portable core and its tests.
#   make            build and run the suite (ASan + UBSan)
#   make samples    also write every line kind to out/samples.txt
CC ?= cc
CORE := ../spectre-sniffer/main/core
SRC := $(wildcard $(CORE)/*.c) $(wildcard test_*.c) main.c
CFLAGS += -std=c11 -O1 -g -Wall -Wextra -Werror -Wshadow -Wconversion -Wno-sign-conversion \
          -fsanitize=address,undefined -fno-sanitize-recover=all -I$(CORE)

# ASan in the GCC 12 toolchain can spin forever on "DEADLYSIGNAL" when the
# kernel uses high mmap randomization (seen 11/30 runs on a 7.x kernel), so
# the suite runs with ASLR off for its own process.
RUN := setarch $(shell uname -m) -R ./out/run_tests

.PHONY: test samples clean
test: out/run_tests
	$(RUN)

out/run_tests: $(SRC) $(wildcard $(CORE)/*.h) $(wildcard *.h)
	@mkdir -p out
	$(CC) $(CFLAGS) $(SRC) -o $@

samples: out/run_tests
	SAMPLES_OUT=out/samples.txt $(RUN)
	python3 check_samples.py out/samples.txt

clean:
	rm -rf out
