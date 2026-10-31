#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Anonymizer pour EffectCraft : moteur IA local.

Le panneau ScriptUI d'EffectCraft ne peut pas lancer de programme, il parle donc à ce moteur
par une connexion TCP locale (127.0.0.1:47811, une requête JSON par ligne).

Ce que fait le moteur :
  1. Détecte tous les visages de chaque image (SCRFD, modèle buffalo_l d'InsightFace).
  2. Les suit d'une image à l'autre et reconnaît une personne qui sort puis revient
     (IoU + empreinte ArcFace), estime son genre et son âge.
  3. Écrit les pistes (boîtes, points du visage, images clés réduites) dans un JSON que le
     panneau transforme en masques animés pour le flou et la pixelisation.
  4. Option « Visage IA » : remplace chaque personne par un visage généré par IA, choisi
     au même genre et à un âge proche (inswapper_128), avec amélioration HD optionnelle
     (GFPGAN 1.4). Résultat : une séquence PNG avec alpha, posée au-dessus de la vidéo.

Commandes :
  python anonymizer_engine.py setup              télécharge les modèles
  python anonymizer_engine.py serve              lance le serveur pour le panneau
  python anonymizer_engine.py faces --count 24   télécharge des visages IA dans faces/
  python anonymizer_engine.py run --input clip.mp4 --swap --blur   traitement sans EffectCraft

Dépendances : numpy, opencv-python, onnx, onnxruntime (ou onnxruntime-directml / -gpu).
"""

import argparse
import glob
import hashlib
import json
import math
import os
import queue
import random
import re
import shutil
import socketserver
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np

VERSION = "1.1.1"
HOST = "127.0.0.1"
PORT = 47811

ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(ENGINE_DIR, "models")
FACES_DIR = os.path.join(ENGINE_DIR, "faces")
CACHE_DIR = os.path.join(ENGINE_DIR, "cache")
OUTPUT_DIR = os.path.join(ENGINE_DIR, "sorties")

BUFFALO_URL = "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip"
MODELS = {
    "det": {"file": "det_10g.onnx", "zip": BUFFALO_URL},
    "rec": {"file": "w600k_r50.onnx", "zip": BUFFALO_URL},
    "genderage": {"file": "genderage.onnx", "zip": BUFFALO_URL},
    "swap": {"file": "inswapper_128.onnx", "urls": [
        "https://github.com/facefusion/facefusion-assets/releases/download/models-3.0.0/inswapper_128.onnx",
        "https://huggingface.co/ezioruan/inswapper_128.onnx/resolve/main/inswapper_128.onnx",
    ]},
    "enhance": {"file": "gfpgan_1.4.onnx", "urls": [
        "https://github.com/facefusion/facefusion-assets/releases/download/models-3.0.0/gfpgan_1.4.onnx",
    ]},
}
AI_FACE_URL = "https://thispersondoesnotexist.com/"

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".exr", ".webp")

ARCFACE_DST = np.array([[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
                        [41.5493, 92.3655], [70.7299, 92.2041]], dtype=np.float32)
FFHQ_512 = np.array([[0.37691676, 0.46864664], [0.62285697, 0.46912813], [0.50123859, 0.61331904],
                     [0.39308822, 0.72541100], [0.61150205, 0.72490465]], dtype=np.float32) * 512


class Cancelled(Exception):
    pass


def log(*a):
    print(time.strftime("[%H:%M:%S]"), *a, flush=True)


# --------------------------------------------------------------------------- téléchargements

def _download(url, dest, progress=None, headers=None):
    tmp = dest + ".part"
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "Mozilla/5.0 Anonymizer"})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress and total:
                progress(done / total)
    os.replace(tmp, dest)


def model_path(key):
    return os.path.join(MODELS_DIR, MODELS[key]["file"])


def ensure_models(keys, progress=None):
    """Télécharge les modèles manquants. progress(fraction, message)."""
    os.makedirs(MODELS_DIR, exist_ok=True)
    missing = [k for k in keys if not os.path.isfile(model_path(k))]
    for i, k in enumerate(missing):
        spec = MODELS[k]
        if os.path.isfile(model_path(k)):
            continue
        msg = "Téléchargement du modèle " + spec["file"]
        log(msg)
        step = lambda x, i=i: progress and progress((i + x) / len(missing), msg)
        if "zip" in spec:
            zpath = os.path.join(MODELS_DIR, "buffalo_l.zip")
            if not os.path.isfile(zpath):
                _download(spec["zip"], zpath, step)
            with zipfile.ZipFile(zpath) as z:
                for name in z.namelist():
                    base = os.path.basename(name)
                    if base in ("det_10g.onnx", "w600k_r50.onnx", "genderage.onnx"):
                        with z.open(name) as src, open(os.path.join(MODELS_DIR, base), "wb") as dst:
                            shutil.copyfileobj(src, dst)
            os.remove(zpath)
        else:
            last = None
            for url in spec["urls"]:
                try:
                    _download(url, model_path(k), step)
                    last = None
                    break
                except Exception as e:  # essaie le miroir suivant
                    last = e
                    log("  échec sur", url, ":", e)
            if last is not None:
                raise RuntimeError("Impossible de télécharger %s : %s" % (spec["file"], last))


def _fetch(url, referer=None):
    h = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0 Safari/537.36",
         "Accept": "image/avif,image/webp,image/jpeg,image/png,text/html;q=0.8,*/*;q=0.5"}
    if referer:
        h["Referer"] = referer
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30) as r:
        return r.read(), r.headers.get("Content-Type", ""), r.geturl()


def _decode_portrait(data):
    """L'image décodée si `data` est bien une photo d'au moins 256 px, sinon None."""
    if len(data) < 10000:
        return None
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None or min(img.shape[:2]) < 256:
        return None
    return img


def _ai_face_bytes():
    """Un visage généré par IA. Le site renvoie parfois une page web au lieu de la photo :
    on cherche alors l'image dans la page."""
    data, ctype, final = b"", "", AI_FACE_URL
    for direct in (AI_FACE_URL + "random-person.jpeg", AI_FACE_URL):
        try:
            data, ctype, final = _fetch(direct, referer=AI_FACE_URL)
        except Exception:
            continue
        if _decode_portrait(data) is not None:
            return data
    html = data.decode("utf-8", "ignore")
    cands = re.findall(r'(?:src|href|content)=["\']([^"\']+?\.(?:jpe?g|png|webp)(?:\?[^"\']*)?)["\']', html, re.I)
    cands += re.findall(r'url\(\s*["\']?([^"\')]+?\.(?:jpe?g|png|webp)[^"\')]*)["\']?\s*\)', html, re.I)
    cands += re.findall(r'(https?://[^"\'\s)]+?\.(?:jpe?g|png|webp))', html, re.I)
    seen = set()
    for c in cands:
        url = urllib.parse.urljoin(final, c.replace("&amp;", "&"))
        if url in seen or "logo" in url.lower() or "icon" in url.lower():
            continue
        seen.add(url)
        try:
            img_data, _, _ = _fetch(url, referer=final)
        except Exception:
            continue
        if _decode_portrait(img_data) is not None:
            return img_data
    raise RuntimeError("le site n'a pas renvoyé de photo (%s, %d octets)" % (ctype or "?", len(data)))


def download_ai_faces(count, progress=None, cancel=None):
    """Récupère `count` visages générés par IA (StyleGAN) dans faces/. Chaque fichier est vérifié :
    seules de vraies photos sont gardées."""
    os.makedirs(FACES_DIR, exist_ok=True)
    got = 0
    errors = 0
    last = None
    while got < count and errors < 5:
        if cancel and cancel.is_set():
            raise Cancelled()
        try:
            data = _ai_face_bytes()
            ext = ".png" if data[:4] == b"\x89PNG" else (".webp" if data[8:12] == b"WEBP" else ".jpg")
            name = "ia_%s_%03d%s" % (time.strftime("%Y%m%d%H%M%S"), got, ext)
            with open(os.path.join(FACES_DIR, name), "wb") as f:
                f.write(data)
            got += 1
            errors = 0
            if progress:
                progress(got / count, "Visages IA téléchargés : %d/%d" % (got, count))
            time.sleep(1.1)  # le site renvoie un nouveau visage environ chaque seconde
        except Cancelled:
            raise
        except Exception as e:
            errors += 1
            last = e
            log("  visage IA :", e)
            time.sleep(1)
    if got == 0:
        raise RuntimeError("Impossible de télécharger des visages IA (%s). Mettez 6 à 10 portraits (JPG ou PNG, "
                           "un visage par image, hommes et femmes) dans %s" % (last, FACES_DIR))
    return got


# --------------------------------------------------------------------------- ONNX

def _providers(device):
    import onnxruntime as ort
    avail = ort.get_available_providers()
    if device == "cpu":
        return ["CPUExecutionProvider"]
    order = ["CUDAExecutionProvider", "DmlExecutionProvider", "CPUExecutionProvider"]
    return [p for p in order if p in avail] or ["CPUExecutionProvider"]


def _session(path, device):
    import onnxruntime as ort
    opts = ort.SessionOptions()
    opts.log_severity_level = 3
    provs = _providers(device)
    try:
        return ort.InferenceSession(path, sess_options=opts, providers=provs)
    except Exception as e:
        if provs != ["CPUExecutionProvider"]:
            log("GPU indisponible pour", os.path.basename(path), "->", e, "; passage au CPU")
            return ort.InferenceSession(path, sess_options=opts, providers=["CPUExecutionProvider"])
        raise


def _mean_std(path, default):
    """Même règle qu'InsightFace : certains modèles normalisent eux-mêmes leur entrée."""
    import onnx
    graph = onnx.load(path).graph
    sub = mul = False
    for nid, node in enumerate(graph.node[:8]):
        if node.name.startswith("Sub") or node.name.startswith("_minus"):
            sub = True
        if node.name.startswith("Mul") or node.name.startswith("_mul"):
            mul = True
        if nid < 3 and node.name == "bn_data":
            sub = mul = True
    return (0.0, 1.0) if (sub and mul) else default


def umeyama(src, dst):
    """Transformation de similarité src -> dst (comme skimage.SimilarityTransform)."""
    num, dim = src.shape
    src_mean, dst_mean = src.mean(0), dst.mean(0)
    sd, dd = src - src_mean, dst - dst_mean
    A = dd.T @ sd / num
    d = np.ones((dim,), dtype=np.float64)
    if np.linalg.det(A) < 0:
        d[dim - 1] = -1
    T = np.eye(dim + 1, dtype=np.float64)
    U, S, V = np.linalg.svd(A)
    rank = np.linalg.matrix_rank(A)
    if rank == 0:
        return None
    if rank == dim - 1:
        if np.linalg.det(U) * np.linalg.det(V) > 0:
            T[:dim, :dim] = U @ V
        else:
            s = d[dim - 1]
            d[dim - 1] = -1
            T[:dim, :dim] = U @ np.diag(d) @ V
            d[dim - 1] = s
    else:
        T[:dim, :dim] = U @ np.diag(d) @ V
    scale = 1.0 / sd.var(0).sum() * (S @ d)
    T[:dim, dim] = dst_mean - scale * (T[:dim, :dim] @ src_mean.T)
    T[:dim, :dim] *= scale
    return T[:2, :]


def norm_crop_matrix(kps, size):
    ratio = size / 112.0 if size % 112 == 0 else size / 128.0
    dst = ARCFACE_DST * ratio
    if size % 112 != 0:
        dst[:, 0] += 8.0 * ratio
    return umeyama(np.asarray(kps, np.float64), dst.astype(np.float64))


def norm_crop(img, kps, size):
    M = norm_crop_matrix(kps, size)
    return cv2.warpAffine(img, M, (size, size), borderValue=0.0), M


class Detector:
    """SCRFD (det_10g) : boîtes + 5 points (yeux, nez, coins de la bouche)."""

    def __init__(self, path, device):
        self.s = _session(path, device)
        self.inp = self.s.get_inputs()[0].name
        self.outs = [o.name for o in self.s.get_outputs()]
        self.size = 640
        self.fmc = 3
        self.strides = [8, 16, 32]
        self.anchors = 2
        self._centers = {}

    def detect(self, img, thresh=0.5, nms=0.4):
        h, w = img.shape[:2]
        S = self.size
        scale = min(S / w, S / h)
        nw, nh = int(round(w * scale)), int(round(h * scale))
        det = np.zeros((S, S, 3), np.uint8)
        det[:nh, :nw] = cv2.resize(img, (nw, nh))
        blob = cv2.dnn.blobFromImage(det, 1.0 / 128, (S, S), (127.5, 127.5, 127.5), swapRB=True)
        out = self.s.run(self.outs, {self.inp: blob})
        if out[0].ndim == 3:
            out = [o[0] for o in out]
        boxes, scores, kpss = [], [], []
        for i, st in enumerate(self.strides):
            sc = out[i].reshape(-1)
            bb = out[i + self.fmc].reshape(-1, 4) * st
            kp = out[i + self.fmc * 2].reshape(-1, 10) * st
            fh, fw = S // st, S // st
            key = (fh, fw, st)
            if key not in self._centers:
                c = np.stack(np.mgrid[:fh, :fw][::-1], axis=-1).astype(np.float32)
                c = (c * st).reshape(-1, 2)
                c = np.stack([c] * self.anchors, axis=1).reshape(-1, 2)
                self._centers[key] = c
            c = self._centers[key]
            pos = np.where(sc >= thresh)[0]
            if not len(pos):
                continue
            cc = c[pos]
            b = bb[pos]
            boxes.append(np.stack([cc[:, 0] - b[:, 0], cc[:, 1] - b[:, 1], cc[:, 0] + b[:, 2], cc[:, 1] + b[:, 3]], -1))
            k = kp[pos].reshape(-1, 5, 2) + cc[:, None, :]
            kpss.append(k)
            scores.append(sc[pos])
        if not boxes:
            return []
        boxes = np.concatenate(boxes) / scale
        kpss = np.concatenate(kpss) / scale
        scores = np.concatenate(scores)
        keep = self._nms(boxes, scores, nms)
        return [{"box": boxes[i].astype(float).tolist(), "kps": kpss[i].astype(float).tolist(), "score": float(scores[i])}
                for i in keep]

    @staticmethod
    def _nms(b, s, th):
        x1, y1, x2, y2 = b.T
        areas = (x2 - x1 + 1) * (y2 - y1 + 1)
        order = s.argsort()[::-1]
        keep = []
        while order.size:
            i = order[0]
            keep.append(i)
            xx1 = np.maximum(x1[i], x1[order[1:]])
            yy1 = np.maximum(y1[i], y1[order[1:]])
            xx2 = np.minimum(x2[i], x2[order[1:]])
            yy2 = np.minimum(y2[i], y2[order[1:]])
            inter = np.maximum(0, xx2 - xx1 + 1) * np.maximum(0, yy2 - yy1 + 1)
            ovr = inter / (areas[i] + areas[order[1:]] - inter)
            order = order[np.where(ovr <= th)[0] + 1]
        return keep


class Recognizer:
    """ArcFace (w600k_r50) : empreinte 512-D normalisée."""

    def __init__(self, path, device):
        self.s = _session(path, device)
        self.inp = self.s.get_inputs()[0].name
        self.mean, self.std = _mean_std(path, (127.5, 127.5))

    def embed(self, img, kps):
        crop, _ = norm_crop(img, kps, 112)
        blob = cv2.dnn.blobFromImage(crop, 1.0 / self.std, (112, 112), (self.mean,) * 3, swapRB=True)
        v = self.s.run(None, {self.inp: blob})[0][0]
        return v / (np.linalg.norm(v) + 1e-9)


class GenderAge:
    def __init__(self, path, device):
        self.s = _session(path, device)
        self.inp = self.s.get_inputs()[0].name
        self.size = 96
        self.mean, self.std = _mean_std(path, (127.5, 128.0))

    def predict(self, img, box):
        x1, y1, x2, y2 = box
        w, h = x2 - x1, y2 - y1
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        s = self.size / (max(w, h) * 1.5)
        M = np.array([[s, 0, self.size / 2 - cx * s], [0, s, self.size / 2 - cy * s]], np.float32)
        crop = cv2.warpAffine(img, M, (self.size, self.size), borderValue=0.0)
        blob = cv2.dnn.blobFromImage(crop, 1.0 / self.std, (self.size, self.size), (self.mean,) * 3, swapRB=True)
        p = self.s.run(None, {self.inp: blob})[0][0]
        return ("M" if int(np.argmax(p[:2])) == 1 else "F"), float(p[2] * 100)


class Swapper:
    """inswapper_128 : remplace le visage cible par l'identité d'une empreinte ArcFace."""

    def __init__(self, path, device):
        import onnx
        from onnx import numpy_helper
        self.emap = numpy_helper.to_array(onnx.load(path).graph.initializer[-1])
        self.s = _session(path, device)
        ins = self.s.get_inputs()
        self.in_target, self.in_source = ins[0].name, ins[1].name

    def latent(self, embedding):
        l = embedding.reshape(1, -1) @ self.emap
        return (l / np.linalg.norm(l)).astype(np.float32)

    def swap(self, img, kps, latent):
        crop, M = norm_crop(img, kps, 128)
        blob = cv2.dnn.blobFromImage(crop, 1.0 / 255, (128, 128), (0, 0, 0), swapRB=True)
        pred = self.s.run(None, {self.in_target: blob, self.in_source: latent})[0]
        fake = np.clip(255 * pred.transpose(0, 2, 3, 1)[0], 0, 255).astype(np.uint8)[:, :, ::-1]
        return fake, M


class Enhancer:
    """GFPGAN 1.4 : restaure un visage net en 512 px (le swap sort en 128 px)."""

    def __init__(self, path, device):
        self.s = _session(path, device)
        self.inp = self.s.get_inputs()[0].name

    def enhance(self, img, kps):
        M = umeyama(np.asarray(kps, np.float64), FFHQ_512.astype(np.float64))
        crop = cv2.warpAffine(img, M, (512, 512), borderMode=cv2.BORDER_REPLICATE)
        x = crop[:, :, ::-1].astype(np.float32) / 255.0
        x = ((x - 0.5) / 0.5).transpose(2, 0, 1)[None]
        y = self.s.run(None, {self.inp: x})[0][0]
        y = np.clip((y.transpose(1, 2, 0) + 1) / 2, 0, 1)
        return (y[:, :, ::-1] * 255).round().astype(np.uint8), M


# --------------------------------------------------------------------------- vidéo

class FrameSource:
    """Lit une vidéo ou une séquence d'images image par image (index source à partir de 0)."""

    def __init__(self, path):
        self.path = path
        self.files = None
        self.cap = None
        self.pos = 0
        ext = os.path.splitext(path)[1].lower()
        if os.path.isdir(path):
            self.files = sorted([os.path.join(path, f) for f in os.listdir(path) if f.lower().endswith(IMAGE_EXT)],
                                key=_natural)
        elif ext in IMAGE_EXT:
            self.files = _sequence_of(path)
        if self.files is not None:
            if not self.files:
                raise RuntimeError("Aucune image trouvée pour " + path)
            first = _imread(self.files[0])
            self.height, self.width = first.shape[:2]
            self.count = len(self.files)
            self.fps = 0.0
        else:
            self.cap = cv2.VideoCapture(path)
            if not self.cap.isOpened():
                raise RuntimeError("OpenCV ne sait pas lire " + path)
            self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self.count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
            self.fps = float(self.cap.get(cv2.CAP_PROP_FPS) or 0)

    def frames(self, start, end, stride=1):
        """Itère (index, image BGR) pour start <= index <= end, une image sur `stride`.

        Les images sautées ne sont pas décodées en vidéo (grab sans retrieve) : c'est bien plus rapide."""
        stride = max(1, int(stride))
        if self.files is not None:
            for i in range(max(0, start), min(end, self.count - 1) + 1, stride):
                yield i, _imread(self.files[i])
            return
        if start < self.pos:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            self.pos = 0
        if start > self.pos + 1:
            # Saut approximatif puis lecture exacte : les codecs inter-images se positionnent mal.
            target = max(0, start - 30)
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, target)
            got = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))
            self.pos = got if 0 <= got <= target else 0
            if self.pos == 0:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        while self.pos < start:
            if not self.cap.grab():
                return
            self.pos += 1
        while self.pos <= end:
            if (self.pos - start) % stride:
                if not self.cap.grab():
                    return
            else:
                ok, img = self.cap.read()
                if not ok:
                    return
                yield self.pos, img
            self.pos += 1

    def close(self):
        if self.cap is not None:
            self.cap.release()


def _natural(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def _sequence_of(path):
    d, name = os.path.split(path)
    m = re.match(r"^(.*?)(\d+)(\.[^.]+)$", name)
    if not m:
        return [path]
    pre, ext = m.group(1), m.group(3)
    pat = re.compile("^" + re.escape(pre) + r"\d+" + re.escape(ext) + "$", re.I)
    files = [os.path.join(d, f) for f in os.listdir(d or ".") if pat.match(f)]
    return sorted(files, key=_natural)


def _imread(p):
    img = cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_UNCHANGED)  # chemins avec accents
    if img is None:
        raise RuntimeError("Image illisible : " + p)
    if img.dtype != np.uint8:
        img = np.clip(img.astype(np.float32) * (255.0 if img.dtype.kind == "f" else 255.0 / np.iinfo(img.dtype).max), 0, 255).astype(np.uint8)
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    elif img.shape[2] == 4:
        img = img[:, :, :3]
    return np.ascontiguousarray(img)


def _imwrite(p, img):
    ok, buf = cv2.imencode(os.path.splitext(p)[1], img, [cv2.IMWRITE_PNG_COMPRESSION, 3])
    if not ok:
        raise RuntimeError("Écriture impossible : " + p)
    buf.tofile(p)


# --------------------------------------------------------------------------- suivi des visages

def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0.0


class Track:
    def __init__(self, tid):
        self.id = tid
        self.frames = {}          # index -> {"box", "kps", "score"}
        self.emb_sum = None
        self.emb_n = 0
        self.emb_last = -10 ** 9
        self.last = -1
        self.vel = np.zeros(4)
        self.genders = []
        self.ages = []
        self.ga_last = -10 ** 9

    @property
    def embedding(self):
        return None if self.emb_sum is None else self.emb_sum / (np.linalg.norm(self.emb_sum) + 1e-9)

    def add_embedding(self, e, f):
        self.emb_sum = e.copy() if self.emb_sum is None else self.emb_sum + e
        self.emb_n += 1
        self.emb_last = f

    def predict(self, f):
        b = np.array(self.frames[self.last]["box"])
        return (b + self.vel * (f - self.last)).tolist()

    def add(self, f, det):
        if self.last >= 0 and f > self.last:
            nb, ob = np.array(det["box"]), np.array(self.frames[self.last]["box"])
            self.vel = 0.6 * self.vel + 0.4 * (nb - ob) / (f - self.last)
        self.frames[f] = det
        self.last = f


def analyze(src, start, end, p, models, progress, cancel):
    """Détection + suivi. Renvoie la liste des pistes brutes."""
    det, rec, ga = models["det"], models["rec"], models["genderage"]
    tracks = []
    max_gap = int(p.get("maxGap", 12))
    reid = float(p.get("reidThreshold", 0.42))
    min_size = float(p.get("minFace", 16))
    total = max(1, end - start + 1)
    stride = max(1, int(p.get("detectStride", 1)))
    for f, img in src.frames(start, end, stride):
        if cancel.is_set():
            raise Cancelled()
        dets = [d for d in det.detect(img, float(p.get("threshold", 0.5)))
                if min(d["box"][2] - d["box"][0], d["box"][3] - d["box"][1]) >= min_size]
        active = [t for t in tracks if f - t.last <= max_gap]
        pairs = []
        for di, d in enumerate(dets):
            for t in active:
                v = iou(d["box"], t.predict(f))
                if v > 0.25:
                    pairs.append((v, di, t))
        pairs.sort(key=lambda x: -x[0])
        used_d, used_t, assign = set(), set(), {}
        for v, di, t in pairs:
            if di in used_d or t.id in used_t:
                continue
            used_d.add(di)
            used_t.add(t.id)
            assign[di] = t
        for di, d in enumerate(dets):
            t = assign.get(di)
            need_emb = t is None or f - t.emb_last >= 15 or t.emb_n < 3
            e = rec.embed(img, d["kps"]) if need_emb else None
            if t is None:
                best, bs = None, reid
                for c in tracks:
                    if c.id in used_t or c.embedding is None:
                        continue
                    s = float(np.dot(e, c.embedding))
                    if s > bs:
                        best, bs = c, s
                if best is None:
                    best = Track(len(tracks))
                    tracks.append(best)
                t = best
                used_t.add(t.id)
            if e is not None:
                t.add_embedding(e, f)
            if len(t.genders) < 25 and f - t.ga_last >= 5:
                g, a = ga.predict(img, d["box"])
                t.genders.append(g)
                t.ages.append(a)
                t.ga_last = f
            t.add(f, d)
        progress((f - start + 1) / total, "Analyse : image %d/%d, %d visage(s) suivi(s)" % (f - start + 1, total, len(tracks)))
    return tracks


def _smooth(arr, radius):
    if radius <= 0 or len(arr) < 3:
        return arr
    out = np.empty_like(arr)
    n = len(arr)
    for i in range(n):
        a, b = max(0, i - radius), min(n, i + radius + 1)
        r = min(i - a, b - 1 - i)  # fenêtre symétrique : pas de dérive aux extrémités
        out[i] = arr[i - r:i + r + 1].mean(0)
    return out


def _key_reduce(values, tol):
    """Indices à garder pour qu'une interpolation linéaire reste à moins de `tol` pixels."""
    n = len(values)
    if n <= 2:
        return list(range(n))
    keep = [0]
    a = 0
    i = 2
    while i < n:
        seg = values[a:i + 1]
        t = np.linspace(0, 1, len(seg))[:, None]
        lin = seg[0] * (1 - t) + seg[-1] * t
        if np.abs(seg - lin).max() > tol:
            keep.append(i - 1)
            a = i - 1
        i += 1
    keep.append(n - 1)
    return keep


def finalize_tracks(raw, p, start, end):
    """Bouche les trous, lisse, découpe en segments et choisit les images clés des masques."""
    # sur une plage très courte (test sur quelques images), on garde toutes les détections
    stride = max(1, int(p.get("detectStride", 1)))
    min_frames = min(max(1, int(p.get("minFrames", 4)) // stride), max(1, (end - start + 1) // (2 * stride)))
    fill = int(p.get("fillGap", 8))
    radius = int(p.get("smooth", 2))
    tol = float(p.get("keyTolerance", 1.5))
    out = []
    for t in raw:
        if len(t.frames) < min_frames:
            continue
        fs = sorted(t.frames)
        # segments continus, les trous courts sont interpolés
        segs, cur = [], [fs[0]]
        for f in fs[1:]:
            if f - cur[-1] <= fill + 1:
                cur.append(f)
            else:
                segs.append(cur)
                cur = [f]
        segs.append(cur)
        seg_out = []
        for s in segs:
            full = list(range(s[0], s[-1] + 1))
            known = np.array(s)
            box = np.array([t.frames[f]["box"] for f in s])
            kps = np.array([t.frames[f]["kps"] for f in s]).reshape(len(s), 10)
            B = np.stack([np.interp(full, known, box[:, j]) for j in range(4)], 1)
            K = np.stack([np.interp(full, known, kps[:, j]) for j in range(10)], 1)
            B, K = _smooth(B, radius), _smooth(K, radius)
            keys = _key_reduce(B, tol)
            seg_out.append({
                "start": full[0], "end": full[-1],
                "box": np.round(B, 2).tolist(),
                "kps": np.round(K, 2).reshape(-1, 5, 2).tolist(),
                "detected": [1 if f in t.frames else 0 for f in full],
                "keys": keys,
            })
        g = "M" if t.genders.count("M") >= t.genders.count("F") else "F"
        age = float(np.median(t.ages)) if t.ages else 35.0
        out.append({"id": len(out) + 1, "gender": g, "age": round(age, 1), "segments": seg_out,
                    "frames": sum(len(s["box"]) for s in seg_out),
                    "embedding": t.embedding.round(5).tolist() if t.embedding is not None else None})
    return out


# --------------------------------------------------------------------------- visages IA

class FacePool:
    def __init__(self, models):
        self.models = models
        self.index_path = os.path.join(FACES_DIR, "index.json")
        try:
            with open(self.index_path, "r", encoding="utf-8") as f:
                self.index = json.load(f)
        except Exception:
            self.index = {}

    def refresh(self):
        os.makedirs(FACES_DIR, exist_ok=True)
        changed = False
        files = [f for f in os.listdir(FACES_DIR) if f.lower().endswith(IMAGE_EXT)]
        for name in files:
            p = os.path.join(FACES_DIR, name)
            stamp = "%d-%d" % (os.path.getsize(p), int(os.path.getmtime(p)))
            e = self.index.get(name)
            # v2 : vérification d'image + marge ; les entrées d'une ancienne version sont refaites une fois
            if e and e.get("stamp") == stamp and e.get("v") == 2:
                continue
            try:
                with open(p, "rb") as fh:
                    head = fh.read(512)
                if head.lstrip()[:1] == b"<" or cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR) is None:
                    # pas une image (page web enregistrée par une ancienne version) : mise de côté
                    bad = os.path.join(FACES_DIR, "_invalides")
                    os.makedirs(bad, exist_ok=True)
                    os.replace(p, os.path.join(bad, name))
                    self.index.pop(name, None)
                    changed = True
                    continue
                img = _imread(p)
                # Un portrait serré (visage qui remplit le cadre) est mal noté par le détecteur :
                # on le pose au centre d'un cadre deux fois plus grand.
                h, w = img.shape[:2]
                img = cv2.copyMakeBorder(img, h // 2, h // 2, w // 2, w // 2, cv2.BORDER_CONSTANT, value=(0, 0, 0))
                dets = self.models["det"].detect(img, 0.5)
                if not dets:
                    self.index[name] = {"stamp": stamp, "ok": False, "v": 2}
                else:
                    d = max(dets, key=lambda d: (d["box"][2] - d["box"][0]) * (d["box"][3] - d["box"][1]))
                    g, a = self.models["genderage"].predict(img, d["box"])
                    emb = self.models["rec"].embed(img, d["kps"])
                    self.index[name] = {"stamp": stamp, "ok": True, "v": 2, "gender": g, "age": round(a, 1),
                                        "embedding": emb.round(6).tolist()}
            except Exception as ex:
                self.index[name] = {"stamp": stamp, "ok": False, "v": 2, "error": str(ex)}
            changed = True
        for name in list(self.index):
            if name not in files:
                del self.index[name]
                changed = True
        if changed:
            with open(self.index_path, "w", encoding="utf-8") as f:
                json.dump(self.index, f)
        return [(n, e) for n, e in self.index.items() if e.get("ok")]

    def assign(self, tracks, seed, match):
        faces = self.refresh()
        if not faces:
            raise RuntimeError("Aucun visage source dans " + FACES_DIR)
        rng = random.Random(seed)
        used = set()
        out = {}
        for t in tracks:
            cands = [(n, e) for n, e in faces if n not in used] or faces
            if match:
                # même genre d'abord ; si tous ont servi, on réutilise un visage du même genre
                same = ([(n, e) for n, e in cands if e["gender"] == t["gender"]]
                        or [(n, e) for n, e in faces if e["gender"] == t["gender"]] or cands)
                same.sort(key=lambda ne: abs(ne[1]["age"] - t["age"]))
                pick = rng.choice(same[:3])
            else:
                pick = rng.choice(cands)
            used.add(pick[0])
            out[t["id"]] = pick
        return out

    def count_by_gender(self):
        faces = self.refresh()
        return {"F": sum(1 for _, e in faces if e["gender"] == "F"), "M": sum(1 for _, e in faces if e["gender"] == "M")}


# --------------------------------------------------------------------------- rendu du swap

def _paste(canvas, fake, M, erode=1.0, blur=1.0):
    """Colle `fake` (espace aligné) dans le canevas BGRA (alpha droit) avec un masque adouci."""
    H, W = canvas.shape[:2]
    n = fake.shape[0]
    IM = cv2.invertAffineTransform(M)
    corners = np.array([[0, 0, 1], [n, 0, 1], [0, n, 1], [n, n, 1]], np.float64) @ IM.T
    size = math.sqrt(max(1.0, cv2.contourArea(corners[[0, 1, 3, 2]].astype(np.float32))))
    pad = int(size * 0.1) + 4
    x0, y0 = int(max(0, math.floor(corners[:, 0].min()) - pad)), int(max(0, math.floor(corners[:, 1].min()) - pad))
    x1, y1 = int(min(W, math.ceil(corners[:, 0].max()) + pad)), int(min(H, math.ceil(corners[:, 1].max()) + pad))
    if x1 <= x0 or y1 <= y0:
        return
    IMr = IM.copy()
    IMr[:, 2] -= (x0, y0)
    w, h = x1 - x0, y1 - y0
    face = cv2.warpAffine(fake, IMr, (w, h), borderValue=0.0)
    white = cv2.warpAffine(np.full((n, n), 255, np.float32), IMr, (w, h), borderValue=0.0)
    white[white > 20] = 255
    k = max(int(size * 0.1 * erode), 3)
    white = cv2.erode(white, np.ones((k, k), np.uint8), iterations=1)
    b = max(int(size * 0.05 * blur), 3)
    white = cv2.GaussianBlur(white, (2 * b + 1, 2 * b + 1), 0)
    a = (white / 255.0)[:, :, None]
    roi = canvas[y0:y1, x0:x1].astype(np.float32)
    A0 = roi[:, :, 3:4] / 255.0
    A = a + A0 * (1 - a)
    C = (face.astype(np.float32) * a + roi[:, :, :3] * A0 * (1 - a)) / np.maximum(A, 1e-6)
    roi[:, :, :3] = C
    roi[:, :, 3:4] = A * 255
    canvas[y0:y1, x0:x1] = np.clip(roi + 0.5, 0, 255).astype(np.uint8)


def _match_color(fake, crop, mask_border=0.15):
    """Ajuste la moyenne/écart-type des couleurs du visage généré sur le visage d'origine (en Lab)."""
    n = fake.shape[0]
    m = int(n * mask_border)
    a = cv2.cvtColor(fake, cv2.COLOR_BGR2LAB).astype(np.float32)
    b = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB).astype(np.float32)
    ca, cb = a[m:n - m, m:n - m].reshape(-1, 3), b[m:n - m, m:n - m].reshape(-1, 3)
    a = (a - ca.mean(0)) / (ca.std(0) + 1e-6) * cb.std(0) + cb.mean(0)
    return cv2.cvtColor(np.clip(a, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)


def _cover(canvas, img, box):
    """Dépose sous le visage une version très floutée (tache de peau) de la zone d'origine.

    Même si le remplacement rate (visage coupé par le bord, de profil, très petit), les vrais pixels du
    visage ne sont jamais conservés sous le flou : il n'en reste qu'une tache de couleur sans détail."""
    H, W = canvas.shape[:2]
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    if w < 4 or h < 4:
        return
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    rx, ry = w * 0.62, h * 0.70
    X1, Y1 = int(max(0, math.floor(cx - rx * 1.4))), int(max(0, math.floor(cy - ry * 1.4)))
    X2, Y2 = int(min(W, math.ceil(cx + rx * 1.4))), int(min(H, math.ceil(cy + ry * 1.4)))
    if X2 - X1 < 4 or Y2 - Y1 < 4:
        return
    k = max(3, int(min(w, h) * 0.5)) | 1
    blur = cv2.GaussianBlur(img[Y1:Y2, X1:X2], (k, k), 0, borderType=cv2.BORDER_REPLICATE)
    m = np.zeros((Y2 - Y1, X2 - X1), np.float32)
    cv2.ellipse(m, (int(round(cx - X1)), int(round(cy - Y1))), (max(1, int(rx)), max(1, int(ry))), 0, 0, 360, 1.0, -1)
    e = max(3, int(min(w, h) * 0.12)) | 1
    m = cv2.GaussianBlur(m, (e, e), 0)[:, :, None]
    roi = canvas[Y1:Y2, X1:X2].astype(np.float32)
    A0 = roi[:, :, 3:4] / 255.0
    A = m + A0 * (1 - m)
    C = (blur.astype(np.float32) * m + roi[:, :, :3] * A0 * (1 - m)) / np.maximum(A, 1e-6)
    roi[:, :, :3] = C
    roi[:, :, 3:4] = A * 255
    canvas[Y1:Y2, X1:X2] = np.clip(roi + 0.5, 0, 255).astype(np.uint8)


def render_swap(src, tracks, assignment, p, models, out_dir, progress, cancel):
    os.makedirs(out_dir, exist_ok=True)
    swapper, enhancer = models["swap"], models.get("enhance")
    latents = {}
    for t in tracks:
        name, e = assignment[t["id"]]
        latents[t["id"]] = swapper.latent(np.array(e["embedding"], np.float32))
    by_frame = {}
    for t in tracks:
        for s in t["segments"]:
            for i, kp in enumerate(s["kps"]):
                by_frame.setdefault(s["start"] + i, []).append((t["id"], kp, s["box"][i]))
    start, end = p["start"], p["end"]
    total = max(1, end - start + 1)
    blank = None
    color = bool(p.get("colorMatch", True))
    first = None
    # Pas du swap : le réseau ne tourne que sur 1 image sur `stride` pour chaque personne ; entre deux,
    # le dernier visage généré est recollé à la position suivie. Sous un flou ou une pixelisation,
    # la différence est invisible et le calcul est `stride` fois plus court.
    stride = max(1, int(p.get("swapStride", 1)))
    if stride > 1 and enhancer is not None:
        enhancer = None  # la restauration HD n'a pas de sens avec un visage réutilisé
    cover = bool(p.get("cover", False))
    cache = {}
    pool = ThreadPoolExecutor(max_workers=2)
    pending = []

    def write(path, arr):
        pending.append(pool.submit(_imwrite, path, arr))
        while len(pending) > 6:
            pending.pop(0).result()

    for f, img in src.frames(start, end):
        if cancel.is_set():
            pool.shutdown(wait=False, cancel_futures=True)
            raise Cancelled()
        H, W = img.shape[:2]
        canvas = np.zeros((H, W, 4), np.uint8)
        if cover:
            for tid, kp, box in by_frame.get(f, []):
                _cover(canvas, img, box)
        for tid, kp, box in by_frame.get(f, []):
            hit = cache.get(tid)
            if stride > 1 and hit is not None and f - hit[0] < stride:
                crop_M = norm_crop_matrix(kp, 128)
                _paste(canvas, hit[1], crop_M)
                continue
            fake, M = swapper.swap(img, kp, latents[tid])
            if color:
                crop = cv2.warpAffine(img, M, (128, 128), borderValue=0.0)
                fake = _match_color(fake, crop)
            if stride > 1:
                cache[tid] = (f, fake)
            if enhancer is not None:
                # Le visage échangé est d'abord recollé dans l'image, puis restauré en 512 px.
                tmp = img.copy()
                full = np.zeros((H, W, 4), np.uint8)
                _paste(full, fake, M)
                al = full[:, :, 3:4].astype(np.float32) / 255
                tmp = (full[:, :, :3] * al + tmp * (1 - al)).astype(np.uint8)
                kps_arr = np.asarray(kp, np.float64)
                hd, M2 = enhancer.enhance(tmp, kps_arr)
                blend = float(p.get("enhanceBlend", 80)) / 100.0
                base = cv2.warpAffine(tmp, M2, (512, 512), borderMode=cv2.BORDER_REPLICATE)
                hd = cv2.addWeighted(hd, blend, base, 1 - blend, 0)
                _paste(canvas, hd, M2, erode=0.9, blur=1.0)
            else:
                _paste(canvas, fake, M)
        path = os.path.join(out_dir, "anon_%06d.png" % f)
        if not by_frame.get(f):
            if blank is None or blank.shape[:2] != (H, W):
                blank = np.zeros((H, W, 4), np.uint8)
            write(path, blank)
        else:
            write(path, canvas)
        if first is None:
            first = path
        progress((f - start + 1) / total, "Visages IA : image %d/%d" % (f - start + 1, total))
    for fut in pending:
        fut.result()
    pool.shutdown()
    return first


# --------------------------------------------------------------------------- travaux

class Engine:
    def __init__(self, device="auto"):
        self.device = device
        self.models = {}
        self.lock = threading.Lock()

    def load(self, keys, progress):
        ensure_models(keys, lambda x, m: progress(x, m))
        cls = {"det": Detector, "rec": Recognizer, "genderage": GenderAge, "swap": Swapper, "enhance": Enhancer}
        for k in keys:
            if k not in self.models:
                progress(1.0, "Chargement du modèle " + MODELS[k]["file"])
                self.models[k] = cls[k](model_path(k), self.device)
        return self.models

    def providers(self):
        try:
            return _providers(self.device)
        except Exception:
            return []


def _cache_key(p):
    path = p["input"]
    try:
        st = os.stat(path)
        stamp = "%d-%d" % (st.st_size, int(st.st_mtime))
    except OSError:
        stamp = "?"
    keys = ["threshold", "minFace", "maxGap", "reidThreshold", "minFrames", "fillGap", "smooth", "keyTolerance", "detectStride"]
    raw = json.dumps([os.path.abspath(path), stamp, p["start"], p["end"], [p.get(k) for k in keys], VERSION])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def run_job(engine, p, progress, cancel):
    """Un traitement complet. `p` vient du panneau (voir Anonymizer.jsx, startJob)."""
    t0 = time.time()
    src = FrameSource(p["input"])
    try:
        p["start"] = max(0, int(p.get("start", 0)))
        p["end"] = int(p.get("end", src.count - 1))
        if src.count > 0:
            p["end"] = min(p["end"], src.count - 1)
        if p["end"] < p["start"]:
            raise RuntimeError("Plage d'images vide (%d à %d)" % (p["start"], p["end"]))
        out_dir = p.get("outDir") or os.path.join(OUTPUT_DIR, time.strftime("%Y%m%d_%H%M%S"))
        os.makedirs(out_dir, exist_ok=True)
        swap = bool(p.get("swap"))
        keys = ["det", "rec", "genderage"] + (["swap"] if swap else []) + (["enhance"] if swap and p.get("enhance") else [])
        with engine.lock:
            models = engine.load(keys, lambda x, m: progress(0.0, m))
            os.makedirs(CACHE_DIR, exist_ok=True)
            cpath = os.path.join(CACHE_DIR, _cache_key(p) + ".json")
            tracks = None
            if not p.get("reanalyze") and os.path.isfile(cpath):
                with open(cpath, "r", encoding="utf-8") as f:
                    tracks = json.load(f)
                progress(0.5 if swap else 1.0, "Analyse réutilisée (%d visage(s))" % len(tracks))
            if tracks is None:
                span = 0.5 if swap else 1.0
                raw = analyze(src, p["start"], p["end"], p, models, lambda x, m: progress(x * span, m), cancel)
                tracks = finalize_tracks(raw, p, p["start"], p["end"])
                with open(cpath, "w", encoding="utf-8") as f:
                    json.dump(tracks, f)
            result = {"width": src.width, "height": src.height, "fps": src.fps, "start": p["start"], "end": p["end"],
                      "input": p["input"], "tracks": tracks, "swapDir": None, "swapFirst": None, "assignment": {}}
            if swap and tracks:
                pool = FacePool(models)
                have = pool.count_by_gender()
                needF = sum(1 for t in tracks if t["gender"] == "F")
                needM = sum(1 for t in tracks if t["gender"] == "M")
                if p.get("autoFaces", True) and (have["F"] < max(needF, 2) or have["M"] < max(needM, 2)):
                    want = max(8, 2 * len(tracks))
                    progress(0.5, "Téléchargement de visages IA…")
                    try:
                        download_ai_faces(want, lambda x, m: progress(0.5, m), cancel)
                    except Cancelled:
                        raise
                    except Exception as e:
                        if not pool.refresh():
                            raise
                        log("Visages IA :", e)
                assignment = pool.assign(tracks, int(p.get("seed", 1)), bool(p.get("matchFaces", True)))
                swap_dir = os.path.join(out_dir, "visages_ia")
                if os.path.isdir(swap_dir):
                    for old in glob.glob(os.path.join(swap_dir, "anon_*.png")):
                        os.remove(old)
                first = render_swap(src, tracks, assignment, p, models, swap_dir,
                                    lambda x, m: progress(0.5 + 0.5 * x, m), cancel)
                result["swapDir"] = swap_dir
                result["swapFirst"] = first
                result["assignment"] = {str(k): v[0] for k, v in assignment.items()}
            for t in result["tracks"]:
                t.pop("embedding", None)
            rpath = os.path.join(out_dir, "pistes.json")
            with open(rpath, "w", encoding="utf-8") as f:
                json.dump(result, f)
            log("Terminé en %.1f s : %d visage(s), résultat %s" % (time.time() - t0, len(tracks), rpath))
            return {"tracksFile": rpath, "faces": len(tracks), "swapFirst": result["swapFirst"], "seconds": round(time.time() - t0, 1)}
    finally:
        src.close()


class JobQueue:
    def __init__(self, engine):
        self.engine = engine
        self.jobs = {}
        self.q = queue.Queue()
        self.n = 0
        self.mutex = threading.Lock()
        threading.Thread(target=self._worker, daemon=True).start()

    def submit(self, kind, params):
        with self.mutex:
            self.n += 1
            jid = "job%d" % self.n
            self.jobs[jid] = {"id": jid, "kind": kind, "state": "queued", "progress": 0.0, "message": "En attente…",
                              "result": None, "error": None, "cancel": threading.Event()}
        self.q.put((jid, kind, params))
        return jid

    def status(self, jid):
        j = self.jobs.get(jid)
        if not j:
            return None
        return {k: v for k, v in j.items() if k != "cancel"}

    def cancel(self, jid):
        j = self.jobs.get(jid)
        if j:
            j["cancel"].set()
        return bool(j)

    def _worker(self):
        while True:
            jid, kind, p = self.q.get()
            j = self.jobs[jid]
            if j["cancel"].is_set():
                j["state"] = "cancelled"
                continue
            j["state"] = "running"

            def progress(x, msg, j=j):
                j["progress"] = round(float(min(max(x, 0), 1)), 4)
                j["message"] = msg

            try:
                if kind == "anonymize":
                    log("Traitement :", p.get("input"))
                    j["result"] = run_job(self.engine, p, progress, j["cancel"])
                elif kind == "setup":
                    keys = ["det", "rec", "genderage", "swap"] + (["enhance"] if p.get("enhance", True) else [])
                    ensure_models(keys, progress)
                    j["result"] = {"models": keys}
                elif kind == "faces":
                    with self.engine.lock:
                        n = download_ai_faces(int(p.get("count", 16)), progress, j["cancel"])
                        models = self.engine.load(["det", "rec", "genderage"], progress)
                        counts = FacePool(models).count_by_gender()
                    j["result"] = {"downloaded": n, "pool": counts}
                j["state"] = "done"
                j["progress"] = 1.0
                j["message"] = "Terminé"
            except Cancelled:
                j["state"] = "cancelled"
                j["message"] = "Annulé"
                log("Annulé :", jid)
            except Exception as e:
                j["state"] = "error"
                j["error"] = str(e)
                j["message"] = "Erreur : %s" % e
                traceback.print_exc()


def models_ready():
    return {k: os.path.isfile(model_path(k)) for k in MODELS}


def handle(jobs, req):
    cmd = req.get("cmd")
    if cmd == "ping":
        n = len([f for f in os.listdir(FACES_DIR) if f.lower().endswith(IMAGE_EXT)]) if os.path.isdir(FACES_DIR) else 0
        return {"ok": True, "version": VERSION, "providers": jobs.engine.providers(), "models": models_ready(),
                "faces": n, "facesDir": FACES_DIR, "outputDir": OUTPUT_DIR}
    if cmd in ("anonymize", "setup", "faces"):
        p = req.get("params") or {}
        if cmd == "anonymize":
            if not p.get("input") or not os.path.exists(p["input"]):
                return {"ok": False, "error": "Fichier source introuvable : %s" % p.get("input")}
        return {"ok": True, "job": jobs.submit(cmd, p)}
    if cmd in ("status", "wait"):
        jid = req.get("job")
        if cmd == "wait":
            # Attente longue : répond dès que le travail se termine, ou après `timeout` secondes.
            # Le panneau s'en sert quand EffectCraft ne déclenche pas les tâches répétées.
            end = time.time() + min(float(req.get("timeout", 10)), 60)
            while time.time() < end:
                s = jobs.status(jid)
                if not s or s["state"] not in ("queued", "running"):
                    break
                time.sleep(0.2)
        s = jobs.status(jid)
        return {"ok": True, "job": s} if s else {"ok": False, "error": "Travail inconnu"}
    if cmd == "cancel":
        return {"ok": jobs.cancel(req.get("job"))}
    return {"ok": False, "error": "Commande inconnue : %s" % cmd}


def _disable_quick_edit():
    """Windows : un clic dans la console active la « Sélection », ce qui fige le moteur. On la coupe."""
    if os.name != "nt":
        return
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        mode = ctypes.c_uint32()
        if k32.GetConsoleMode(h, ctypes.byref(mode)):
            # ENABLE_EXTENDED_FLAGS (0x80) sans ENABLE_QUICK_EDIT_MODE (0x40)
            k32.SetConsoleMode(h, (mode.value | 0x80) & ~0x40)
    except Exception:
        pass


def serve(port, device):
    _disable_quick_edit()
    jobs = JobQueue(Engine(device))

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            for line in self.rfile:
                line = line.strip()
                if not line:
                    continue
                try:
                    resp = handle(jobs, json.loads(line.decode("utf-8")))
                except Exception as e:
                    resp = {"ok": False, "error": str(e)}
                self.wfile.write((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
                self.wfile.flush()

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    with Server((HOST, port), Handler) as srv:
        log("Anonymizer %s : moteur prêt sur %s:%d (exécution : %s)" % (VERSION, HOST, port, ", ".join(_providers(device))))
        log("Laissez cette fenêtre ouverte pendant que vous utilisez le panneau dans EffectCraft.")
        srv.serve_forever()


def main():
    ap = argparse.ArgumentParser(description="Anonymizer pour EffectCraft : moteur IA local")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=PORT)
    s.add_argument("--device", default="auto", choices=["auto", "cpu"])
    st = sub.add_parser("setup")
    st.add_argument("--no-enhance", action="store_true")
    fc = sub.add_parser("faces")
    fc.add_argument("--count", type=int, default=24)
    r = sub.add_parser("run")
    r.add_argument("--input", required=True)
    r.add_argument("--out", default="")
    r.add_argument("--start", type=int, default=0)
    r.add_argument("--end", type=int, default=10 ** 9)
    r.add_argument("--swap", action="store_true")
    r.add_argument("--enhance", action="store_true")
    r.add_argument("--seed", type=int, default=1)
    r.add_argument("--threshold", type=float, default=0.5)
    r.add_argument("--device", default="auto", choices=["auto", "cpu"])
    r.add_argument("--no-auto-faces", action="store_true")
    r.add_argument("--reanalyze", action="store_true")
    r.add_argument("--detect-stride", type=int, default=1, help="détecter 1 image sur N (les autres sont interpolées)")
    r.add_argument("--swap-stride", type=int, default=1, help="générer le visage IA 1 image sur N")
    r.add_argument("--cover", action="store_true", help="tache floue sous chaque visage (à utiliser avec un flou)")
    a = ap.parse_args()

    def bar(x, m):
        sys.stdout.write("\r%5.1f%%  %s" % (x * 100, m[:90].ljust(90)))
        sys.stdout.flush()

    if a.cmd == "serve":
        serve(a.port, a.device)
    elif a.cmd == "setup":
        ensure_models(["det", "rec", "genderage", "swap"] + ([] if a.no_enhance else ["enhance"]), bar)
        print("\nModèles prêts dans", MODELS_DIR)
    elif a.cmd == "faces":
        n = download_ai_faces(a.count, bar)
        print("\n%d visage(s) IA ajoutés dans %s" % (n, FACES_DIR))
    elif a.cmd == "run":
        p = {"input": a.input, "outDir": a.out, "start": a.start, "end": a.end, "swap": a.swap, "enhance": a.enhance,
             "seed": a.seed, "threshold": a.threshold, "autoFaces": not a.no_auto_faces, "reanalyze": a.reanalyze,
             "detectStride": a.detect_stride, "swapStride": a.swap_stride, "cover": a.cover}
        res = run_job(Engine(a.device), p, bar, threading.Event())
        print("\n" + json.dumps(res, ensure_ascii=False, indent=2))
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
