import argparse
import json
import logging
import sys

from .config import load_config
from .pipeline import run, tailor_one
from .sources import source_status


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m jobhunt", description="KSA/Qatar job & recruiter discovery with CV tailoring")
    ap.add_argument("--config", default=None)
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="full pipeline")
    r.add_argument("--offline", metavar="FIXTURE_DIR", help="no network: read saved HTML fixtures from this dir")
    r.add_argument("--no-llm", action="store_true", help="skip Claude; deterministic tailoring only")
    r.add_argument("--no-email", action="store_true", help="do not send the digest or create drafts")
    r.add_argument("--only", nargs="*", help="run only these sources")
    r.add_argument("--max-tailor", type=int, default=None)

    t = sub.add_parser("tailor", help="tailor CV for one posting")
    t.add_argument("--url", default="")
    t.add_argument("--title", default="")
    t.add_argument("--company", default="")
    t.add_argument("--description-file", default=None, help="text file with the pasted job description")
    t.add_argument("--no-llm", action="store_true")

    sub.add_parser("sources", help="show which sources are enabled and which keys are present")
    sub.add_parser("render-master", help="render the master CV (no tailoring) to DOCX/PDF")

    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if a.cmd == "run":
        res = run(a.config, offline_dir=a.offline, use_llm=not a.no_llm, send_email=not a.no_email,
                  only_sources=a.only, max_tailor=a.max_tailor)
        print(json.dumps(res, indent=1))
    elif a.cmd == "tailor":
        if not a.url and not a.description_file:
            ap.error("give --url or --description-file")
        print(json.dumps(tailor_one(a.url, a.title, a.company, a.config, use_llm=not a.no_llm,
                                    description_file=a.description_file), indent=1))
    elif a.cmd == "sources":
        for name, ok, why in source_status(load_config(a.config)):
            print(f"{'ON ' if ok else 'off'}  {name:<20} {why}")
    elif a.cmd == "render-master":
        import yaml
        from pathlib import Path
        from .models import Job
        from .render import render_docx, render_pdf
        from .tailor import tailor_deterministic
        cfg = load_config(a.config)
        cv = yaml.safe_load(open(cfg["paths"]["cv"], encoding="utf-8"))
        t = tailor_deterministic(cv, Job(source="manual", title="", url="x"))
        out = Path(cfg["paths"]["out"]) / "master"
        print(render_docx(cv, t, out / "Ibrahim_Alsalem_CV_master.docx"), render_pdf(cv, t, out / "Ibrahim_Alsalem_CV_master.pdf"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
