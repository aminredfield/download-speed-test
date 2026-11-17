import contextlib
import io
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

import speedtest

PAYLOAD = b"x" * 300_000


def run_quietly(argv):
    """Запускает main, пряча его вывод, чтобы не засорять отчёт тестов."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return speedtest.main(argv)


class PayloadHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/missing":
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(PAYLOAD)))
        self.end_headers()
        if self.path == "/truncated":
            # обещаем весь файл, а отдаём только половину
            self.wfile.write(PAYLOAD[: len(PAYLOAD) // 2])
            return
        self.wfile.write(PAYLOAD)

    def log_message(self, *args):
        pass  # не засоряем вывод тестов логами сервера


class DownloadTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), PayloadHandler)
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_download_reads_whole_body(self):
        result = speedtest.download(f"{self.base_url}/file")

        self.assertEqual(result.size_bytes, len(PAYLOAD))
        self.assertGreater(result.seconds, 0)

    def test_main_returns_zero_on_success(self):
        exit_code = run_quietly([f"{self.base_url}/file", "-n", "2"])

        self.assertEqual(exit_code, 0)

    def test_main_returns_one_on_http_error(self):
        exit_code = run_quietly([f"{self.base_url}/missing"])

        self.assertEqual(exit_code, 1)

    def test_main_returns_one_on_truncated_response(self):
        exit_code = run_quietly([f"{self.base_url}/truncated"])

        self.assertEqual(exit_code, 1)

    def test_main_returns_one_on_bad_url(self):
        for url in ("ftp://example.com/a.jpg", "http://[::1/", f"{self.base_url}/файл"):
            with self.subTest(url=url):
                self.assertEqual(run_quietly([url]), 1)

    def test_main_rejects_bad_count_and_timeout(self):
        for extra in (["-n", "0"], ["-t", "-1"], ["-t", "nan"]):
            with self.subTest(extra=extra):
                # argparse на неверных аргументах завершает программу с кодом 2
                with self.assertRaises(SystemExit) as raised:
                    run_quietly([f"{self.base_url}/file", *extra])
                self.assertEqual(raised.exception.code, 2)


class MathTest(unittest.TestCase):
    def test_speed_is_in_megabits_per_second(self):
        # 1 000 000 байт за 1 секунду = 8 Мбит/с
        self.assertEqual(speedtest.speed_mbps(1_000_000, 1), 8.0)

    def test_speed_is_zero_when_time_is_zero(self):
        self.assertEqual(speedtest.speed_mbps(1_000_000, 0), 0.0)

    def test_summarize_counts_average_total_and_speed(self):
        results = [speedtest.Result(1.0, 1_000_000), speedtest.Result(3.0, 3_000_000)]

        summary = speedtest.summarize(results)

        self.assertEqual(summary.average_seconds, 2.0)
        self.assertEqual(summary.total_bytes, 4_000_000)
        self.assertEqual(summary.speed_mbps, 8.0)

    def test_only_http_urls_are_accepted(self):
        self.assertTrue(speedtest.is_http_url("https://example.com/a.jpg"))
        self.assertFalse(speedtest.is_http_url("file:///etc/passwd"))
        self.assertFalse(speedtest.is_http_url("example.com/a.jpg"))


if __name__ == "__main__":
    unittest.main()
