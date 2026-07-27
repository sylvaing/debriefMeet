from __future__ import annotations

import logging

import numpy as np
import pytest
from PySide6.QtCore import QObject, Signal

from debrief_meet.core.config import Config
from debrief_meet.core.modes import EtatVisuel, MachineEtats
from debrief_meet.core.reunion import OrchestrateurReunion
from debrief_meet.platform.interfaces import ResultatTranscription, Segment
from tests.fakes.adapters import MicroFake, MoteurFake, SystemeFake


class _FauxSurveillant(QObject):
    """Émet `change` à la demande pour simuler un changement de périphérique."""
    change = Signal()


def _config(tmp_path, intervalle=30, micro_index=None, transcription_live=True):
    cfg = Config(chemin=tmp_path / "config.json")
    cfg.set("dossier_reunions", str(tmp_path))
    cfg.set("intervalle_reunion", intervalle)
    cfg.set("micro_index", micro_index)
    cfg.set("transcription_live", transcription_live)
    return cfg


def _creer(machine, tmp_path, systeme=None, micro=None, moteur=None, intervalle=30,
           delai_termine_ms=100, surveillant=None, micro_index=None,
           processeur_aec=None, aec_actif=True, retention_audio=False,
           transcription_live=True):
    cfg = _config(tmp_path, intervalle=intervalle, micro_index=micro_index,
                  transcription_live=transcription_live)
    cfg.set("aec_actif", aec_actif)
    cfg.set("retention_audio", retention_audio)
    systeme = systeme or SystemeFake()
    micro = micro or MicroFake(echantillons=np.ones(1600, dtype=np.float32))
    moteur = moteur or MoteurFake()
    orch = OrchestrateurReunion(
        machine=machine,
        micro=micro,
        systeme=systeme,
        moteur=moteur,
        config=cfg,
        delai_termine_ms=delai_termine_ms,
        surveillant=surveillant,
        processeur_aec=processeur_aec,
    )
    return orch, micro, systeme, moteur


class _FakeAEC:
    """Faux ProcesseurAEC : enregistre les appels, renvoie un marqueur en sortie."""

    def __init__(self, sortie: np.ndarray) -> None:
        self.sortie = sortie
        self.appels_demarrer = 0
        self.appels_terminer = 0
        self.appels_recalibrer = 0
        self.appels_pousser: list[tuple[np.ndarray, np.ndarray]] = []

    def demarrer(self) -> None:
        self.appels_demarrer += 1

    def pousser(self, micro: np.ndarray, systeme: np.ndarray) -> np.ndarray:
        self.appels_pousser.append((micro.copy(), systeme.copy()))
        return self.sortie.copy()

    def recalibrer(self) -> None:
        self.appels_recalibrer += 1

    def terminer(self) -> None:
        self.appels_terminer += 1


def test_demarrer_reunion_passe_en_enregistrement(qapp, tmp_path):
    machine = MachineEtats()
    etats = []
    orch, *_ = _creer(machine, tmp_path)
    orch.etat_visuel_change.connect(etats.append)

    machine.toggle_reunion()

    assert EtatVisuel.ENREGISTREMENT in etats


def test_demarrer_cree_le_fichier(qapp, tmp_path):
    machine = MachineEtats()
    orch, *_ = _creer(machine, tmp_path)

    machine.toggle_reunion()

    fichiers_md = list(tmp_path.glob("*.md"))
    assert len(fichiers_md) == 1


def test_demarrer_emet_reunion_demarree_avec_le_chemin(qapp, tmp_path):
    machine = MachineEtats()
    orch, *_ = _creer(machine, tmp_path)
    recus = []
    orch.reunion_demarree.connect(recus.append)

    machine.toggle_reunion()

    fichiers_md = list(tmp_path.glob("*.md"))
    assert recus == fichiers_md


def test_arreter_reunion_emet_termine(qapp, qtbot, tmp_path):
    machine = MachineEtats()
    etats = []
    orch, *_ = _creer(machine, tmp_path, delai_termine_ms=100)
    orch.etat_visuel_change.connect(etats.append)

    machine.toggle_reunion()
    machine.toggle_reunion()

    qtbot.waitUntil(lambda: EtatVisuel.TERMINE in etats, timeout=5000)


def test_timer_declenche_transcription(qapp, qtbot, tmp_path):
    machine = MachineEtats()
    moteur = MoteurFake()
    orch, micro, systeme, _ = _creer(machine, tmp_path, moteur=moteur, intervalle=1)

    machine.toggle_reunion()

    qtbot.waitUntil(lambda: len(moteur.appels_transcrire) >= 1, timeout=3000)


def test_repli_micro_seul_systeme_non_disponible(qapp, tmp_path):
    machine = MachineEtats()
    systeme = SystemeFake(disponible=False)
    micro = MicroFake(echantillons=np.ones(1600, dtype=np.float32))
    orch, micro, systeme, _ = _creer(machine, tmp_path, systeme=systeme, micro=micro)

    machine.toggle_reunion()

    assert systeme.appels_demarrer == 0
    assert micro.appels_demarrer == 1
    fichiers = list(tmp_path.glob("*.md"))
    assert len(fichiers) == 1
    assert "⚠️" in fichiers[0].read_text(encoding="utf-8")


def test_systeme_indisponible_logue_un_avertissement(qapp, tmp_path, caplog):
    """Symétrique du micro indisponible — sans ce log, une capture système en échec
    (ex. helper SCK absent) passait totalement inaperçue dans les logs."""
    machine = MachineEtats()
    systeme = SystemeFake(disponible=False)
    orch, micro, systeme, _ = _creer(machine, tmp_path, systeme=systeme)

    with caplog.at_level(logging.WARNING, logger="debrief_meet.core.reunion"):
        machine.toggle_reunion()

    assert any("système" in r.message.lower() and "indisponible" in r.message.lower()
              for r in caplog.records)


def test_etat_reste_rouge_pendant_enregistrement(qapp, qtbot, tmp_path):
    machine = MachineEtats()
    etats = []
    orch, *_ = _creer(machine, tmp_path, intervalle=1, delai_termine_ms=100)
    orch.etat_visuel_change.connect(etats.append)

    machine.toggle_reunion()

    qtbot.wait(1500)

    assert EtatVisuel.ENREGISTREMENT in etats
    assert EtatVisuel.TERMINE not in etats


def test_micro_indisponible_reunion_continue_sans_micro(qapp, tmp_path):
    """Si le micro échoue au démarrage, la réunion continue (audio système seul)."""
    machine = MachineEtats()
    micro = MicroFake(lever_au_demarrage=RuntimeError("PortAudioError -9986"))
    systeme = SystemeFake(disponible=True)
    orch, micro, systeme, _ = _creer(machine, tmp_path, micro=micro, systeme=systeme)

    machine.toggle_reunion()

    # La réunion démarre malgré l'échec micro ; le système, lui, tourne.
    assert micro.appels_demarrer == 1
    assert not micro.en_cours
    assert systeme.appels_demarrer == 1
    fichiers = list(tmp_path.glob("*.md"))
    assert len(fichiers) == 1
    assert "Microphone non disponible" in fichiers[0].read_text(encoding="utf-8")


def test_echec_demarrage_systeme_annule_et_arrete_le_micro(qapp, tmp_path):
    """Si une étape après le micro échoue (ici la capture système), on ne laisse pas
    le micro tourner sans timer pour le drainer : rollback complet + retour à IDLE."""
    machine = MachineEtats()
    micro = MicroFake(echantillons=np.ones(1600, dtype=np.float32))
    systeme = SystemeFake(disponible=True, lever_au_demarrage=RuntimeError("WASAPI HRESULT 0x8..."))
    erreurs = []
    machine.erreur.connect(erreurs.append)
    orch, micro, systeme, _ = _creer(machine, tmp_path, micro=micro, systeme=systeme)

    machine.toggle_reunion()

    assert micro.appels_demarrer == 1
    assert micro.appels_arreter == 1
    assert not micro.en_cours
    assert systeme.appels_demarrer == 1
    assert not orch._actif
    assert machine.mode.name == "IDLE"
    assert len(erreurs) == 1
    assert "WASAPI" in erreurs[0]
    assert not orch._timer.isActive()


def test_arreter_sans_micro_ne_lit_pas_le_micro(qapp, qtbot, tmp_path):
    """Après un démarrage sans micro, l'arrêt ne sollicite pas micro.arreter()."""
    machine = MachineEtats()
    micro = MicroFake(lever_au_demarrage=RuntimeError("pas de micro"))
    orch, micro, systeme, _ = _creer(machine, tmp_path, micro=micro, delai_termine_ms=100)

    machine.toggle_reunion()
    machine.toggle_reunion()

    qtbot.waitUntil(lambda: not (orch._thread and orch._thread.isRunning()), timeout=5000)
    assert micro.appels_arreter == 0


def test_terminer_sans_transcription_ne_leve_pas(qapp, tmp_path):
    machine = MachineEtats()
    orch, *_ = _creer(machine, tmp_path)
    # Aucune réunion lancée : terminer() est un no-op sûr.
    orch.terminer()


def test_terminer_attend_le_thread_en_cours(qapp, qtbot, tmp_path):
    """terminer() stoppe le timer et attend le QThread de transcription en cours."""
    machine = MachineEtats()
    orch, micro, systeme, _ = _creer(machine, tmp_path, delai_termine_ms=100)

    machine.toggle_reunion()
    machine.toggle_reunion()  # lance la transcription finale (un QThread)

    orch.terminer()

    # Après terminer(), plus aucun thread ne tourne et le timer est arrêté.
    assert not (orch._thread and orch._thread.isRunning())
    assert not orch._timer.isActive()


# ── Câblage AEC (Phase A, étape 2) ───────────────────────────────────────────

def test_aec_nettoie_le_micro_avant_transcription(qapp, qtbot, tmp_path):
    """AEC active → le micro brut + système passent par pousser(), et c'est le micro
    NETTOYÉ (16 kHz) qui est transcrit."""
    machine = MachineEtats()
    marqueur = np.full(800, 0.5, dtype=np.float32)
    aec = _FakeAEC(sortie=marqueur)
    moteur = MoteurFake()
    micro = MicroFake(echantillons=np.ones(1600, dtype=np.float32))
    systeme = SystemeFake(echantillons=np.zeros(1600, dtype=np.float32))
    orch, *_ = _creer(machine, tmp_path, micro=micro, systeme=systeme, moteur=moteur,
                      processeur_aec=aec)

    machine.toggle_reunion()
    assert aec.appels_demarrer == 1          # session AEC démarrée
    machine.toggle_reunion()                 # _arreter → pousser (synchrone)

    assert len(aec.appels_pousser) == 1
    micro_brut, systeme_brut = aec.appels_pousser[0]
    assert np.array_equal(micro_brut, np.ones(1600, dtype=np.float32))   # micro brut en entrée
    assert np.array_equal(systeme_brut, np.zeros(1600, dtype=np.float32))
    # Le micro nettoyé (marqueur) est bien ce qui part en transcription.
    qtbot.waitUntil(
        lambda: any(np.array_equal(a, marqueur) for a, _ in moteur.appels_transcrire),
        timeout=5000,
    )


def test_aec_desactivee_en_config_non_utilisee(qapp, tmp_path):
    machine = MachineEtats()
    aec = _FakeAEC(sortie=np.full(800, 0.5, dtype=np.float32))
    orch, *_ = _creer(machine, tmp_path, processeur_aec=aec, aec_actif=False)

    machine.toggle_reunion()

    assert aec.appels_demarrer == 0
    assert aec.appels_pousser == []


def test_aec_ignoree_si_systeme_indisponible(qapp, tmp_path):
    """Sans capture système, pas de référence → AEC non démarrée (micro brut)."""
    machine = MachineEtats()
    aec = _FakeAEC(sortie=np.full(800, 0.5, dtype=np.float32))
    systeme = SystemeFake(disponible=False)
    orch, *_ = _creer(machine, tmp_path, systeme=systeme, processeur_aec=aec)

    machine.toggle_reunion()

    assert aec.appels_demarrer == 0


def test_retention_audio_cree_les_fichiers(qapp, qtbot, tmp_path):
    machine = MachineEtats()
    micro = MicroFake(echantillons=np.ones(1600, dtype=np.float32) * 0.2)
    systeme = SystemeFake(echantillons=np.ones(1600, dtype=np.float32) * 0.1)
    orch, *_ = _creer(machine, tmp_path, micro=micro, systeme=systeme, retention_audio=True)

    machine.toggle_reunion()
    machine.toggle_reunion()                       # _arreter : écrit la tranche finale + ferme

    md = list(tmp_path.glob("*.md"))[0]
    # format .opus (ffmpeg) ou .wav (repli) selon la machine → on globe les deux pistes
    moi = list(tmp_path.glob(md.stem + "_moi.*"))
    sysw = list(tmp_path.glob(md.stem + "_systeme.*"))
    assert moi and sysw
    assert moi[0].stat().st_size > 0 and sysw[0].stat().st_size > 0


def test_retention_audio_desactivee_pas_de_fichier(qapp, tmp_path):
    machine = MachineEtats()
    orch, *_ = _creer(machine, tmp_path, retention_audio=False)
    machine.toggle_reunion()
    machine.toggle_reunion()
    assert list(tmp_path.glob("*_moi.*")) == [] and list(tmp_path.glob("*_systeme.*")) == []


def test_aec_terminee_a_la_fermeture(qapp, tmp_path):
    machine = MachineEtats()
    aec = _FakeAEC(sortie=np.full(800, 0.5, dtype=np.float32))
    orch, *_ = _creer(machine, tmp_path, processeur_aec=aec)

    orch.terminer()

    assert aec.appels_terminer == 1


# ── Détection changement de périphérique en réunion (Phase 3.5) ──────────────

def test_changement_peripherique_en_reunion_redemarre_micro(qapp, tmp_path):
    machine = MachineEtats()
    surveillant = _FauxSurveillant()
    orch, micro, *_ = _creer(machine, tmp_path, surveillant=surveillant)

    machine.toggle_reunion()
    surveillant.change.emit()

    assert micro.appels_redemarrer == 1


def test_changement_rebascule_sur_micro_prefere(qapp, tmp_path):
    """Au changement, on retente toujours l'index préféré (config.micro_index)."""
    machine = MachineEtats()
    surveillant = _FauxSurveillant()
    orch, micro, *_ = _creer(machine, tmp_path, surveillant=surveillant, micro_index=5)

    machine.toggle_reunion()
    surveillant.change.emit()

    assert micro.index_redemarrage == [5]


def test_changement_peripherique_hors_reunion_ignore(qapp, tmp_path):
    machine = MachineEtats()
    surveillant = _FauxSurveillant()
    orch, micro, *_ = _creer(machine, tmp_path, surveillant=surveillant)

    # Aucune réunion en cours (mode IDLE).
    surveillant.change.emit()

    assert micro.appels_redemarrer == 0


def test_changement_sans_micro_actif_tente_une_recuperation(qapp, tmp_path):
    """docs/25 correctif 2 : réunion démarrée sans micro (échec au démarrage) → un
    changement de périphérique tente désormais une récupération via `demarrer()` (pas
    `redemarrer()`, puisqu'aucun flux n'est ouvert) — plus de désarmement définitif."""
    machine = MachineEtats()
    surveillant = _FauxSurveillant()
    micro = MicroFake(lever_au_demarrage=RuntimeError("pas de micro"))
    orch, micro, *_ = _creer(machine, tmp_path, micro=micro, surveillant=surveillant)

    machine.toggle_reunion()  # _avec_micro devient False
    appels_avant = micro.appels_demarrer
    surveillant.change.emit()

    assert micro.appels_redemarrer == 0
    assert micro.appels_demarrer == appels_avant + 1  # tentative de récupération
    assert orch._avec_micro is False  # échoue toujours (lever_au_demarrage persistant)


def test_reconnexion_echouee_bascule_sans_micro(qapp, tmp_path):
    """Si la reconnexion échoue totalement, on poursuit la réunion sans micro."""
    machine = MachineEtats()
    surveillant = _FauxSurveillant()
    micro = MicroFake(echantillons=np.ones(1600, dtype=np.float32))
    micro.lever_au_redemarrage = RuntimeError("plus aucun micro")
    orch, micro, *_ = _creer(machine, tmp_path, micro=micro, surveillant=surveillant)

    machine.toggle_reunion()
    surveillant.change.emit()

    assert micro.appels_redemarrer == 1
    assert orch._avec_micro is False


def test_deux_changements_successifs_redemarrent_deux_fois(qapp, tmp_path):
    """docs/25 : la comparaison via `resoudre_peripherique` (table PortAudio périmée,
    pouvait juger un vrai changement « inchangé ») a disparu — chaque signal `change`
    retente systématiquement, sans exception pour les événements en double."""
    machine = MachineEtats()
    surveillant = _FauxSurveillant()
    micro = MicroFake(echantillons=np.ones(1600, dtype=np.float32))
    orch, micro, *_ = _creer(machine, tmp_path, micro=micro, surveillant=surveillant)

    machine.toggle_reunion()
    surveillant.change.emit()
    surveillant.change.emit()

    assert micro.appels_redemarrer == 2


def test_changement_reel_recalibre_aec(qapp, tmp_path):
    """Un vrai changement de périphérique doit recaler l'AEC (nouveau chemin d'écho)."""
    machine = MachineEtats()
    surveillant = _FauxSurveillant()
    micro = MicroFake(echantillons=np.ones(1600, dtype=np.float32))
    aec = _FakeAEC(sortie=np.ones(1600, dtype=np.float32))
    orch, micro, *_ = _creer(machine, tmp_path, micro=micro, surveillant=surveillant,
                              processeur_aec=aec)

    machine.toggle_reunion()
    surveillant.change.emit()

    assert micro.appels_redemarrer == 1
    assert aec.appels_recalibrer == 1


# ── Robustesse micro hot-plug (docs/25) ──────────────────────────────────────

def test_signal_micro_perdu_emis_au_demarrage_sans_micro(qapp, tmp_path):
    machine = MachineEtats()
    micro = MicroFake(lever_au_demarrage=RuntimeError("pas de micro"))
    orch, micro, *_ = _creer(machine, tmp_path, micro=micro)
    messages = []
    orch.micro_perdu.connect(messages.append)

    machine.toggle_reunion()

    assert len(messages) == 1


def test_signal_micro_perdu_emis_a_la_perte_en_cours_de_reunion(qapp, tmp_path):
    machine = MachineEtats()
    surveillant = _FauxSurveillant()
    micro = MicroFake(echantillons=np.ones(1600, dtype=np.float32))
    micro.lever_au_redemarrage = RuntimeError("plus aucun micro")
    orch, micro, *_ = _creer(machine, tmp_path, micro=micro, surveillant=surveillant)
    messages = []
    orch.micro_perdu.connect(messages.append)

    machine.toggle_reunion()
    surveillant.change.emit()

    assert len(messages) == 1


def test_micro_retabli_recupere_le_micro_et_active_la_piste_moi(qapp, tmp_path):
    """Récupération tardive (docs/25 correctif 2) : la piste Moi n'existe pas au
    démarrage (base_moi=None puisque `_avec_micro` est False), mais s'active dès
    que le micro revient — les tranches suivantes streament la piste Moi."""
    machine = MachineEtats()
    surveillant = _FauxSurveillant()
    micro = MicroFake(echantillons=np.ones(1600, dtype=np.float32))
    micro.lever_au_demarrage = RuntimeError("pas de micro au démarrage")
    orch, micro, *_ = _creer(machine, tmp_path, micro=micro, surveillant=surveillant,
                              retention_audio=True)
    machine.toggle_reunion()
    assert orch._avec_micro is False
    assert orch._enregistreur is not None
    assert orch._enregistreur.chemin_moi is None    # pas de piste Moi au démarrage

    messages = []
    orch.micro_retabli.connect(messages.append)
    micro.lever_au_demarrage = None                 # le micro redevient disponible
    surveillant.change.emit()

    assert orch._avec_micro is True
    assert len(messages) == 1
    assert orch._enregistreur.chemin_moi is not None  # piste Moi activée à la volée

    machine.toggle_reunion()  # arrêt propre


def test_tranche_vide_au_tick_declenche_une_reconnexion(qapp, qtbot, tmp_path):
    """Watchdog « tranche muette » (docs/25 correctif 3) : un flux mort livre un
    buffer vide sans qu'aucun événement `change` ne le signale — le tick suivant
    doit détecter le silence total et tenter un redémarrage."""
    machine = MachineEtats()
    micro = MicroFake(echantillons=np.zeros(0, dtype=np.float32))
    orch, micro, *_ = _creer(machine, tmp_path, micro=micro, intervalle=1, delai_termine_ms=50)

    machine.toggle_reunion()
    qtbot.waitUntil(lambda: micro.appels_redemarrer >= 1, timeout=3000)
    machine.toggle_reunion()


def test_tranche_vide_au_tick_echec_emet_micro_perdu_une_seule_fois(qapp, qtbot, tmp_path):
    machine = MachineEtats()
    micro = MicroFake(echantillons=np.zeros(0, dtype=np.float32))
    micro.lever_au_redemarrage = RuntimeError("plus de micro")
    orch, micro, *_ = _creer(machine, tmp_path, micro=micro, intervalle=1, delai_termine_ms=50)
    messages = []
    orch.micro_perdu.connect(messages.append)

    machine.toggle_reunion()
    qtbot.waitUntil(lambda: orch._avec_micro is False, timeout=3000)
    qtbot.wait(1500)  # laisse d'autres ticks passer : pas de ré-émission tant que perdu

    assert len(messages) == 1
    machine.toggle_reunion()


def test_tranche_vide_a_larret_ne_declenche_pas_de_reconnexion(qapp, tmp_path):
    """Le watchdog ne doit jamais se déclencher depuis `_arreter()` : la dernière
    tranche peut être légitimement vide si l'utilisateur arrête juste après un tick."""
    machine = MachineEtats()
    micro = MicroFake(echantillons=np.zeros(0, dtype=np.float32))
    orch, micro, *_ = _creer(machine, tmp_path, micro=micro)

    machine.toggle_reunion()
    machine.toggle_reunion()  # _arreter() : capture une tranche finale vide

    assert micro.appels_redemarrer == 0


class _MoteurGate(MoteurFake):
    """Reproduit le gate anti-silence réel de MoteurMLX (RMS < 0.008 → texte vide).

    Sert à prouver que la réunion normalise le niveau du micro (atténué par l'AEC)
    AVANT le moteur, sinon une tranche de parole faible serait jetée comme silence."""

    _SEUIL_RMS = 0.008

    def _transcrire_pret(self, audio, langue):
        self.appels_transcrire.append((audio, langue))
        rms = float(np.sqrt(np.mean(audio.astype(np.float32) ** 2))) if len(audio) else 0.0
        if rms < self._SEUIL_RMS:
            return ResultatTranscription(texte="", langue_detectee=None)
        return self.resultat_fixe


def _micro_faible(rms_cible=0.006, n=44_100):
    """Sinus de parole-faible à un RMS sous le gate (≈ micro post-AEC réel)."""
    t = np.arange(n, dtype=np.float32) / 44_100.0
    sig = np.sin(2 * np.pi * 220.0 * t).astype(np.float32)
    return (sig * (rms_cible * np.sqrt(2.0))).astype(np.float32)


def test_micro_faible_post_aec_est_transcrit(qapp, qtbot, tmp_path):
    """Régression : un micro de parole faible (RMS < gate, cas AEC) doit être
    normalisé puis transcrit — pas jeté comme silence (sinon .md vide)."""
    machine = MachineEtats()
    moteur = _MoteurGate()
    systeme = SystemeFake(disponible=False)  # seul → micro uniquement
    micro = MicroFake(echantillons=_micro_faible())
    orch, micro, systeme, moteur = _creer(
        machine, tmp_path, systeme=systeme, micro=micro, moteur=moteur,
        delai_termine_ms=50)

    etats = []
    orch.etat_visuel_change.connect(etats.append)
    machine.toggle_reunion()   # démarre
    machine.toggle_reunion()   # arrête → tranche finale
    qtbot.waitUntil(lambda: EtatVisuel.TERMINE in etats, timeout=5000)

    # L'audio remis au moteur a bien été remonté au-dessus du gate.
    assert moteur.appels_transcrire
    audio_recu = moteur.appels_transcrire[-1][0]
    rms = float(np.sqrt(np.mean(audio_recu.astype(np.float32) ** 2)))
    assert rms >= _MoteurGate._SEUIL_RMS
    # Et la transcription atterrit dans le .md (au lieu d'un fichier vide).
    md = next(tmp_path.glob("*.md")).read_text(encoding="utf-8")
    assert "transcription de test" in md


def test_micro_silence_pur_reste_vide(qapp, qtbot, tmp_path):
    """Garde-fou : le silence pur n'est PAS amplifié → reste filtré (pas d'hallucination)."""
    machine = MachineEtats()
    moteur = _MoteurGate()
    systeme = SystemeFake(disponible=False)
    micro = MicroFake(echantillons=np.zeros(44_100, dtype=np.float32))
    orch, micro, systeme, moteur = _creer(
        machine, tmp_path, systeme=systeme, micro=micro, moteur=moteur,
        delai_termine_ms=50)

    etats = []
    orch.etat_visuel_change.connect(etats.append)
    machine.toggle_reunion()
    machine.toggle_reunion()
    qtbot.waitUntil(lambda: EtatVisuel.TERMINE in etats, timeout=5000)

    md = next(tmp_path.glob("*.md")).read_text(encoding="utf-8")
    assert "transcription de test" not in md


# ── Mode « enregistrement seul » (transcription différée — docs/10) ──────────

def test_audio_seul_ne_transcrit_pas(qapp, qtbot, tmp_path):
    from debrief_meet.core.fichiers import transcription_en_attente
    machine = MachineEtats()
    orch, micro, systeme, moteur = _creer(
        machine, tmp_path, transcription_live=False, delai_termine_ms=50)

    machine.toggle_reunion()
    machine.toggle_reunion()
    qtbot.wait(200)

    assert moteur.appels_transcrire == []          # aucune transcription live
    md = next(tmp_path.glob("*.md"))
    assert transcription_en_attente(md) is True     # placeholder en attente


def test_audio_seul_pas_de_phase_transcription(qapp, qtbot, tmp_path):
    machine = MachineEtats()
    orch, *_ = _creer(machine, tmp_path, transcription_live=False, delai_termine_ms=50)
    etats = []
    orch.etat_visuel_change.connect(etats.append)

    machine.toggle_reunion()
    machine.toggle_reunion()
    qtbot.wait(200)

    assert EtatVisuel.ENREGISTREMENT in etats
    assert EtatVisuel.TRANSCRIPTION not in etats     # arrêt direct, pas de transcription
    assert EtatVisuel.REPOS in etats


def test_audio_seul_force_la_retention(qapp, tmp_path):
    """Même avec retention_audio=False, le mode audio-seul enregistre l'audio."""
    machine = MachineEtats()
    orch, *_ = _creer(machine, tmp_path, transcription_live=False, retention_audio=False)

    machine.toggle_reunion()  # pendant la session, l'enregistreur doit exister
    assert orch._enregistreur is not None
    machine.toggle_reunion()


def test_transcription_live_par_defaut_transcrit(qapp, qtbot, tmp_path):
    """Garde-fou : le mode live (défaut) transcrit toujours."""
    machine = MachineEtats()
    micro = MicroFake(echantillons=np.ones(44_100, dtype=np.float32))
    orch, micro, systeme, moteur = _creer(
        machine, tmp_path, micro=micro, transcription_live=True, delai_termine_ms=50)

    machine.toggle_reunion()
    machine.toggle_reunion()
    qtbot.waitUntil(lambda: len(moteur.appels_transcrire) >= 1, timeout=5000)


# ── Régression crash à l'arrêt (EXC_BAD_ACCESS dans getWrapperForQObject) ───────

def test_worker_tranche_emet_offset_dans_le_signal(qapp):
    """L'offset voyage DANS le signal `terminee` → le slot n'a plus besoin de
    `sender()` (dont le wrapper d'un worker en cours de destruction plantait)."""
    from debrief_meet.core.reunion import _WorkerTranche
    recu = []
    w = _WorkerTranche(
        moteur=MoteurFake(), audio_micro=np.ones(1600, dtype=np.float32),
        audio_systeme=np.zeros(0, dtype=np.float32), sr_micro=16000, sr_systeme=48000,
        avec_systeme=False, offset_s=42.0)
    w.terminee.connect(lambda micro, systeme, offset: recu.append(offset))
    w.transcrire()
    assert recu == [42.0]


def test_arret_pendant_tranche_en_vol_ne_crash_pas(qapp, qtbot, tmp_path):
    """Stopper une réunion alors qu'une tranche est encore en transcription : la
    sérialisation évite d'écraser le worker en vol (crash historique à l'arrêt)."""
    import time

    class MoteurLent(MoteurFake):
        def transcrire(self, audio, langue=None):
            time.sleep(0.3)                      # garde le worker « en vol »
            return super().transcrire(audio, langue)

    machine = MachineEtats()
    etats = []
    micro = MicroFake(echantillons=np.ones(16_000, dtype=np.float32))
    orch, *_ = _creer(machine, tmp_path, micro=micro, moteur=MoteurLent(),
                      intervalle=1, delai_termine_ms=50)
    orch.etat_visuel_change.connect(etats.append)

    machine.toggle_reunion()
    # Laisse une tranche périodique démarrer (timer 1 s) puis stoppe en plein vol.
    qtbot.wait(1200)
    machine.toggle_reunion()                     # _arreter → sérialise puis tranche finale

    qtbot.waitUntil(lambda: EtatVisuel.TERMINE in etats, timeout=10_000)
    qtbot.waitUntil(lambda: not (orch._thread and orch._thread.isRunning()), timeout=10_000)


# ── Câblage arreter_thread() (docs/26) ────────────────────────────────────────

class _MoteurLent(MoteurFake):
    """Transcription volontairement lente — garde le QThread « en vol » pour les
    tests de câblage ci-dessous (pas de course avec l'assertion)."""

    def transcrire(self, audio, langue=None):
        import time
        time.sleep(0.4)
        return super().transcrire(audio, langue)


def _espionner(monkeypatch, module):
    """Remplace `module.arreter_thread` par un espion qui délègue au vrai code (le
    thread est réellement joint, pas de fuite entre tests) tout en enregistrant les
    arguments d'appel."""
    reel = module.arreter_thread
    appels = []

    def _espion(thread, timeout_ms, debloquer=None, timeout_deblocage_ms=5_000, garder=()):
        appels.append((thread, timeout_ms, debloquer, garder))
        return reel(thread, timeout_ms, debloquer=debloquer,
                    timeout_deblocage_ms=timeout_deblocage_ms, garder=garder)

    monkeypatch.setattr(module, "arreter_thread", _espion)
    return appels


def test_terminer_appelle_arreter_thread_avec_deblocage_moteur(qapp, monkeypatch, tmp_path):
    import debrief_meet.core.reunion as reunion_module

    machine = MachineEtats()
    moteur = _MoteurLent()
    micro = MicroFake(echantillons=np.ones(16_000, dtype=np.float32))
    orch, *_ = _creer(machine, tmp_path, micro=micro, moteur=moteur, delai_termine_ms=100)
    appels = _espionner(monkeypatch, reunion_module)

    machine.toggle_reunion()
    machine.toggle_reunion()  # tranche finale : QThread encore en cours (moteur lent)
    assert orch._thread is not None and orch._thread.isRunning()

    orch.terminer()

    assert len(appels) == 1
    _, timeout_ms, debloquer, garder = appels[0]
    assert timeout_ms == 10_000
    assert debloquer == moteur.terminer
    assert garder == (orch._worker,)


def test_lancer_worker_garde_serialisation_sans_deblocage(qapp, monkeypatch, tmp_path):
    import debrief_meet.core.reunion as reunion_module

    machine = MachineEtats()
    moteur = _MoteurLent()
    orch, *_ = _creer(machine, tmp_path, moteur=moteur, delai_termine_ms=100)
    appels = _espionner(monkeypatch, reunion_module)

    audio = np.ones(16_000, dtype=np.float32)
    vide = np.zeros(0, dtype=np.float32)
    orch._lancer_worker(audio, vide, 16_000, 0.0, finale=False)
    assert orch._thread is not None and orch._thread.isRunning()
    orch._lancer_worker(audio, vide, 16_000, 1.0, finale=False)  # thread précédent encore en vol

    assert len(appels) == 1
    _, timeout_ms, debloquer, _garder = appels[0]
    assert timeout_ms == 10_000
    assert debloquer is None                 # volontairement sans déblocage (docs/26 §4.2)


def test_terminer_joint_le_thread_meme_apres_isRunning_faux(qapp, qtbot, monkeypatch, tmp_path):
    """Régression gel/SIGSEGV à l'arrêt : `terminer()` doit attendre le thread de
    transcription MÊME quand `QThread.isRunning()` rend déjà False.

    Un QThread repasse à non-running dès que `run()` retourne, AVANT que
    `QThreadPrivate::finish()` ait vidé le `deleteLater()` du worker (destruction du
    wrapper → appel Shiboken/Python, côté thread worker). L'ancienne garde
    `and self._thread.isRunning()` faisait sauter l'attente dans cette fenêtre : le
    thread principal repartait (teardown pytest) pendant que le thread worker touchait
    encore Shiboken → SIGSEGV concurrent (ou gel). Ici on prouve que la garde a disparu :
    thread bel et bien terminé (isRunning() False) et pourtant `arreter_thread` appelé."""
    import debrief_meet.core.reunion as reunion_module

    machine = MachineEtats()
    orch, *_ = _creer(machine, tmp_path, delai_termine_ms=50)

    machine.toggle_reunion()
    machine.toggle_reunion()                 # tranche finale → un QThread
    qtbot.waitUntil(
        lambda: orch._thread is not None and not orch._thread.isRunning(), timeout=5000)

    appels = _espionner(monkeypatch, reunion_module)
    orch.terminer()

    # Avant le correctif : 0 appel (garde isRunning() court-circuitait). Après : 1.
    assert len(appels) == 1
    assert appels[0][0] is orch._thread
