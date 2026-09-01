#!/usr/bin/env bash
# Render cv.html -> PDF and set clean document metadata.
# Chromium stamps Producer=Skia/PDF and Creator=Mozilla/... which we overwrite.
set -euo pipefail
cd "$(dirname "$0")"

CHROME="${CHROME:-/opt/pw-browsers/chromium-1194/chrome-linux/chrome}"
OUT="Ibrahim_Alsalem_CV_Whiteshield.pdf"

"$CHROME" --headless --disable-gpu --no-sandbox --no-pdf-header-footer \
          --print-to-pdf="$OUT" cv.html 2>/dev/null

python3 - "$OUT" <<'PY'
import sys
from pypdf import PdfReader, PdfWriter
path = sys.argv[1]
r = PdfReader(path); w = PdfWriter()
for p in r.pages: w.add_page(p)
w.add_metadata({
    "/Title":    "Ibrahim H. Alsalem - Curriculum Vitae",
    "/Author":   "Ibrahim H. Alsalem",
    "/Subject":  "Data Scientist & Applied Economist - Curriculum Vitae",
    "/Keywords": "Data Science, Economics, Labour Market, Econometrics, Forecasting, GCC",
    "/Creator":  "Ibrahim H. Alsalem",
    "/Producer": "Ibrahim H. Alsalem",
})
with open(path, "wb") as f: w.write(f)
print(f"{path}: {len(PdfReader(path).pages)} pages, metadata set")
PY
