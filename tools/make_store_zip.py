"""Construit le zip à envoyer au NZO Store : le panneau, son icône et un texte court.

Le store n'accepte que .wasm .jsx .json .png .md .txt (20 Mo max). Le moteur Python n'y entre donc pas :
il se télécharge sur la page Releases du dépôt, et le texte du store l'explique.

    python tools/make_store_zip.py  ->  dist/com.nozomagarion.tool.anonymizer-1.1.2.zip
"""
import os, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION = "1.1.2"
PLUGIN_ID = "com.nozomagarion.tool.anonymizer"
STORE_README = """# Anonymizer

Hide every face in a clip: a fake AI face, a blur, a pixelation. Tracked and stackable.

This panel needs the local engine, which is not part of the store (it is a Python program with AI models).
Install it once from the GitHub page:

https://github.com/Nozomagarion/NZO-Anonymizer/releases/latest

Then in EffectCraft: Settings > Scripting & Expressions > tick "Allow Scripts to Write Files and Access Network",
start the engine (demarrer_moteur.bat) and open Window > Anonymizer.jsx.

Free. Code under MIT. The face models are for non-commercial use (see NOTICE.md on GitHub).
"""


def main():
    os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)
    out = os.path.join(ROOT, "dist", "%s-%s.zip" % (PLUGIN_ID, VERSION))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(os.path.join(ROOT, "Anonymizer.jsx"), "Anonymizer.jsx")
        z.write(os.path.join(ROOT, "Plug-ins", "AnonymizerControls.wasm"), "AnonymizerControls.wasm")
        z.write(os.path.join(ROOT, "icon.png"), "icon.png")
        z.writestr("README.md", STORE_README)
    print(out)


if __name__ == "__main__":
    main()
