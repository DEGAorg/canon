AIKEN ?= aiken

.PHONY: check build
check:
	$(AIKEN) fmt --check lib/*.ak validators/*.ak
	$(AIKEN) check

build: check
	$(AIKEN) build
