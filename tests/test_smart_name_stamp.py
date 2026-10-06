import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

import smart_name_stamp as stamp


FONT = Path(__file__).resolve().parents[1] / "assets" / "fonts" / "NotoSansCJKsc-Regular.otf"


class SmartNameStampTests(unittest.TestCase):
    def test_manual_position_is_clamped_and_caption_override_is_exported(self):
        settings = stamp.Settings(manual_position=(2, -1), face_avoidance="off")
        image = Image.new("RGB", (800, 600), "white")
        layout = stamp.fit_text_layout("标注", image.size, FONT, settings)
        box = stamp.generate_candidate_boxes(image.size, layout, settings)[0]
        self.assertEqual(box[2], 800)
        self.assertEqual(box[1], 0)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/"source.png"
            image.save(source)
            result = stamp.stamp_one(source, Path(directory)/"out.png", source, FONT,
                                     settings, False, False, False, False, caption_override="自定义说明")
            self.assertEqual(result["text"], "自定义说明")

    def test_fixed_anchor_and_explicit_color(self):
        image = Image.new("RGB", (800, 600), "white")
        settings = stamp.Settings(placement_mode="bottom-right", text_color="white",
                                  backing="always", backing_opacity=0.7, face_avoidance="off")
        layout = stamp.fit_text_layout("位置测试", image.size, FONT, settings)
        placement, _, _ = stamp.choose_placement(image, layout, settings)
        self.assertEqual(placement.box[2], 800 - round(600 * settings.margin_ratio))
        self.assertEqual(placement.box[3], 600 - round(600 * settings.margin_ratio))
        self.assertEqual(placement.text_color, (250, 250, 250, 255))
        self.assertEqual(placement.backing_color, (0, 0, 0, round(255 * 0.7)))

    def test_uses_light_text_on_dark_region(self):
        image = Image.new("RGB", (640, 420), (18, 20, 24))
        settings = stamp.Settings(face_avoidance="off")
        layout = stamp.fit_text_layout("夜色测试", image.size, FONT, settings)
        placement, _faces, _status = stamp.choose_placement(image, layout, settings)
        self.assertGreater(placement.text_color[0], 200)

    def test_uses_dark_text_on_light_region(self):
        image = Image.new("RGB", (640, 420), (240, 236, 228))
        settings = stamp.Settings(face_avoidance="off")
        layout = stamp.fit_text_layout("浅色测试", image.size, FONT, settings)
        placement, _faces, _status = stamp.choose_placement(image, layout, settings)
        self.assertLess(placement.text_color[0], 60)

    def test_prefers_clean_area_over_noisy_area(self):
        rng = np.random.default_rng(7)
        noisy = rng.integers(0, 255, size=(420, 320, 3), dtype=np.uint8)
        clean = np.full((420, 320, 3), 230, dtype=np.uint8)
        arr = np.concatenate([noisy, clean], axis=1)
        image = Image.fromarray(arr, "RGB")
        settings = stamp.Settings(face_avoidance="off", placement_mode="anywhere")
        layout = stamp.fit_text_layout("clean-zone", image.size, FONT, settings)
        placement, _faces, _status = stamp.choose_placement(image, layout, settings)
        self.assertGreaterEqual(placement.box[0], 250)

    def test_batch_report_uses_file_stem(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            src = root / "测试_image_01.png"
            dst_dir = root / "out"
            Image.new("RGB", (500, 360), (250, 250, 250)).save(src)

            code = stamp.main(
                [
                    str(src),
                    str(dst_dir),
                    "--face-avoidance",
                    "off",
                    "--contact-sheet",
                ]
            )

            self.assertEqual(code, 0)
            report_path = dst_dir / "caption_report.json"
            report = report_path.read_text(encoding="utf-8")
            self.assertIn('"text": "测试_image_01"', report)
            self.assertTrue((dst_dir / src.name).exists())
            self.assertTrue((dst_dir / "_contact_sheet.jpg").exists())


if __name__ == "__main__":
    unittest.main()
