# Makefile for card-game-pics
# Generate card PNGs from XCF templates + properties.json

.PHONY: help init generate generate-all init-properties format clean

# Colors
RED    := \033[0;31m
GREEN  := \033[0;32m
YELLOW := \033[1;33m
CYAN   := \033[0;36m
RESET  := \033[0m
BOLD   := \033[1m

CARD_LANG ?= pl

help: ## Show this help message
	@echo "$(BOLD)Card Game Pics$(RESET) — generate card PNGs from XCF templates"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(CYAN)%-20s$(RESET) %s\n", $$1, $$2}'
	@echo ""
	@echo "  $(CYAN)CARD_LANG=en make generate$(RESET) to override language (default: pl)"

init: ## Verify system dependencies
	@echo "$(BOLD)Checking system dependencies...$(RESET)"
	@echo ""
	@FAIL=0; \
	if [ "$$(uname -s)" != "Linux" ]; then \
		echo "  $(YELLOW)⚠ WARNING: This project is designed for Linux. Your OS: $$(uname -s)$(RESET)"; \
	fi; \
	echo -n "  uv             "; \
	if command -v uv >/dev/null 2>&1; then \
		echo "$(GREEN)OK$(RESET) ($$(uv --version 2>&1))"; \
	else \
		echo "$(RED)MISSING$(RESET) — curl -LsSf https://astral.sh/uv/install.sh | sh"; FAIL=1; \
	fi; \
	echo -n "  python3        "; \
	if command -v python3 >/dev/null 2>&1; then \
		echo "$(GREEN)OK$(RESET) ($$(python3 --version 2>&1))"; \
	else \
		echo "$(RED)MISSING$(RESET) — install python3"; FAIL=1; \
	fi; \
	echo -n "  gimp           "; \
	if command -v gimp >/dev/null 2>&1; then \
		echo "$(GREEN)OK$(RESET) ($$(gimp --version 2>&1))"; \
	else \
		echo "$(RED)MISSING$(RESET) — sudo apt install gimp"; FAIL=1; \
	fi; \
	echo -n "  EB Garamond    "; \
	if fc-list | grep -qi "EB Garamond"; then \
		echo "$(GREEN)OK$(RESET)"; \
	else \
		echo "$(YELLOW)MISSING$(RESET) — sudo apt install fonts-ebgaramond"; \
	fi; \
	echo ""; \
	if [ $$FAIL -eq 1 ]; then \
		echo "  $(RED)$(BOLD)✗ Missing required dependencies. Install them and re-run make init.$(RESET)"; \
		exit 1; \
	else \
		echo "  $(GREEN)$(BOLD)✓ All required dependencies present.$(RESET)"; \
	fi

generate: ## Generate card PNGs (use CARD_LANG=xx to override, default: pl)
	@uv run generate_cards.py generate --lang "$(CARD_LANG)"

generate-all: ## Generate card PNGs for all languages
	@uv run generate_cards.py generate --lang ""

init-properties: ## Generate default properties.json (use CARD_LANG=xx to add language section)
	@uv run generate_cards.py init-properties $(if $(filter-out pl,$(CARD_LANG)),--lang "$(CARD_LANG)",)

format: ## Format Python code with black
	@uv run black .

clean: ## Remove generated output
	@rm -rf output/
	@echo "$(GREEN)Cleaned output/$(RESET)"
