# CropBot extraction

Turns the PDFs in `../BooksData` into one markdown file per crop per book (`out/<crop>_<source_id>.md`), ready for knowledge-graph extraction. It runs locally on the GX10 GPU.

There are two ways to run it:

| | Script | Sources | Use |
|---|---|---|---|
| **MVP** | `../extract.py` (the original, unchanged) | 4 fixed books (TNAU Agriculture + Horticulture, ICAR Kharif + Rabi e-courses) | MVP run now |
| **Project** | `extraction/extract.py` (this folder) | Every PDF in `BooksData`, with metadata from `sources.toml` | The project going forward |

Both use the uv environment in this folder.

## 1. Set up on the GX10 (once)

The GX10 is an ARM64 machine (NVIDIA GB10) with CUDA 13. `pyproject.toml` pulls `torch`/`torchvision` from PyTorch's `cu130` index, which has ARM64 Linux wheels. `uv.lock` pins `torch 2.14.1+cu130` and Python 3.12.

```bash
# install uv if the image doesn't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

cd CropBot/extraction
uv sync

# check the GPU is visible: expect a 2.14.x+cu130 version, CUDA 13.x, True, and the GB10
uv run python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

If `torch.version.cuda` doesn't start with `13`, the wrong wheel was installed. Run `uv sync --reinstall-package torch` and check again.

The first conversion downloads docling's layout and table models, plus EasyOCR models when a book needs them, from Hugging Face. The POD needs internet for that first run.

## 2. MVP run: the original script, 4 sources

Run from the repo root so the script works exactly as written. It writes `sources/`, `converted/` and `out/` in the repo root.

```bash
cd CropBot

# optional: 3 of the 4 PDFs are already in BooksData with the exact sizes the
# script expects, so copying them skips their download (only Horticulture is fetched)
mkdir -p sources/pdfs
cp BooksData/AGRICULTURE.pdf sources/pdfs/tnau_agriculture.pdf
cp BooksData/Field-Crop-Kharif.pdf sources/pdfs/icar_kharif.pdf
cp BooksData/FIELD-CROPS-RABI-with-Multiple-choice-questions.pdf sources/pdfs/icar_rabi.pdf

uv run --project extraction python extract.py --all
```

Known limits of the original script, all fixed in the project version:
- Repeated section headings ("CROP PROTECTION", "SEASON AND VARIETIES") are deleted as page headers.
- Chapter titles that docling labels as captions get attached to the previous table, so crop boundaries can be late.
- Headings like "Lime requirement" (→ citrus) or "Gram panchayat" (→ chickpea) start false crop sections.
- `--emit --source X` deletes every other source's output.
- `general_<id>.md` is never written.

Check `out/segmentation_report.md` before using its output.

## 3. Project run: all of BooksData

```bash
cd CropBot/extraction

uv run extract.py --list                          # what will be processed, duplicates, unregistered files
uv run extract.py --sanity tnau_agriculture 10    # quick test on 10 pages
uv run extract.py --all --source tnau_agriculture # one book: convert + emit
uv run extract.py --all                           # every included book
```

- **Conversion is cached** per book (by PDF hash and OCR settings). Re-running skips finished books; `--force` redoes them.
- **`--emit` is fast** and re-runnable after fixing aliases or overrides. `--emit --source X` replaces only X's files.
- **Another folder:** `--books-dir /path/to/pdfs` or `CROPBOT_BOOKS_DIR=/path/to/pdfs` points it elsewhere.

### Adding or changing books

New book PDFs are never committed. Each book is recorded in the source registry by its URL and sha256, so anyone can download it and check it is the same file. `BooksData/*.pdf` and `sources/pdfs/` are in `.gitignore`; the PDFs already tracked there stay as they are.

1. Download the PDF into your local `BooksData` folder. Git ignores it.
2. Add an entry to the source registry (`sources.toml`): `url` and `sha256`, plus id, type, region, season, language, include, and `crop` if the whole book is about one crop.
3. Run `uv run extract.py --list` to check it, then `uv run extract.py --all --source <id>`.

A PDF without an entry is still processed with default settings and is flagged as "unregistered" by `--list`.

### Hindi and scanned books
- **Image-only PDFs** (the millet booklets, the pulses handbook) are OCRed automatically. Set `ocr_lang = ["hi", "en"]` for Hindi.
- **Legacy-font Hindi** (`RabiCrops.pdf`) has a garbage text layer, so it needs `ocr = "force"`. The segmentation report warns when a book's text looks like this.
- **Hindi books need `crop` set.** English crop names can't match Hindi headings, so a Hindi book without `crop` goes to `general_<id>.md`.
- **Three millet booklets still need `crop`:** Kodra, Sawaan and Swank. Confirm each from the OCR output.

## Output

```
out/
  <crop>_<source_id>.md        one per crop per book; front-matter has source, region, season, doc type, page range
  general_<source_id>.md       chapters not tied to one crop
  images/<source_id>/          figures referenced from the .md files
  reports/segmentation_<id>.md crop boundaries: check these first
  reports/qa_<id>.md           suspected garbled numbers
  manifest.json                index of all files, for knowledge-graph ingestion
converted/<source_id>.index.json   every block with page number and bounding box (for SourceSpan provenance)
```

Every page change in a `.md` file is marked `<!-- p. N -->`, so each fact can be traced to its page.
