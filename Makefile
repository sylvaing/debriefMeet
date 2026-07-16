PYTHON     := python3
VENV       := .venv
VENV_BUILD := .venv-build
PIP        := $(VENV)/bin/pip
PYTEST     := $(VENV)/bin/pytest
APP        := $(VENV)/bin/debrief-meet

.PHONY: setup test test-all build-helpers run clean help build-app dmg

help:
	@echo ""
	@echo "debriefMeet — commandes de build"
	@echo ""
	@echo "  make setup          Installation complète (venv + deps Python + helpers Swift)"
	@echo "  make test           Tests unitaires rapides (sans matériel, ~5 s)"
	@echo "  make test-all       Tous les tests (y compris intégration)"
	@echo "  make build-helpers  Recompiler les helpers Swift (si source modifiée)"
	@echo "  make run            Lancer debriefMeet"
	@echo "  make build-app      Packaging macOS : dist/debriefMeet.app (signature stable)"
	@echo "  make dmg            Packaging macOS : dist/debriefMeet-<version>.dmg (implique build-app)"
	@echo "  make clean          Supprimer le venv et les artefacts de build"
	@echo ""

# ── Installation ─────────────────────────────────────────────────────────────

setup: $(VENV)/bin/activate build-helpers
	@echo ""
	@echo "✓ Environnement prêt."
	@echo "  → Tester : make test"
	@echo "  → Lancer : make run"
	@echo ""

$(VENV)/bin/activate:
	@bash scripts/setup.sh --deps-only

# ── Tests ─────────────────────────────────────────────────────────────────────

test:
	$(PYTEST) -m "not integration"

test-all:
	$(PYTEST)

# ── Helpers Swift ─────────────────────────────────────────────────────────────

build-helpers:
	@bash helpers/macos/sck-audio/build.sh

# ── Lancement ─────────────────────────────────────────────────────────────────

run: $(VENV)/bin/activate
	$(APP)

# ── Packaging macOS (docs/16) ──────────────────────────────────────────────────
# Nécessite $(VENV_BUILD) (Python 3.13, cf. docs/16 §2) — pas $(VENV) (3.14, non
# supporté par PyInstaller).

build-app:
	@bash packaging/build_ffmpeg.sh
	@bash packaging/build_app.sh

dmg: build-app
	@bash packaging/build_dmg.sh

# ── Nettoyage ─────────────────────────────────────────────────────────────────

clean:
	rm -rf $(VENV) .pytest_cache .coverage htmlcov
	find . -path ./.venv -prune -o -name "__pycache__" -type d -print | xargs rm -rf
	find . -path ./.venv -prune -o -name "*.pyc" -print | xargs rm -f
	@echo "✓ Nettoyé."
