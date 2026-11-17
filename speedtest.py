"""Замер скорости скачивания.

Делает несколько последовательных запросов к одному адресу, дожидается
полного ответа на каждый и считает среднее время, объём и скорость.
"""

import argparse
import http.client
import math
import sys
import time
import urllib.request
from typing import NamedTuple, Optional, Sequence
from urllib.parse import urlparse

REQUEST_COUNT = 10
TIMEOUT_SECONDS = 30
CHUNK_SIZE = 64 * 1024  # читаем ответ кусками, чтобы не держать весь файл в памяти
BITS_IN_BYTE = 8
BYTES_IN_MEGABYTE = 1_000_000  # десятичные мегабайты/мегабиты, как у провайдеров
USER_AGENT = "download-speed-test/1.0"


class Result(NamedTuple):
    """Итог одного запроса."""

    seconds: float
    size_bytes: int


class Summary(NamedTuple):
    """Итог всей серии запросов."""

    average_seconds: float
    total_bytes: int
    speed_mbps: float


def download(url: str, timeout: float = TIMEOUT_SECONDS) -> Result:
    """Скачивает url целиком и возвращает время и размер ответа."""
    # no-cache просит прокси и CDN отдать свежий ответ, а не кэш
    headers = {"User-Agent": USER_AGENT, "Cache-Control": "no-cache"}
    request = urllib.request.Request(url, headers=headers)

    size = 0
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        # read() возвращает пустые байты, когда тело ответа закончилось
        while chunk := response.read(CHUNK_SIZE):
            size += len(chunk)
        expected = response.headers.get("Content-Length")
    elapsed = time.perf_counter() - started

    # если соединение оборвалось раньше времени, read() просто вернёт пустоту,
    # поэтому сверяем размер с тем, что обещал сервер
    if expected is not None and size != int(expected):
        raise http.client.IncompleteRead(b"", int(expected) - size)

    return Result(elapsed, size)


def megabytes(size_bytes: int) -> float:
    return size_bytes / BYTES_IN_MEGABYTE


def speed_mbps(size_bytes: int, seconds: float) -> float:
    """Скорость в мегабитах в секунду."""
    if seconds <= 0:
        return 0.0
    return size_bytes * BITS_IN_BYTE / seconds / BYTES_IN_MEGABYTE


def summarize(results: Sequence[Result]) -> Summary:
    """Считает среднее время, общий объём и скорость по всем запросам."""
    total_seconds = sum(result.seconds for result in results)
    total_bytes = sum(result.size_bytes for result in results)
    return Summary(
        average_seconds=total_seconds / len(results),
        total_bytes=total_bytes,
        # общая скорость = все байты / всё время, а не среднее из скоростей
        speed_mbps=speed_mbps(total_bytes, total_seconds),
    )


def is_http_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("нужно целое число больше нуля")
    return number


def positive_seconds(value: str) -> float:
    seconds = float(value)
    if not (math.isfinite(seconds) and seconds > 0):
        raise argparse.ArgumentTypeError("нужно число секунд больше нуля")
    return seconds


def parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Замер скорости скачивания по URL")
    parser.add_argument("url", help="адрес файла, например тяжёлой картинки")
    parser.add_argument("-n", "--count", type=positive_int, default=REQUEST_COUNT,
                        help=f"сколько запросов сделать (по умолчанию {REQUEST_COUNT})")
    parser.add_argument("-t", "--timeout", type=positive_seconds, default=TIMEOUT_SECONDS,
                        help=f"сколько секунд ждать данных от сервера (по умолчанию {TIMEOUT_SECONDS})")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    if not is_http_url(args.url):
        print(f"Ошибка: нужен адрес вида http(s)://..., получено: {args.url}", file=sys.stderr)
        return 1

    print(f"Адрес: {args.url}")
    print(f"Запросов: {args.count}\n")

    results = []
    for number in range(1, args.count + 1):
        try:
            result = download(args.url, args.timeout)
        except (OSError, http.client.HTTPException, ValueError) as error:
            # OSError покрывает ошибки сети, таймауты и HTTP-коды 4xx/5xx,
            # ValueError прилетает на кривых адресах (например, кириллица в пути)
            print(f"Ошибка на запросе {number}: {error}", file=sys.stderr)
            return 1

        if result.size_bytes == 0:
            print(f"Ошибка на запросе {number}: сервер вернул пустой ответ", file=sys.stderr)
            return 1

        results.append(result)
        print(f"{number:>3}/{args.count}  {result.seconds:7.3f} с  "
              f"{megabytes(result.size_bytes):8.2f} МБ  "
              f"{speed_mbps(result.size_bytes, result.seconds):8.2f} Мбит/с")

    summary = summarize(results)
    megabytes_per_second = summary.speed_mbps / BITS_IN_BYTE

    print()
    print(f"Среднее время запроса: {summary.average_seconds:.3f} с")
    print(f"Скачано всего:         {megabytes(summary.total_bytes):.2f} МБ "
          f"({summary.total_bytes} байт)")
    print(f"Скорость скачивания:   {summary.speed_mbps:.2f} Мбит/с "
          f"({megabytes_per_second:.2f} МБ/с)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nПрервано", file=sys.stderr)
        sys.exit(130)  # стандартный код выхода при Ctrl+C
