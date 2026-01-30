# Root Makefile (wrapper)
DEVOS_DIR := devos

.PHONY: help
help:
	@$(MAKE) -C $(DEVOS_DIR) help

%:
	@$(MAKE) -C $(DEVOS_DIR) $@
