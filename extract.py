#!/usr/bin/env python3
"""
extract.py - CropBot source-extraction pipeline (single file).

Downloads 4 verified government-published agriculture books, converts them
fully with docling (local OCR + accurate table structure + referenced
figures), auto-segments each book by crop, and emits one markdown file per
(crop, source):  out/<crop>_<source_id>.md  plus general_<source_id>.md,
reports and manifest. All processing is local - no cloud APIs, zero cost.

Stages:
  --download                 fetch the 4 source PDFs (cached)
  --sanity SRC_ID [N pages]  quick test conversion + preview
  --convert [--source ID]    full docling conversion (slow, GPU)
  --emit   [--source ID]     segment + emit + reports (fast, re-runnable)
  --all                      everything
"""

import argparse
import hashlib
import json
import logging
import re
import shutil
import sys
import time
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent
PDF_DIR = BASE / "sources" / "pdfs"
CONV = BASE / "converted"
OUT = BASE / "out"
TMP = Path("/tmp/opencode/extract_sanity")

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
# CONFIG 1 - sources (all verified HTTP 200; government-published, free
# farmer-education distribution; rights notes recorded for attribution)
# ============================================================================
SOURCES = [
    dict(
        id="icar_kharif",
        title="Field Crops (Kharif) - ICAR e-course",
        file="icar_kharif.pdf",
        size=5220018,
        url="https://agrimoon.com/wp-content/uploads/Field-Crop-Kharif.pdf",
        publisher="ICAR e-course (TNAU/SAU consortium, NAIP); mirrored by agrimoon.com",
        rights_note="Free ICAR e-course teaching material; attribute ICAR/TNAU, not the mirror",
    ),
    dict(
        id="icar_rabi",
        title="Field Crops (Rabi) - ICAR e-course",
        file="icar_rabi.pdf",
        size=3017579,
        url="https://agrimoon.com/wp-content/uploads/FIELD-CROPS-RABI-with-Multiple-choice-questions.pdf",
        publisher="ICAR e-course (TNAU/SAU consortium, NAIP); mirrored by agrimoon.com",
        rights_note="Free ICAR e-course teaching material; attribute ICAR/TNAU, not the mirror",
    ),
    dict(
        id="tnau_agriculture",
        title="Agriculture - TNAU production guide",
        file="tnau_agriculture.pdf",
        size=4316300,
        url="https://agritech.tnau.ac.in/pdf/AGRICULTURE.pdf",
        publisher="Tamil Nadu Agricultural University (agritech extension portal)",
        rights_note="State agricultural university extension publication, free farmer education",
    ),
    dict(
        id="tnau_horticulture",
        title="Horticulture - TNAU production guide",
        file="tnau_horticulture.pdf",
        size=7221894,
        url="https://agritech.tnau.ac.in/pdf/HORTICULTURE.pdf",
        publisher="Tamil Nadu Agricultural University (agritech extension portal)",
        rights_note="State agricultural university extension publication, free farmer education",
    ),
]

# Manual fixes after auditing out/segmentation_report.md, e.g.:
#   OVERRIDES = {"icar_rabi": {"exclude_crops": ["oats"],
#                              "force": [["mustard", 300, 315]]}}
OVERRIDES = {}

TOC_SCAN_PAGES = 16          # pages scanned for a table of contents
FUZZY_THRESHOLD = 87.0        # fuzzy heading->crop acceptance score
MAX_MENTIONS = 80            # cap per (crop, source) file
MENTION_MIN_PAGE = TOC_SCAN_PAGES + 1  # skip TOC pages in mention search

# ============================================================================
# CONFIG 2 - crop registry: filename key -> [aliases]. Keys become filenames:
# <key>_<source_id>.md. Aliases include common Indian and botanical names.
# <=5-char aliases match as whole words; longer ones as substrings.
# ============================================================================
CROPS = {
    # --- cereals & millets ---
    "rice": ["rice", "paddy", "oryza sativa"],
    "wheat": ["wheat", "triticum aestivum"],
    "maize": ["maize", "corn", "zea mays"],
    "sorghum": ["sorghum", "jowar", "great millet", "sorghum bicolor"],
    "pearl_millet": ["pearl millet", "bajra", "pennisetum glaucum"],
    "finger_millet": ["finger millet", "ragi", "mandua", "eleusine"],
    "foxtail_millet": ["foxtail millet", "italian millet", "kangni", "setaria italica"],
    "proso_millet": ["proso millet", "cheena", "panicum miliaceum"],
    "kodo_millet": ["kodo millet", "paspalum"],
    "barnyard_millet": ["barnyard millet", "sanwa", "jhangora", "echinochloa"],
    "little_millet": ["little millet", "kutki", "panicum sumatrense"],
    "small_millets": ["small millets", "minor millets"],
    "barley": ["barley", "hordeum vulgare"],
    "oats": ["oats", "oat", "avena sativa"],
    "triticale": ["triticale"],
    # --- pulses ---
    "chickpea": ["chickpea", "chick pea", "gram", "bengal gram", "chana",
                 "cicer arietinum", "kabuli chickpea", "desi chickpea"],
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
    "dolichos_bean": ["dolichos bean", "lablab", "sem", "hyacinth bean",
                      "country bean"],
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

# alias -> compiled matcher; short aliases need word boundaries (avoid
# matching "gram" inside "graminaceous"); also avoid hyphen joins like
# "PEA-LIKE" via lookarounds.
ALIAS_PATTERNS = {}
for _c, _aliases in CROPS.items():
    _plist = []
    for _a in _aliases:
        _n = _a.lower()
        if len(_n) <= 5:
            _plist.append((_a,
                           re.compile(r"(?<![\w-])" + re.escape(_n) + r"(?![\w-])"),
                           True))
        else:
            _plist.append((_a, None, False))
    ALIAS_PATTERNS[_c] = _plist

# ============================================================================
# Small utilities
# ============================================================================

def norm(s):
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", str(s)).lower()
    return re.sub(r"\s+", " ", s).strip()


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
    raise SystemExit("unknown source id: %s (valid: %s)"
                      % (sid, [s["id"] for s in SOURCES]))

# ============================================================================
# Download
# ============================================================================
def download():
    import requests
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    for s in SOURCES:
        dest = PDF_DIR / s["file"]
        if dest.exists() and dest.stat().st_size == s["size"]:
            log.info("cached OK: %s (%d bytes)", s["file"], s["size"])
            continue
        log.info("downloading %s ...", s["file"])
        for attempt in (1, 2):
            try:
                with requests.get(s["url"], stream=True, timeout=90,
                                  headers={"User-Agent": "Mozilla/5.0"}) as r:
                    r.raise_for_status()
                    tmp = dest.with_suffix(".part")
                    with open(tmp, "wb") as f:
                        for chunk in r.iter_content(65536):
                            f.write(chunk)
                if tmp.stat().st_size == s["size"]:
                    tmp.replace(dest)
                    log.info("saved %s (%d bytes)", s["file"], s["size"])
                    break
                log.warning("size mismatch %s: got %d expected %d",
                            s["file"], tmp.stat().st_size, s["size"])
            except Exception as e:
                log.warning("attempt %d failed for %s: %s", attempt, s["file"], e)
        else:
            raise SystemExit("could not download %s — check network" % s["file"])


# ============================================================================
# Docling conversion layer
# ============================================================================
_DEVICE = None
_FORCE_CPU = False
_CONVERTER = None


def torch_device():
    global _DEVICE
    if _DEVICE is not None:
        return _DEVICE
    if _FORCE_CPU:
        _DEVICE = "cpu"
        return _DEVICE
    try:
        import torch
        if torch.cuda.is_available():
            _DEVICE = "cuda"
        else:
            _DEVICE = "cpu"
    except Exception:
        _DEVICE = "cpu"
    log.info("docling device: %s", _DEVICE)
    return _DEVICE


def get_converter():
    global _CONVERTER
    if _CONVERTER is not None:
        return _CONVERTER
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
        popts.accelerator_options = AcceleratorOptions(
            num_threads=8, device=dev)
    except Exception:
        pass
    fmt = PdfFormatOption(pipeline_options=popts)
    _CONVERTER = DocumentConverter(
        format_options={InputFormat.PDF: fmt})
    log.info("converter ready (device=%s)", dev)
    return _CONVERTER


def _label(item):
    lab = getattr(item, "label", None)
    if lab is None:
        return ""
    return (getattr(lab, "value", str(lab)) if lab is not None else "").lower()


def _prov(item):
    prov = getattr(item, "prov", None) or []
    if not prov:
        return None, None
    pg = getattr(prov[0], "page_no", None)
    conf = getattr(prov[0], "confidence", None)
    return pg, (float(conf) if conf is not None else None)


def table_to_md(item, doc):
    for call in ("kw", "pos", "raw"):
        try:
            if call == "kw":
                return item.export_to_markdown(doc=doc)
            if call == "pos":
                return item.export_to_markdown(doc)
            if call == "raw":
                d = getattr(item, "data", None)
                return "<!-- table not rendered -->\n" + str(d)[:500] if d else "<!-- table not rendered -->"
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


def walk_to_index(doc, imgdir):
    items, counters = [], {"pic": 0}
    try:
        seq = doc.iterate_items(traverse_pictures=True)
    except TypeError:
        seq = doc.iterate_items()
    SKIP = {"page_header", "page_footer", "footnote", "form",
            "checkbox_selected", "checkbox_unselected", "key_value_region"}
    for item, lvl in seq:
        lab = _label(item)
        if lab in SKIP:
            continue
        pg, conf = _prov(item)
        txt = (getattr(item, "text", "") or "").strip()
        if lab in ("section_header", "title"):
            items.append({"k": "h", "lvl": int(lvl or 1), "t": txt,
                          "md": None, "img": None, "cap": None,
                          "pg": pg, "conf": conf})
        elif lab == "list_item":
            items.append({"k": "li", "lvl": None, "t": txt,
                          "md": None, "img": None, "cap": None,
                          "pg": pg, "conf": conf})
        elif lab == "table":
            md = table_to_md(item, doc)
            items.append({"k": "tbl", "lvl": None, "t": None, "md": md,
                          "img": None, "cap": None, "pg": pg, "conf": conf})
        elif lab == "picture":
            name = save_picture(item, pg, imgdir, counters)
            items.append({"k": "img", "lvl": None, "t": None, "md": None,
                          "img": name, "cap": None, "pg": pg, "conf": conf})
        elif lab == "caption":
            for prev in reversed(items):
                if prev["k"] in ("tbl", "img"):
                    if prev.get("cap"):
                        prev["cap"] = prev["cap"].strip() + " " + txt
                    else:
                        prev["cap"] = txt
                    break
        else:
            if txt:
                items.append({"k": "p", "lvl": None, "t": txt,
                              "md": None, "img": None, "cap": None,
                              "pg": pg, "conf": conf})
    # fallback if traverse_pictures wasn't supported / yielded nothing
    if not any(it["k"] == "img" for it in items):
        pics = getattr(doc, "pictures", [])
        if isinstance(pics, dict):
            pics = list(pics.values())
        for item in pics:
            prov = getattr(item, "prov", None) or []
            pg = getattr(prov[0], "page_no", None) if prov else None
            name = save_picture(item, pg, imgdir, counters)
            if name:
                items.append({"k": "img", "lvl": None, "t": None,
                              "md": None, "img": name, "cap": None,
                              "pg": pg, "conf": None})
    # drop running headers: same short heading appearing on >=4 pages
    c = Counter(norm(it["t"]) for it in items if it["k"] == "h")
    items = [it for it in items if not (
        it["k"] == "h" and len(it.get("t") or "") <= 45 and
        c[norm(it["t"])] >= 4)]
    return items


def render_markdown(items, imgprefix, i0=0, i1=None, heading_shift=0,
                    page_tags=True):
    if i1 is None:
        i1 = len(items) - 1
    out = []
    for i in range(i0, i1 + 1):
        it = items[i]
        pg = it.get("pg")
        if it["k"] == "h":
            lvl = min(max((it.get("lvl") or 1) + heading_shift, 1), 6)
            out.append("%s %s" % ("#" * lvl, it["t"]))
            if page_tags and pg is not None:
                out.append("<!-- p. %d -->" % pg)
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
PAT_DOTS = re.compile(r"^(.{3,70}?)[\s._·•\u2026—–]{2,}(\d{1,4})\s*$")
PAT_PLAIN = re.compile(r"^\s*(?:(?:unit|part|chapter|lesson)\s*[-–.]?\s*"
                        r"[ivx\d]*[.\s\-–:]*\s*)?(?:\d{1,2}[.)]\s*)?"
                        r"([A-Za-z][A-Za-z ()'’/-]{2,55}?)\s+(\d{1,4})$")


def match_crop(text):
    """Return (crop_key, score, matched_alias) or (None, 0.0, None)."""
    t = norm(text)
    if len(t) < 3 or len(t) > 60:
        return None, 0.0, None
    # exact / word-boundary pass
    best_c, best_s, best_len = None, 0.0, 0
    for crop, patterns in ALIAS_PATTERNS.items():
        for alias, rx, is_word in patterns:
            a = norm(alias)
            if is_word:
                if rx.search(t):
                    if (100, len(a)) > (best_s, best_len):
                        best_c, best_s, best_len = crop, 100.0, len(a)
            else:
                if a in t:
                    if (100, len(a)) > (best_s, best_len):
                        best_c, best_s, best_len = crop, 100.0, len(a)
    if best_s >= 100:
        return best_c, best_s, None
    # fuzzy fallback (only for longer aliases)
    if len(t) > 60:
        return None, 0.0, None
    best_c, best_s = None, 0.0
    for crop, patterns in ALIAS_PATTERNS.items():
        for alias, rx, is_word in patterns:
            if len(alias) >= 6:
                s = fuzz.partial_ratio(norm(alias), t)
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
        if pg <= p1:
            i1 = i
    if i0 is None:
        i0 = 0
    if i1 is None or i1 < i0:
        return None
    return (i0, i1)


def segment(index, src):
    """Return (segments, toc, unmatched_headings, toc_only)."""
    items = index["items"]
    sid = src["id"]
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
    # 3. candidate segments from heading marks
    cands = []
    if marks:
        if marks[0]["i"] > 0:
            cands.append({"i0": 0, "i1": marks[0]["i"] - 1,
                          "crop": None, "conf": 0.0, "ev": "leading"})
        for m, nxt in zip(marks, marks[1:]):
            # TOC agreement boost
            pg = m["pg"]
            ev = "heading"
            conf = m["score"] / 100.0
            if pg is not None and m["crop"] in toc_crops:
                for e in toc_crops[m["crop"]]:
                    if abs(e["page"] - pg) <= 2:
                        conf = max(conf, 0.98)
                        ev = "heading+toc"
                        break
            cands.append({"i0": m["i"], "i1": nxt["i"] - 1,
                          "crop": m["crop"], "conf": conf, "ev": ev,
                          "head": m["title"]})
        last = marks[-1]
        pg = last["pg"]
        ev = "heading"
        conf = last["score"] / 100.0
        if pg is not None and last["crop"] in toc_crops:
            for e in toc_crops[last["crop"]]:
                if abs(e["page"] - pg) <= 2:
                    conf = max(conf, 0.98)
                    ev = "heading+toc"
                    break
        cands.append({"i0": last["i"], "i1": len(items) - 1,
                      "crop": last["crop"], "conf": conf, "ev": ev,
                      "head": last["title"]})
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
            p0 = e["page"]
            p1 = (entries[j + 1]["page"] - 1) if j + 1 < len(entries) else None
            span = _pages_span_to_items(items, p0, p1)
            if span:
                i0, i1 = span
                # check overlap with existing higher-conf crop
                cands.append({"i0": i0, "i1": i1, "crop": crop,
                              "conf": 0.55, "ev": "toc", "head": e["title"]})
    # 5. Manual overrides (force / exclude)
    ov = OVERRIDES.get(src["id"], {})
    # exclude crops
    if "exclude_crops" in ov:
        ex = set(ov["exclude_crops"])
        cands = [c for c in cands if c["crop"] not in ex]
    # force page-range segments (conf 1.0)
    for crop, p0, p1 in ov.get("force", []):
        span = _pages_span_to_items(items, p0, p1)
        if span:
            i0, i1 = span
            cands.append({"i0": i0, "i1": i1, "crop": crop,
                          "conf": 1.0, "ev": "manual", "head": ""})
    # 6. Assignment fill (highest conf wins per index)
    cands.sort(key=lambda c: c["conf"], reverse=True)
    assign = {}  # idx -> (crop, conf, ev, head)
    for c in cands:
        if c["i0"] > c["i1"]:
            continue
        for idx in range(c["i0"], c["i1"] + 1):
            if idx not in assign:
                assign[idx] = (c["crop"], c["conf"], c["ev"], c.get("head", ""))
    # 7. Build contiguous final segments
    segs = []
    cur_crop = cur_conf = cur_ev = cur_head = None
    cur_i0 = None
    for i in range(len(items)):
        a = assign.get(i)
        crop = a[0] if a else None
        conf = a[1] if a else 0.0
        ev = a[2] if a else ""
        head = a[3] if a else ""
        if cur_crop == crop and cur_i0 is not None:
            continue  # extend current
        if cur_crop is not None:
            segs.append({"crop": cur_crop, "i0": cur_i0, "i1": i - 1,
                         "conf": cur_conf, "ev": cur_ev, "head": cur_head})
        cur_crop, cur_conf, cur_ev, cur_head = crop, conf, ev, head
        cur_i0 = i
    if cur_crop is not None:
        segs.append({"crop": cur_crop, "i0": cur_i0, "i1": len(items) - 1,
                     "conf": cur_conf, "ev": cur_ev, "head": cur_head})
    # 8. compute page spans and drop empty
    final = []
    for s in segs:
        if s["i0"] > s["i1"]:
            continue
        pgs = [it.get("pg") for it in items[s["i0"]:s["i1"] + 1] if it.get("pg") is not None]
        s["p0"], s["p1"] = (min(pgs), max(pgs)) if pgs else (None, None)
        final.append(s)
    # 9. unmatched headings for report
    unmatched = [{"pg": it.get("pg"), "t": it["t"]}
                 for it in items if it["k"] == "h" and
                 not any(c["i0"] <= items.index(it) <= c["i1"] and c["crop"]
                         for c in final)]
    # 10. toc-only crops (for report)
    toc_only = sorted([c for c in toc_crops if c not in marked])
    return final, toc, unmatched, toc_only

# ============================================================================
# QA checks
# ============================================================================
GARBLE_RE = re.compile(
    r"(?:\b\d+[OIl]{1,2}\d*\b)|"         # 4O, 1OO, 5l6...
    r"(?:\b(?=[OIl]{2,}\b)(?=[^\s]*[Ol])[OIl]{2,}\b)|"  # lOO, OIl...
    r"(?:\b[OIl]\d{1,3}\b)|(?:\b\d{1,3}[OIl]\b)"  # l6, 5l
)
LOW_CONF_THRESH = 0.60


def qa_slice(items):
    """Return list of {'pg': int, 'issue': str} for a file."""
    out = []
    for it in items:
        pg = it.get("pg")
        if it["k"] == "tbl" and it["md"]:
            if GARBLE_RE.search(it["md"]):
                out.append({"pg": pg, "issue": "possible garbled numbers in table"})
        if it["k"] == "img" and not it["img"]:
            out.append({"pg": pg, "issue": "figure not exported"})
        c = it.get("conf")
        if c is not None and c < LOW_CONF_THRESH:
            out.append({"pg": pg, "issue": "low OCR confidence (%.2f)" % c})
    return out


def qa_source_pages(items):
    """Return list of page numbers with very little extracted text (likely OCR failures)."""
    per = {}
    for it in items:
        pg = it.get("pg") or 0
        L = len(it.get("t") or "") + len(it.get("md") or "")
        per[pg] = per.get(pg, 0) + L
    return sorted([p for p, v in per.items() if v < 25])


# ============================================================================
# Mentions + emit
# ============================================================================
def find_mentions(items, main_segs, crop, items_low):
    """Return list of mention dicts outside main_segs for crop."""
    in_main = set()
    for s in main_segs:
        in_main.update(range(s["i0"], s["i1"] + 1))
    aliases = CROPS[crop]
    res = []
    last_head = ""
    for i, low in items_low:
        if i in in_main:
            continue
        it = items[i]
        pg = it.get("pg")
        if pg is not None and pg <= TOC_SCAN_PAGES:
            continue
        if it["k"] not in ("p", "li", "tbl"):
            continue
        text = low
        if not text:
            continue
        hit = False
        for a in aliases:
            an = norm(a)
            if len(an) <= 5:
                if re.search(r"(?<![\w-])" + re.escape(an) + r"(?![\w-])", text):
                    hit = True
                    break
            else:
                if an in text:
                    hit = True
                    break
        if hit:
            res.append({"pg": it.get("pg"), "ctx": last_head,
                        "k": it["k"], "t": it.get("t"),
                        "md": it.get("md")})
            if len(res) >= MAX_MENTIONS:
                break
        if it["k"] == "h":
            last_head = it["t"]
    return res


def emit_source(src, index, segs, items_low):
    """Write out/<crop>_<source_id>.md files and general_<id>.md.
    Returns (manifest_entries list, per_file_qa dict, copy_imgs_set)."""
    sid = src["id"]
    items = index["items"]
    (OUT / "images" / sid).mkdir(parents=True, exist_ok=True)
    # group crop segments
    by_crop = {}
    for s in segs:
        if s["crop"]:
            by_crop.setdefault(s["crop"], []).append(s)
    gen_segs = [s for s in segs if not s["crop"]]
    manifest = []
    per_file_qa = {}
    used_imgs = set()
    # crop files
    for crop, seglist in by_crop.items():
        fname = "%s_%s.md" % (crop, sid)
        # front-matter
        pgs = [it.get("pg") for s in seglist for it in items[s["i0"]:s["i1"] + 1] if it.get("pg") is not None]
        p0, p1 = (min(pgs), max(pgs)) if pgs else (None, None)
        disp = crop.replace("_", " ").title()
        mentions = find_mentions(items, seglist, crop, items_low)
        # render body
        body = []
        body.append("# %s — %s\n" % (disp, src["title"]))
        body.append("> Auto-extracted from government extension sources by CropBot pipeline. "
                     "Content is faithful to the source; see front-matter for provenance.\n")
        for k, s in enumerate(seglist, 1):
            body.append("## Main content — Part %d (pp. %s–%s)\n" %
                        (k, s["p0"] or "?", s["p1"] or "?"))
            body.append(render_markdown(items, "images/%s/" % sid,
                                        s["i0"], s["i1"], heading_shift=1) + "\n")
        body.append("## Other mentions in this source\n")
        if mentions:
            for m in mentions:
                ctx = " — in “%s”" % m["ctx"] if m["ctx"] else ""
                body.append("### p. %d%s\n\n" % (m["pg"] or 0, ctx))
                if m["k"] == "tbl" and m["md"]:
                    body.append(m["md"] + "\n")
                else:
                    body.append((m["t"] or "") + "\n")
        else:
            body.append("_No other mentions of this crop were found in this source._\n")
        # collect image files used in main segs
        for s in seglist:
            for it in items[s["i0"]:s["i1"] + 1]:
                if it["k"] == "img" and it["img"]:
                    used_imgs.add((sid, it["img"]))
        # QA
        qa = qa_slice([it for s in seglist for it in items[s["i0"]:s["i1"] + 1]] + mentions)
        qa_status = "clean" if not qa else "flagged (%d)" % len(qa)
        per_file_qa[fname] = qa
        # write
        out = []
        out.append("---\n")
        out.append("crop: %s\n" % crop)
        out.append("crop_display: %s\n" % disp)
        out.append("source_id: %s\n" % sid)
        out.append("source_title: %s\n" % yv(src["title"]))
        out.append("publisher: %s\n" % yv(src["publisher"]))
        out.append("source_url: %s\n" % yv(src["url"]))
        out.append("rights_note: %s\n" % yv(src["rights_note"]))
        out.append("page_range: %s\n" % ("%d-%d" % (p0, p1) if p0 and p1 else "unknown"))
        out.append("main_sections: %d\n" % len(seglist))
        out.append("mentions: %d\n" % len(mentions))
        out.append("extracted_with: docling %s (TableFormer accurate, OCR on)\n" %
                   (index.get("docling_version", "?")))
        out.append("extracted_on: %s\n" % date.today().isoformat())
        out.append("qa_status: %s\n" % qa_status)
        out.append("---\n\n")
        out.extend(body)
        (OUT / fname).write_text("".join(out), encoding="utf-8")
        manifest.append({
            "file": fname,
            "crop": crop,
            "source": sid,
            "page_range": "%d-%d" % (p0, p1) if p0 and p1 else "unknown",
            "main_sections": len(seglist),
            "mentions": len(mentions),
            "sha256": sha256_file(OUT / fname),
            "qa_status": qa_status,
        })
    # general file
    if gen_segs:
        gfname = "general_%s.md" % sid
        body = ["# General chapters — %s\n" % src["title"],
                "> Chapters not matched to a specific crop (intro, soils, cropping systems, etc.).\n"]
        for s in gen_segs:
            body.append("## (pp. %s–%s)\n" % (s["p0"] or "?", s["p1"] or "?"))
            body.append(render_markdown(items, "images/%s/" % sid,
                                        s["i0"], s["i1"], heading_shift=1) + "\n")
        # front-matter minimal
        out = ["---\nsource_id: %s\nsource_title: %s\n---\n\n" % (sid, yv(src["title"]))]
        out.extend(body)
        (OUT / gfname).write_text("".join(out), encoding="utf-8")
        manifest.append({
            "file": gfname,
            "crop": None,
            "source": sid,
            "page_range": "mixed",
            "main_sections": len(gen_segs),
            "mentions": 0,
            "sha256": sha256_file(OUT / gfname),
            "qa_status": "n/a",
        })
    return manifest, per_file_qa, used_imgs


def emit_all(ids=None):
    """Full emit: segment + write files + reports."""
    # load all converted indexes
    indexes = {}
    for src in SOURCES:
        if ids and src["id"] not in ids:
            continue
        p = CONV / ("%s.index.json" % src["id"])
        if not p.exists():
            log.warning("no index for %s — run --convert --source %s first",
                        src["id"], src["id"])
            continue
        indexes[src["id"]] = json.loads(p.read_text())
    if not indexes:
        raise SystemExit("no converted indexes found")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "images").mkdir(parents=True, exist_ok=True)
    # wipe old outputs
    for p in OUT.glob("*.md"): p.unlink()
    for p in OUT.glob("*.json"): p.unlink()
    shutil.rmtree(OUT / "images", ignore_errors=True)
    (OUT / "images").mkdir(parents=True, exist_ok=True)
    # process
    all_manifest = []
    all_qa = {}
    all_used = set()
    segs_by_src = {}
    for sid, index in indexes.items():
        src = source_by_id(sid)
        log.info("segmenting %s ...", sid)
        segs, toc, unmatched, toc_only = segment(index, src)
        segs_by_src[sid] = (segs, toc, unmatched, toc_only)
        items = index["items"]
        items_low = [(i, norm(it.get("t") or "")) for i, it in enumerate(items)
                     if it["k"] in ("p", "li", "tbl")]
        mf, qa, used = emit_source(src, index, [s for s in segs if s["crop"]], items_low)
        all_manifest.extend(mf)
        all_qa.update(qa)
        all_used.update(used)
    # copy used images to out/images/<sid>/
    for sid, name in all_used:
        s = CONV / "images" / sid / name
        d = OUT / "images" / sid / name
        if s.exists():
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, d)
    # reports
    write_reports(segs_by_src, all_manifest, all_qa)
    log.info("emit complete: %d files", len(all_manifest))


def write_reports(segs_by_src, manifest, all_qa):
    # segmentation_report.md
    lines = ["# Segmentation report", "",
             "Generated %s\n" % date.today().isoformat()]
    for sid, (segs, toc, unmatched, toc_only) in segs_by_src.items():
        lines.append("## Source: %s\n" % sid)
        lines.append("TOC entries detected: %d\n" % len(toc))
        lines.append("Crops found by heading: %d\n" %
                     len([s for s in segs if s["crop"]]))
        lines.append("Unmatched headings (potential missing aliases or general chapters): %d\n"
                     % len(unmatched))
        lines.append("Crops in TOC but without heading match: %s\n" %
                     (", ".join(toc_only) if toc_only else "none"))
        lines.append("\n### Segments")
        lines.append("| crop | i0 | i1 | p0 | p1 | conf | evidence |")
        lines.append("|---|---|---|---|---|---|---|")
        for s in segs:
            crop = s["crop"] or "GENERAL"
            lines.append("| %s | %d | %d | %s | %s | %.2f | %s |" %
                         (crop, s["i0"], s["i1"],
                          s["p0"] or "?", s["p1"] or "?",
                          s["conf"], s["ev"]))
        if unmatched:
            lines.append("\n### Unmatched headings (first 50)")
            for u in unmatched[:50]:
                lines.append("- p.%s: %s" % (u["pg"] or "?", u["t"]))
        lines.append("\n---\n")
    # how to fix
    lines.append("## Fixing issues")
    lines.append("1. Add missing aliases to `CROPS` dict in extract.py")
    lines.append("2. Add manual page boundaries in `OVERRIDES` dict:")
    lines.append("   `OVERRIDES = {\"icar_rabi\": {\"exclude_crops\": [...], "
                 "\"force\": [[\"crop\", p0, p1]]}}`")
    lines.append("3. Re-run `--emit --source <id>` (fast, no re-OCR)")
    (OUT / "segmentation_report.md").write_text("\n".join(lines), encoding="utf-8")
    # qa_report.md
    qlines = ["# QA report", "", "Generated %s\n" % date.today().isoformat()]
    for fname, issues in all_qa.items():
        if not issues:
            continue
        qlines.append("## %s (%d issues)" % (fname, len(issues)))
        for isu in issues:
            qlines.append("- p.%s: %s" % (isu["pg"] or "?", isu["issue"]))
        qlines.append("")
    (OUT / "qa_report.md").write_text("\n".join(qlines), encoding="utf-8")
    # manifest.json
    m = {
        "generated_on": date.today().isoformat(),
        "extracted_with": "docling (TableFormer accurate, OCR on)",
        "sources": [{k: s[k] for k in ("id", "title", "url", "publisher", "rights_note")}
                    for s in SOURCES],
        "files": manifest,
    }
    (OUT / "manifest.json").write_text(
        json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    # README.md
    r = [
        "# CropBot extracted corpus",
        "",
        "Generated %s by `extract.py --all`\n" % date.today().isoformat(),
        "## File naming",
        "- `<crop>_<source_id>.md` — one file per crop per source",
        "- `general_<source_id>.md` — non-crop chapters (intro, soils, etc.)",
        "- `images/<source_id>/` — figure PNGs referenced from the .md files",
        "- `segmentation_report.md` — audit this to verify crop boundaries",
        "- `qa_report.md` — suspected OCR/number issues",
        "- `manifest.json` — machine-readable index for KG ingestion",
        "",
        "## Sources (all government-published, free farmer-education distribution)",
        "| id | title | publisher | rights |",
        "|---|---|---|---|",
    ]
    for s in SOURCES:
        r.append("| %s | %s | %s | %s |" %
                 (s["id"], s["title"], s["publisher"], s["rights_note"]))
    r.append("")
    r.append("## Front-matter fields")
    r.append("`crop`, `crop_display`, `source_id`, `source_title`, `publisher`, "
              "`source_url`, `rights_note`, `page_range`, `main_sections`, "
              "`mentions`, `extracted_with`, `extracted_on`, `qa_status`")
    r.append("")
    r.append("## Images")
    r.append("Figure PNGs are under `images/<source_id>/`. They **must travel with the .md files** "
              "or all image links will be broken. Original PDFs are kept locally and are NOT "
              "part of this deliverable (rights guardrail).")
    r.append("")
    r.append("## Re-run")
    r.append("```bash")
    r.append("python extract.py --all          # full pipeline")
    r.append("python extract.py --convert --source <id>  # re-convert one book")
    r.append("python extract.py --emit --source <id>     # re-segment+emit (fast)")
    r.append("```")
    (OUT / "README.md").write_text("\n".join(r), encoding="utf-8")

# ============================================================================
# Conversion orchestration
# ============================================================================
def clip_pdf(src_pdf, n_pages, out_pdf):
    """Write first n_pages of src_pdf to out_pdf using pypdf."""
    from pypdf import PdfReader, PdfWriter
    r = PdfReader(str(src_pdf))
    w = PdfWriter()
    for i in range(min(n_pages, len(r.pages))):
        w.add_page(r.pages[i])
    out_pdf = Path(out_pdf)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    with open(out_pdf, "wb") as f:
        w.write(f)
    return out_pdf


def convert_source(src, pdf_path, save=True, tag=""):
    """Run docling on pdf_path, return index dict. If save, writes .index.json + .md + images."""
    conv = get_converter()
    log.info("converting %s (%s) ...", src["id"], Path(pdf_path).name)
    t0 = time.time()
    result = conv.convert(str(pdf_path))
    doc = result.document
    imgdir = CONV / "images" / src["id"]
    imgdir.mkdir(parents=True, exist_ok=True)
    items = walk_to_index(doc, imgdir)
    pages = len(getattr(doc, "pages", {}) or {}) or max(
        [it.get("pg") or 0 for it in items], default=0)
    dver = None
    try:
        import docling as _d
        dver = getattr(_d, "__version__", None)
    except Exception:
        pass
    index = {
        "source_id": src["id"],
        "title": src["title"],
        "url": src["url"],
        "publisher": src["publisher"],
        "rights_note": src["rights_note"],
        "converted_on": date.today().isoformat(),
        "device": _DEVICE,
        "docling_version": dver,
        "pages": pages,
        "items": items,
    }
    dt = time.time() - t0
    tbl = sum(1 for it in items if it["k"] == "tbl")
    img = sum(1 for it in items if it["k"] == "img")
    log.info("done %s in %.0fs: %d items, %d tables, %d images",
             src["id"], dt, len(items), tbl, img)
    if save:
        (CONV / ("%s.index.json" % src["id"])).write_text(
            json.dumps(index, ensure_ascii=False, default=str), encoding="utf-8")
        md = render_markdown(items, "images/%s/" % src["id"])
        (CONV / ("%s.md" % src["id"])).write_text(
            "---\ntitle: %s\nsource_id: %s\n---\n\n" %
            (yv(src["title"]), src["id"]) + md, encoding="utf-8")
    return index


def convert_all(ids=None):
    """Full conversion of all (or subset) sources, with CUDA OOM fallback."""
    global _FORCE_CPU, _CONVERTER
    for src in SOURCES:
        if ids and src["id"] not in ids:
            continue
        pdf = PDF_DIR / src["file"]
        if not pdf.exists():
            log.error("missing %s — run --download first", pdf.name)
            continue
        try:
            convert_source(src, pdf, save=True)
        except Exception as e:
            if "CUDA" in str(e) or "out of memory" in str(e).lower():
                log.warning("CUDA OOM on %s — retrying on CPU (slower)",
                            src["id"])
                _FORCE_CPU = True
                _CONVERTER = None
                convert_source(src, pdf, save=True)
            else:
                log.error("FAILED %s: %s", src["id"], e)


def sanity(sid, n_pages):
    """Quick test: clip first n_pages, convert, print preview + match_crop self-test."""
    src = source_by_id(sid)
    clip = clip_pdf(PDF_DIR / src["file"], n_pages, TMP / ("%s_%dp.pdf" % (sid, n_pages)))
    idx = convert_source(src, clip, save=False, tag="sanity")
    items = idx["items"]
    # kind counts
    from collections import Counter
    kcount = Counter(it["k"] for it in items)
    print("\n=== SANITY %s (first %d pages) ===" % (sid, n_pages))
    print("kinds:", dict(kcount), "| pages:", idx["pages"])
    print("\nHeadings found:")
    for it in items:
        if it["k"] == "h":
            print("  p.%s lvl%s  %s" % (it.get("pg"), it.get("lvl"), (it["t"] or "")[:70]))
    print("\nFirst text items:")
    for it in items:
        if it["k"] == "p":
            print("  p.%s  %s" % (it.get("pg"), (it["t"] or "")[:90]))
    toc = parse_toc(items)
    print("\nTOC entries:", len(toc))
    for e in toc[:12]:
        print("  p.%d: %s" % (e["page"], e["title"]))
    tables = [it for it in items if it["k"] == "tbl"]
    if tables:
        print("\nFirst table (first 300 chars):")
        print(tables[0]["md"][:300])
    imgs = [it for it in items if it["k"] == "img"]
    print("\nImages saved:", len(imgs))
    # match_crop self-test
    print("\n=== match_crop self-test ===")
    tests = ["RICE (Oryza sativa)", "WHEAT (Triticum aestivum)",
             "BLACK GRAM (Vigna mungo)", "BENGAL GRAM",
             "SOYBEAN", "TOMATO (Lycopersicon esculentum)",
             "UNIT-III OILSEEDS", "MANURES AND FERTILIZERS"]
    for t in tests:
        c, s, _ = match_crop(t)
        print("  '%s' -> crop=%s score=%.1f" % (t, c, s))

# ============================================================================
# CLI entry
# ============================================================================
def main():
    ap = argparse.ArgumentParser(description="CropBot source extraction pipeline")
    ap.add_argument("--download", action="store_true", help="fetch the 4 source PDFs")
    ap.add_argument("--sanity", nargs=2, metavar=("SRC_ID", "PAGES"),
                    help="quick test conversion of SRC_ID first PAGES pages")
    ap.add_argument("--convert", action="store_true",
                    help="full docling conversion (slow, GPU)")
    ap.add_argument("--emit", action="store_true",
                    help="segment + emit + reports (fast, re-runnable)")
    ap.add_argument("--all", action="store_true", help="everything")
    ap.add_argument("--source", help="limit --convert/--emit to this source id")
    ap.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    ids = [a.source] if a.source else None
    if a.download:
        download()
    if a.sanity:
        sid, n = a.sanity
        sanity(sid, int(n))
    if a.convert:
        convert_all(ids)
    if a.emit:
        emit_all(ids)
    if a.all:
        download()
        convert_all()
        emit_all()
    if not (a.download or a.sanity or a.convert or a.emit or a.all):
        ap.print_help()


if __name__ == "__main__":
    main()
