from __future__ import annotations

from pathlib import Path

from debrief_meet.platform.windows.presse_papiers import PressePapiersWindows


def test_copier_puis_lire_aller_retour(qapp):
    pp = PressePapiersWindows()
    pp.copier("texte de test")
    assert pp.lire() == "texte de test"


def test_copier_fichier_pose_une_url_de_fichier(qapp, tmp_path):
    from PySide6.QtGui import QGuiApplication

    fichier = tmp_path / "transcription.md"
    fichier.write_text("contenu", encoding="utf-8")
    PressePapiersWindows().copier_fichier(fichier)
    mime = QGuiApplication.clipboard().mimeData()
    assert mime.hasUrls()
    # `toLocalFile()` rend des slashes même sous Windows — comparer via Path, pas
    # en chaîne brute (`str(fichier)` porte des antislashes sur cet OS).
    assert Path(mime.urls()[0].toLocalFile()) == fichier
