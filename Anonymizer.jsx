// Anonymizer pour EffectCraft — panneau ScriptUI.
//
// Anonymise automatiquement tous les visages d'un calque vidéo, comme le plug-in « Anonymizer »
// d'aescripts : remplacement par des visages générés par IA, flou et pixelisation, cumulables.
//
// Installation : Fichier ▸ Scripts ▸ Installer un panneau ScriptUI… (ou copier ce fichier dans
// « Scripts/ScriptUI Panels » du dossier de réglages d'EffectCraft), puis Fenêtre ▸ Anonymizer.jsx.
// Le travail IA est fait par le moteur local (dossier « moteur », démarrer_moteur.bat) : un script
// EffectCraft ne peut pas lancer de programme, le panneau lui parle donc en TCP sur 127.0.0.1.
// À activer une fois : Réglages ▸ Scripting & Expressions ▸ Allow Scripts to Write Files and
// Access Network.
//
// Ce que le panneau crée au-dessus du calque choisi, tout reste modifiable à la main :
//   • « Anonymizer · Visages IA » : séquence PNG avec alpha des visages remplacés ;
//   • « Anonymizer · Flou » : calque d'effets avec un masque suivi par visage + Flou gaussien ;
//   • « Anonymizer · Pixelisation » : idem avec Mosaïque.
// Les calques sont parentés au calque vidéo, donc ils suivent ses déplacements et son échelle.

(function anonymizerPanel(thisObj) {
  var SECTION = "Anonymizer";
  var VERSION = "1.1.1";
  var G = $.global;

  // ------------------------------------------------------------------ réglages persistants

  var DEFAULTS = {
    port: "47811", engineDir: "",
    swap: "true", seed: "1", match: "true", hd: "true", color: "true",
    blur: "false", blurAmount: "40",
    pixel: "false", pixelSize: "24",
    sensitivity: "50", minFace: "16", smooth: "2",
    maskScale: "120", feather: "20", expansion: "0",
    range: "layer", reanalyze: "false", wait: "true", fast: "true"
  };
  function getSetting(k) {
    try {
      if (app.settings.haveSetting(SECTION, k)) return String(app.settings.getSetting(SECTION, k));
    } catch (e) {}
    return DEFAULTS[k];
  }
  function saveSetting(k, v) {
    try { app.settings.saveSetting(SECTION, k, String(v)); } catch (e) {}
  }

  // ------------------------------------------------------------------ interface

  var ui = thisObj instanceof Panel ? thisObj : new Window("palette", "Anonymizer", undefined, { resizeable: true });
  ui.orientation = "column";
  ui.alignChildren = ["fill", "top"];
  ui.spacing = 6;
  ui.margins = 8;

  var head = ui.add("group");
  head.alignChildren = ["left", "center"];
  var engineState = head.add("statictext", undefined, "Moteur : non vérifié");
  engineState.characters = 30;
  var checkBtn = head.add("button", undefined, "Vérifier");

  var tabs = ui.add("tabbedpanel");
  tabs.alignChildren = ["fill", "top"];
  var tMain = tabs.add("tab", undefined, "Anonymiser");
  var tDetect = tabs.add("tab", undefined, "Détection");
  var tSetup = tabs.add("tab", undefined, "Moteur");
  [tMain, tDetect, tSetup].forEach(function (t) {
    t.orientation = "column";
    t.alignChildren = ["fill", "top"];
    t.spacing = 6;
    t.margins = [10, 34, 10, 10]; // haut : laisse la place aux titres des onglets
  });

  function row(parent) {
    var g = parent.add("group");
    g.orientation = "row";
    g.alignChildren = ["left", "center"];
    return g;
  }
  var LABEL_W = 150; // largeur commune des libellés : les champs s'alignent en colonne
  function numField(parent, label, key, chars) {
    var g = row(parent);
    g.add("statictext", undefined, label).preferredSize.width = LABEL_W;
    var e = g.add("edittext", undefined, getSetting(key));
    e.characters = chars || 5;
    e.onChange = function () { saveSetting(key, e.text); };
    return e;
  }
  function check(parent, label, key) {
    // chaque case dans sa propre ligne : elles restent alignées à gauche
    var c = row(parent).add("checkbox", undefined, label);
    c.value = getSetting(key) === "true";
    c.onClick = function () { saveSetting(key, c.value); refreshEnabled(); };
    return c;
  }

  // Méthodes (cumulables, comme l'original)
  var pSwap = tMain.add("panel", undefined, "Visage IA (remplacement)");
  pSwap.alignChildren = ["left", "top"]; // "fill" décale les cases vers la droite dans EffectCraft
  var cbSwap = check(pSwap, "Remplacer par un visage IA", "swap");
  var gSwap1 = row(pSwap);
  gSwap1.add("statictext", undefined, "Tirage n° :").helpTip = "Même numéro = mêmes visages IA à chaque relance. « Autres visages » en tire de nouveaux.";
  var etSeed = gSwap1.add("edittext", undefined, getSetting("seed"));
  etSeed.characters = 5;
  etSeed.onChange = function () { saveSetting("seed", etSeed.text); };
  var btnReroll = gSwap1.add("button", undefined, "Autres visages");
  btnReroll.onClick = function () {
    etSeed.text = String(1 + Math.floor(Math.random() * 99999));
    saveSetting("seed", etSeed.text);
  };
  var cbMatch = check(pSwap, "Même genre et âge proche", "match");
  var cbHD = check(pSwap, "Qualité HD (plus lent)", "hd");
  var cbColor = check(pSwap, "Couleurs de la scène", "color");

  var pBlur = tMain.add("panel", undefined, "Flou");
  pBlur.alignChildren = ["fill", "top"];
  var cbBlur = check(pBlur, "Flouter les visages", "blur");
  var etBlur = numField(pBlur, "Intensité du flou :", "blurAmount");

  var pPix = tMain.add("panel", undefined, "Pixelisation");
  pPix.alignChildren = ["fill", "top"];
  var cbPix = check(pPix, "Pixeliser les visages", "pixel");
  var etPix = numField(pPix, "Taille des blocs (px) :", "pixelSize");

  var gRange = row(tMain);
  var rbLayer = gRange.add("radiobutton", undefined, "Tout le calque");
  rbLayer.helpTip = "Traiter tout le calque vidéo.";
  var rbWork = gRange.add("radiobutton", undefined, "Zone de travail");
  rbLayer.value = getSetting("range") !== "work";
  rbWork.value = !rbLayer.value;
  rbLayer.onClick = function () { saveSetting("range", "layer"); };
  rbWork.onClick = function () { saveSetting("range", "work"); };

  var cbWait = check(tMain, "Attendre la fin (plans courts)", "wait");
  cbWait.helpTip = "Coché : pour un plan de 150 images ou moins, le panneau suit le calcul jusqu'au bout et crée les calques tout seul (EffectCraft ne répond pas pendant ce temps). Plan plus long : suivi au survol. Décoché : cliquez sur Vérifier ou survolez le panneau pour voir l'avancement.";
  var gGo = row(tMain);
  gGo.alignChildren = ["fill", "center"];
  var btnGo = gGo.add("button", undefined, "Anonymiser");
  btnGo.helpTip = "Anonymise le calque vidéo sélectionné.";
  btnGo.preferredSize.width = 90;
  var btnCancel = gGo.add("button", undefined, "Annuler");
  btnCancel.preferredSize.width = 70;
  btnCancel.enabled = false;

  // Pour vérifier qu'un faux visage est bien dessous : coupe / remet le flou et la pixelisation.
  var btnPeek = gGo.add("button", undefined, "Voir dessous");
  btnPeek.preferredSize.width = 90;
  btnPeek.helpTip = "Voir sous le flou : coupe ou remet les calques Anonymizer · Flou et Pixelisation de la composition active, pour voir les faux visages dessous.";
  btnPeek.onClick = function () {
    var comp = app.project.activeItem;
    if (!(comp instanceof CompItem)) { status.text = wrap("Ouvrez la composition."); return; }
    var found = [], i;
    for (i = 1; i <= comp.numLayers; i++) {
      var nm = comp.layer(i).name;
      if (nm.indexOf("Anonymizer · Flou") === 0 || nm.indexOf("Anonymizer · Pixelisation") === 0) found.push(comp.layer(i));
    }
    if (!found.length) { status.text = wrap("Aucun calque Flou ou Pixelisation d'Anonymizer dans cette composition."); return; }
    var on = !found[0].enabled;
    for (i = 0; i < found.length; i++) found[i].enabled = on;
    status.text = wrap(on ? "Flou et pixelisation remis." : "Flou coupé : vous voyez les faux visages IA. Cliquez de nouveau pour remettre le flou.");
  };

  // EffectCraft ne coupe pas les textes multilignes : on les coupe à la main (n caractères par ligne).
  function wrap(t, n) {
    n = n || 38;
    var out = [], lines = String(t).split("\n");
    for (var i = 0; i < lines.length; i++) {
      var words = lines[i].split(" "), cur = "";
      for (var w = 0; w < words.length; w++) {
        var word = words[w];
        while (word.length > n) {
          if (cur) { out.push(cur); cur = ""; }
          out.push(word.substring(0, n));
          word = word.substring(n);
        }
        if (!cur) cur = word;
        else if (cur.length + 1 + word.length <= n) cur += " " + word;
        else { out.push(cur); cur = word; }
      }
      out.push(cur);
    }
    return out.join("\n");
  }

  var bar = tMain.add("progressbar", undefined, 0, 100);
  bar.preferredSize.height = 8;
  var status = tMain.add("statictext", undefined, wrap("Sélectionnez un calque vidéo puis cliquez sur Anonymiser."), { multiline: true });
  status.preferredSize = [250, 48];

  // Détection
  var gSens = row(tDetect);
  gSens.add("statictext", undefined, "Sensibilité :").preferredSize.width = LABEL_W;
  var slSens = gSens.add("slider", undefined, Number(getSetting("sensitivity")), 0, 100);
  slSens.preferredSize = [60, 22];
  var stSens = gSens.add("statictext", undefined, Math.round(slSens.value) + " %");
  stSens.characters = 4;
  slSens.onChanging = function () { stSens.text = Math.round(slSens.value) + " %"; };
  slSens.onChange = function () { saveSetting("sensitivity", Math.round(slSens.value)); };
  var etMinFace = numField(tDetect, "Visage minimal (px) :", "minFace");
  var etSmooth = numField(tDetect, "Lissage (images) :", "smooth");
  var etScale = numField(tDetect, "Taille des masques (%) :", "maskScale");
  var etFeather = numField(tDetect, "Contour adouci (px) :", "feather");
  var etExpand = numField(tDetect, "Expansion (px) :", "expansion");
  var cbFast = check(tDetect, "Mode rapide (recommandé)", "fast");
  cbFast.helpTip = "Détection 1 image sur 2 (les autres sont interpolées) et, sous un flou ou une pixelisation, visage IA recalculé 1 image sur 3. Décochez pour une précision maximale sur des mouvements très rapides.";
  var cbReanalyze = check(tDetect, "Refaire l'analyse", "reanalyze");
  var detectHint = tDetect.add("statictext", undefined, wrap("Contour, expansion, flou et taille des blocs restent réglables ensuite dans les Options d'effet des calques créés."), { multiline: true });
  detectHint.preferredSize = [250, 48];

  // Moteur
  var etPort = numField(tSetup, "Port du moteur :", "port", 6);
  var gDir = row(tSetup);
  gDir.add("statictext", undefined, "Dossier du moteur :");
  var etDir = gDir.add("edittext", undefined, getSetting("engineDir"));
  etDir.characters = 14;
  etDir.onChange = function () { saveSetting("engineDir", etDir.text); };
  var btnStart = tSetup.add("button", undefined, "Démarrer le moteur");
  var btnModels = tSetup.add("button", undefined, "Télécharger les modèles IA");
  var gFaces = row(tSetup);
  var btnFaces = gFaces.add("button", undefined, "Ajouter des visages IA");
  var etFaceCount = gFaces.add("edittext", undefined, "16");
  etFaceCount.characters = 4;
  var btnFacesDir = tSetup.add("button", undefined, "Ouvrir le dossier des visages");
  var setupInfo = tSetup.add("statictext", undefined, "", { multiline: true });
  setupInfo.preferredSize = [250, 140];

  function refreshEnabled() {
    // Sous un flou ou une pixelisation, on glisse toujours un faux visage IA : si le flou est
    // léger ou retiré, on ne retrouve jamais le vrai visage.
    var masked = cbBlur.value || cbPix.value;
    if (masked && !cbSwap.value) { cbSwap.value = true; saveSetting("swap", true); }
    cbSwap.enabled = !masked;
    cbSwap.text = masked ? "Visage IA sous le flou (toujours actif)" : "Remplacer par un visage IA";
    cbMatch.enabled = cbColor.enabled = etSeed.enabled = btnReroll.enabled = cbSwap.value;
    // La restauration HD est inutile (et lente) sous un visage flouté ou pixelisé.
    cbHD.enabled = cbSwap.value && !masked;
    cbHD.text = masked ? "Qualité HD (inutile sous le flou)" : "Qualité HD (plus lent)";
    etBlur.enabled = cbBlur.value;
    etPix.enabled = cbPix.value;
  }
  refreshEnabled();

  // ------------------------------------------------------------------ communication avec le moteur

  var GATE = "Réglages ▸ Scripting & Expressions ▸ « Allow Scripts to Write Files and Access Network »";
  var lastPing = null;

  function request(obj, timeoutSec) {
    var s;
    try {
      s = new Socket();
    } catch (e) {
      throw new Error("Activez " + GATE + " pour que le panneau puisse parler au moteur.");
    }
    s.timeout = timeoutSec || 5;
    s.encoding = "UTF-8";
    if (!s.open("127.0.0.1:" + (parseInt(etPort.text, 10) || 47811), "UTF-8")) {
      throw new Error("Moteur injoignable. Lancez « démarrer_moteur » (onglet Moteur) puis cliquez sur Vérifier.");
    }
    try {
      s.writeln(JSON.stringify(obj));
      var line = s.readln();
      if (!line) throw new Error("Le moteur n'a pas répondu.");
      return JSON.parse(line);
    } finally {
      s.close();
    }
  }

  function ping(quiet) {
    try {
      var r = request({ cmd: "ping" }, 3);
      lastPing = r;
      var gpu = (r.providers || []).join(", ").replace(/ExecutionProvider/g, "");
      var m = r.models || {};
      var ready = m.det && m.rec && m.genderage;
      engineState.text = "Moteur connecté (" + (gpu || "CPU") + ")";
      setupInfo.text = wrap("Moteur " + r.version + " · modèles : " + (ready ? "détection OK" : "détection à télécharger") +
        (m.swap ? ", swap OK" : ", swap à télécharger") + (m.enhance ? ", HD OK" : ", HD à télécharger") +
        "\nVisages IA disponibles : " + r.faces + "\nVisages : " + r.facesDir + "\nSorties : " + r.outputDir);
      return r;
    } catch (e) {
      lastPing = null;
      engineState.text = "Moteur hors ligne";
      if (!quiet) status.text = e.message;
      setupInfo.text = e.message;
      return null;
    }
  }
  checkBtn.onClick = function () {
    if (job) { poll(); return; } // pendant un traitement : relève l'avancement
    ping(false);
  };

  // ------------------------------------------------------------------ travail en cours

  var job = null; // { id, kind, task, ctx }

  // Suivi d'un travail du moteur. EffectCraft 0.11 ne déclenche pas les tâches répétées
  // (app.scheduleTask(…, true)) : par défaut le panneau attend donc la fin lui-même, en
  // « attente longue » auprès du moteur (commande wait). En mode arrière-plan, l'avancement est
  // relevé à chaque survol ou clic du panneau, et par la tâche répétée là où elle fonctionne.
  var WAIT_MAX_FRAMES = 150;

  function startPolling(id, kind, ctx) {
    job = { id: id, kind: kind, ctx: ctx, task: 0, failures: 0, last: 0 };
    btnGo.enabled = btnModels.enabled = btnFaces.enabled = false;
    btnCancel.enabled = true;
    bar.value = 0;
    G.__anonymizerPoll = poll;
    try { job.task = app.scheduleTask("if ($.global.__anonymizerPoll) $.global.__anonymizerPoll();", 500, true); } catch (e) {}
    // EffectCraft est figé pendant l'attente : on n'attend que les traitements courts
    // (setup, visages, ou au plus WAIT_MAX_FRAMES images). Au-delà, suivi au survol.
    job.blocking = cbWait.value && !(ctx && ctx.frames > WAIT_MAX_FRAMES);
    if (job.blocking) waitForJob();
    else if (cbWait.value) status.text = wrap("Plan long (" + ctx.frames + " images) : EffectCraft reste utilisable. Survolez le panneau ou cliquez sur Vérifier pour suivre l'avancement ; les calques se créent à la fin.");
  }

  function waitForJob() {
    while (job) {
      var r;
      try {
        r = request({ cmd: "wait", job: job.id, timeout: 15 }, 30);
        job.failures = 0;
      } catch (e) {
        if (++job.failures >= 3) {
          status.text = wrap("Connexion au moteur perdue : " + e.message);
          stopPolling();
        }
        continue;
      }
      handleStatus(r);
      try { ui.layout.layout(true); } catch (e2) {}
    }
  }

  // Relève l'avancement au plus une fois par seconde (survol, clic, tâche répétée).
  function pollSoon() {
    if (!job || job.blocking) return;
    var now = new Date().getTime();
    if (now - job.last < 1000) return;
    job.last = now;
    poll();
  }

  function stopPolling() {
    if (job && job.task) {
      try { app.cancelTask(job.task); } catch (e) {}
    }
    job = null;
    btnGo.enabled = btnModels.enabled = btnFaces.enabled = true;
    btnCancel.enabled = false;
  }

  function poll() {
    if (!job) return;
    var r;
    try {
      r = request({ cmd: "status", job: job.id }, 3);
      job.failures = 0;
    } catch (e) {
      if (++job.failures >= 6) {
        status.text = wrap("Connexion au moteur perdue : " + e.message);
        stopPolling();
      }
      return;
    }
    handleStatus(r);
  }

  function handleStatus(r) {
    if (!job) return;
    if (!r.ok) {
      status.text = wrap(r.error || "Erreur du moteur");
      stopPolling();
      return;
    }
    var j = r.job;
    bar.value = Math.round((j.progress || 0) * 100);
    status.text = wrap(j.message || "");
    if (j.state === "done") {
      var cur = job;
      stopPolling();
      if (cur.kind === "anonymize") {
        try {
          buildLayers(cur.ctx, j.result);
        } catch (e) {
          status.text = wrap("Erreur pendant la création des calques : " + e.message);
        }
      } else if (cur.kind === "faces") {
        status.text = wrap(j.result.downloaded + " visage(s) IA ajouté(s). Banque : " + j.result.pool.F + " femmes, " + j.result.pool.M + " hommes.");
        ping(true);
      } else {
        status.text = wrap("Modèles IA prêts.");
        ping(true);
      }
    } else if (j.state === "error" || j.state === "cancelled") {
      stopPolling();
      status.text = wrap(j.state === "cancelled" ? "Traitement annulé." : j.message);
      bar.value = 0;
    }
  }

  btnCancel.onClick = function () {
    if (!job) return;
    try { request({ cmd: "cancel", job: job.id }, 3); } catch (e) {}
    status.text = wrap("Annulation…");
  };

  // ------------------------------------------------------------------ temps et images

  // Le calque vidéo affiche l'image source f au temps de composition :
  //   startTime + (f / fps) × (étirement / 100)
  function frameMapper(layer, fps) {
    var start = layer.startTime, k = layer.stretch / 100;
    return {
      toComp: function (f) { return start + (f / fps) * k; },
      toFrame: function (t) { return ((t - start) / k) * fps; }
    };
  }

  function sourceRange(comp, layer, fps, frameCount, useWorkArea) {
    var map = frameMapper(layer, fps);
    var t0 = layer.inPoint, t1 = layer.outPoint;
    if (useWorkArea) {
      t0 = Math.max(t0, comp.workAreaStart);
      t1 = Math.min(t1, comp.workAreaStart + comp.workAreaDuration);
    }
    var a = map.toFrame(t0), b = map.toFrame(t1);
    var lo = Math.min(a, b), hi = Math.max(a, b);
    var first = Math.max(0, Math.floor(lo + 1e-6));
    var last = Math.ceil(hi - 1e-6) - 1;
    if (frameCount > 0) last = Math.min(last, frameCount - 1);
    return { start: first, end: Math.max(first, last) };
  }

  // ------------------------------------------------------------------ lancement

  function selectedFootageLayer() {
    var comp = app.project.activeItem;
    if (!(comp instanceof CompItem)) throw new Error("Ouvrez une composition et sélectionnez le calque vidéo à anonymiser.");
    var sel = comp.selectedLayers;
    if (!sel.length) throw new Error("Sélectionnez le calque vidéo à anonymiser.");
    // Le premier calque de métrage de la sélection (on ignore solides, textes, calques d'effets…)
    for (var i = 0; i < sel.length; i++) {
      var src = sel[i].source;
      if (src instanceof FootageItem && src.file) return { comp: comp, layer: sel[i], item: src };
    }
    throw new Error("« " + sel[0].name + " » n'est pas un calque de métrage (vidéo, séquence ou image). Sélectionnez le calque vidéo.");
  }

  function sanitize(s) {
    return String(s).replace(/[^A-Za-z0-9_\-]+/g, "_").replace(/^_+|_+$/g, "").substring(0, 40) || "calque";
  }
  function stamp() {
    var d = new Date();
    function p(n) { return (n < 10 ? "0" : "") + n; }
    return d.getFullYear() + p(d.getMonth() + 1) + p(d.getDate()) + "_" + p(d.getHours()) + p(d.getMinutes()) + p(d.getSeconds());
  }

  btnGo.onClick = function () {
    try {
      if (!cbSwap.value && !cbBlur.value && !cbPix.value) throw new Error("Cochez au moins une méthode : Visage IA, Flou ou Pixelisation.");
      var sel = selectedFootageLayer();
      if (sel.layer.timeRemapEnabled) status.text = wrap("Attention : le remappage temporel n'est pas pris en compte.");
      var item = sel.item;
      var still = item.mainSource.isStill;
      var fps = still ? sel.comp.frameRate : (item.frameRate || sel.comp.frameRate);
      var frameCount = still ? 1 : Math.round(item.duration * fps);
      var range = still ? { start: 0, end: 0 } : sourceRange(sel.comp, sel.layer, fps, frameCount, rbWork.value);
      if (!ping(false)) return;

      var outDir = "";
      var pf = app.project.file;
      if (pf) outDir = pf.path + "/Anonymizer/" + sanitize(sel.layer.name) + "_" + stamp();

      var sens = Math.round(slSens.value);
      var params = {
        input: item.file.fsName,
        start: range.start,
        end: range.end,
        outDir: outDir,
        swap: cbSwap.value,
        enhance: cbSwap.value && cbHD.value && !(cbBlur.value || cbPix.value),
        detectStride: cbFast.value ? 2 : 1,
        swapStride: (cbFast.value && (cbBlur.value || cbPix.value)) ? 3 : 1,
        cover: !!(cbBlur.value || cbPix.value),
        colorMatch: cbColor.value,
        matchFaces: cbMatch.value,
        seed: parseInt(etSeed.text, 10) || 1,
        autoFaces: true,
        // sensibilité 0 % → seuil 0,8 (strict) ; 100 % → 0,3 (attrape les visages flous ou de profil)
        threshold: Math.round((0.8 - sens / 200) * 100) / 100,
        minFace: Number(etMinFace.text) || 16,
        smooth: parseInt(etSmooth.text, 10) || 0,
        reanalyze: cbReanalyze.value
      };
      var r = request({ cmd: "anonymize", params: params }, 5);
      if (!r.ok) throw new Error(r.error);
      var ctx = {
        comp: sel.comp, layer: sel.layer, item: item, fps: fps, still: still,
        frames: range.end - range.start + 1,
        swap: cbSwap.value, blur: cbBlur.value, pixel: cbPix.value,
        blurAmount: Number(etBlur.text) || 40, pixelSize: Number(etPix.text) || 24,
        maskScale: (Number(etScale.text) || 120) / 100, feather: Number(etFeather.text) || 0,
        expansion: Number(etExpand.text) || 0
      };
      status.text = wrap("Traitement lancé (images " + range.start + " à " + range.end + ")…");
      startPolling(r.job, "anonymize", ctx);
    } catch (e) {
      status.text = e.message;
    }
  };

  btnModels.onClick = function () {
    try {
      var r = request({ cmd: "setup", params: { enhance: true } }, 5);
      if (!r.ok) throw new Error(r.error);
      startPolling(r.job, "setup", null);
    } catch (e) { setupInfo.text = e.message; status.text = e.message; }
  };
  btnFaces.onClick = function () {
    try {
      var r = request({ cmd: "faces", params: { count: parseInt(etFaceCount.text, 10) || 16 } }, 5);
      if (!r.ok) throw new Error(r.error);
      tabs.selection = tMain;
      startPolling(r.job, "faces", null);
    } catch (e) { setupInfo.text = e.message; status.text = e.message; }
  };
  btnFacesDir.onClick = function () {
    var p = ping(false);
    if (!p) return;
    try { new File(p.facesDir).execute(); } catch (e) { setupInfo.text = wrap("Dossier des visages : " + p.facesDir); }
  };
  btnStart.onClick = function () {
    var dir = etDir.text.replace(/[\/\\]+$/, "");
    if (!dir) {
      setupInfo.text = wrap("Indiquez le dossier du moteur (celui qui contient démarrer_moteur.bat), ou lancez-le vous-même par double-clic.");
      return;
    }
    var names = ["demarrer_moteur.bat", "demarrer_moteur.command", "demarrer_moteur.sh"];
    for (var i = 0; i < names.length; i++) {
      var f = new File(dir + "/" + names[i]);
      if (f.exists) {
        try {
          f.execute();
          setupInfo.text = wrap("Démarrage du moteur… cliquez sur Vérifier dans quelques secondes.");
        } catch (e) { setupInfo.text = e.message; }
        return;
      }
    }
    setupInfo.text = wrap("Aucun script de démarrage dans " + dir);
  };

  // ------------------------------------------------------------------ création des calques

  function readJson(path) {
    var f = new File(path);
    f.encoding = "UTF-8";
    if (!f.open("r")) throw new Error("Lecture impossible : " + path);
    var txt = f.read();
    f.close();
    return JSON.parse(txt);
  }

  // Un calque posé exactement sur le calque vidéo : même taille, parenté, aligné.
  function attach(layer, foot, w, h) {
    layer.parent = foot;
    var tr = layer.property("ADBE Transform Group");
    tr.property("ADBE Anchor Point").setValue([w / 2, h / 2]);
    tr.property("ADBE Position").setValue([w / 2, h / 2]);
    tr.property("ADBE Scale").setValue([100, 100]);
    tr.property("ADBE Rotate Z").setValue(0);
  }

  function ellipse(box, scale) {
    var cx = (box[0] + box[2]) / 2, cy = (box[1] + box[3]) / 2;
    var rx = (box[2] - box[0]) / 2 * scale, ry = (box[3] - box[1]) / 2 * scale * 1.12;
    cy -= (box[3] - box[1]) * 0.04;
    var k = 0.5523;
    var s = new Shape();
    s.vertices = [[cx, cy - ry], [cx + rx, cy], [cx, cy + ry], [cx - rx, cy]];
    s.inTangents = [[-rx * k, 0], [0, -ry * k], [rx * k, 0], [0, ry * k]];
    s.outTangents = [[rx * k, 0], [0, ry * k], [-rx * k, 0], [0, -ry * k]];
    s.closed = true;
    return s;
  }

  function addSlider(layer, name, value) {
    var fx = layer.property("ADBE Effect Parade").addProperty("ADBE Slider Control");
    fx.name = name;
    fx.property("Slider").setValue(value);
    return fx;
  }

  // Un masque par personne, animé d'après les pistes, visible seulement quand elle est à l'image.
  function addFaceMasks(layer, tracks, ctx, map, rangeStart, rangeEnd, report) {
    var masks = layer.property("ADBE Mask Parade");
    var featherExpr = 'var v = effect("Contour (px)")("Slider"); [v, v]';
    var expandExpr = 'effect("Expansion (px)")("Slider")';
    var dt = 1 / ctx.fps;
    for (var i = 0; i < tracks.length; i++) {
      var t = tracks[i];
      var m = masks.addProperty("ADBE Mask Atom");
      m.name = "Visage " + t.id + " (" + (t.gender === "F" ? "femme" : "homme") + ", ~" + Math.round(t.age) + " ans)";
      m.maskMode = MaskMode.ADD;
      var path = m.property("ADBE Mask Shape");
      var opacity = m.property("ADBE Mask Opacity");
      var times = [], shapes = [];
      var vis = []; // [temps, valeur]
      var firstStart = t.segments.length ? t.segments[0].start : rangeStart;
      if (firstStart > rangeStart) vis.push([map.toComp(rangeStart), 0]);
      for (var s = 0; s < t.segments.length; s++) {
        var seg = t.segments[s];
        for (var k = 0; k < seg.keys.length; k++) {
          var idx = seg.keys[k];
          times.push(map.toComp(seg.start + idx));
          shapes.push(ellipse(seg.box[idx], ctx.maskScale));
        }
        vis.push([map.toComp(seg.start), 100]);
        if (seg.end < rangeEnd) vis.push([map.toComp(seg.end + 1), 0]);
      }
      if (ctx.still || times.length === 1) {
        path.setValue(shapes[0]);
      } else {
        path.setValuesAtTimes(times, shapes);
      }
      if (!ctx.still && vis.length > 1) {
        vis.sort(function (a, b) { return a[0] - b[0]; });
        var vt = [], vv = [];
        for (var v = 0; v < vis.length; v++) {
          if (vt.length && Math.abs(vt[vt.length - 1] - vis[v][0]) < dt / 4) { vv[vv.length - 1] = vis[v][1]; continue; }
          vt.push(vis[v][0]);
          vv.push(vis[v][1]);
        }
        opacity.setValuesAtTimes(vt, vv);
        for (var n = 1; n <= opacity.numKeys; n++) opacity.setInterpolationTypeAtKey(n, KeyframeInterpolationType.HOLD);
      }
      try { m.property("ADBE Mask Feather").expression = featherExpr; } catch (e) { m.property("ADBE Mask Feather").setValue([ctx.feather, ctx.feather]); }
      try { m.property("ADBE Mask Offset").expression = expandExpr; } catch (e) { m.property("ADBE Mask Offset").setValue(ctx.expansion); }
      report("Masques : visage " + (i + 1) + "/" + tracks.length);
    }
  }

  // Les calques de flou et de pixelisation couvrent exactement la plage traitée,
  // comme le calque Visages IA : hors de cette plage, rien n'est anonymisé.
  function effectsLayer(ctx, name, w, h, above, data, map) {
    var comp = ctx.comp, foot = ctx.layer;
    var solid = comp.layers.addSolid([0.5, 0.5, 0.5], name, w, h, ctx.item.pixelAspect || 1);
    solid.adjustmentLayer = true;
    solid.moveBefore(above);
    if (ctx.still) {
      solid.inPoint = foot.inPoint;
      solid.outPoint = foot.outPoint;
    } else {
      var a = map.toComp(data.start), b = map.toComp(data.end + 1);
      solid.inPoint = Math.max(foot.inPoint, Math.min(a, b));
      solid.outPoint = Math.min(foot.outPoint, Math.max(a, b));
    }
    attach(solid, foot, w, h);
    addSlider(solid, "Contour (px)", ctx.feather);
    addSlider(solid, "Expansion (px)", ctx.expansion);
    return solid;
  }

  function buildLayers(ctx, result) {
    var data = readJson(result.tracksFile);
    var tracks = data.tracks || [];
    var w = data.width || ctx.item.width, h = data.height || ctx.item.height;
    if (!tracks.length) {
      status.text = wrap("Aucun visage détecté. Augmentez la sensibilité (onglet Détection) ou baissez le visage minimal.");
      return;
    }
    var map = frameMapper(ctx.layer, ctx.fps);
    var report = function (msg) { status.text = wrap(msg); };
    var made = [];
    var top = ctx.layer;
    app.beginUndoGroup("Anonymizer");
    try {
      if (ctx.swap && data.swapFirst) {
        report("Import des visages IA…");
        var opts = new ImportOptions(new File(data.swapFirst));
        opts.sequence = !ctx.still;
        var seqItem = app.project.importFile(opts);
        if (!ctx.still) {
          try { seqItem.mainSource.conformFrameRate = ctx.fps; } catch (e) {}
        }
        seqItem.name = "Anonymizer · Visages IA · " + ctx.layer.name;
        var swapLayer = ctx.comp.layers.add(seqItem);
        swapLayer.name = "Anonymizer · Visages IA";
        swapLayer.moveBefore(top);
        if (!ctx.still) {
          swapLayer.stretch = ctx.layer.stretch;
          swapLayer.startTime = map.toComp(data.start);
          swapLayer.inPoint = Math.max(ctx.layer.inPoint, Math.min(map.toComp(data.start), map.toComp(data.end + 1)));
          swapLayer.outPoint = Math.min(ctx.layer.outPoint, Math.max(map.toComp(data.start), map.toComp(data.end + 1)));
        } else {
          swapLayer.inPoint = ctx.layer.inPoint;
          swapLayer.outPoint = ctx.layer.outPoint;
        }
        attach(swapLayer, ctx.layer, w, h);
        top = swapLayer;
        made.push("visages IA");
      }
      if (ctx.blur) {
        report("Calque de flou…");
        var bl = effectsLayer(ctx, "Anonymizer · Flou", w, h, top, data, map);
        var gb = bl.property("ADBE Effect Parade").addProperty("ADBE Gaussian Blur 2");
        gb.property("Blurriness").setValue(ctx.blurAmount);
        addFaceMasks(bl, tracks, ctx, map, data.start, data.end, report);
        top = bl;
        made.push("flou");
      }
      if (ctx.pixel) {
        report("Calque de pixelisation…");
        var px = effectsLayer(ctx, "Anonymizer · Pixelisation", w, h, top, data, map);
        addSlider(px, "Taille des blocs (px)", ctx.pixelSize);
        var mo = px.property("ADBE Effect Parade").addProperty("ADBE Mosaic");
        var bs = 'Math.max(1, effect("Taille des blocs (px)")("Slider"))';
        mo.property("Horizontal Blocks").expression = "Math.max(1, Math.round(thisComp.width / " + bs + "))";
        mo.property("Vertical Blocks").expression = "Math.max(1, Math.round(thisComp.height / " + bs + "))";
        try { mo.property("Sharp Colors").setValue(true); } catch (e) {}
        addFaceMasks(px, tracks, ctx, map, data.start, data.end, report);
        made.push("pixelisation");
      }
    } finally {
      app.endUndoGroup();
    }
    bar.value = 100;
    status.text = wrap(tracks.length + " visage(s) anonymisé(s) en " + result.seconds + " s : " + made.join(" + ") + ". Annulable en une fois (Ctrl+Z).");
  }

  // ------------------------------------------------------------------ démarrage

  try {
    ui.addEventListener("mousemove", pollSoon);
    ui.addEventListener("mousedown", pollSoon);
  } catch (e) {}

  ping(true);
  if (ui instanceof Window) {
    ui.center();
    ui.show();
  } else {
    ui.layout.layout(true);
  }
  ui.onResizing = ui.onResize = function () { this.layout.resize(); };
  ui.onClose = function () {
    if (job && job.task) {
      try { app.cancelTask(job.task); } catch (e) {}
    }
    G.__anonymizerPoll = null;
  };
})(this);
