#!/usr/bin/env python3
"""render_preview.py - render an HTML design to a preview PNG with headless Chrome.

The CEO reviews the preview PNG, never the source, so every review round starts here.

  render_preview.py index.html preview.png --width 1080 --height 1920
  render_preview.py index.html preview.png --width 1123 --height 794 --scale 2.0846
  render_preview.py cert.html preview.png --mode print --dpi 200 --width 2339 --height 1654

Modes:
  screenshot (default)  Chrome --screenshot at --width x --height CSS px times --scale.
                        The output PNG must measure round(W*scale) x round(H*scale).
  print                 Chrome --print-to-pdf (honours @page size) then pdftoppm at
                        --dpi. A4 landscape at 200 dpi is about 2339x1654; pdftoppm
                        rounding can give 1653, so the check allows +/-1 px. --width and
                        --height are the expected output pixels in this mode (optional).

Chrome is found under ~/.cache/puppeteer (full chrome first, then
chrome-headless-shell), then ~/.cache/ms-playwright. --chrome overrides. Chrome runs
under `nice -n 19` with a timeout and a throwaway profile directory, because the VM
has two vCPUs and live services. --dry-run prints the exact command without running.

Exit codes: 0 rendered and verified; 1 render failed or the PNG is wrong;
2 bad input (missing HTML, no Chrome found, missing pdftoppm).
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import png_check  # noqa: E402

CHROME_GLOBS = (
    ".cache/puppeteer/chrome/*/chrome-linux*/chrome",
    ".cache/puppeteer/chrome-headless-shell/*/chrome-headless-shell-linux*/chrome-headless-shell",
    ".cache/ms-playwright/chromium-*/chrome-linux*/chrome",
    ".cache/ms-playwright/chromium_headless_shell-*/chrome-linux*/headless_shell",
)


class RenderError(RuntimeError):
    pass


def find_chrome(home: Path | None = None) -> Path | None:
    """Newest executable Chrome under the known cache directories, or None."""
    home = Path(home or Path.home())
    for pattern in CHROME_GLOBS:
        found = sorted((p for p in home.glob(pattern) if p.is_file()
                        and os.access(p, os.X_OK)), reverse=True)
        if found:
            return found[0]
    return None


def chrome_flags(chrome: Path, user_data_dir: str, wait_ms: int) -> list[str]:
    headless = "--headless" if "headless" in chrome.name else "--headless=new"
    return [str(chrome), headless, "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
            "--no-first-run", "--no-default-browser-check", "--disable-extensions",
            "--mute-audio", "--disable-dev-shm-usage", f"--user-data-dir={user_data_dir}",
            f"--virtual-time-budget={wait_ms}"]


def build_screenshot_cmd(chrome: Path, html: Path, out: Path, width: int, height: int,
                         scale: float, user_data_dir: str, wait_ms: int) -> list[str]:
    return (["nice", "-n", "19"] + chrome_flags(chrome, user_data_dir, wait_ms) +
            [f"--force-device-scale-factor={scale:g}", f"--window-size={width},{height}",
             f"--screenshot={out}", html.resolve().as_uri()])


def build_print_cmds(chrome: Path, html: Path, pdf: Path, out_prefix: Path, dpi: int,
                     user_data_dir: str, wait_ms: int) -> list[list[str]]:
    chrome_cmd = (["nice", "-n", "19"] + chrome_flags(chrome, user_data_dir, wait_ms) +
                  [f"--print-to-pdf={pdf}", "--no-pdf-header-footer", html.resolve().as_uri()])
    raster = ["nice", "-n", "19", "pdftoppm", "-png", "-r", str(dpi), "-singlefile",
              str(pdf), str(out_prefix)]
    return [chrome_cmd, raster]


def expected_size(width: int, height: int, scale: float) -> tuple[int, int]:
    return round(width * scale), round(height * scale)


def run_bounded(cmd: list[str], timeout: int) -> subprocess.CompletedProcess:
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, start_new_session=True)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.communicate()
        raise RenderError(f"{Path(cmd[3] if cmd[0] == 'nice' else cmd[0]).name} "
                          f"timed out after {timeout}s")
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="render_preview.py",
        description="Render an HTML design to a verified preview PNG with headless Chrome.")
    ap.add_argument("html")
    ap.add_argument("out")
    ap.add_argument("--width", type=int, help="CSS viewport width (screenshot) or "
                                              "expected output px (print)")
    ap.add_argument("--height", type=int)
    ap.add_argument("--scale", type=float, default=1.0,
                    help="device scale factor for screenshot mode (default 1)")
    ap.add_argument("--mode", choices=("screenshot", "print"), default="screenshot")
    ap.add_argument("--dpi", type=int, default=200, help="raster dpi in print mode")
    ap.add_argument("--wait-ms", type=int, default=1500,
                    help="virtual time budget so fonts and images settle (default 1500)")
    ap.add_argument("--timeout", type=int, default=120, help="seconds per command")
    ap.add_argument("--chrome", default=None, help="explicit Chrome binary")
    ap.add_argument("--keep-pdf", action="store_true", help="print mode: keep OUT.pdf")
    ap.add_argument("--dry-run", action="store_true", help="print the command only")
    args = ap.parse_args(argv)

    html, out = Path(args.html), Path(args.out)
    if out.suffix.lower() != ".png":
        print(f"render_preview: output must end in .png: {out}", file=sys.stderr)
        return 2
    if not html.is_file():
        print(f"render_preview: no such HTML file: {html}", file=sys.stderr)
        return 2
    if args.mode == "screenshot" and (not args.width or not args.height):
        print("render_preview: screenshot mode needs --width and --height", file=sys.stderr)
        return 2
    if args.scale <= 0:
        print("render_preview: --scale must be positive", file=sys.stderr)
        return 2
    chrome = Path(args.chrome) if args.chrome else find_chrome()
    if chrome is None or not chrome.is_file():
        print("render_preview: no Chrome found under ~/.cache/puppeteer or "
              "~/.cache/ms-playwright (ls those directories, or pass --chrome)",
              file=sys.stderr)
        return 2
    if args.mode == "print" and shutil.which("pdftoppm") is None and not args.dry_run:
        print("render_preview: print mode needs pdftoppm (poppler-utils)", file=sys.stderr)
        return 2

    out.parent.mkdir(parents=True, exist_ok=True)
    profile = tempfile.mkdtemp(prefix="render-preview-profile-")
    try:
        if args.mode == "screenshot":
            cmds = [build_screenshot_cmd(chrome, html, out.resolve(), args.width,
                                         args.height, args.scale, profile, args.wait_ms)]
            want = expected_size(args.width, args.height, args.scale)
            tol = 1 if args.scale != int(args.scale) else 0
        else:
            pdf = out.with_suffix(".pdf")
            cmds = build_print_cmds(chrome, html, pdf.resolve(),
                                    out.with_suffix("").resolve(), args.dpi, profile,
                                    args.wait_ms)
            want = (args.width, args.height) if args.width and args.height else None
            tol = 1
        if args.dry_run:
            for c in cmds:
                print(" ".join(shlex.quote(x) for x in c).replace(profile, "<tmp-profile>"))
            return 0
        if out.exists():
            out.unlink()
        for c in cmds:
            res = run_bounded(c, args.timeout)
            if res.returncode != 0:
                tail = (res.stderr or "").strip().splitlines()[-1:] or ["no stderr"]
                raise RenderError(f"{Path(c[3]).name} exited {res.returncode}: {tail[0][:200]}")
        if args.mode == "print" and not args.keep_pdf:
            out.with_suffix(".pdf").unlink(missing_ok=True)
        if not out.is_file():
            raise RenderError(f"Chrome finished but wrote no file at {out}")
        w, h = (want if want else (None, None))
        info, problems = png_check.check(out, w, h, tol, min_bytes=100)
    except (RenderError, png_check.PNGError, OSError) as exc:
        print(f"render_preview: {exc}", file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(profile, ignore_errors=True)

    print(f"rendered {out} ({info['width']}x{info['height']}, {info['bytes']} bytes) "
          f"with {chrome}")
    print("command: " + " ".join(shlex.quote(x) for x in cmds[0]).replace(profile, "<tmp-profile>"))
    if problems:
        print(f"render_preview: {out}: {problems[0]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
