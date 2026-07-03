from __future__ import annotations

import logging

import pytest


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
        assert handlers[0].maxBytes == 1_000_000
        assert handlers[0].backupCount == 3

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
