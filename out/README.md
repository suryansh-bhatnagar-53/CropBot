# CropBot extracted corpus

Generated 2026-10-19 by `extract.py --all`

## File naming
- `<crop>_<source_id>.md` — one file per crop per source
- `general_<source_id>.md` — non-crop chapters (intro, soils, etc.)
- `images/<source_id>/` — figure PNGs referenced from the .md files
- `segmentation_report.md` — audit this to verify crop boundaries
- `qa_report.md` — suspected OCR/number issues
- `manifest.json` — machine-readable index for KG ingestion

## Sources (all government-published, free farmer-education distribution)
| id | title | publisher | rights |
|---|---|---|---|
| icar_kharif | Field Crops (Kharif) - ICAR e-course | ICAR e-course (TNAU/SAU consortium, NAIP); mirrored by agrimoon.com | Free ICAR e-course teaching material; attribute ICAR/TNAU, not the mirror |
| icar_rabi | Field Crops (Rabi) - ICAR e-course | ICAR e-course (TNAU/SAU consortium, NAIP); mirrored by agrimoon.com | Free ICAR e-course teaching material; attribute ICAR/TNAU, not the mirror |
| tnau_agriculture | Agriculture - TNAU production guide | Tamil Nadu Agricultural University (agritech extension portal) | State agricultural university extension publication, free farmer education |
| tnau_horticulture | Horticulture - TNAU production guide | Tamil Nadu Agricultural University (agritech extension portal) | State agricultural university extension publication, free farmer education |

## Front-matter fields
`crop`, `crop_display`, `source_id`, `source_title`, `publisher`, `source_url`, `rights_note`, `page_range`, `main_sections`, `mentions`, `extracted_with`, `extracted_on`, `qa_status`

## Images
Figure PNGs are under `images/<source_id>/`. They **must travel with the .md files** or all image links will be broken. Original PDFs are kept locally and are NOT part of this deliverable (rights guardrail).

## Re-run
```bash
python extract.py --all          # full pipeline
python extract.py --convert --source <id>  # re-convert one book
python extract.py --emit --source <id>     # re-segment+emit (fast)
```