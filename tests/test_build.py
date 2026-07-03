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
        contenu = (ROOT / "README.md").read_text()
        for section in ("Prérequis", "Installation", "make", "Permissions"):
            assert section in contenu, f"Section manquante dans README.md : {section}"


# ── pyproject.toml ────────────────────────────────────────────────────────────

class TestPyproject:
    def test_pyproject_existe(self):
        assert (ROOT / "pyproject.toml").exists()

    def test_extras_declares(self):
        contenu = (ROOT / "pyproject.toml").read_text()
        for extra in ("macos", "dev"):
            assert extra in contenu, f"Extra manquant dans pyproject.toml : {extra}"

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
