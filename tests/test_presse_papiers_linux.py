from __future__ import annotations

from pathlib import Path

from debrief_meet.platform.linux.presse_papiers import PressePapiersLinux


def test_copier_puis_lire_aller_retour(qapp):
    pp = PressePapiersLinux()
    pp.copier("texte de test")
    assert pp.lire() == "texte de test"


def test_ne_logge_jamais_le_texte_copie(qapp, caplog):
    """Règle docs/31 §3.7.1 : aucun texte transcrit dans les logs — la dictée et la
    copie de transcription passent toutes les deux par ici."""
    import logging

    with caplog.at_level(logging.DEBUG, logger="debrief_meet"):
        PressePapiersLinux().copier("secret à ne jamais journaliser")

    # `getMessage()` applique les arguments : c'est le texte réellement écrit dans le
    # fichier de log, pas le gabarit `%s`.
    messages = [r.getMessage() for r in caplog.records]
    assert not any("secret" in m for m in messages)
    # La longueur, elle, doit bien être tracée (utile au diagnostic).
    assert any("copier(30 chars)" in m for m in messages)


def test_copier_fichier_pose_une_url_de_fichier(qapp, tmp_path):
    from PySide6.QtGui import QGuiApplication

    fichier = tmp_path / "transcription.md"
    fichier.write_text("contenu", encoding="utf-8")
    PressePapiersLinux().copier_fichier(fichier)
    mime = QGuiApplication.clipboard().mimeData()
    assert mime.hasUrls()
    # `toLocalFile()` rend des slashes même sous Windows — comparer via Path, pas
    # en chaîne brute (`str(fichier)` porte des antislashes sur cet OS).
    assert Path(mime.urls()[0].toLocalFile()) == fichier
