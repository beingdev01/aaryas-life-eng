"""Tests for frame_check.py.

Pure-Python analysis (probe parsing, timestamps, closing hold, fade, blink, audio)
is tested on synthetic data. Two end-to-end tests build tiny 72x128 clips with
ffmpeg in a temp dir and only run if ffmpeg and ffprobe are installed.
"""

import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import frame_check as fc  # noqa: E402

SIZE = fc.GRID * fc.GRID


def card(brightness=1.0, shift=0):
    """A structured 32x32 frame: navy field with a gold block, optionally shifted."""
    px = []
    for y in range(fc.GRID):
        for x in range(fc.GRID):
            inside = 8 + shift <= x < 24 + shift and 6 <= y < 26
            px.append(int((200 if inside else 40) * brightness))
    return bytes(px)


def run(args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = fc.main(args)
    return code, out.getvalue(), err.getvalue()


class ProbeParsing(unittest.TestCase):
    def test_parse_basic(self):
        data = {"streams": [{"codec_type": "video", "width": 720, "height": 1280,
                             "avg_frame_rate": "30/1", "codec_name": "h264",
                             "pix_fmt": "yuv420p"},
                            {"codec_type": "audio", "codec_name": "aac"}],
                "format": {"duration": "16.020998"}}
        info = fc.parse_probe(data)
        self.assertEqual((info["width"], info["height"]), (720, 1280))
        self.assertEqual(info["fps"], 30.0)
        self.assertTrue(info["has_audio"])
        self.assertAlmostEqual(info["duration"], 16.021, places=3)

    def test_rotation_swaps_dimensions(self):
        data = {"streams": [{"codec_type": "video", "width": 1920, "height": 1080,
                             "avg_frame_rate": "25/1",
                             "side_data_list": [{"rotation": -90}]}],
                "format": {"duration": "8"}}
        info = fc.parse_probe(data)
        self.assertEqual((info["width"], info["height"]), (1080, 1920))

    def test_no_video_stream(self):
        with self.assertRaises(fc.FrameCheckError):
            fc.parse_probe({"streams": [{"codec_type": "audio"}]})

    def test_resolution_profiles(self):
        wa = {"width": 720, "height": 1280}
        self.assertTrue(fc.resolution_ok(wa, "whatsapp", None)[0])
        self.assertFalse(fc.resolution_ok(wa, "master", None)[0])
        self.assertTrue(fc.resolution_ok(wa, "auto", None)[0])
        self.assertFalse(fc.resolution_ok({"width": 1152, "height": 2048}, "auto", None)[0])
        self.assertTrue(fc.resolution_ok({"width": 72, "height": 128}, "auto", (72, 128))[0])

    def test_percent_timestamps(self):
        stamps = dict(fc.percent_timestamps(16.0, 30.0))
        self.assertEqual(stamps["000"], 0.0)
        self.assertEqual(stamps["050"], 8.0)
        self.assertAlmostEqual(stamps["100"], 15.95, places=2)


class ClosingAnalysis(unittest.TestCase):
    def test_held_frame_with_gentle_fade_passes(self):
        series = [card() for _ in range(40)]
        series += [card(1 - (k + 1) / 8) for k in range(8)]   # 1 s fade at 8 fps
        res = fc.analyse_closing(series, 8, len(series) / 8, hold=2.0, fade_window=1.0)
        self.assertTrue(res["held"], res)
        self.assertTrue(res["faded"], res)
        self.assertTrue(res["gentle"], res)

    def test_zoom_still_moving_at_end_fails(self):
        series = [card(shift=k // 6) for k in range(48)]
        res = fc.analyse_closing(series, 8, 6.0, hold=2.0, fade_window=1.0)
        self.assertFalse(res["held"], res)

    def test_hard_cut_to_black_is_not_gentle(self):
        series = [card() for _ in range(40)] + [bytes(SIZE)]
        res = fc.analyse_closing(series, 8, len(series) / 8, hold=2.0, fade_window=1.0)
        self.assertTrue(res["faded"])
        self.assertFalse(res["gentle"])

    def test_no_fade_detected(self):
        series = [card() for _ in range(48)]
        res = fc.analyse_closing(series, 8, 6.0, hold=2.0, fade_window=1.0)
        self.assertTrue(res["held"])
        self.assertFalse(res["faded"])

    def test_blank_video(self):
        res = fc.analyse_closing([bytes(SIZE)] * 20, 8, 2.5, 2.0, 1.0)
        self.assertFalse(res["held"])


class BlinkDetection(unittest.TestCase):
    def test_blinking_region_is_flagged(self):
        series = [card(1.0 if (k // 2) % 2 == 0 else 0.4) for k in range(48)]
        self.assertGreater(fc.detect_flicker(series, 8)["flagged_regions"], 0)

    def test_slow_reveal_and_fade_are_not_blinking(self):
        series = [card(k / 16) for k in range(17)] + [card()] * 20
        series += [card(1 - k / 8) for k in range(8)]
        self.assertEqual(fc.detect_flicker(series, 8)["flagged_regions"], 0)


class Audio(unittest.TestCase):
    def test_parse_volumedetect(self):
        text = ("[Parsed_volumedetect_0 @ 0x1] mean_volume: -21.4 dB\n"
                "[Parsed_volumedetect_0 @ 0x1] max_volume: -6.0 dB\n")
        self.assertEqual(fc.parse_volumedetect(text), {"mean_db": -21.4, "max_db": -6.0})
        self.assertEqual(fc.parse_volumedetect("mean_volume: -inf dB")["mean_db"],
                         float("-inf"))

    def test_balanced_audio_with_fades_passes(self):
        self.assertEqual(fc.evaluate_audio({"mean_db": -20, "max_db": -4},
                                           {"mean_db": -30}, {"mean_db": -40}), [])

    def test_clipping_and_missing_fades(self):
        probs = fc.evaluate_audio({"mean_db": -14, "max_db": 0.0},
                                  {"mean_db": -14}, {"mean_db": -15})
        joined = " ".join(probs)
        self.assertIn("clips", joined)
        self.assertIn("fade-in", joined)
        self.assertIn("fade-out", joined)

    def test_too_quiet_and_too_hot(self):
        self.assertIn("inaudible", fc.evaluate_audio({"mean_db": -50, "max_db": -30},
                                                     {}, {})[0])
        self.assertIn("too hot", fc.evaluate_audio({"mean_db": -6, "max_db": -1},
                                                   {"mean_db": -20}, {"mean_db": -30})[0])


class CommandLine(unittest.TestCase):
    def test_missing_video_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(run([str(Path(tmp) / "none.mp4"), tmp])[0], 2)

    def test_bad_expect_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            v = Path(tmp) / "v.mp4"
            v.write_bytes(b"x")
            if shutil.which("ffprobe") and shutil.which("ffmpeg"):
                self.assertEqual(run([str(v), tmp, "--expect", "big"])[0], 2)


HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe") and shutil.which("nice"))


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg/ffprobe not installed")
class RealVideo(unittest.TestCase):
    def make(self, path, vf_source, with_audio=True, seconds=6):
        cmd = ["nice", "-n", "19", "ffmpeg", "-v", "error", "-nostdin", "-y",
               "-f", "lavfi", "-i", vf_source]
        if with_audio:
            cmd += ["-f", "lavfi", "-i",
                    f"sine=frequency=440:duration={seconds}:sample_rate=22050",
                    "-af", f"afade=t=in:d=0.6,afade=t=out:st={seconds - 1}:d=1",
                    "-c:a", "aac"]
        cmd += ["-c:v", "mpeg4", "-q:v", "3", "-pix_fmt", "yuv420p", "-threads", "1",
                "-shortest", str(path)]
        subprocess.run(cmd, check=True, timeout=120)

    def test_held_card_with_fades_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            v = Path(tmp) / "invite.mp4"
            self.make(v, "color=c=0x101f3d:s=72x128:d=6:r=8,"
                         "drawbox=x=12:y=20:w=48:h=60:color=0xe6c574:t=fill,"
                         "fade=t=out:st=5:d=1")
            out = Path(tmp) / "qa"
            code, stdout, err = run([str(v), str(out), "--expect", "72x128",
                                     "--min-duration", "3", "--require-audio"])
            self.assertEqual(code, 0, stdout + err)
            for name in ("frame_000.png", "frame_050.png", "frame_100.png",
                         "frame_closing.png", "FRAME_CHECK.json"):
                self.assertTrue((out / name).is_file(), name)
            report = json.loads((out / "FRAME_CHECK.json").read_text())
            self.assertTrue(all(c["ok"] for c in report["checks"]))

    def test_moving_end_and_wrong_size_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            v = Path(tmp) / "moving.mp4"
            self.make(v, "life=s=72x128:rate=8:seed=7:random_fill_ratio=0.3,trim=duration=4",
                      with_audio=False, seconds=4)
            code, stdout, err = run([str(v), str(Path(tmp) / "qa"), "--profile", "whatsapp",
                                     "--min-duration", "1"])
            self.assertEqual(code, 1)
            self.assertIn("resolution", err)
            self.assertIn("closing-hold", err)


if __name__ == "__main__":
    unittest.main()
