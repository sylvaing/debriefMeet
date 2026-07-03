"""Point d'entrée du bundle PyInstaller.

Délègue à debrief_meet.__main__.main(). main() route lui-même le mode worker
MLX (--mlx-worker) avant toute init Qt, donc le même binaire sert d'app et de
sous-processus de transcription.
"""
from debrief_meet.__main__ import main

if __name__ == "__main__":
    main()
