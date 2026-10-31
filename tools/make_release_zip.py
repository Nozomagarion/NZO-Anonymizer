"""Zip de la Release GitHub : le panneau + le moteur + la doc, dans un dossier « Anonymizer ».

    python tools/make_release_zip.py  ->  dist/Anonymizer-EffectCraft-1.1.1.zip
"""
import os, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION = "1.1.1"
SKIP = {"venv", "models", "faces", "__pycache__", "cache", "sorties"}


def main():
    os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)
    out = os.path.join(ROOT, "dist", "Anonymizer-EffectCraft-%s.zip" % VERSION)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in ("Anonymizer.jsx", "README.md", "README.fr.md", "LICENSE", "NOTICE.md"):
            z.write(os.path.join(ROOT, f), "Anonymizer/" + f)
        for root, dirs, files in os.walk(os.path.join(ROOT, "moteur")):
            dirs[:] = [d for d in dirs if d not in SKIP]
            for f in files:
                p = os.path.join(root, f)
                z.write(p, "Anonymizer/" + os.path.relpath(p, ROOT).replace(os.sep, "/"))
    print(out)


if __name__ == "__main__":
    main()
