@echo off
chcp 65001 >nul
title Publier Anonymizer 1.1.1
echo.
echo  Publication d'Anonymizer 1.1.1 : GitHub puis NZO Store
echo.
cd /d "%~dp0"
where gh >nul 2>nul
if errorlevel 1 (
  echo  GitHub CLI "gh" est introuvable. Installe-le : https://cli.github.com
  goto fail
)
where python >nul 2>nul
if errorlevel 1 (
  echo  Python est introuvable.
  goto fail
)

echo  1/5 Preparation des fichiers...
python tools\make_release_zip.py
if errorlevel 1 goto fail
python tools\make_store_zip.py
if errorlevel 1 goto fail

echo  2/5 Depot GitHub Nozomagarion/NZO-Anonymizer...
if not exist ".git" (
  git init -b main >nul
)
git add -A
git -c user.name="Nozomagarion" -c user.email="Nozomagarion@users.noreply.github.com" commit -m "Anonymizer 1.1.1 pour EffectCraft" >nul 2>nul
gh repo view Nozomagarion/NZO-Anonymizer >nul 2>nul
if errorlevel 1 (
  gh repo create Nozomagarion/NZO-Anonymizer --public --source . --remote origin --description "Hide every face in your footage: AI face, blur, pixelation. A panel for EffectCraft." --push
  if errorlevel 1 goto fail
) else (
  git remote get-url origin >nul 2>nul || git remote add origin https://github.com/Nozomagarion/NZO-Anonymizer.git
  git push -u origin main
  if errorlevel 1 goto fail
)

echo  3/5 Release v1.1.1...
(
echo ## Anonymizer 1.1.1
echo.
echo - Fast mode: faces detected every second frame, AI face recomputed every third frame under a blur, no HD under a blur. About 3x faster on the same test, same result.
echo - Blur and pixelation now always have a fake AI face underneath, and their layers stop exactly where the AI faces stop.
echo - Long shots no longer freeze EffectCraft: hover the panel to follow progress.
echo - Under a blur, a blurred patch of the original face area is laid under the fake face, so no real detail is ever left, even when the swap misses a face.
echo - New button: See under the blur.
echo.
echo Unzip, copy the "moteur" folder to Documents\Anonymizer\moteur, run installer.bat, then install Anonymizer.jsx in EffectCraft. See the README.
) > "%TEMP%\anonymizer-notes.md"
gh release view v1.1.1 -R Nozomagarion/NZO-Anonymizer >nul 2>nul
if errorlevel 1 (
  gh release create v1.1.1 "dist\Anonymizer-EffectCraft-1.1.1.zip" -R Nozomagarion/NZO-Anonymizer --title "Anonymizer 1.1.1" --notes-file "%TEMP%\anonymizer-notes.md" --latest
) else (
  gh release upload v1.1.1 "dist\Anonymizer-EffectCraft-1.1.1.zip" -R Nozomagarion/NZO-Anonymizer --clobber
)
if errorlevel 1 goto fail

echo  4/5 Adresse du NZO Store...
set "STORE="
for /f "usebackq delims=" %%u in (`powershell -NoProfile -Command "try { $c = gh api repos/Nozomagarion/NZO-STORE-SERVER/contents/launcher/config.json --jq .content; ([System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($c)) | ConvertFrom-Json).store_url } catch { '' }"`) do set "STORE=%%u"
if "%STORE%"=="" (
  echo  Adresse du store introuvable.
  goto storefail
)
echo  Store : %STORE%

echo  5/5 Envoi au NZO Store (en attente de ta validation)...
curl.exe -sS -m 60 -F "file=@dist\com.nozomagarion.tool.anonymizer-1.1.1.zip" -F "plugin_id=com.nozomagarion.tool.anonymizer" -F "name=Anonymizer" -F "version=1.1.1" -F "app_id=effectcraft" -F "desc=Hide every face: fake AI face, blur or pixelation, tracked and stackable. Needs the local engine from GitHub." -F "author=Nozomagarion" "%STORE%/api/submit"
if errorlevel 1 goto storefail
echo.
echo.
echo  ===== C'EST BON =====
echo  GitHub : https://github.com/Nozomagarion/NZO-Anonymizer
echo  Store  : envoye, il reste a le valider sur le Raspberry (voir POUR_LE_RASPBERRY.md).
echo.
pause
exit /b 0

:storefail
echo.
echo  ===== GitHub est publie, mais l'envoi au NZO Store a echoue. =====
echo  Le zip pour le store est ici : %~dp0dist\com.nozomagarion.tool.anonymizer-1.1.1.zip
echo  Dis-le a Claude et copie-lui le texte ci-dessus.
echo.
pause
exit /b 1

:fail
echo.
echo  ===== ECHEC : rien de plus n'a ete publie. Previens Claude et copie-lui le texte ci-dessus. =====
echo.
pause
exit /b 1
