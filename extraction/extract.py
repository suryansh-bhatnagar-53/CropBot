#!/usr/bin/env python3
"""
extract.py - CropBot source-extraction pipeline, driven by the BooksData folder.

Scans ../BooksData (or --books-dir) for PDFs, applies per-file metadata from
sources.toml, converts each book with docling (local OCR + accurate table
structure + figures), splits it by crop, and writes one markdown file per
(crop, source):  out/<crop>_<source_id>.md  plus general_<source_id>.md,
per-source reports and a merged manifest. All processing is local.

Stages:
  --list                     show discovered sources, duplicates, unregistered files
  --sanity SRC_ID N          quick test conversion of the first N pages
  --convert [--source ID]    full docling conversion (slow, GPU); cached by PDF hash
  --emit   [--source ID]     segment + emit + reports (fast, re-runnable)
  --all    [--source ID]     convert + emit

Derived from the team's original extract.py (4 fixed sources). Changes:
  * sources come from the BooksData folder + sources.toml, not hardcoded URLs
  * exact-duplicate PDFs are detected by SHA-256 and skipped
  * repeated section headings ("CROP PROTECTION") are no longer deleted as
    running headers; only headings repeated on a large share of pages are
  * crop matching ignores ambiguous words ("lime", "gram", "tea") unless the
    heading is exactly that word, and skips headings naming two crops
  * single-crop books (crop = ... in sources.toml) skip segmentation
  * per-source OCR settings (force OCR + Hindi for legacy-font PDFs)
  * page markers on every page change, bounding boxes kept in the index
  * --emit --source X replaces only X's outputs; the manifest is merged
"""

import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import time
import tomllib
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent
DEFAULT_BOOKS_DIR = BASE.parent / "BooksData"
REGISTRY = BASE / "sources.toml"
CONV = BASE / "converted"
OUT = BASE / "out"
TMP = BASE / ".sanity"

log = logging.getLogger("extract")

try:
    from rapidfuzz import fuzz
except ImportError:  # stdlib fallback, weaker but works
    import difflib

    class _Fuzz:
        @staticmethod
        def partial_ratio(a, b):
            return difflib.SequenceMatcher(None, a, b).ratio() * 100

    fuzz = _Fuzz()

# ============================================================================
# CONFIG 1 - sources: discovered from the BooksData folder, metadata from
# sources.toml. Populated by discover_sources().
# ============================================================================
SOURCES = []

SOURCE_DEFAULTS = dict(
    id=None, title=None, doc_type="unknown", region="unknown", season="",
    year="", language="en", include=True, crop="", ocr="auto",
    ocr_lang=["en"], page_range=None, publisher="", rights_note="", url="",
    note="",
)

# Manual fixes after auditing out/reports/segmentation_<id>.md, e.g.:
#   OVERRIDES = {"icar_ecourse_rabi": {"exclude_crops": ["oats"],
#                                      "force": [["mustard", 300, 315]]}}
OVERRIDES = {}

TOC_SCAN_PAGES = 16          # pages scanned for a table of contents
FUZZY_THRESHOLD = 90.0       # fuzzy heading->crop acceptance score
MAX_MENTIONS = 80            # cap per (crop, source) file
RUNNING_HEADER_SHARE = 0.30  # heading on >=30% of pages = running header
RUNNING_HEADER_MIN_PAGES = 8

# ============================================================================
# CONFIG 2 - crop registry: filename key -> [aliases]. Keys become filenames:
# <key>_<source_id>.md. Aliases include common Indian and botanical names.
# ============================================================================
CROPS = {
    # --- cereals & millets ---
    "rice": ["rice", "paddy", "oryza sativa"],
    "wheat": ["wheat", "triticum aestivum"],
    "maize": ["maize", "corn", "zea mays"],
    "sorghum": ["sorghum", "jowar", "cholam", "great millet", "sorghum bicolor"],
    "pearl_millet": ["pearl millet", "bajra", "cumbu", "pennisetum glaucum"],
    "finger_millet": ["finger millet", "ragi", "mandua", "eleusine"],
    "foxtail_millet": ["foxtail millet", "italian millet", "kangni", "setaria italica"],
    "proso_millet": ["proso millet", "cheena", "chena", "panicum miliaceum"],
    "kodo_millet": ["kodo millet", "paspalum"],
    "barnyard_millet": ["barnyard millet", "sanwa", "jhangora", "echinochloa"],
    "little_millet": ["little millet", "kutki", "panicum sumatrense"],
    "small_millets": ["small millets", "minor millets"],
    "barley": ["barley", "hordeum vulgare"],
    "oats": ["oats", "oat", "avena sativa"],
    "triticale": ["triticale"],
    # --- pulses ---
    "chickpea": ["chickpea", "chick pea", "gram", "bengal gram", "bengalgram",
                 "chana", "cicer arietinum", "kabuli chickpea", "desi chickpea"],
    "pigeonpea": ["pigeonpea", "pigeon pea", "arhar", "tur", "redgram",
                  "red gram", "cajanus cajan"],
    "mungbean": ["mungbean", "mung bean", "green gram", "greengram", "moong",
                 "vigna radiata"],
    "urdbean": ["urdbean", "urd bean", "black gram", "blackgram", "urad",
                "vigna mungo"],
    "lentil": ["lentil", "masoor", "lens culinaris"],
    "fieldpea": ["field pea", "fieldpea", "garden pea", "pea", "peas",
                 "pisum sativum"],
    "lathyrus": ["lathyrus", "khesari", "grass pea", "grasspea",
                 "lathyrus sativus"],
    "cowpea": ["cowpea", "lobia", "vigna unguiculata"],
    "horsegram": ["horse gram", "horsegram", "kulthi", "macrotyloma"],
    "mothbean": ["moth bean", "mothbean", "vigna aconitifolia"],
    "clusterbean": ["clusterbean", "cluster bean", "guar", "cyamopsis"],
    "frenchbean": ["french bean", "frenchbean", "snap bean", "bush bean",
                   "phaseolus vulgaris"],
    "fababean": ["faba bean", "fababean", "broad bean", "bakla", "vicia faba"],
    "rajmash": ["rajmash", "rajma", "kidney bean"],
    # --- oilseeds ---
    "groundnut": ["groundnut", "peanut", "arachis hypogaea"],
    "soybean": ["soybean", "soy bean", "soya", "soya bean", "glycine max"],
    "sunflower": ["sunflower", "helianthus annuus"],
    "castor": ["castor", "castor bean", "ricinus", "arandi"],
    "sesame": ["sesame", "sesamum", "til", "gingelly"],
    "niger": ["niger", "nigerseed", "niger seed", "guizotia"],
    "linseed": ["linseed", "flax", "flaxseed", "linum", "alsi"],
    "safflower": ["safflower", "carthamus", "kusum"],
    "mustard": ["mustard", "rapeseed", "indian mustard", "brassica juncea",
                "brassica napus", "toria", "sarson", "raya", "rai",
                "yellow sarson", "brown sarson", "black mustard", "karan rai",
                "rapeseed and mustard"],
    # --- fibres, sugar, commercial, tubers ---
    "cotton": ["cotton", "gossypium"],
    "jute": ["jute", "corchorus", "tossa jute", "white jute"],
    "sugarcane": ["sugarcane", "saccharum", "ganna"],
    "potato": ["potato", "aloo", "solanum tuberosum"],
    "tobacco": ["tobacco", "nicotiana"],
    "mesta": ["mesta", "kenaf", "roselle", "hibiscus cannabinus",
              "hibiscus sabdariffa", "ambadi"],
    # --- fodder ---
    "berseem": ["berseem", "trifolium alexandrinum", "egyptian clover"],
    "lucerne": ["lucerne", "alfalfa", "medicago"],
    "napier": ["napier grass", "napier", "elephant grass",
               "pennisetum purpureum"],
    # --- vegetables ---
    "tomato": ["tomato", "lycopersicon", "solanum lycopersicum", "tamatar"],
    "brinjal": ["brinjal", "eggplant", "aubergine", "solanum melongena",
                "baingan"],
    "bhendi": ["bhendi", "bhindi", "okra", "ladys finger",
               "abelmoschus esculentus"],
    "onion": ["onion", "bellary onion", "aggregatum onion",
              "multiplier onion", "allium cepa"],
    "garlic": ["garlic", "allium sativum"],
    "chilli": ["chilli", "chillies", "chili", "hot pepper", "mirchi"],
    "capsicum": ["capsicum", "bell pepper", "sweet pepper", "shimla mirch"],
    "cabbage": ["cabbage", "head cabbage"],
    "cauliflower": ["cauliflower", "phool gobhi", "phul gobhi"],
    "broccoli": ["broccoli", "sprouting broccoli"],
    "knolkhol": ["knol khol", "knolkhol", "kohlrabi"],
    "cucumber": ["cucumber", "khira", "cucumis sativus"],
    "pumpkin": ["pumpkin", "kaddu", "cucurbita moschata", "cucurbita maxima"],
    "ash_gourd": ["ash gourd", "wax gourd", "white gourd", "petha",
                  "benincasa"],
    "bitter_gourd": ["bitter gourd", "bitter melon", "karela", "momordica"],
    "bottle_gourd": ["bottle gourd", "lagenaria", "lauki", "calabash"],
    "ridge_gourd": ["ridge gourd", "ribbed gourd", "luffa acutangula", "tori"],
    "snake_gourd": ["snake gourd", "trichosanthes", "chichinda"],
    "sponge_gourd": ["sponge gourd", "smooth gourd", "gilki",
                     "luffa cylindrica"],
    "watermelon": ["watermelon", "citrullus", "tarbuz"],
    "muskmelon": ["muskmelon", "cantaloupe", "kharbooja", "cucumis melo"],
    "carrot": ["carrot", "gajar", "daucus"],
    "radish": ["radish", "mooli", "mool", "raphanus"],
    "beetroot": ["beetroot", "beet root", "chakundar", "beta vulgaris"],
    "turnip": ["turnip", "shalgam", "brassica rapa"],
    "palak": ["palak", "spinach", "spinach beet"],
    "amaranthus": ["amaranthus", "amaranth", "chaulai"],
    "curry_leaf": ["curry leaf", "curry leaves", "murraya", "kadhi patta"],
    "mint": ["mint", "pudina", "mentha", "menthol mint", "spearmint"],
    "coriander": ["coriander", "dhania", "coriandrum"],
    "fenugreek": ["fenugreek", "methi", "trigonella"],
    "tapioca": ["tapioca", "cassava", "maravalli", "manihot"],
    "colocasia": ["colocasia", "taro", "arvi"],
    "elephant_foot_yam": ["elephant foot yam", "elephant-foot yam", "suran",
                          "amorphophallus"],
    "sweet_potato": ["sweet potato", "ipomoea", "shakarkand"],
    "drumstick": ["drumstick", "moringa", "moringa oleifera"],
    "dolichos_bean": ["dolichos bean", "lablab", "lab lab", "avarai", "sem",
                      "hyacinth bean", "country bean"],
    "mushroom": ["mushroom", "oyster mushroom", "button mushroom"],
    # --- fruits ---
    "mango": ["mango", "mangifera", "aam"],
    "banana": ["banana", "plantain", "musa", "kela"],
    "citrus": ["citrus", "sweet orange", "acid lime", "mandarin", "kinnow",
               "santra", "orange", "lime", "lemon", "citrus sinensis",
               "citrus reticulata", "citrus aurantifolia"],
    "grapes": ["grape", "grapes", "grapevine", "vitis", "vitis vinifera"],
    "guava": ["guava", "psidium", "amrood"],
    "papaya": ["papaya", "carica", "papita"],
    "sapota": ["sapota", "sapodilla", "chiku", "chikoo", "manilkara"],
    "jackfruit": ["jackfruit", "jack fruit", "artocarpus", "kathal"],
    "pineapple": ["pineapple", "ananas"],
    "pomegranate": ["pomegranate", "anar", "punica"],
    "annona": ["annona", "custard apple", "sitaphal", "sugar apple",
               "bullocks heart"],
    "aonla": ["aonla", "amla", "emblica", "indian gooseberry"],
    "ber": ["ber", "indian jujube", "ziziphus", "bor"],
    "bael": ["bael", "aegle", "stone apple"],
    "apple": ["apple", "malus"],
    "peach": ["peach", "prunus persica"],
    "pear": ["pear", "nashpati", "pyrus"],
    "plum": ["plum", "prunus domestica"],
    "strawberry": ["strawberry", "fragaria"],
    "litchi": ["litchi", "lychee", "litchi chinensis"],
    "fig": ["fig", "anjeer", "ficus carica"],
    # --- flowers ---
    "jasmine": ["jasmine", "mallika"],
    "rose": ["rose", "rosa"],
    "chrysanthemum": ["chrysanthemum"],
    "marigold": ["marigold", "genda"],
    "crossandra": ["crossandra", "aboli"],
    "tuberose": ["tuberose", "rajanigandha", "polianthes"],
    "gladiolus": ["gladiolus", "gladious"],
    "gerbera": ["gerbera"],
    "carnation": ["carnation", "dianthus caryophyllus"],
    "orchid": ["orchid", "orchids", "vanda", "dendrobium", "cymbidium"],
    "anthurium": ["anthurium"],
    "china_aster": ["china aster"],
    # --- spices, plantation, medicinal & aromatic ---
    "black_pepper": ["black pepper", "blackpepper", "piper nigrum",
                     "pepper vine", "pepper"],
    "cardamom": ["cardamom", "elettaria", "small cardamom"],
    "cinnamon": ["cinnamon", "cinnamomum"],
    "turmeric": ["turmeric", "haldi", "curcuma longa"],
    "ginger": ["ginger", "adrak", "zingiber"],
    "clove": ["clove", "eugenia caryophyllus", "syzygium aromaticum"],
    "nutmeg": ["nutmeg", "myristica"],
    "cumin": ["cumin", "jeera", "cuminum"],
    "fennel": ["fennel", "saunf", "foeniculum"],
    "dill": ["dill", "sowa", "anethum"],
    "tamarind": ["tamarind", "imli", "tamarindus"],
    "vanilla": ["vanilla"],
    "coconut": ["coconut", "cocos nucifera", "copra"],
    "arecanut": ["arecanut", "areca nut", "areca", "supari"],
    "oilpalm": ["oil palm", "oilpalm", "elaeis"],
    "cashew": ["cashew", "cashewnut", "cashew nut", "anacardium", "kaju"],
    "cocoa": ["cocoa", "theobroma"],
    "coffee": ["coffee", "coffea", "arabica coffee", "robusta coffee"],
    "tea": ["tea", "camellia sinensis", "tea bush"],
    "betelvine": ["betel vine", "betelvine", "betel leaf", "piper betle",
                  "pan"],
    "palmyrah": ["palmyrah", "palmyra", "borassus"],
    "senna": ["senna", "cassia angustifolia"],
    "periwinkle": ["periwinkle", "catharanthus", "sadabahar"],
    "isabgol": ["isabgol", "psyllium", "plantago"],
    "ashwagandha": ["ashwagandha", "aswagandha", "withania"],
    "lemongrass": ["lemongrass", "lemon grass", "cymbopogon"],
    "palmarosa": ["palmarosa", "rosa grass"],
    "vetiver": ["vetiver", "khus", "chrysopogon zizanioides", "vetiveria"],
    "geranium": ["geranium", "pelargonium"],
}

# Aliases that are also everyday words. They count only when the whole
# heading is that word ("LIME" alone), never inside a longer heading
# ("Lime requirement of acid soils", "Gram panchayat", "Tea break").
AMBIGUOUS_ALIASES = {
    "lime", "lemon", "orange", "gram", "pan", "tea", "til", "rai", "raya",
    "sem", "tur", "bor", "ber", "mint", "fig", "rose", "rosa", "dill", "mool",
    "pepper", "musa", "kela", "aam", "anar", "sowa", "tori", "khus", "corn",
}

# Words allowed next to a short (<=5 character) alias in a crop heading:
# "Fodder maize", "Summer rice", "Package of Practices - Millet Chena".
HEADING_MODIFIERS = {
    "fodder", "hybrid", "hybrids", "summer", "kharif", "rabi", "spring",
    "winter", "zaid", "irrigated", "rainfed", "upland", "lowland", "crop",
    "crops", "cultivation", "production", "sweet", "baby", "seed", "the",
    "of", "and", "in", "for", "management", "practices", "practice",
    "package", "millet", "millets", "technology", "guide", "transplanted",
    "direct", "seeded", "sown", "late", "early", "varietal", "variety",
    "varieties", "nursery", "seedlings",
}

_ALIAS_RX = {}


def _alias_rx(alias):
    rx = _ALIAS_RX.get(alias)
    if rx is None:
        rx = re.compile(r"(?<![a-z])" + re.escape(alias) + r"(?![a-z])")
        _ALIAS_RX[alias] = rx
    return rx

# ============================================================================
# Small utilities
# ============================================================================

def norm(s):
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", str(s)).lower()
    return re.sub(r"\s+", " ", s).strip()


def slug(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")
    return s[:48] or "source"


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def yv(v):
    """YAML-safe quoted value for front-matter."""
    return json.dumps(str(v), ensure_ascii=False)


def source_by_id(sid):
    for s in SOURCES:
        if s["id"] == sid:
            return s
    raise SystemExit("unknown or excluded source id: %s (valid: %s)"
                     % (sid, [s["id"] for s in SOURCES]))

# ============================================================================
# Source discovery (BooksData folder + sources.toml)
# ============================================================================

def load_registry():
    if not REGISTRY.exists():
        log.warning("no %s found; every PDF gets default metadata", REGISTRY.name)
        return {}
    with open(REGISTRY, "rb") as f:
        data = tomllib.load(f)
    reg = {}
    for e in data.get("source", []):
        if "file" not in e:
            raise SystemExit("sources.toml entry without `file`: %r" % e)
        reg[e["file"]] = e
    return reg


def discover_sources(books_dir):
    """Scan books_dir and return a report dict; fills the global SOURCES
    with included, de-duplicated sources."""
    books_dir = Path(books_dir)
    if not books_dir.is_dir():
        raise SystemExit("books folder not found: %s (use --books-dir)" % books_dir)
    reg = load_registry()
    pdfs = [p for p in books_dir.iterdir()
            if p.is_file() and p.suffix.lower() == ".pdf"]
    # registered + included files first, so they win over byte-identical copies
    pdfs.sort(key=lambda p: (p.name not in reg,
                             not reg.get(p.name, {}).get("include", True),
                             p.name.lower()))
    included, excluded, dups, unregistered = [], [], [], []
    seen_hash, seen_ids = {}, {}
    for p in pdfs:
        entry = reg.get(p.name)
        if entry is None:
            unregistered.append(p.name)
        s = dict(SOURCE_DEFAULTS)
        s.update(entry or {})
        s["file"] = p.name
        s["path"] = str(p)
        s["id"] = s["id"] or slug(p.stem)
        s["title"] = s["title"] or p.stem
        if isinstance(s["ocr_lang"], str):
            s["ocr_lang"] = [s["ocr_lang"]]
        h = sha256_file(p)
        s["sha256"] = h
        if h in seen_hash:
            dups.append((p.name, seen_hash[h]))
            continue
        seen_hash[h] = p.name
        if not s["include"]:
            excluded.append(s)
            continue
        if s["id"] in seen_ids:
            raise SystemExit("duplicate source id %r for %s and %s; set `id` in "
                             "sources.toml" % (s["id"], seen_ids[s["id"]], p.name))
        if s["crop"] and s["crop"] not in CROPS:
            raise SystemExit("sources.toml: crop %r for %s is not a key in CROPS"
                             % (s["crop"], p.name))
        seen_ids[s["id"]] = p.name
        included.append(s)
    missing = sorted(f for f in reg if not (books_dir / f).exists())
    SOURCES[:] = included
    return {"included": included, "excluded": excluded, "duplicates": dups,
            "unregistered": unregistered, "missing": missing}


def print_listing(rep, books_dir):
    print("Books folder: %s\n" % books_dir)
    print("INCLUDED (%d):" % len(rep["included"]))
    for s in rep["included"]:
        extra = []
        if s["crop"]:
            extra.append("crop=" + s["crop"])
        if s["ocr"] != "auto" or s["ocr_lang"] != ["en"]:
            extra.append("ocr=%s/%s" % (s["ocr"], "+".join(s["ocr_lang"])))
        if s["page_range"]:
            extra.append("pages=%s-%s" % tuple(s["page_range"]))
        done = (CONV / ("%s.index.json" % s["id"])).exists()
        print("  %-30s %-15s %-28s %s %s" % (
            s["id"], s["doc_type"], s["region"][:28],
            "[converted]" if done else "", " ".join(extra)))
        if s["file"] in rep["unregistered"]:
            print("      ^ unregistered file: %s (add an entry to sources.toml)" % s["file"])
        if s.get("note"):
            print("      note: %s" % s["note"])
    print("\nEXCLUDED (%d):" % len(rep["excluded"]))
    for s in rep["excluded"]:
        print("  %-15s %s" % (s["doc_type"], s["file"]))
    if rep["duplicates"]:
        print("\nDUPLICATES skipped (identical content):")
        for a, b in rep["duplicates"]:
            print("  %s  ==  %s" % (a, b))
    if rep["missing"]:
        print("\nIn sources.toml but not in the folder:")
        for f in rep["missing"]:
            print("  " + f)

# ============================================================================
# Docling conversion layer
# ============================================================================
_DEVICE = None
_FORCE_CPU = False
_CONVERTERS = {}


def torch_device():
    global _DEVICE
    if _DEVICE is not None:
        return _DEVICE
    if _FORCE_CPU:
        _DEVICE = "cpu"
        return _DEVICE
    try:
        import torch
        _DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
        if _DEVICE == "cuda":
            log.info("torch %s, CUDA %s, GPU %s", torch.__version__,
                     torch.version.cuda, torch.cuda.get_device_name(0))
    except Exception:
        _DEVICE = "cpu"
    log.info("docling device: %s", _DEVICE)
    return _DEVICE


def get_converter(ocr_mode="auto", ocr_lang=("en",)):
    key = (ocr_mode, tuple(ocr_lang))
    if key in _CONVERTERS:
        return _CONVERTERS[key]
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        PdfPipelineOptions, TableFormerMode, AcceleratorOptions
    )
    dev = torch_device()
    popts = PdfPipelineOptions()
    popts.do_ocr = True
    popts.do_table_structure = True
    try:
        popts.table_structure_options.mode = TableFormerMode.ACCURATE
    except Exception:
        pass
    try:
        popts.generate_picture_images = True
    except Exception:
        pass
    try:
        popts.accelerator_options = AcceleratorOptions(num_threads=8, device=dev)
    except Exception:
        pass
    force = ocr_mode == "force"
    try:
        import easyocr  # noqa: F401  (checks the engine is installed)
        from docling.datamodel.pipeline_options import EasyOcrOptions
        popts.ocr_options = EasyOcrOptions(
            lang=list(ocr_lang), force_full_page_ocr=force,
            use_gpu=(dev == "cuda"))
    except ImportError:
        log.warning("easyocr not installed: using docling's default OCR engine "
                    "(language %s will be ignored)", list(ocr_lang))
        popts.ocr_options.force_full_page_ocr = force
    fmt = PdfFormatOption(pipeline_options=popts)
    conv = DocumentConverter(format_options={InputFormat.PDF: fmt})
    _CONVERTERS[key] = conv
    log.info("converter ready (device=%s, ocr=%s, lang=%s)", dev, ocr_mode,
             "+".join(ocr_lang))
    return conv


def _label(item):
    lab = getattr(item, "label", None)
    if lab is None:
        return ""
    return str(getattr(lab, "value", lab)).lower()


def _prov(item):
    """Return (page_no, bbox[l,t,r,b] or None, coord_origin or None)."""
    prov = getattr(item, "prov", None) or []
    if not prov:
        return None, None, None
    pg = getattr(prov[0], "page_no", None)
    bb = getattr(prov[0], "bbox", None)
    if bb is None:
        return pg, None, None
    origin = getattr(bb, "coord_origin", None)
    origin = str(getattr(origin, "value", origin)) if origin is not None else None
    try:
        box = [round(float(bb.l), 1), round(float(bb.t), 1),
               round(float(bb.r), 1), round(float(bb.b), 1)]
    except Exception:
        box = None
    return pg, box, origin


def table_to_md(item, doc):
    for call in ("kw", "pos", "raw"):
        try:
            if call == "kw":
                return item.export_to_markdown(doc=doc)
            if call == "pos":
                return item.export_to_markdown(doc)
            if call == "raw":
                d = getattr(item, "data", None)
                return ("<!-- table not rendered -->\n" + str(d)[:500]) if d else "<!-- table not rendered -->"
        except Exception:
            continue
    return "<!-- table not rendered -->"


def save_picture(item, pg, imgdir, counters):
    try:
        img = getattr(item, "image", None)
        pil = getattr(img, "pil_image", None) if img is not None else None
        if pil is None:
            return None
        counters["pic"] += 1
        name = "p%04d_f%03d.png" % (pg or 0, counters["pic"])
        pil.save(str(imgdir / name))
        return name
    except Exception:
        return None


def _entry(k, txt=None, md=None, img=None, lvl=None, pg=None, box=None, origin=None):
    return {"k": k, "lvl": lvl, "t": txt, "md": md, "img": img, "cap": None,
            "pg": pg, "bbox": box, "origin": origin}


def walk_to_index(doc, imgdir):
    items, counters = [], {"pic": 0}
    try:
        seq = doc.iterate_items(traverse_pictures=True)
    except TypeError:
        seq = doc.iterate_items()
    # footnotes are kept: they often carry scope rules ("per ha unless stated")
    SKIP = {"page_header", "page_footer", "form", "checkbox_selected",
            "checkbox_unselected", "key_value_region"}
    for item, lvl in seq:
        lab = _label(item)
        if lab in SKIP:
            continue
        pg, box, origin = _prov(item)
        txt = (getattr(item, "text", "") or "").strip()
        if lab in ("section_header", "title"):
            items.append(_entry("h", txt=txt, lvl=int(lvl or 1), pg=pg, box=box, origin=origin))
        elif lab == "list_item":
            items.append(_entry("li", txt=txt, pg=pg, box=box, origin=origin))
        elif lab == "table":
            items.append(_entry("tbl", md=table_to_md(item, doc), pg=pg, box=box, origin=origin))
        elif lab == "picture":
            name = save_picture(item, pg, imgdir, counters)
            items.append(_entry("img", img=name, pg=pg, box=box, origin=origin))
        elif lab == "caption":
            # Docling sometimes labels chapter titles as captions ("2. MILLETS
            # (i) SORGHUM (Sorghum bicolor)"). A caption naming a crop becomes
            # a heading; others attach only to a table/figure on the same page.
            prev = items[-1] if items else None
            if txt and match_crop(txt)[0]:
                items.append(_entry("h", txt=txt, lvl=1, pg=pg, box=box, origin=origin))
            elif prev and prev["k"] in ("tbl", "img") and prev.get("pg") == pg:
                prev["cap"] = (prev["cap"].strip() + " " + txt) if prev.get("cap") else txt
            elif txt:
                items.append(_entry("p", txt=txt, pg=pg, box=box, origin=origin))
        elif txt:
            items.append(_entry("p", txt=txt, pg=pg, box=box, origin=origin))
    # fallback if traverse_pictures wasn't supported / yielded nothing
    if not any(it["k"] == "img" for it in items):
        pics = getattr(doc, "pictures", [])
        if isinstance(pics, dict):
            pics = list(pics.values())
        for item in pics:
            pg, box, origin = _prov(item)
            name = save_picture(item, pg, imgdir, counters)
            if name:
                items.append(_entry("img", img=name, pg=pg, box=box, origin=origin))
    # Drop running headers only: short headings repeated on a large share of
    # pages. Section headings a book repeats per crop ("CROP PROTECTION",
    # "SEASON AND VARIETIES") appear on a few % of pages and are kept.
    n_pages = len({it["pg"] for it in items if it.get("pg")}) or 1
    limit = max(RUNNING_HEADER_MIN_PAGES, int(RUNNING_HEADER_SHARE * n_pages))
    head_pages = {}
    for it in items:
        if it["k"] == "h" and len(it.get("t") or "") <= 45:
            head_pages.setdefault(norm(it["t"]), set()).add(it.get("pg"))
    running = {t for t, pgs in head_pages.items() if len(pgs) >= limit}
    if running:
        log.info("dropping %d running header text(s): %s", len(running),
                 sorted(running)[:5])
    return [it for it in items if not (it["k"] == "h" and norm(it["t"]) in running)]


def render_markdown(items, imgprefix, i0=0, i1=None, heading_shift=0,
                    page_tags=True):
    if i1 is None:
        i1 = len(items) - 1
    out, last_pg = [], None
    for i in range(i0, i1 + 1):
        it = items[i]
        pg = it.get("pg")
        if page_tags and pg is not None and pg != last_pg:
            out.append("<!-- p. %d -->" % pg)
            last_pg = pg
        if it["k"] == "h":
            lvl = min(max((it.get("lvl") or 1) + heading_shift, 1), 6)
            out.append("%s %s" % ("#" * lvl, it["t"]))
        elif it["k"] == "p":
            out.append(it["t"])
        elif it["k"] == "li":
            out.append("- %s" % it["t"])
        elif it["k"] == "tbl":
            if it["md"]:
                out.append(it["md"])
        elif it["k"] == "img":
            cap = (it.get("cap") or "figure").replace("[", "(").replace("]", ")")
            if it["img"]:
                out.append("\n![%s](%s%s)\n" % (cap, imgprefix, it["img"]))
            else:
                out.append("<!-- figure (p.%s) not exported -->" % (pg or "?"))
            if it.get("cap"):
                out.append("*%s*" % it["cap"])
    return "\n\n".join(out) + "\n"

# ============================================================================
# Heading -> crop matching + TOC parsing
# ============================================================================
PAT_DOTS = re.compile(r"^(.{3,70}?)[\s._·•…—–]{2,}(\d{1,4})\s*$")
PAT_PLAIN = re.compile(r"^\s*(?:(?:unit|part|chapter|lesson)\s*[-–.]?\s*"
                       r"[ivx\d]*[.\s\-–:]*\s*)?(?:\d{1,2}[.)]\s*)?"
                       r"([A-Za-z][A-Za-z ()'’/-]{2,55}?)\s+(\d{1,4})$")
_NUMBERING = re.compile(
    r"^(?:(?:unit|part|chapter|lesson|section|module)\s*[-–.:]?\s*[ivxlc\d]+\s*[-–.:)]*\s*)?"
    r"(?:(?:[ivx]{1,5}|\d{1,2}|[a-h])\s*[.)]\s+)?")


def heading_core(text):
    """Lower-cased heading without numbering, parentheses and punctuation."""
    t = norm(text)
    t = re.sub(r"\([^)]*\)", " ", t)          # botanical names in brackets
    t = re.sub(r"\([^)]*$", " ", t)           # unclosed "( Sorghum bicolor"
    t = _NUMBERING.sub("", t)
    t = re.sub(r"[^a-z\s]", " ", t)           # punctuation, digits, hyphens
    return re.sub(r"\s+", " ", t).strip()


def match_crop(text):
    """Return (crop_key, score, matched_alias) or (None, 0.0, None).

    A heading starts a crop section only if it names exactly one crop. Short
    aliases (<=5 chars) must stand alone or with modifiers ("Fodder maize");
    everyday words ("lime", "gram") must be the whole heading."""
    t = norm(text)
    if len(t) < 3 or len(t) > 80:
        return None, 0.0, None
    core = heading_core(text)
    words = core.split()
    if not words or len(words) > 8:
        return None, 0.0, None
    found = {}  # crop -> longest alias found
    for crop, aliases in CROPS.items():
        for alias in aliases:
            a = norm(alias)
            if a in AMBIGUOUS_ALIASES:
                ok = core == a
            else:
                ok = bool(_alias_rx(a).search(core))
            if ok and len(a) > len(found.get(crop, "")):
                found[crop] = a
    # an alias nested inside a longer one ("potato" in "sweet potato") loses
    for c in list(found):
        if any(o != c and found[c] != found[o] and found[c] in found[o] for o in found):
            del found[c]
    if len(found) == 1:
        crop, alias = next(iter(found.items()))
        if len(alias) <= 5:
            alias_words = set(alias.split())
            if not all(w in HEADING_MODIFIERS or w in alias_words for w in words):
                return None, 0.0, None
        return crop, 100.0, alias
    if len(found) > 1:
        return None, 0.0, None   # names two crops: "Rice-wheat cropping system"
    # fuzzy fallback for OCR slips, short headings only
    if len(words) > 4:
        return None, 0.0, None
    best_c, best_s = None, 0.0
    for crop, aliases in CROPS.items():
        for alias in aliases:
            a = norm(alias)
            if len(a) >= 6 and a not in AMBIGUOUS_ALIASES:
                s = fuzz.partial_ratio(a, core)
                if s > best_s:
                    best_c, best_s = crop, float(s)
    if best_s >= FUZZY_THRESHOLD:
        return best_c, best_s, None
    return None, 0.0, None


def parse_toc(items):
    """Return list of {'title': str, 'page': int} from early pages."""
    hits = {}
    for it in items:
        pg = it.get("pg")
        if pg is None or pg > TOC_SCAN_PAGES:
            continue
        if it["k"] not in ("p", "li", "h"):
            continue
        txt = (it.get("t") or "").strip()
        if not txt:
            continue
        m = PAT_DOTS.match(txt) or PAT_PLAIN.match(txt)
        if not m:
            continue
        title = re.sub(r"[\s.:•·—–-]+$", "", m.group(1)).strip()
        tgt = int(m.group(2))
        tl = norm(title)
        if not tl or tl in {
            "contents", "index", "list of tables", "list of figures",
            "preface", "foreword", "acknowledgement", "introduction"
        }:
            continue
        hits.setdefault(pg, []).append((title, tgt))
    entries = []
    for pg, lst in sorted(hits.items()):
        if len(lst) >= 4:
            seen = set()
            for title, tgt in lst:
                key = (norm(title), tgt)
                if key not in seen and 0 < tgt <= 1200:
                    seen.add(key)
                    entries.append({"title": title, "page": tgt})
    return entries

# ============================================================================
# Segmentation
# ============================================================================
def _pages_span_to_items(items, p0, p1):
    i0 = i1 = None
    for i, it in enumerate(items):
        pg = it.get("pg")
        if pg is None:
            continue
        if pg >= p0 and i0 is None:
            i0 = i
        if p1 is None or pg <= p1:
            i1 = i
    if i0 is None:
        i0 = 0
    if i1 is None or i1 < i0:
        return None
    return (i0, i1)


def _finish_segments(items, segs):
    final = []
    for s in segs:
        if s["i0"] > s["i1"]:
            continue
        pgs = [it.get("pg") for it in items[s["i0"]:s["i1"] + 1] if it.get("pg") is not None]
        s["p0"], s["p1"] = (min(pgs), max(pgs)) if pgs else (None, None)
        final.append(s)
    return final


def segment(index, src):
    """Return (segments, toc, unmatched_headings, toc_only)."""
    items = index["items"]
    if not items:
        return [], [], [], []
    # single-crop book: the whole book is one crop section
    if src.get("crop"):
        segs = _finish_segments(items, [{
            "i0": 0, "i1": len(items) - 1, "crop": src["crop"], "conf": 1.0,
            "ev": "registry", "head": src["title"]}])
        return segs, [], [], []
    # 1. heading marks
    marks = []
    for i, it in enumerate(items):
        if it["k"] != "h":
            continue
        crop, score, _ = match_crop(it["t"] or "")
        if crop:
            marks.append({"i": i, "crop": crop, "score": score,
                          "pg": it.get("pg"), "title": it["t"]})
    # 2. TOC entries -> crops
    toc = parse_toc(items)
    toc_crops = {}
    for e in toc:
        crop, _, _ = match_crop(e["title"])
        if crop:
            toc_crops.setdefault(crop, []).append(e)

    def mark_conf(m):
        conf, ev = m["score"] / 100.0, "heading"
        if m["pg"] is not None and m["crop"] in toc_crops:
            for e in toc_crops[m["crop"]]:
                if abs(e["page"] - m["pg"]) <= 2:
                    return max(conf, 0.98), "heading+toc"
        return conf, ev

    # 3. candidate segments from heading marks
    cands = []
    if marks:
        if marks[0]["i"] > 0:
            cands.append({"i0": 0, "i1": marks[0]["i"] - 1,
                          "crop": None, "conf": 0.0, "ev": "leading"})
        for m, nxt in zip(marks, marks[1:] + [None]):
            conf, ev = mark_conf(m)
            i1 = (nxt["i"] - 1) if nxt else len(items) - 1
            cands.append({"i0": m["i"], "i1": i1, "crop": m["crop"],
                          "conf": conf, "ev": ev, "head": m["title"]})
    else:
        cands.append({"i0": 0, "i1": len(items) - 1,
                      "crop": None, "conf": 0.0, "ev": "full"})
    # 4. TOC-only recovery for crops not in marks
    marked = {c["crop"] for c in cands if c["crop"]}
    for crop, entries in toc_crops.items():
        if crop in marked:
            continue
        entries.sort(key=lambda e: e["page"])
        for j, e in enumerate(entries):
            p1 = (entries[j + 1]["page"] - 1) if j + 1 < len(entries) else None
            span = _pages_span_to_items(items, e["page"], p1)
            if span:
                cands.append({"i0": span[0], "i1": span[1], "crop": crop,
                              "conf": 0.55, "ev": "toc", "head": e["title"]})
    # 5. Manual overrides (force / exclude)
    ov = OVERRIDES.get(src["id"], {})
    if "exclude_crops" in ov:
        ex = set(ov["exclude_crops"])
        cands = [c for c in cands if c["crop"] not in ex]
    for crop, p0, p1 in ov.get("force", []):
        span = _pages_span_to_items(items, p0, p1)
        if span:
            cands.append({"i0": span[0], "i1": span[1], "crop": crop,
                          "conf": 1.0, "ev": "manual", "head": ""})
    # 6. Assignment fill (highest conf wins per index)
    cands.sort(key=lambda c: c["conf"], reverse=True)
    assign = {}
    for c in cands:
        for idx in range(c["i0"], c["i1"] + 1):
            if idx not in assign:
                assign[idx] = (c["crop"], c["conf"], c["ev"], c.get("head", ""))
    # 7. Build contiguous final segments (general runs included, crop=None)
    segs, cur, cur_i0 = [], None, None
    for i in range(len(items)):
        a = assign.get(i, (None, 0.0, "", ""))
        if cur is not None and a[0] == cur[0]:
            continue
        if cur is not None:
            segs.append({"crop": cur[0], "i0": cur_i0, "i1": i - 1,
                         "conf": cur[1], "ev": cur[2], "head": cur[3]})
        cur, cur_i0 = a, i
    if cur is not None:
        segs.append({"crop": cur[0], "i0": cur_i0, "i1": len(items) - 1,
                     "conf": cur[1], "ev": cur[2], "head": cur[3]})
    final = _finish_segments(items, segs)
    # 8. unmatched headings for the report
    in_crop = set()
    for s in final:
        if s["crop"]:
            in_crop.update(range(s["i0"], s["i1"] + 1))
    unmatched = [{"pg": it.get("pg"), "t": it["t"]}
                 for i, it in enumerate(items) if it["k"] == "h" and i not in in_crop]
    toc_only = sorted(c for c in toc_crops if c not in marked)
    return final, toc, unmatched, toc_only

# ============================================================================
# QA checks
# ============================================================================
GARBLE_RE = re.compile(
    r"(?:\b\d+[OIl]{1,2}\d*\b)|"                       # 4O, 1OO, 5l6...
    r"(?:\b(?=[OIl]{2,}\b)(?=[^\s]*[Ol])[OIl]{2,}\b)|"  # lOO, OIl...
    r"(?:\b[OIl]\d{1,3}\b)|(?:\b\d{1,3}[OIl]\b)"        # l6, 5l
)
# legacy-font Hindi/Tamil extracted as ASCII mojibake: symbols inside words
MOJIBAKE_RE = re.compile(r"[A-Za-z][`;\]\[{}~|][A-Za-z]")


def qa_slice(items):
    """Return list of {'pg': int, 'issue': str} for a file."""
    out = []
    for it in items:
        pg = it.get("pg")
        if it["k"] == "tbl" and it.get("md") and GARBLE_RE.search(it["md"]):
            out.append({"pg": pg, "issue": "possible garbled numbers in table"})
        if it["k"] == "img" and not it.get("img"):
            out.append({"pg": pg, "issue": "figure not exported"})
    return out


def qa_source(items):
    """Source-level checks: near-empty pages and legacy-font mojibake."""
    per = {}
    words = bad = 0
    for it in items:
        pg = it.get("pg") or 0
        txt = it.get("t") or ""
        per[pg] = per.get(pg, 0) + len(txt) + len(it.get("md") or "")
        for w in txt.split():
            words += 1
            if MOJIBAKE_RE.search(w):
                bad += 1
    empty = sorted(p for p, v in per.items() if v < 25)
    share = (bad / words) if words else 0.0
    return empty, share

# ============================================================================
# Mentions + emit
# ============================================================================
def find_mentions(items, main_segs, crop, items_low):
    """Return mentions of `crop` outside its main sections."""
    in_main = set()
    for s in main_segs:
        in_main.update(range(s["i0"], s["i1"] + 1))
    aliases = [norm(a) for a in CROPS[crop] if norm(a) not in AMBIGUOUS_ALIASES]
    res = []
    last_head = ""
    for i, low in items_low:
        it = items[i]
        if it["k"] == "h":
            last_head = it["t"]
            continue
        if i in in_main:
            continue
        pg = it.get("pg")
        if pg is not None and pg <= TOC_SCAN_PAGES:
            continue
        if low and any(_alias_rx(a).search(low) for a in aliases):
            res.append({"pg": pg, "ctx": last_head, "k": it["k"],
                        "t": it.get("t"), "md": it.get("md")})
            if len(res) >= MAX_MENTIONS:
                break
    return res


def _front_matter(fields):
    out = ["---\n"]
    for k, v in fields:
        out.append("%s: %s\n" % (k, v))
    out.append("---\n\n")
    return out


def clear_source_outputs(sid):
    """Delete only this source's emitted files (identified by front-matter)."""
    marker = "source_id: %s\n" % sid
    for p in OUT.glob("*.md"):
        try:
            with open(p, encoding="utf-8") as f:
                head = f.read(600)
        except OSError:
            continue
        if head.startswith("---\n") and marker in head:
            p.unlink()
    shutil.rmtree(OUT / "images" / sid, ignore_errors=True)


def emit_source(src, index, segs, items_low):
    """Write out/<crop>_<source_id>.md files and general_<id>.md.
    Returns (manifest_entries, per_file_qa, used_images)."""
    sid = src["id"]
    items = index["items"]
    by_crop = {}
    for s in segs:
        if s["crop"]:
            by_crop.setdefault(s["crop"], []).append(s)
    gen_segs = [s for s in segs if not s["crop"]]
    manifest, per_file_qa, used_imgs = [], {}, set()
    common = [
        ("source_id", sid),
        ("source_title", yv(src["title"])),
        ("source_file", yv(src["file"])),
        ("source_sha256", src["sha256"]),
        ("doc_type", src["doc_type"]),
        ("region", yv(src["region"])),
        ("season", yv(src["season"])),
        ("year", yv(src["year"])),
        ("language", src["language"]),
        ("publisher", yv(src["publisher"])),
        ("source_url", yv(src["url"])),
        ("rights_note", yv(src["rights_note"])),
    ]
    extracted = ("docling %s (TableFormer accurate, OCR %s, lang %s)" %
                 (index.get("docling_version", "?"), src["ocr"], "+".join(src["ocr_lang"])))
    for crop, seglist in by_crop.items():
        fname = "%s_%s.md" % (crop, sid)
        pgs = [it.get("pg") for s in seglist for it in items[s["i0"]:s["i1"] + 1]
               if it.get("pg") is not None]
        p0, p1 = (min(pgs), max(pgs)) if pgs else (None, None)
        disp = crop.replace("_", " ").title()
        mentions = find_mentions(items, seglist, crop, items_low)
        body = ["# %s — %s\n" % (disp, src["title"]),
                "> Auto-extracted from %s by the CropBot pipeline. Content is faithful "
                "to the source; `<!-- p. N -->` markers give source page numbers.\n"
                % src["title"]]
        for k, s in enumerate(seglist, 1):
            head = (" — %s" % s["head"]) if s.get("head") else ""
            body.append("## Main content — Part %d (pp. %s–%s)%s\n" %
                        (k, s["p0"] or "?", s["p1"] or "?", head))
            body.append(render_markdown(items, "images/%s/" % sid,
                                        s["i0"], s["i1"], heading_shift=1) + "\n")
        body.append("## Other mentions in this source\n")
        if mentions:
            for m in mentions:
                ctx = " — in “%s”" % m["ctx"] if m["ctx"] else ""
                body.append("### p. %d%s\n\n" % (m["pg"] or 0, ctx))
                body.append(((m["md"] if m["k"] == "tbl" else m["t"]) or "") + "\n")
        else:
            body.append("_No other mentions of this crop were found in this source._\n")
        for s in seglist:
            for it in items[s["i0"]:s["i1"] + 1]:
                if it["k"] == "img" and it["img"]:
                    used_imgs.add((sid, it["img"]))
        qa = qa_slice([it for s in seglist for it in items[s["i0"]:s["i1"] + 1]] + mentions)
        qa_status = "clean" if not qa else "flagged (%d)" % len(qa)
        per_file_qa[fname] = qa
        page_range = "%d-%d" % (p0, p1) if p0 and p1 else "unknown"
        fm = [("crop", crop), ("crop_display", disp)] + common + [
            ("page_range", page_range),
            ("main_sections", len(seglist)),
            ("segment_evidence", yv(", ".join(sorted({s["ev"] for s in seglist})))),
            ("mentions", len(mentions)),
            ("extracted_with", yv(extracted)),
            ("extracted_on", date.today().isoformat()),
            ("qa_status", yv(qa_status)),
        ]
        (OUT / fname).write_text("".join(_front_matter(fm) + body), encoding="utf-8")
        manifest.append({"file": fname, "crop": crop, "source": sid,
                         "doc_type": src["doc_type"], "region": src["region"],
                         "page_range": page_range, "main_sections": len(seglist),
                         "mentions": len(mentions),
                         "sha256": sha256_file(OUT / fname), "qa_status": qa_status})
    if gen_segs:
        gfname = "general_%s.md" % sid
        body = ["# General chapters — %s\n" % src["title"],
                "> Chapters not matched to a specific crop (intro, soils, cropping systems, etc.).\n"]
        for s in gen_segs:
            body.append("## (pp. %s–%s)\n" % (s["p0"] or "?", s["p1"] or "?"))
            body.append(render_markdown(items, "images/%s/" % sid,
                                        s["i0"], s["i1"], heading_shift=1) + "\n")
            for it in items[s["i0"]:s["i1"] + 1]:
                if it["k"] == "img" and it["img"]:
                    used_imgs.add((sid, it["img"]))
        fm = [("crop", "general")] + common + [
            ("extracted_with", yv(extracted)),
            ("extracted_on", date.today().isoformat())]
        (OUT / gfname).write_text("".join(_front_matter(fm) + body), encoding="utf-8")
        manifest.append({"file": gfname, "crop": None, "source": sid,
                         "doc_type": src["doc_type"], "region": src["region"],
                         "page_range": "mixed", "main_sections": len(gen_segs),
                         "mentions": 0, "sha256": sha256_file(OUT / gfname),
                         "qa_status": "n/a"})
    return manifest, per_file_qa, used_imgs


def emit_all(ids=None):
    """Segment + write files + reports for the selected (or all) sources."""
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "images").mkdir(parents=True, exist_ok=True)
    (OUT / "reports").mkdir(parents=True, exist_ok=True)
    done_ids, new_manifest = [], []
    for src in SOURCES:
        if ids and src["id"] not in ids:
            continue
        p = CONV / ("%s.index.json" % src["id"])
        if not p.exists():
            log.warning("no index for %s — run --convert --source %s first",
                        src["id"], src["id"])
            continue
        index = json.loads(p.read_text(encoding="utf-8"))
        if index.get("source_sha256") and index["source_sha256"] != src["sha256"]:
            log.warning("%s: the PDF changed since conversion; re-run --convert",
                        src["id"])
        log.info("segmenting %s ...", src["id"])
        segs, toc, unmatched, toc_only = segment(index, src)
        items = index["items"]
        items_low = [(i, norm(it.get("t") or it.get("md") or ""))
                     for i, it in enumerate(items) if it["k"] in ("p", "li", "tbl", "h")]
        clear_source_outputs(src["id"])
        mf, qa, used = emit_source(src, index, segs, items_low)
        for s_id, name in used:
            s_img = CONV / "images" / s_id / name
            d_img = OUT / "images" / s_id / name
            if s_img.exists():
                d_img.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(s_img, d_img)
        write_source_reports(src, index, segs, toc, unmatched, toc_only, qa)
        new_manifest.extend(mf)
        done_ids.append(src["id"])
        log.info("%s: %d files", src["id"], len(mf))
    if not done_ids:
        raise SystemExit("nothing emitted: no converted indexes for the selected sources")
    write_manifest(done_ids, new_manifest)
    write_readme()


def write_source_reports(src, index, segs, toc, unmatched, toc_only, qa):
    sid = src["id"]
    items = index["items"]
    empty, moji = qa_source(items)
    lines = ["# Segmentation report — %s" % sid, "",
             "Generated %s from `%s`\n" % (date.today().isoformat(), src["file"]),
             "TOC entries detected: %d\n" % len(toc),
             "Crop sections: %d\n" % len([s for s in segs if s["crop"]]),
             "Crops in TOC but without a heading match: %s\n" %
             (", ".join(toc_only) if toc_only else "none")]
    if src.get("crop"):
        lines.append("Single-crop source (crop set in sources.toml): %s\n" % src["crop"])
    elif src["doc_type"] == "practice_guide" and src["language"] != "en":
        lines.append("**Note:** non-English book without `crop` set: English crop "
                     "aliases cannot match its headings, so it all goes to general_%s.md. "
                     "Set `crop` in sources.toml.\n" % sid)
    if moji > 0.03:
        lines.append("**Warning:** %.0f%% of words look like legacy-font mojibake. "
                     "Set `ocr = \"force\"` (and `ocr_lang`) for this file in "
                     "sources.toml and re-convert.\n" % (100 * moji))
    if empty:
        lines.append("Pages with almost no text (OCR failures or image-only pages): %s\n"
                     % ", ".join(str(p) for p in empty[:60]))
    lines += ["### Segments", "| crop | i0 | i1 | p0 | p1 | conf | evidence | heading |",
              "|---|---|---|---|---|---|---|---|"]
    for s in segs:
        lines.append("| %s | %d | %d | %s | %s | %.2f | %s | %s |" % (
            s["crop"] or "GENERAL", s["i0"], s["i1"], s["p0"] or "?", s["p1"] or "?",
            s["conf"], s["ev"], (s.get("head") or "").replace("|", "/")[:60]))
    if unmatched:
        lines.append("\n### Headings outside crop sections (first 80)")
        for u in unmatched[:80]:
            lines.append("- p.%s: %s" % (u["pg"] or "?", u["t"]))
    lines += ["", "## Fixing issues",
              "1. Add missing aliases to `CROPS` in extract.py",
              "2. Add page boundaries in `OVERRIDES` in extract.py:",
              "   `OVERRIDES = {\"%s\": {\"exclude_crops\": [...], "
              "\"force\": [[\"crop\", p0, p1]]}}`" % sid,
              "3. Re-run `uv run extract.py --emit --source %s` (fast, no re-OCR)" % sid]
    (OUT / "reports" / ("segmentation_%s.md" % sid)).write_text("\n".join(lines),
                                                                encoding="utf-8")
    q = ["# QA report — %s" % sid, "", "Generated %s\n" % date.today().isoformat()]
    for fname, issues in qa.items():
        if issues:
            q.append("## %s (%d issues)" % (fname, len(issues)))
            q += ["- p.%s: %s" % (i["pg"] or "?", i["issue"]) for i in issues]
            q.append("")
    if len(q) == 3:
        q.append("No issues flagged.")
    (OUT / "reports" / ("qa_%s.md" % sid)).write_text("\n".join(q), encoding="utf-8")


def write_manifest(done_ids, new_entries):
    mpath = OUT / "manifest.json"
    files = []
    if mpath.exists():
        try:
            old = json.loads(mpath.read_text(encoding="utf-8"))
            files = [f for f in old.get("files", []) if f.get("source") not in done_ids]
        except (OSError, ValueError):
            files = []
    files.extend(new_entries)
    present = {f["source"] for f in files}
    m = {
        "generated_on": date.today().isoformat(),
        "extracted_with": "docling (TableFormer accurate, OCR on)",
        "sources": [{k: s[k] for k in ("id", "title", "file", "sha256", "doc_type",
                                       "region", "season", "year", "language", "url",
                                       "publisher", "rights_note")}
                    for s in SOURCES if s["id"] in present],
        "files": sorted(files, key=lambda f: (f["source"], f["file"])),
    }
    mpath.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")


def write_readme():
    r = [
        "# CropBot extracted corpus", "",
        "Generated %s by `extraction/extract.py`\n" % date.today().isoformat(),
        "## Files",
        "- `<crop>_<source_id>.md`: one file per crop per source",
        "- `general_<source_id>.md`: chapters not tied to one crop",
        "- `images/<source_id>/`: figure PNGs referenced from the .md files",
        "- `reports/segmentation_<source_id>.md`: audit crop boundaries here",
        "- `reports/qa_<source_id>.md`: suspected OCR/number issues",
        "- `manifest.json`: machine-readable index for knowledge-graph ingestion",
        "",
        "Page numbers: every page change in a .md file has a `<!-- p. N -->` marker.",
        "Exact positions (bounding boxes) are in `converted/<source_id>.index.json`.",
        "",
        "## Sources",
        "| id | title | type | region | rights |", "|---|---|---|---|---|",
    ]
    for s in SOURCES:
        r.append("| %s | %s | %s | %s | %s |" % (s["id"], s["title"], s["doc_type"],
                                               s["region"], s["rights_note"]))
    (OUT / "README.md").write_text("\n".join(r) + "\n", encoding="utf-8")

# ============================================================================
# Conversion orchestration
# ============================================================================
def clip_pdf(src_pdf, n_pages, out_pdf, first=1):
    """Write n_pages starting at `first` (1-based) of src_pdf to out_pdf."""
    from pypdf import PdfReader, PdfWriter
    r = PdfReader(str(src_pdf))
    w = PdfWriter()
    for i in range(first - 1, min(first - 1 + n_pages, len(r.pages))):
        w.add_page(r.pages[i])
    out_pdf = Path(out_pdf)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    with open(out_pdf, "wb") as f:
        w.write(f)
    return out_pdf


def convert_source(src, pdf_path, save=True, page_range=None):
    """Run docling on pdf_path and return the index dict. If save, writes
    converted/<id>.index.json + <id>.md + images."""
    conv = get_converter(src["ocr"], src["ocr_lang"])
    log.info("converting %s (%s) ...", src["id"], Path(pdf_path).name)
    t0 = time.time()
    if page_range:
        result = conv.convert(str(pdf_path), page_range=tuple(page_range))
    else:
        result = conv.convert(str(pdf_path))
    doc = result.document
    imgdir = CONV / "images" / src["id"]
    if save:
        shutil.rmtree(imgdir, ignore_errors=True)
    imgdir.mkdir(parents=True, exist_ok=True)
    items = walk_to_index(doc, imgdir)
    pages = len(getattr(doc, "pages", {}) or {}) or max(
        [it.get("pg") or 0 for it in items], default=0)
    dver = None
    try:
        from importlib.metadata import version
        dver = version("docling")
    except Exception:
        pass
    index = {
        "source_id": src["id"], "title": src["title"], "file": src["file"],
        "source_sha256": src["sha256"], "url": src["url"],
        "publisher": src["publisher"], "rights_note": src["rights_note"],
        "converted_on": date.today().isoformat(), "device": _DEVICE,
        "docling_version": dver, "ocr": src["ocr"], "ocr_lang": src["ocr_lang"],
        "page_range": page_range, "pages": pages, "items": items,
    }
    tbl = sum(1 for it in items if it["k"] == "tbl")
    img = sum(1 for it in items if it["k"] == "img")
    log.info("done %s in %.0fs: %d items, %d tables, %d images",
             src["id"], time.time() - t0, len(items), tbl, img)
    if save:
        CONV.mkdir(parents=True, exist_ok=True)
        (CONV / ("%s.index.json" % src["id"])).write_text(
            json.dumps(index, ensure_ascii=False, default=str), encoding="utf-8")
        md = render_markdown(items, "images/%s/" % src["id"])
        (CONV / ("%s.md" % src["id"])).write_text(
            "---\ntitle: %s\nsource_id: %s\n---\n\n" % (yv(src["title"]), src["id"]) + md,
            encoding="utf-8")
    return index


def convert_all(ids=None, force=False):
    """Convert all (or selected) sources; skips ones already converted from
    the same PDF unless force=True. Falls back to CPU on CUDA OOM."""
    global _FORCE_CPU, _DEVICE
    for src in SOURCES:
        if ids and src["id"] not in ids:
            continue
        idx_path = CONV / ("%s.index.json" % src["id"])
        if idx_path.exists() and not force:
            try:
                old = json.loads(idx_path.read_text(encoding="utf-8"))
                if (old.get("source_sha256") == src["sha256"]
                        and old.get("page_range") == src["page_range"]
                        and old.get("ocr") == src["ocr"]
                        and old.get("ocr_lang") == src["ocr_lang"]):
                    log.info("%s already converted (use --force to redo)", src["id"])
                    continue
            except (OSError, ValueError):
                pass
        try:
            convert_source(src, src["path"], save=True, page_range=src["page_range"])
        except Exception as e:
            if "CUDA" in str(e) or "out of memory" in str(e).lower():
                log.warning("CUDA OOM on %s — retrying on CPU (slower)", src["id"])
                _FORCE_CPU, _DEVICE = True, None
                _CONVERTERS.clear()
                convert_source(src, src["path"], save=True, page_range=src["page_range"])
            else:
                log.error("FAILED %s: %s", src["id"], e)


def sanity(sid, n_pages):
    """Quick test: clip the first N pages, convert, print a preview."""
    src = source_by_id(sid)
    first = (src["page_range"] or [1])[0]
    clip = clip_pdf(src["path"], n_pages, TMP / ("%s_%dp.pdf" % (sid, n_pages)), first)
    idx = convert_source(src, clip, save=False)
    items = idx["items"]
    print("\n=== SANITY %s (%d pages from p.%d) ===" % (sid, n_pages, first))
    print("kinds:", dict(Counter(it["k"] for it in items)), "| pages:", idx["pages"])
    print("\nHeadings found (-> crop match):")
    for it in items:
        if it["k"] == "h":
            c, _, _ = match_crop(it["t"] or "")
            print("  p.%s lvl%s  %-60s -> %s" % (it.get("pg"), it.get("lvl"),
                                                (it["t"] or "")[:60], c))
    print("\nFirst text items:")
    for it in [x for x in items if x["k"] == "p"][:15]:
        print("  p.%s  %s" % (it.get("pg"), (it["t"] or "")[:90]))
    toc = parse_toc(items)
    print("\nTOC entries:", len(toc))
    for e in toc[:12]:
        print("  p.%d: %s" % (e["page"], e["title"]))
    tables = [it for it in items if it["k"] == "tbl"]
    if tables:
        print("\nFirst table (first 300 chars):")
        print(tables[0]["md"][:300])
    _, moji = qa_source(items)
    print("\nImages saved:", sum(1 for it in items if it["k"] == "img"),
          "| mojibake share: %.1f%%" % (100 * moji))

# ============================================================================
# CLI entry
# ============================================================================
def main():
    ap = argparse.ArgumentParser(description="CropBot source extraction (BooksData folder)")
    ap.add_argument("--books-dir", default=os.environ.get("CROPBOT_BOOKS_DIR",
                                                          str(DEFAULT_BOOKS_DIR)),
                    help="folder of source PDFs (default: ../BooksData)")
    ap.add_argument("--list", action="store_true", help="list discovered sources")
    ap.add_argument("--sanity", nargs=2, metavar=("SRC_ID", "PAGES"),
                    help="quick test conversion of SRC_ID first PAGES pages")
    ap.add_argument("--convert", action="store_true", help="docling conversion (slow, GPU)")
    ap.add_argument("--emit", action="store_true", help="segment + emit + reports (fast)")
    ap.add_argument("--all", action="store_true", help="convert + emit")
    ap.add_argument("--source", action="append",
                    help="limit to this source id (repeat or comma-separate)")
    ap.add_argument("--force", action="store_true", help="re-convert even if cached")
    ap.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    rep = discover_sources(a.books_dir)
    ids = None
    if a.source:
        ids = [x.strip() for v in a.source for x in v.split(",") if x.strip()]
        for sid in ids:
            source_by_id(sid)  # validates
    if a.list:
        print_listing(rep, a.books_dir)
    if a.sanity:
        sanity(a.sanity[0], int(a.sanity[1]))
    if a.convert or a.all:
        convert_all(ids, force=a.force)
    if a.emit or a.all:
        emit_all(ids)
    if not (a.list or a.sanity or a.convert or a.emit or a.all):
        ap.print_help()


if __name__ == "__main__":
    main()
