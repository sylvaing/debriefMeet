from __future__ import annotations

import logging
import sys

import pytest


class TestCheminLog:
    def test_appauthor_false_evite_le_doublon_windows(self, monkeypatch):
        import platformdirs
        from debrief_meet.core.logs import chemin_log

        appels = []
        monkeypatch.setattr(
            platformdirs, "user_log_dir",
            lambda *a, **kw: appels.append((a, kw)) or "/tmp/logs",
        )
        chemin_log()
        assert appels[0][1].get("appauthor") is False


class TestLogsDesactives:
    def test_desactives_par_defaut(self, tmp_path, monkeypatch):
        import platformdirs
        monkeypatch.setattr(platformdirs, "user_log_dir", lambda *a, **kw: str(tmp_path))

        from debrief_meet.core.logs import configurer_logs
        configurer_logs(actifs=False)

        root = logging.getLogger("debrief_meet")
        assert root.level > logging.CRITICAL
        assert not any(isinstance(h, logging.handlers.RotatingFileHandler)
                       for h in root.handlers)

    def test_messages_non_ecrits_quand_desactives(self, tmp_path, monkeypatch):
        import platformdirs
        monkeypatch.setattr(platformdirs, "user_log_dir", lambda *a, **kw: str(tmp_path))

        from debrief_meet.core.logs import configurer_logs, chemin_log
        configurer_logs(actifs=False)

        logger = logging.getLogger("debrief_meet.test")
        logger.info("ce message ne doit pas créer de fichier")

        assert not chemin_log().exists()


class TestLogsActives:
    def test_actives_cree_fichier(self, tmp_path, monkeypatch):
        import platformdirs
        monkeypatch.setattr(platformdirs, "user_log_dir", lambda *a, **kw: str(tmp_path))

        from debrief_meet.core.logs import configurer_logs, chemin_log
        configurer_logs(actifs=True)

        logger = logging.getLogger("debrief_meet")
        logger.info("message de test")

        # Flush tous les handlers
        for h in logger.handlers:
            h.flush()

        assert chemin_log().exists()

    def test_niveau_info_par_defaut(self, tmp_path, monkeypatch):
        import platformdirs
        monkeypatch.setattr(platformdirs, "user_log_dir", lambda *a, **kw: str(tmp_path))

        from debrief_meet.core.logs import configurer_logs
        configurer_logs(actifs=True, debug=False)
        root = logging.getLogger("debrief_meet")
        assert root.level == logging.INFO

    def test_niveau_debug_si_demande(self, tmp_path, monkeypatch):
        import platformdirs
        monkeypatch.setattr(platformdirs, "user_log_dir", lambda *a, **kw: str(tmp_path))

        from debrief_meet.core.logs import configurer_logs
        configurer_logs(actifs=True, debug=True)
        root = logging.getLogger("debrief_meet")
        assert root.level == logging.DEBUG

    def test_rotation_configuree(self, tmp_path, monkeypatch):
        import logging.handlers
        import platformdirs
        monkeypatch.setattr(platformdirs, "user_log_dir", lambda *a, **kw: str(tmp_path))

        from debrief_meet.core.logs import configurer_logs
        configurer_logs(actifs=True)
        root = logging.getLogger("debrief_meet")
        handlers = [h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)]
        assert handlers
        assert handlers[0].maxBytes == 5_000_000
        assert handlers[0].backupCount == 5


class TestEnteteSession:
    def test_bloc_present_avec_version(self, tmp_path, monkeypatch):
        import platformdirs
        monkeypatch.setattr(platformdirs, "user_log_dir", lambda *a, **kw: str(tmp_path))

        from debrief_meet import VERSION_COMPLETE
        from debrief_meet.core.logs import chemin_log, configurer_logs, journaliser_entete_session
        configurer_logs(actifs=True)
        journaliser_entete_session({"os": "Test-OS-1.0", "cpu": "Test-CPU"})

        root = logging.getLogger("debrief_meet")
        for h in root.handlers:
            h.flush()
        contenu = chemin_log().read_text(encoding="utf-8")
        assert "===== SESSION debriefMeet" in contenu
        assert VERSION_COMPLETE in contenu
        assert "os: Test-OS-1.0" in contenu
        assert "cpu: Test-CPU" in contenu


class TestTracesCrash:
    def test_exception_non_rattrapee_logguee_en_critical_et_rappelle_le_hook_precedent(
        self, tmp_path, monkeypatch
    ):
        import threading
        import platformdirs
        monkeypatch.setattr(platformdirs, "user_log_dir", lambda *a, **kw: str(tmp_path))

        from debrief_meet.core.logs import chemin_log, configurer_logs, installer_traces_crash
        configurer_logs(actifs=True, debug=True)

        hook_original = sys.excepthook
        thread_hook_original = threading.excepthook
        appels_precedent = []
        sys.excepthook = lambda *a: appels_precedent.append(a)
        try:
            installer_traces_crash()
            try:
                raise RuntimeError("boom-test-crash-hook")
            except RuntimeError:
                exc_info = sys.exc_info()
            sys.excepthook(*exc_info)

            root = logging.getLogger("debrief_meet")
            for h in root.handlers:
                h.flush()
            contenu = chemin_log().read_text(encoding="utf-8")
            assert "CRITICAL" in contenu
            assert "boom-test-crash-hook" in contenu
            assert len(appels_precedent) == 1
        finally:
            sys.excepthook = hook_original
            threading.excepthook = thread_hook_original

    def test_reconfiguration_propre(self, tmp_path, monkeypatch):
        import platformdirs
        monkeypatch.setattr(platformdirs, "user_log_dir", lambda *a, **kw: str(tmp_path))

        from debrief_meet.core.logs import configurer_logs
        configurer_logs(actifs=True)
        configurer_logs(actifs=False)
        root = logging.getLogger("debrief_meet")
        assert not any(isinstance(h, logging.handlers.RotatingFileHandler)
                       for h in root.handlers)


# Import tardif pour éviter les effets de bord au niveau module
import logging.handlers
