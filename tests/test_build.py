"""
tests/test_build.py — vérification de l'infrastructure de build.

Ces tests s'assurent que les artefacts nécessaires au build et au lancement
existent, sont exécutables et ont le bon contenu.

Pas de test unitaire ici : on vérifie que ce qu'un développeur clone
peut effectivement compiler et lancer sans aide extérieure.

Marqueurs :
    (aucun)         — vérifications statiques (présence, exécutabilité, contenu)
    integration     — exécute le compilateur ou lance le binaire
"""
from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
IS_MACOS = sys.platform == "darwin"


# ── Scripts & Makefile ────────────────────────────────────────────────────────

class TestScripts:
    def test_makefile_existe(self):
        assert (ROOT / "Makefile").exists()

    def test_makefile_cibles_requises(self):
        contenu = (ROOT / "Makefile").read_text()
        for cible in ("setup", "test", "test-all", "build-helpers", "run", "clean", "help"):
            assert f"{cible}:" in contenu, f"Cible manquante dans Makefile : {cible}"

    def test_setup_sh_existe(self):
        assert (ROOT / "scripts" / "setup.sh").exists()

    def test_setup_sh_executable(self):
        assert os.access(ROOT / "scripts" / "setup.sh", os.X_OK), (
            "scripts/setup.sh n'est pas exécutable — lancer : chmod +x scripts/setup.sh"
        )

    def test_readme_existe(self):
        assert (ROOT / "README.md").exists()

    def test_readme_contient_sections_essentielles(self):
        # Insensible à la casse : la refonte du README (2026-10-23) a rangé les
        # permissions TCC sous « macOS — permissions », en minuscule dans le titre.
        contenu = (ROOT / "README.md").read_text().lower()
        for section in ("Prérequis", "Installation", "make", "Permissions"):
            assert section.lower() in contenu, f"Section manquante dans README.md : {section}"


# ── pyproject.toml ────────────────────────────────────────────────────────────

class TestPyproject:
    def test_pyproject_existe(self):
        assert (ROOT / "pyproject.toml").exists()

    def test_extras_declares(self):
        contenu = (ROOT / "pyproject.toml").read_text()
        for extra in ("macos", "dev"):
            assert extra in contenu, f"Extra manquant dans pyproject.toml : {extra}"

    def test_tzdata_declare_pour_windows(self):
        """`zoneinfo` est inerte sur Windows sans `tzdata` (aucune base de fuseaux
        système) : `ZoneInfo(...)` y lève, et comme `core/bluemind/sync.py` et
        `recurrence.py` l'enveloppent dans un try/except, la régression est
        SILENCIEUSE — retour à l'offset figé, soit le bug DST de docs/40 §5.2.
        Diagnostiqué le 2026-07-30 sur la gate VM (erreur de collecte)."""
        contenu = (ROOT / "pyproject.toml").read_text()
        assert 'tzdata; sys_platform == \'win32\'' in contenu, \
            "tzdata doit rester déclaré pour Windows (docs/44 §7)"

    def test_point_entree_declare(self):
        contenu = (ROOT / "pyproject.toml").read_text()
        assert "debrief-meet" in contenu

    def test_pytest_configure(self):
        contenu = (ROOT / "pyproject.toml").read_text()
        assert "[tool.pytest.ini_options]" in contenu
        assert "integration" in contenu


# ── Artefacts Phase 1 ────────────────────────────────────────────────────────

class TestPhase1:
    CORE = ROOT / "src" / "debrief_meet" / "core"
    PLATFORM = ROOT / "src" / "debrief_meet" / "platform"

    def test_core_audio_existe(self):
        assert (self.CORE / "audio.py").exists()

    def test_core_modeles_existe(self):
        assert (self.CORE / "modeles.py").exists()

    def test_core_dictee_existe(self):
        assert (self.CORE / "dictee.py").exists()

    def test_macos_moteur_mlx_existe(self):
        assert (self.PLATFORM / "macos" / "moteur_mlx.py").exists()

    def test_macos_presse_papiers_existe(self):
        assert (self.PLATFORM / "macos" / "presse_papiers.py").exists()

    def test_commun_micro_sounddevice_existe(self):
        assert (self.PLATFORM / "commun" / "micro_sounddevice.py").exists()

    def test_table_mlx_complete(self):
        contenu = (self.CORE / "modeles.py").read_text()
        for nom in ("tiny", "base", "small", "medium", "large-v2", "large-v3"):
            assert nom in contenu, f"Modèle manquant dans TABLE_MLX : {nom}"

    def test_orchestrateur_cable_dans_main(self):
        main = (ROOT / "src" / "debrief_meet" / "__main__.py").read_text()
        assert "OrchestrateurDictee" in main

    def test_factory_macos_utilise_mlx(self):
        factory = (self.PLATFORM / "factory.py").read_text()
        assert "MoteurMLX" in factory

    def test_mlx_worker_existe(self):
        assert (self.PLATFORM / "macos" / "_mlx_worker.py").exists()

    def test_mlx_worker_protocole(self):
        contenu = (self.PLATFORM / "macos" / "_mlx_worker.py").read_text()
        assert "READY" in contenu
        assert "pickle" in contenu
        assert "verbose=None" in contenu

    def test_interfaces_taux_echantillonnage(self):
        interfaces = (self.PLATFORM / "interfaces.py").read_text()
        assert "taux_echantillonnage" in interfaces


# ── Artefacts Phase 2 ────────────────────────────────────────────────────────

class TestPhase2:
    CORE = ROOT / "src" / "debrief_meet" / "core"
    PLATFORM = ROOT / "src" / "debrief_meet" / "platform"

    def test_core_fichiers_existe(self):
        assert (self.CORE / "fichiers.py").exists()

    def test_core_reunion_existe(self):
        assert (self.CORE / "reunion.py").exists()

    def test_macos_capture_systeme_existe(self):
        assert (self.PLATFORM / "macos" / "capture_systeme.py").exists()

    def test_factory_macos_utilise_sck(self):
        factory = (self.PLATFORM / "factory.py").read_text()
        assert "CaptureAudioSCK" in factory

    def test_interfaces_systeme_taux_echantillonnage(self):
        interfaces = (self.PLATFORM / "interfaces.py").read_text()
        # CaptureAudioSysteme doit aussi exposer taux_echantillonnage
        contenu = interfaces
        idx = contenu.find("class CaptureAudioSysteme")
        assert idx != -1
        assert "taux_echantillonnage" in contenu[idx:]

    def test_format_reunion_dans_fichiers(self):
        contenu = (self.CORE / "fichiers.py").read_text()
        assert "Réunion —" in contenu
        assert "Moi" in contenu
        assert "Participants" in contenu

    def test_orchestrateur_reunion_dans_main(self):
        main = (ROOT / "src" / "debrief_meet" / "__main__.py").read_text()
        assert "OrchestrateurReunion" in main


# ── Helper Swift (macOS uniquement) ──────────────────────────────────────────

@pytest.mark.skipif(not IS_MACOS, reason="helper Swift macOS uniquement")
class TestHelperSwift:
    SWIFT_DIR  = ROOT / "helpers" / "macos" / "sck-audio"
    BINAIRE    = SWIFT_DIR / "SCKAudioCapture"
    SOURCE     = SWIFT_DIR / "SCKAudioCapture.swift"
    BUILD_SH   = SWIFT_DIR / "build.sh"
    ENTITLEMENTS = SWIFT_DIR / "entitlements.plist"

    def test_source_swift_existe(self):
        assert self.SOURCE.exists()

    def test_build_sh_existe(self):
        assert self.BUILD_SH.exists()

    def test_build_sh_executable(self):
        assert os.access(self.BUILD_SH, os.X_OK), (
            "build.sh n'est pas exécutable — lancer : chmod +x helpers/macos/sck-audio/build.sh"
        )

    def test_entitlements_existe(self):
        assert self.ENTITLEMENTS.exists()

    def test_binaire_existe(self):
        """Le binaire compilé doit être présent.
        S'il manque, lancer : make build-helpers"""
        assert self.BINAIRE.exists(), (
            "SCKAudioCapture non trouvé. Compiler d'abord : make build-helpers"
        )

    def test_binaire_executable(self):
        if not self.BINAIRE.exists():
            pytest.skip("SCKAudioCapture non compilé")
        assert os.access(self.BINAIRE, os.X_OK)

    def test_binaire_est_mach_o(self):
        """Vérifie que le binaire est bien un exécutable Mach-O (pas un fichier tronqué)."""
        if not self.BINAIRE.exists():
            pytest.skip("SCKAudioCapture non compilé")
        header = self.BINAIRE.read_bytes()[:4]
        # Mach-O arm64 : 0xCFFAEDFE (little-endian)
        assert header == b"\xcf\xfa\xed\xfe", (
            f"Le binaire ne semble pas être un exécutable Mach-O valide (header={header.hex()})"
        )

    def test_source_contient_protocol_stdout(self):
        """Le helper doit écrire FORMAT:<sr>:<ch> sur stderr — vérifié dans la source."""
        source = self.SOURCE.read_text()
        assert 'fputs("FORMAT:' in source, (
            "Le helper doit écrire 'FORMAT:<sr>:<ch>' sur stderr pour que test_tap.py "
            "détecte automatiquement le sample rate."
        )

    @pytest.mark.integration
    def test_compilation_depuis_zero(self, tmp_path):
        """Recompile le helper et vérifie le code de retour."""
        out = tmp_path / "SCKAudioCapture_test"
        result = subprocess.run(
            [
                "swiftc", "-O",
                "-framework", "ScreenCaptureKit",
                "-framework", "AVFoundation",
                "-framework", "CoreMedia",
                "-framework", "Foundation",
                str(self.SOURCE),
                "-o", str(out),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, (
            f"Compilation échouée :\n{result.stderr}"
        )
        assert out.exists()

    @pytest.mark.integration
    def test_binaire_demarre_proprement(self):
        """Lance le binaire 2 s et vérifie qu'il ne crashe pas.

        Sans permission Screen Recording, SCK échouera avec code 2 (erreur propre).
        Avec la permission, il capturera 2 s et retournera 0.
        Un segfault ou abort retournerait un code négatif.
        """
        if not self.BINAIRE.exists():
            pytest.skip("SCKAudioCapture non compilé")
        result = subprocess.run(
            [str(self.BINAIRE), "2"],
            capture_output=True,
            timeout=15,
        )
        assert result.returncode in (0, 2), (
            f"Crash inattendu (code {result.returncode}).\n"
            f"stderr : {result.stderr.decode(errors='replace')}"
        )


@pytest.mark.skipif(not IS_MACOS, reason="ffmpeg embarqué macOS uniquement")
class TestFfmpegVendor:
    """ffmpeg LGPL embarqué (docs/16-packaging-macos.md §5.5).

    `packaging/vendor/ffmpeg` n'est produit que par un `bash packaging/build_ffmpeg.sh`
    explicite (pas par `make setup`) : les vérifications de contenu sont skippées
    quand le binaire est absent (fresh clone / CI)."""

    BUILD_SH = ROOT / "packaging" / "build_ffmpeg.sh"
    BINAIRE = ROOT / "packaging" / "vendor" / "ffmpeg"

    def test_build_ffmpeg_sh_existe(self):
        assert self.BUILD_SH.exists()

    def test_build_ffmpeg_sh_executable(self):
        assert os.access(self.BUILD_SH, os.X_OK), (
            "build_ffmpeg.sh n'est pas exécutable — chmod +x packaging/build_ffmpeg.sh"
        )

    def test_binaire_sans_dependance_homebrew(self):
        if not self.BINAIRE.exists():
            pytest.skip("ffmpeg non compilé — lancer : bash packaging/build_ffmpeg.sh")
        libs = subprocess.run(
            ["otool", "-L", str(self.BINAIRE)], capture_output=True, text=True, check=True
        ).stdout
        for ligne in libs.splitlines()[1:]:
            assert "/opt/homebrew" not in ligne, f"dylib Homebrew non portable : {ligne}"

    def test_binaire_sans_gpl(self):
        if not self.BINAIRE.exists():
            pytest.skip("ffmpeg non compilé — lancer : bash packaging/build_ffmpeg.sh")
        version = subprocess.run(
            [str(self.BINAIRE), "-version"], capture_output=True, text=True, check=True
        ).stdout
        assert "--enable-gpl" not in version, "build ffmpeg --enable-gpl inattendu (licence)"

    def test_binaire_a_libopus(self):
        if not self.BINAIRE.exists():
            pytest.skip("ffmpeg non compilé — lancer : bash packaging/build_ffmpeg.sh")
        encoders = subprocess.run(
            [str(self.BINAIRE), "-hide_banner", "-encoders"],
            capture_output=True, text=True, check=True,
        ).stdout
        assert "libopus" in encoders

    # `--disable-everything` n'active QUE ce qui est listé dans `build_ffmpeg.sh` :
    # toute nouvelle invocation de ffmpeg dans le code peut donc marcher en dev
    # (ffmpeg Homebrew complet) et échouer DANS L'APP LIVRÉE. Deux occurrences
    # réelles : `aselect`/`asetpts` absents (compaction des silences cassée depuis
    # toujours, docs/48) et le muxer `segment` absent (repli découpage Mistral, CR
    # d'une réunion de 1 h 52 perdu le 2026-09-02). Les deux étaient invisibles à la
    # lecture du code comme à `make test` — d'où ces deux tests, qui interrogent le
    # binaire réellement livré.
    MUXERS_REQUIS = {
        "opus": "rétention audio (core/fichiers.py)",
        "wav": "repli WAV Mistral + passe 1 de la compaction",
        "segment": "repli découpage Mistral (core/mistral/decoupage.py)",
    }
    FILTRES_REQUIS = {
        "aselect": "compaction des silences (core/mistral/silences.py)",
        "asetpts": "compaction des silences (core/mistral/silences.py)",
        "aresample": "rééchantillonnage 16 kHz",
    }

    def _noms(self, option: str) -> set[str]:
        sortie = subprocess.run(
            [str(self.BINAIRE), "-hide_banner", option],
            capture_output=True, text=True, check=True,
        ).stdout
        return {
            parties[1]
            for ligne in sortie.splitlines()
            if len(parties := ligne.split()) >= 2
        }

    def test_binaire_a_les_muxers_utilises_par_le_code(self):
        if not self.BINAIRE.exists():
            pytest.skip("ffmpeg non compilé — lancer : bash packaging/build_ffmpeg.sh")
        dispo = self._noms("-muxers")
        for muxer, usage in self.MUXERS_REQUIS.items():
            assert muxer in dispo, (
                f"muxer {muxer} absent du binaire embarqué — {usage} échouera "
                f"dans l'app livrée (ajouter à --enable-muxer dans build_ffmpeg.sh)"
            )

    def test_binaire_a_les_filtres_utilises_par_le_code(self):
        if not self.BINAIRE.exists():
            pytest.skip("ffmpeg non compilé — lancer : bash packaging/build_ffmpeg.sh")
        dispo = self._noms("-filters")
        for filtre, usage in self.FILTRES_REQUIS.items():
            assert filtre in dispo, (
                f"filtre {filtre} absent du binaire embarqué — {usage} échouera "
                f"dans l'app livrée (ajouter à --enable-filter dans build_ffmpeg.sh)"
            )

    def _opus_de_test(self, tmp_path, duree_s: int = 40):
        """Petit Opus sonore, encodé PAR le binaire embarqué (pas de fixture)."""
        import math
        import struct

        pcm = tmp_path / "src.f32"
        pcm.write_bytes(b"".join(
            struct.pack("<f", 0.2 * math.sin(2 * math.pi * 440 * i / 16000))
            for i in range(16000 * duree_s)
        ))
        source = tmp_path / "src.opus"
        subprocess.run(
            [str(self.BINAIRE), "-y", "-loglevel", "error",
             "-f", "f32le", "-ar", "16000", "-ac", "1", "-i", str(pcm),
             "-c:a", "libopus", "-b:a", "24k", str(source)],
            check=True, capture_output=True,
        )
        return source

    def test_compaction_reelle_a_beaucoup_de_plages_avec_le_binaire_embarque(
            self, tmp_path, monkeypatch):
        """`compacter_piste` sur le binaire EMBARQUÉ, avec un nombre RÉALISTE de plages.

        Le terrain du 2026-09-07 (réunion de 93 min, 107 plages) sortait en 244 :
        l'évaluateur d'expressions de ffmpeg s'arrête à 100 niveaux d'imbrication
        et `a+b+c` en consomme un par terme, alors que `MAX_PLAGES` en autorise 120.
        Les tests unitaires ne pouvaient pas le voir — ils mockent `subprocess.run`,
        donc l'expression n'était jamais analysée par ffmpeg. La limite vit dans
        `libavutil`, pas dans le build minimal : les 3 OS étaient touchés.
        """
        if not self.BINAIRE.exists():
            pytest.skip("ffmpeg non compilé — lancer : bash packaging/build_ffmpeg.sh")
        from debrief_meet.core.mistral import silences

        monkeypatch.setattr(silences, "chemin_ffmpeg", lambda: str(self.BINAIRE))
        source = self._opus_de_test(tmp_path, duree_s=40)
        # Plus de plages que la limite de l'évaluateur, jusqu'au pire cas autorisé.
        nb = max(110, silences.MAX_PLAGES)
        assert nb > silences.PROFONDEUR_EVAL_FFMPEG, "le cas testé doit dépasser la limite"
        plages = tuple((i * 0.3, i * 0.3 + 0.1) for i in range(nb))
        plan = silences.PlanCompaction(plages=plages, duree_totale_s=40.0)

        sortie = silences.compacter_piste(source, tmp_path, plan)

        assert sortie.exists() and sortie.stat().st_size > 0
        assert not (tmp_path / "src_compacte.wav").exists(), "WAV intermédiaire non nettoyé"

    def test_expression_plate_echoue_bien_sur_le_binaire_embarque(self, tmp_path):
        """Fige la limite mesurée : sans groupement, ffmpeg REFUSE l'expression.

        C'est le témoin du correctif — s'il devenait vert, le groupement de
        `expression_selection` ne protégerait plus de rien et le test précédent
        passerait pour de mauvaises raisons."""
        if not self.BINAIRE.exists():
            pytest.skip("ffmpeg non compilé — lancer : bash packaging/build_ffmpeg.sh")
        from debrief_meet.core.mistral import silences

        source = self._opus_de_test(tmp_path, duree_s=40)
        plate = "+".join(
            f"between(t,{i * 0.3:.3f},{i * 0.3 + 0.1:.3f})"
            for i in range(silences.PROFONDEUR_EVAL_FFMPEG + 7)
        )
        resultat = subprocess.run(
            [str(self.BINAIRE), "-y", "-loglevel", "error", "-i", str(source),
             "-af", f"aselect='{plate}',asetpts=N/SR",
             "-ac", "1", "-ar", "16000", str(tmp_path / "plate.wav")],
            capture_output=True, text=True,
        )
        assert resultat.returncode == silences.CODE_SORTIE_ENOMEM, (
            f"code inattendu {resultat.returncode} — la limite d'imbrication de ffmpeg "
            f"a changé, revoir PROFONDEUR_EVAL_FFMPEG :\n{resultat.stderr[-300:]}"
        )
        assert "Cannot allocate memory" in resultat.stderr

    def test_decoupage_reel_avec_le_binaire_embarque(self, tmp_path, monkeypatch):
        """`decouper_piste` sur le binaire EMBARQUÉ, pas celui du PATH.

        Le test de disponibilité du muxer ne suffit pas : `-f segment` délègue à un
        muxer enfant déduit de l'extension (ici `opus`), qui doit être présent lui
        aussi. C'est la commande exacte du repli qui sortait en 8 le 2026-09-02.
        """
        if not self.BINAIRE.exists():
            pytest.skip("ffmpeg non compilé — lancer : bash packaging/build_ffmpeg.sh")
        import math
        import struct

        from debrief_meet.core.mistral import decoupage

        monkeypatch.setattr(decoupage, "chemin_ffmpeg", lambda: str(self.BINAIRE))
        pcm = tmp_path / "src.f32"
        pcm.write_bytes(b"".join(
            struct.pack("<f", 0.2 * math.sin(2 * math.pi * 440 * i / 16000))
            for i in range(16000 * 5)
        ))
        source = tmp_path / "src.opus"
        subprocess.run(
            [str(self.BINAIRE), "-y", "-loglevel", "error",
             "-f", "f32le", "-ar", "16000", "-ac", "1", "-i", str(pcm),
             "-c:a", "libopus", "-b:a", "24k", str(source)],
            check=True, capture_output=True,
        )
        segments = decoupage.decouper_piste(source, tmp_path / "out", limite_s=2)
        assert len(segments) >= 2, f"découpage sans effet : {segments}"
        assert all(s.stat().st_size > 0 for s in segments)


@pytest.mark.skipif(not IS_MACOS, reason="PortAudio recompilé : macOS uniquement")
class TestPortaudioVendor:
    """PortAudio 19.7.0 + correctif amont #1175 (docs/16 §5.7).

    La dylib que sounddevice embarque peut s'interbloquer dans `stream.stop()` avec le
    thread d'E/S de CoreAudio : micro resté ouvert après une réunion, app figée à la
    sortie (terrain du 2026-10-23, reproduit en 265 à 327 cycles sur cette dylib).
    Comme pour ffmpeg, on vérifie ce qui est RÉELLEMENT livré : une substitution qui
    cesserait de s'appliquer redonnerait la dylib fautive sans aucun autre symptôme."""

    BUILD_SH = ROOT / "packaging" / "build_portaudio.sh"
    PATCH = ROOT / "packaging" / "patches" / "portaudio-1175-coreaudio-deadlock.patch"
    DYLIB = ROOT / "packaging" / "vendor" / "libportaudio.dylib"
    SPEC = ROOT / "packaging" / "debriefMeet.spec"
    # Libellé de la file GCD créée par le patch : absent de la dylib d'origine.
    MARQUEUR = b"PortAudio.CoreAudio.startStop"

    def test_build_portaudio_sh_executable(self):
        assert os.access(self.BUILD_SH, os.X_OK), (
            "build_portaudio.sh n'est pas exécutable — chmod +x packaging/build_portaudio.sh"
        )

    def test_patch_retire_l_appel_fautif_du_listener(self):
        """Le cœur du correctif : plus d'`AudioUnitGetProperty` dans le listener
        `IsRunning`, appelé sur le thread d'E/S qui tient le mutex du HAL."""
        patch = self.PATCH.read_text(encoding="utf-8")
        assert "-    err = AudioUnitGetProperty( ci, kAudioOutputUnitProperty_IsRunning" in patch
        assert "+            dispatch_source_merge_data( stream->startStopSource, 1 );" in patch

    def test_spec_substitue_la_dylib_de_sounddevice(self):
        spec = self.SPEC.read_text(encoding="utf-8")
        assert '"_sounddevice_data", "portaudio-binaries", "libportaudio.dylib"' in spec
        # C'est la liste substituée qui part dans le bundle, pas `a.binaries`.
        assert "    binaires_app,\n" in spec
        assert "COLLECT(\n    exe,\n    a.binaries," not in spec

    def test_build_app_refuse_un_bundle_sans_le_correctif(self):
        build_app = (ROOT / "packaging" / "build_app.sh").read_text(encoding="utf-8")
        assert self.MARQUEUR.decode() in build_app

    def test_dylib_vendor_porte_le_correctif(self):
        if not self.DYLIB.exists():
            pytest.skip("PortAudio non compilé — lancer : bash packaging/build_portaudio.sh")
        assert self.MARQUEUR in self.DYLIB.read_bytes(), (
            "packaging/vendor/libportaudio.dylib ne contient pas le correctif #1175")

    def test_dylib_d_origine_ne_porte_pas_le_marqueur(self):
        """Contre-épreuve : sans elle, le test précédent pourrait être vert pour une
        chaîne présente dans toute dylib PortAudio."""
        sd = pytest.importorskip("sounddevice")
        origine = (Path(sd.__file__).parent / "_sounddevice_data" / "portaudio-binaries"
                   / "libportaudio.dylib")
        if not origine.exists():
            pytest.skip("sounddevice sans dylib embarquée (PortAudio système)")
        assert self.MARQUEUR not in origine.read_bytes()

    def test_dylib_vendor_compatible_avec_celle_qu_elle_remplace(self):
        if not self.DYLIB.exists():
            pytest.skip("PortAudio non compilé — lancer : bash packaging/build_portaudio.sh")
        nom = subprocess.run(["otool", "-D", str(self.DYLIB)],
                             capture_output=True, text=True, check=True).stdout
        assert nom.strip().splitlines()[-1] == "@rpath/libportaudio.dylib"
        archs = subprocess.run(["lipo", "-archs", str(self.DYLIB)],
                               capture_output=True, text=True, check=True).stdout.split()
        assert "arm64" in archs
        deps = subprocess.run(["otool", "-L", str(self.DYLIB)],
                              capture_output=True, text=True, check=True).stdout
        for ligne in deps.splitlines():
            if ligne.startswith(("\t", " ")):
                assert "/opt/homebrew" not in ligne and "/usr/local" not in ligne, ligne


@pytest.mark.skipif(not IS_MACOS, reason="build_app.sh macOS uniquement")
class TestBuildAppVersion:
    """VERSION_COMPLETE générée côté macOS avec le même outillage que Windows
    (packaging/windows/generer_version.py, docs/16 §5.2 / docs/32) — même format
    "<version>+<AAAAMMJJ>.<hash-git-court>" sur les deux plateformes."""

    BUILD_APP_SH = ROOT / "packaging" / "build_app.sh"
    BUILD_DMG_SH = ROOT / "packaging" / "build_dmg.sh"

    def test_build_app_genere_version_complete(self):
        contenu = self.BUILD_APP_SH.read_text()
        assert "generer_version.py" in contenu
        assert "BUILD_INFO" in contenu

    def test_build_dmg_utilise_version_complete(self):
        contenu = self.BUILD_DMG_SH.read_text()
        assert "VERSION_COMPLETE" in contenu


# ── Packaging Windows : éditions complète / lite (docs/44) ────────────────────

class TestSpecWindows:
    """Hygiène du spec PyInstaller et du .iss Windows.

    Lecture **structurelle** (`ast`) des listes plutôt que textuelle : un commentaire
    citant « ctranslate2 » ne doit pas pouvoir faire passer le test. Aucun lancement
    de PyInstaller ni d'ISCC : ces vérifications tournent partout, en ms.
    """

    SPEC = ROOT / "packaging" / "windows" / "debriefMeet.spec"
    ISS = ROOT / "packaging" / "windows" / "debriefMeet.iss"

    # GUID figé le 2026-07-03 — c'est lui qui rend une réinstallation (y compris
    # par-dessus une ancienne édition lite de docs/44) équivalente à une mise à
    # jour. Ne jamais le changer (docs/32 §3.3).
    APP_ID = "{{C18F22B8-EBDF-46FD-8E97-2F4334DA3182}"

    def _liste(self, nom: str) -> list[str]:
        """Valeur d'une affectation de liste de chaînes au niveau module du spec."""
        import ast

        arbre = ast.parse(self.SPEC.read_text(encoding="utf-8"))
        for noeud in arbre.body:
            if isinstance(noeud, ast.Assign) and any(
                    isinstance(c, ast.Name) and c.id == nom for c in noeud.targets):
                return [e.value for e in noeud.value.elts]
        raise AssertionError(f"{nom} introuvable au niveau module de {self.SPEC.name}")

    def _directives(self) -> str:
        """Le .iss sans ses lignes de commentaire (`;`) — les commentaires citent
        `[Files]`, `[UninstallDelete]`, `#if`… et fausseraient tout découpage."""
        return "\n".join(
            l for l in self.ISS.read_text(encoding="utf-8").splitlines()
            if not l.lstrip().startswith(";")
        )

    def _section(self, debut: str, fin: str) -> str:
        directives = self._directives()
        return directives[directives.index(debut):directives.index(fin)]

    # ── Spec : bundle unifié (docs/45) ────────────────────────────────────────

    def test_pile_locale_toujours_collectee(self):
        """Bundle unique : la pile de transcription locale est embarquée
        inconditionnellement — c'est le réglage `mode_transcription` qui décide à
        l'exécution si le moteur est construit."""
        paquets = set(self._liste("PAQUETS_MOTEUR_LOCAL"))
        for paquet in ("faster_whisper", "ctranslate2", "huggingface_hub", "tokenizers"):
            assert paquet in paquets

    def test_excludes_communs_conservent_macos_et_diarization(self):
        exclus = set(self._liste("EXCLUDES"))
        for paquet in ("mlx", "mlx_whisper", "pyannote", "torch"):
            assert paquet in exclus

    def test_aucun_residu_de_la_chaine_editions(self):
        """docs/44 retiré : plus d'EDITION_COMPILEE, de MonAppEdition ni de branche
        lite nulle part dans la chaîne de build."""
        spec = self.SPEC.read_text(encoding="utf-8")
        iss = self.ISS.read_text(encoding="utf-8")
        for marqueur in ("EDITION_COMPILEE", "DEBRIEFMEET_EDITION", "EXCLUDES_LITE"):
            assert marqueur not in spec, f"résidu d'édition dans le spec : {marqueur}"
        assert "MonAppEdition" not in iss

    def test_worker_faster_whisper_en_hiddenimport(self):
        """Relancé via --fw-worker (import dynamique) : invisible à l'analyse
        statique de PyInstaller sans hiddenimport explicite."""
        assert "debrief_meet.platform.windows._fw_worker" in self._liste("hiddenimports")

    # ── .iss : ce qui doit rester gelé ────────────────────────────────────────

    def test_app_id_unique_et_inchange(self):
        lignes = [l for l in self._directives().splitlines()
                  if l.strip().startswith("AppId=")]
        assert lignes == [f"AppId={self.APP_ID}"], \
            "AppId doit rester unique et inchangé (MAJ depuis toute installation antérieure)"

    def test_app_mutex_egal_au_mutex_de_l_app(self):
        """Invariant inter-fichiers tenu jusqu'ici par un simple commentaire : si les
        deux noms divergent, Inno ne détecte pas l'app lancée et écrase des fichiers
        verrouillés."""
        from debrief_meet.platform.windows.instance_unique import NOM_MUTEX

        contenu = self.ISS.read_text(encoding="utf-8")
        assert f"AppMutex={NOM_MUTEX}" in contenu

    def test_uninstall_delete_racine_unique_sans_branche(self):
        section = self._section("[UninstallDelete]", "[Code]")
        assert r"{localappdata}\debriefMeet" in section
        assert "#if" not in section, "la racine de données est partagée, jamais conditionnelle"

    def test_install_delete_vide_le_bundle_precedent(self):
        """[Files] copie sans miroir : sans ce nettoyage, les fichiers d'un ancien
        bundle survivent aux MAJ. Les deux .lnk restent listés pour la transition
        depuis une installation lite d'avant docs/45."""
        section = self._section("[InstallDelete]", "[Files]")
        assert r"{app}\_internal" in section
        assert r"debriefMeet.lnk" in section
        assert r"debriefMeet Lite.lnk" in section

    def test_nom_et_fichier_setup_uniques(self):
        contenu = self.ISS.read_text(encoding="utf-8")
        assert '#define MonAppNom "debriefMeet"' in contenu
        assert '#define MonAppFichier "debriefMeet-setup"' in contenu
        assert "OutputBaseFilename={#MonAppFichier}-{#MonAppVersion}" in contenu

    # ── .iss : mise à jour automatique (docs/53) ──────────────────────────────

    def _run(self) -> list[str]:
        return [l for l in self._section("[Run]", "[UninstallDelete]").splitlines()
                if l.strip().startswith("Filename:")]

    def test_run_relance_conditionnelle_apres_mise_a_jour_auto(self):
        """Deux entrées [Run] et pas une de plus : l'interactive (page finale, jamais
        en silencieux) et celle de la mise à jour auto (silencieux + /AUTOUPDATE=1,
        sans `postinstall` — sinon une case de plus sur la page finale — ni
        `skipifsilent` — sinon elle ne tournerait jamais)."""
        lignes = self._run()
        assert len(lignes) == 2
        assert all('Filename: "{app}\\debriefMeet.exe"' in l for l in lignes)
        interactive = [l for l in lignes if "postinstall nowait skipifsilent" in l]
        auto = [l for l in lignes if "Check: EstMiseAJourAuto" in l]
        assert len(interactive) == 1 and len(auto) == 1
        assert "nowait" in auto[0]
        assert "postinstall" not in auto[0] and "skipifsilent" not in auto[0]

    def test_code_est_mise_a_jour_auto(self):
        directives = self._directives()
        assert directives.count("[Code]") == 1, "un seul bloc [Code] (le découpage des tests s'arrête au premier)"
        code = directives[directives.index("[Code]"):]
        assert "function EstMiseAJourAuto(): Boolean;" in code
        assert "WizardSilent" in code
        assert "ExpandConstant('{param:AUTOUPDATE|0}') = '1'" in code

    def test_param_autoupdate_commun_app_et_iss(self):
        """Invariant inter-fichiers : le paramètre que l'app passe au setup est celui
        que le .iss lit — même famille que `test_app_mutex_egal_au_mutex_de_l_app`."""
        from pathlib import PurePath

        from debrief_meet.core.mise_a_jour import PARAM_AUTOUPDATE, script_lanceur_windows

        assert "{param:" + PARAM_AUTOUPDATE + "|0}" in self._directives()
        script = script_lanceur_windows(1, PurePath("C:/s.exe"), PurePath("C:/s.log"))
        assert f"/SILENT /{PARAM_AUTOUPDATE}=1" in script

    def test_setup_mutex_contre_deux_setups_simultanes(self):
        lignes = [l for l in self._directives().splitlines() if l.strip().startswith("SetupMutex=")]
        assert lignes == ["SetupMutex=debriefMeet-setup-instance"]


# ── Mise à jour automatique : chaîne de publication (docs/53 §4) ──────────────

class TestMiseAJourPackaging:
    """Ce que la CI doit publier pour que `core/mise_a_jour.py` trouve quelque chose :
    zip macOS, assets renommés, manifeste signé et vérifié, uploadés dans le bon ordre.
    Lecture textuelle du workflow (comme les tests Linux lisent `build_deb.sh`)."""

    BUILD_DMG_SH = ROOT / "packaging" / "build_dmg.sh"
    PUBLIER_SH = ROOT / "packaging" / "publier_manifeste.sh"
    WORKFLOW = ROOT / ".github" / "workflows" / "build.yml"

    def _jobs(self) -> dict:
        import yaml

        return yaml.safe_load(self.WORKFLOW.read_text(encoding="utf-8"))["jobs"]

    def test_build_dmg_produit_le_zip_de_mise_a_jour(self):
        contenu = self.BUILD_DMG_SH.read_text(encoding="utf-8")
        assert "ditto -c -k" in contenu and "--keepParent" in contenu
        assert 'dist/debriefMeet-$VERSION.zip' in contenu
        assert "unzip" not in contenu and " zip " not in contenu

    def test_job_macos_uploade_dmg_et_zip_et_verifie_l_aller_retour(self):
        job = self._jobs()["macos"]
        upload = next(s for s in job["steps"] if s.get("uses", "").startswith("actions/upload-artifact"))
        assert "dist/debriefMeet-*.dmg" in upload["with"]["path"]
        assert "dist/debriefMeet-*.zip" in upload["with"]["path"]
        aller_retour = "\n".join(s.get("run", "") for s in job["steps"])
        assert "ditto -x -k dist/debriefMeet-*.zip" in aller_retour
        assert "codesign --verify --deep --strict" in aller_retour

    def test_job_release_signe_verifie_et_publie_dans_l_ordre(self):
        job = self._jobs()["release"]
        uses = [s.get("uses", "") for s in job["steps"]]
        assert any(u.startswith("actions/checkout") for u in uses), "checkout requis : generer_manifeste.py + core/mise_a_jour.py"
        signature = next(s for s in job["steps"] if "publier_manifeste.sh" in s.get("run", ""))
        assert signature["env"]["MAJ_CLE_PRIVEE_PEM"] == "${{ secrets.MAJ_CLE_PRIVEE_PEM }}"
        gh = next(s for s in job["steps"] if s.get("uses", "").startswith("softprops/action-gh-release"))
        fichiers = [l.strip() for l in gh["with"]["files"].splitlines() if l.strip()]
        assert gh["with"]["fail_on_unmatched_files"] is True
        assert not any("*" in f for f in fichiers), "noms exacts : une release incomplète doit échouer"
        assert fichiers[-2:] == ["artefacts/manifest.json", "artefacts/manifest.sig"], \
            "manifest.* en DERNIER : jamais un manifeste en ligne avant ses binaires"
        assert any(f.endswith(".zip") for f in fichiers)
        assert "-rc" in gh["with"]["prerelease"]
        assert "Pas de mise à jour automatique" not in gh["with"]["body"]

    def test_job_manifeste_en_dispatch_rejoue_la_meme_chaine(self):
        jobs = self._jobs()
        assert "workflow_dispatch" in jobs["manifeste"]["if"]
        run_dispatch = next(s["run"] for s in jobs["manifeste"]["steps"] if "publier_manifeste.sh" in s.get("run", ""))
        run_release = next(s["run"] for s in jobs["release"]["steps"] if "publier_manifeste.sh" in s.get("run", ""))
        assert run_dispatch.split()[:2] == run_release.split()[:2]

    def test_version_verifie_le_tag_par_le_script_teste(self):
        """La règle tag ↔ __version__ vit dans verifier_tag_version.py (testé à part) :
        le workflow doit l'appeler sur un tag, sans regex parallèle qui divergerait."""
        run = self._jobs()["version"]["steps"][1]["run"]
        assert 'python3 packaging/verifier_tag_version.py "$init" "$REF_NAME"' in run
        assert "-rc[0-9]" not in run

    def test_publier_manifeste_renomme_sans_plus_puis_verifie(self):
        contenu = self.PUBLIER_SH.read_text(encoding="utf-8")
        for cible in ('"debriefMeet-setup-$VERSION.exe"', '"debriefmeet_${VERSION}_amd64.deb"',
                      '"debriefMeet-$VERSION.dmg"', '"debriefMeet-$VERSION.zip"'):
            assert cible in contenu
        assert contenu.index("generer_manifeste.py\" generer") < contenu.index("generer_manifeste.py\" signer") \
            < contenu.index("generer_manifeste.py\" verifier")
        assert "MAJ_CLE_PRIVEE_PEM" in contenu
        assert os.access(self.PUBLIER_SH, os.X_OK)

    def test_publier_manifeste_tourne_reellement(self, tmp_path, monkeypatch):
        """Le script shell de la CI, exécuté sur de faux artefacts avec une paire
        éphémère substituée à la clé embarquée (via le code de l'app)."""
        import subprocess

        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import (
            Encoding, NoEncryption, PrivateFormat, PublicFormat,
        )

        cle = Ed25519PrivateKey.generate()
        art = tmp_path / "artefacts"
        art.mkdir()
        for nom in ("debriefMeet-setup-0.4.0+20261023.abc1234.exe", "debriefmeet_0.4.0+20261023.abc1234_amd64.deb",
                    "debriefMeet-0.4.0+20261023.abc1234.dmg", "debriefMeet-0.4.0+20261023.abc1234.zip"):
            (art / nom).write_bytes(nom.encode())
        # La vérification passe par la clé embarquée : on la remplace dans une copie
        # du module, importée par le sous-processus via sitecustomize.
        pub = cle.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()
        site = tmp_path / "site"
        site.mkdir()
        (site / "sitecustomize.py").write_text(
            "import debrief_meet.core.mise_a_jour as m\n"
            f"m.CLE_PUBLIQUE_PEM = {pub!r}\n", encoding="utf-8")
        env = dict(os.environ,
                   MAJ_CLE_PRIVEE_PEM=cle.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode(),
                   PYTHONPATH=f"{site}{os.pathsep}{ROOT / 'src'}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
                   PATH=f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}")
        r = subprocess.run(["bash", str(self.PUBLIER_SH), "0.4.0", "v0.4.0", "x/y", str(art)],
                           env=env, capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        assert sorted(p.name for p in art.iterdir()) == [
            "debriefMeet-0.4.0.dmg", "debriefMeet-0.4.0.zip", "debriefMeet-setup-0.4.0.exe",
            "debriefmeet_0.4.0_amd64.deb", "manifest.json", "manifest.sig"]
        assert "signature OK" in r.stdout
        # Relance idempotente (noms déjà finaux) : même résultat.
        r2 = subprocess.run(["bash", str(self.PUBLIER_SH), "0.4.0", "v0.4.0", "x/y", str(art)],
                            env=env, capture_output=True, text=True)
        assert r2.returncode == 0, r2.stdout + r2.stderr


# ── Benchmark : assemblage du bundle portable ─────────────────────────────────

class TestBenchmarkBundle:
    """Vérifie l'outil de benchmark et son assembleur de bundle (cf. docs/08-benchmark.md)."""

    BENCH = ROOT / "benchmark"

    def test_package_benchmark_existe(self):
        for fichier in ("__init__.py", "__main__.py", "materiel.py", "moteurs.py",
                        "pipeline.py", "rapport.py", "assembler_bundle.py"):
            assert (self.BENCH / fichier).exists(), f"Manquant : benchmark/{fichier}"

    def test_audio_canonique_present(self):
        wav = self.BENCH / "assets" / "audio_canonique.wav"
        assert wav.exists(), "Audio canonique absent — lancer construire_audio_canonique.py"
        assert wav.stat().st_size > 1_000_000  # ~30 min 16 kHz → dizaines de Mo

    def test_lanceur_windows_sans_installation(self):
        from benchmark.assembler_bundle import generer_lanceur

        bat = generer_lanceur("windows")
        assert "PYTHONPATH" in bat and "python\\python.exe" in bat
        assert "pip install" not in bat  # le bundle s'EXÉCUTE, ne s'installe pas
        assert "HF_HUB_OFFLINE" in bat   # hors-ligne forcé

    def test_pth_embeddable_declare_les_libs(self):
        """L'embeddable Windows ignore PYTHONPATH → le ._pth doit lister ..\\libs,
        sinon `python -m benchmark` échoue par « No module named benchmark »."""
        from benchmark.assembler_bundle import _pth_avec_libs

        defaut = "python311.zip\n.\n\n# Uncomment to run site.main() automatically\n#import site\n"
        out = _pth_avec_libs(defaut)
        assert "..\\libs" in out                       # libs sur sys.path
        assert "import site" in out and "#import site" not in out
        assert _pth_avec_libs(out) == out              # idempotent

    def test_lanceur_linux_sans_installation(self):
        from benchmark.assembler_bundle import generer_lanceur

        sh = generer_lanceur("linux")
        assert 'PYTHONPATH="$BASE/libs"' in sh and "pip install" not in sh

    def test_deps_bundle_non_vide_et_sans_pyside(self):
        from benchmark.assembler_bundle import DEPS_TIERS

        assert "faster-whisper" in DEPS_TIERS
        assert any(d.startswith("pyannote.audio") for d in DEPS_TIERS)
        # PySide6 inutile au benchmark → ne pas alourdir le bundle.
        assert not any("pyside" in d.lower() for d in DEPS_TIERS)

    def test_deps_pin_pyannote4_et_torch_cuda12(self):
        """pyannote épinglé ≥4 (sinon pip recule à 1.1) ; torch <2.9 (CUDA 12, pilote large)."""
        from benchmark.assembler_bundle import DEPS_TIERS

        assert "pyannote.audio>=4" in DEPS_TIERS
        assert "torch<2.9" in DEPS_TIERS

    def test_args_wheels_natif_sans_platform(self, tmp_path):
        """En natif : aucun --platform/--python-version (résolution native, markers corrects).
        En croisé : --platform présent. Les deps épinglées sont toujours passées."""
        from benchmark.assembler_bundle import _args_wheels

        natif = _args_wheels(tmp_path, "linux", "3.11", natif=True)
        croise = _args_wheels(tmp_path, "linux", "3.11", natif=False)
        assert "--platform" not in natif and "--python-version" not in natif
        assert "--platform" in croise
        assert "pyannote.audio>=4" in natif and "torch<2.9" in natif

    def test_macos_intel_deps_sans_torch_ni_pyannote(self):
        """Intel Mac : pas de wheel torch x86_64 → on retire torch/pyannote, garde sherpa."""
        from benchmark.assembler_bundle import deps_pour, supporte_pyannote

        deps = deps_pour("macos-intel")
        assert "faster-whisper" in deps and "sherpa-onnx" in deps  # cœur conservé
        assert not any(d.startswith(("torch", "pyannote")) for d in deps)
        assert supporte_pyannote("macos-intel") is False
        # Les autres cibles gardent la chaîne complète (torch épinglé CUDA 12).
        assert "torch<2.9" in deps_pour("windows") and supporte_pyannote("linux")

    def test_openvino_deps_windows_linux_seulement(self):
        """OpenVINO (optimum-intel) embarqué pour Windows/Linux, pas Intel Mac (pas de wheel)."""
        from benchmark.assembler_bundle import deps_pour, supporte_openvino

        for cible in ("windows", "linux"):
            assert any("optimum-intel" in d for d in deps_pour(cible)), cible
            assert supporte_openvino(cible) is True
        assert not any("optimum-intel" in d for d in deps_pour("macos-intel"))
        assert supporte_openvino("macos-intel") is False

    def test_table_openvino_et_resolution(self):
        from benchmark import modeles

        assert set(modeles.TABLE_OPENVINO) == {"small", "medium", "large-v3"}
        assert "whisper-large-v3-int8-ov" in modeles.resoudre_openvino("large-v3")

    def test_moteur_openvino_transcrire_modele_injecte(self):
        """transcrire() décode via processor + model.generate injectés (sans optimum réel)."""
        import numpy as np
        from benchmark.moteur_openvino import MoteurOpenVINO

        class FauxFeats:
            input_features = "FEATS"

        class FauxProcessor:
            def __call__(self, audio, sampling_rate, return_tensors):
                return FauxFeats()

            def batch_decode(self, ids, skip_special_tokens):
                return ["  bonjour le monde  "]

        class FauxModele:
            def generate(self, feats, **kw):
                assert feats == "FEATS" and kw.get("task") == "transcribe"
                return [[1, 2, 3]]

        m = MoteurOpenVINO(device="GPU")
        m._modele = FauxModele()
        m._processor = FauxProcessor()
        res = m.transcrire(np.zeros(16000, dtype=np.float32), "fr")
        assert res.texte == "bonjour le monde"
        assert len(res.segments) == 1

    def test_gpu_intel_disponible_gate(self, monkeypatch):
        """Le gate ne se déclenche que si OpenVINO liste un périphérique GPU."""
        from benchmark import sondes_accel

        monkeypatch.setattr(sondes_accel, "sonde_intel_openvino",
                            lambda: {"disponible": True, "peripheriques": ["CPU", "GPU.0"]})
        assert sondes_accel.gpu_intel_disponible() is True
        monkeypatch.setattr(sondes_accel, "sonde_intel_openvino",
                            lambda: {"disponible": False, "peripheriques": ["CPU"]})
        assert sondes_accel.gpu_intel_disponible() is False

    def test_lanceur_macos_command(self):
        """macOS : .command lève la quarantaine Gatekeeper et restaure +x, sans pip."""
        from benchmark.assembler_bundle import generer_lanceur

        cmd = generer_lanceur("macos-intel")
        assert "com.apple.quarantine" in cmd  # déblocage Gatekeeper
        assert "chmod +x" in cmd and "python/bin/python3" in cmd
        assert "pip install" not in cmd

    def test_modeles_macos_intel_sans_pyannote(self, monkeypatch, tmp_path):
        """telecharger_modeles n'embarque pas pyannote quand avec_pyannote=False."""
        from benchmark import assembler_bundle

        appels = {"pyannote": 0, "fw": 0}

        def faux_snapshot(repo, **kw):
            if "pyannote" in repo:
                appels["pyannote"] += 1
            else:
                appels["fw"] += 1
            (tmp_path / "x").mkdir(exist_ok=True)
            return str(tmp_path / "x")

        monkeypatch.setattr("huggingface_hub.snapshot_download", faux_snapshot)
        # Sans modèles sherpa du spike → on neutralise la copie.
        monkeypatch.setattr(assembler_bundle, "MODELES_SHERPA_SPIKE", tmp_path / "absent")
        assembler_bundle.telecharger_modeles(
            tmp_path / "models", token=None, tailles=["small"], avec_pyannote=False)
        assert appels["fw"] == 1 and appels["pyannote"] == 0

    def test_telecharger_python_embeddable_active_site(self, monkeypatch, tmp_path):
        """L'embeddable Windows est extrait et le ._pth active import site."""
        import io as _io, zipfile as _zf
        from benchmark import assembler_bundle

        # Zip factice simulant la distribution embeddable officielle.
        pth_original = "python311.zip\n.\n\n# Uncomment to run site.py at startup\n#import site\n"
        buf = _io.BytesIO()
        with _zf.ZipFile(buf, "w") as z:
            z.writestr("python311._pth", pth_original)
            z.writestr("python.exe", b"fake-exe")
        buf.seek(0)

        class _FauxReponse:
            def read(self): return buf.getvalue()
            def __enter__(self): return self
            def __exit__(self, *_): pass

        monkeypatch.setattr("urllib.request.urlopen", lambda url: _FauxReponse())
        bundle = tmp_path / "bundle-windows"
        assembler_bundle.telecharger_python_embeddable(bundle, "windows")

        pth = bundle / "python" / "python311._pth"
        assert pth.exists(), "python311._pth absent après extraction"
        contenu = pth.read_text(encoding="utf-8")
        assert "import site" in contenu, "import site non activé"
        assert "#import site" not in contenu, "La ligne est encore commentée"

    def test_telecharger_python_standalone_linux(self, monkeypatch, tmp_path):
        """Linux : le tarball standalone est extrait en python/bin/python3."""
        import io as _io, tarfile as _tf
        from benchmark import assembler_bundle

        # Tarball factice reproduisant la structure install_only (racine python/).
        buf = _io.BytesIO()
        with _tf.open(fileobj=buf, mode="w:gz") as tar:
            contenu = b"#!/fake/python\n"
            info = _tf.TarInfo("python/bin/python3")
            info.size = len(contenu)
            info.mode = 0o755
            tar.addfile(info, _io.BytesIO(contenu))
        buf.seek(0)

        class _FauxReponse:
            def read(self): return buf.getvalue()
            def __enter__(self): return self
            def __exit__(self, *_): pass

        monkeypatch.setattr("urllib.request.urlopen", lambda url: _FauxReponse())
        bundle = tmp_path / "bundle-linux"
        assembler_bundle.telecharger_python_embeddable(bundle, "linux")
        assert (bundle / "python" / "bin" / "python3").exists()

    def test_lanceur_linux_restaure_executable(self):
        """lancer.sh restaure le bit exécutable du python embarqué (extraction GUI)."""
        from benchmark.assembler_bundle import generer_lanceur

        sh = generer_lanceur("linux")
        assert "chmod +x" in sh and "python/bin/python3" in sh

    @pytest.mark.integration
    def test_resolution_wheels_windows(self):
        """Détecte tôt une dépendance légère sans wheel Windows (réseau requis)."""
        from benchmark.assembler_bundle import verifier_wheels

        legers = ["faster-whisper", "sherpa-onnx", "sounddevice", "psutil", "py-cpuinfo"]
        res = verifier_wheels("windows", legers)
        manquants = [p for p, ok in res.items() if not ok]
        assert not manquants, f"Sans wheel win_amd64 : {manquants}"


class TestVersionRcParOs:
    """Une rc (`__version__ = "0.4.1rc1"`, docs/53 §6) traduite dans chaque format OS."""

    def test_info_plist_ne_porte_que_des_entiers(self):
        spec = (ROOT / "packaging" / "debriefMeet.spec").read_text(encoding="utf-8")
        assert '"CFBundleShortVersionString": VERSION_PLIST' in spec
        assert '"CFBundleVersion": VERSION_PLIST' in spec
        import re
        motif = re.search(r'VERSION_PLIST = re\.match\(r"([^"]+)", VERSION\)', spec).group(1)
        assert re.match(motif, "0.4.1rc1").group(0) == "0.4.1"

    @pytest.mark.parametrize("complete, attendu", [
        ("0.4.1rc1+20261023.abc1234", "0.4.1~rc1+20261023.abc1234"),
        ("0.4.1+20261023.abc1234", "0.4.1+20261023.abc1234"),
    ])
    def test_deb_ecrit_la_rc_avec_un_tilde(self, complete, attendu):
        """Sans tilde, dpkg classe 0.4.1rc1 APRÈS 0.4.1. On exécute la ligne réelle."""
        script = (ROOT / "packaging" / "linux" / "build_deb.sh").read_text(encoding="utf-8")
        ligne = next(l for l in script.splitlines() if l.startswith('VERSION="$(printf'))
        sortie = subprocess.run(["bash", "-c", f'VERSION="{complete}"; {ligne}; printf %s "$VERSION"'],
                                capture_output=True, text=True, check=True).stdout
        assert sortie == attendu


class TestSpecLinux:
    """Hygiène du spec PyInstaller, du .desktop et de la chaîne .deb Linux (docs/49
    §6.1) — miroir de TestSpecWindows : lecture structurelle, aucun lancement de
    PyInstaller ni de dpkg-deb, ces vérifications tournent partout en ms."""

    SPEC = ROOT / "packaging" / "linux" / "debriefMeet.spec"
    DESKTOP = ROOT / "packaging" / "linux" / "debriefmeet.desktop"
    BUILD_DEB = ROOT / "packaging" / "linux" / "build_deb.sh"
    BUILD_APP = ROOT / "packaging" / "linux" / "build_app.sh"

    def _liste(self, nom: str) -> list[str]:
        import ast

        arbre = ast.parse(self.SPEC.read_text(encoding="utf-8"))
        for noeud in arbre.body:
            if isinstance(noeud, ast.Assign) and any(
                    isinstance(c, ast.Name) and c.id == nom for c in noeud.targets):
                return [e.value for e in noeud.value.elts]
        raise AssertionError(f"{nom} introuvable au niveau module de {self.SPEC.name}")

    def test_excludes_couvre_les_piles_des_autres_os(self):
        """v1 Linux = distant seul (docs/49 L1) : ni moteur local, ni piles
        macOS/Windows. L'exclusion est explicite pour qu'un paquet présent par
        accident dans le venv de build ne gonfle pas le .deb en silence."""
        excludes = self._liste("EXCLUDES")
        for paquet in ("mlx", "pyannote", "torch", "faster_whisper", "ctranslate2",
                       "soundcard"):
            assert paquet in excludes, f"{paquet} doit être exclu du bundle Linux v1"

    def test_aucun_ffmpeg_embarque(self):
        """Décision L3 : `Depends: ffmpeg`, rien d'embarqué. Le mot ne doit apparaître
        dans le spec qu'en documentation (docstring/commentaires), jamais en code."""
        import ast

        arbre = ast.parse(self.SPEC.read_text(encoding="utf-8"))
        # clean=False : la valeur BRUTE, identique à la constante rencontrée par
        # ast.walk (le nettoyage d'indentation ferait échouer la comparaison).
        docstring = ast.get_docstring(arbre, clean=False) or ""
        assert "ffmpeg" in docstring.lower(), "la décision L3 doit rester documentée"
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Constant) and isinstance(noeud.value, str):
                if noeud.value == docstring:
                    continue
                assert "ffmpeg" not in noeud.value.lower(), (
                    f"référence code à ffmpeg dans le spec Linux : {noeud.value!r}")

    def test_livekit_collecte(self):
        """L'AEC3 nettoie la piste micro retenue même en mode distant (docs/48) —
        livekit doit être collecté (ses .so natives échappent à l'analyse statique)."""
        import ast

        arbre = ast.parse(self.SPEC.read_text(encoding="utf-8"))
        constantes = [n.value for n in ast.walk(arbre)
                      if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        assert "livekit" in constantes

    def test_desktop_conforme_freedesktop(self):
        contenu = self.DESKTOP.read_text(encoding="utf-8")
        assert contenu.startswith("[Desktop Entry]")
        for ligne in ("Type=Application", "Exec=/opt/debriefmeet/debriefMeet",
                      "Icon=debriefmeet", "Terminal=false"):
            assert ligne in contenu, f"{ligne} manquant dans debriefmeet.desktop"

    def test_depends_du_deb(self):
        """Chaque Depends a une raison mesurée (docs/49 §6.1). `libportaudio2`
        surtout : la roue pip de sounddevice ne fournit PAS la bibliothèque C sous
        Linux — crash à l'import vécu chez le premier utilisateur du spike."""
        contenu = self.BUILD_DEB.read_text(encoding="utf-8")
        ligne_depends = next(
            (l for l in contenu.splitlines() if l.startswith("Depends:")), None)
        assert ligne_depends is not None, "ligne Depends absente de build_deb.sh"
        for dep in ("ffmpeg", "libportaudio2", "pulseaudio-utils", "libxcb-cursor0",
                    "libgtk-3-0t64", "adwaita-icon-theme"):
            assert dep in ligne_depends, f"Depends sans {dep}"

    def test_le_build_teste_avant_de_geler(self):
        """La gate pytest est bloquante AVANT PyInstaller, comme sur la VM Windows
        (docs/32) : un build ne doit jamais sortir d'un arbre rouge."""
        contenu = self.BUILD_APP.read_text(encoding="utf-8")
        # "bin/pyinstaller" = l'invocation réelle — "pyinstaller" seul matcherait le
        # `pip install … pyinstaller` de l'étape venv, avant la gate.
        assert contenu.index("pytest") < contenu.index("bin/pyinstaller ")

    def test_icone_source_presente(self):
        assert (ROOT / "src" / "debrief_meet" / "ui" / "assets" / "icons"
                / "app-icon-512.png").exists()
