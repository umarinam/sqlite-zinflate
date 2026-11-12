"""Tests for the zinflate SQLite extension.

    python tests/test_zinflate.py [path/to/zinflate.dll]

The extension is taken from the command line, the ZINFLATE_PATH environment variable, or the
usual build output folders (out/, build/, build/Release/). Needs Python 3.9+ with a sqlite3
module that can load extensions; nothing else is required.
"""
import gzip
import json
import os
import pathlib
import random
import sqlite3
import sys
import unittest
import zlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
LIBRARY_NAMES = ("zinflate.dll", "zinflate.so", "zinflate.dylib")
SEARCH_DIRS = ("out", "build", "build/Release", "build/Debug")


def find_extension():
    explicit = os.environ.get("ZINFLATE_PATH")
    if explicit:
        return pathlib.Path(explicit).resolve()
    for folder in SEARCH_DIRS:
        for name in LIBRARY_NAMES:
            candidate = ROOT / folder / name
            if candidate.is_file():
                return candidate
    return None


def random_utf8(rng, length):
    """`length` random code points (no NUL, no surrogates) encoded as UTF-8."""
    chars = []
    while len(chars) < length:
        low, high = rng.choice(((1, 0x80), (0x80, 0x800), (0x800, 0x10000), (0x10000, 0x110000)))
        code_point = rng.randrange(low, high)
        if not 0xD800 <= code_point <= 0xDFFF:
            chars.append(chr(code_point))
    return "".join(chars).encode("utf-8")


@unittest.skipUnless(hasattr(sqlite3.Connection, "enable_load_extension"),
                     "this Python's sqlite3 module cannot load extensions")
class ZinflateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = find_extension()
        if cls.path is None:
            raise RuntimeError("zinflate library not found: build it first or set ZINFLATE_PATH")

    def connect(self):
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.enable_load_extension(True)
        db.load_extension(str(self.path))
        db.enable_load_extension(False)
        return db

    @staticmethod
    def inflate(db, data):
        """Returns (value, typeof) of zinflate(data)."""
        return db.execute("SELECT zinflate(?1), typeof(zinflate(?1))", (data,)).fetchone()

    def test_null_and_non_blob_values_pass_through(self):
        db = self.connect()
        row = db.execute(
            "SELECT zinflate(NULL), zinflate('text'), typeof(zinflate('text')),"
            " zinflate(42), typeof(zinflate(42)), zinflate(1.5), typeof(zinflate(1.5))"
        ).fetchone()
        self.assertEqual(row, (None, "text", "text", 42, "integer", 1.5, "real"))

    def test_zlib_text_is_inflated_to_text(self):
        db = self.connect()
        document = json.dumps(
            {"name": "Valve V-101", "size": 50, "note": "caf\u00e9 \u65e5\u672c\u8a9e \U0001F600"},
            ensure_ascii=False)
        for level in (0, 1, 6, 9):
            with self.subTest(level=level):
                blob = zlib.compress(document.encode("utf-8"), level)
                self.assertEqual(self.inflate(db, blob), (document, "text"))

    def test_inflated_text_works_with_json_functions(self):
        db = self.connect()
        db.execute("CREATE TABLE docs(id INTEGER PRIMARY KEY, payload BLOB)")
        db.executemany(
            "INSERT INTO docs(payload) VALUES (?)",
            [(zlib.compress(json.dumps({"tag": "T-%d" % n}).encode()),) for n in range(3)])
        try:
            rows = db.execute(
                "SELECT json_extract(zinflate(payload), '$.tag') FROM docs ORDER BY id").fetchall()
        except sqlite3.OperationalError as error:
            if "no such function" in str(error):
                self.skipTest("this SQLite build has no JSON functions")
            raise
        self.assertEqual(rows, [("T-0",), ("T-1",), ("T-2",)])

    def test_binary_and_nul_containing_results_are_blobs(self):
        db = self.connect()
        samples = {
            "all byte values": bytes(range(256)),
            "embedded NUL": b"abc\x00def",
            "truncated UTF-8": "caf\u00e9".encode("utf-8")[:-1],
            "overlong encoding": b"\xc0\x80",
            "surrogate": b"\xed\xa0\x80",
            "above U+10FFFF": b"\xf4\x90\x80\x80",
            "lone continuation byte": b"\x80",
        }
        for label, raw in samples.items():
            with self.subTest(label):
                self.assertEqual(self.inflate(db, zlib.compress(raw)), (raw, "blob"))

    def test_empty_stream_gives_empty_text(self):
        db = self.connect()
        self.assertEqual(self.inflate(db, zlib.compress(b"")), ("", "text"))

    def test_data_without_a_zlib_header_is_returned_unchanged(self):
        db = self.connect()
        compressor = zlib.compressobj(wbits=-15)
        raw_deflate = compressor.compress(b"hello hello hello") + compressor.flush()
        samples = {
            "empty blob": b"",
            "plain bytes": b"just some bytes",
            "gzip": gzip.compress(b"hello hello hello"),
            "raw deflate": raw_deflate,
            "too short to be a stream": zlib.compress(b"x")[:5],
        }
        for label, blob in samples.items():
            with self.subTest(label):
                self.assertEqual(self.inflate(db, blob), (blob, "blob"))

    def test_preset_dictionary_streams_are_returned_unchanged(self):
        db = self.connect()
        compressor = zlib.compressobj(zdict=b"hello")
        blob = compressor.compress(b"hello world") + compressor.flush()
        self.assertTrue(blob[1] & 0x20, "expected the FDICT flag to be set")
        self.assertEqual(self.inflate(db, blob), (blob, "blob"))

    def test_corrupt_or_truncated_streams_raise_an_error(self):
        db = self.connect()
        good = zlib.compress(b"a fairly compressible payload " * 200)
        corrupted_body = bytearray(good)
        corrupted_body[len(good) // 2] ^= 0xFF
        broken = {
            "truncated": good[: len(good) // 2],
            "checksum missing": good[:-4],
            "bad checksum": good[:-1] + bytes([good[-1] ^ 0xFF]),
            "corrupted body": bytes(corrupted_body),
        }
        for label, blob in broken.items():
            with self.subTest(label):
                with self.assertRaisesRegex(sqlite3.Error, "corrupt or truncated zlib data"):
                    db.execute("SELECT zinflate(?)", (blob,)).fetchone()

    def test_large_results(self):
        db = self.connect()
        samples = (
            ("14 MB of text", b'{"key":"value"}\n' * 900_000, "text"),
            ("32 MB of zeros", bytes(32 * 1024 * 1024), "blob"),
        )
        for label, raw, kind in samples:
            with self.subTest(label):
                same, actual_kind = db.execute(
                    "SELECT CAST(zinflate(?1) AS BLOB) = ?2, typeof(zinflate(?1))",
                    (zlib.compress(raw), raw)).fetchone()
                self.assertEqual((same, actual_kind), (1, kind))

    def test_honours_the_sqlite_length_limit(self):
        db = self.connect()
        if not hasattr(db, "setlimit"):
            self.skipTest("Connection.setlimit needs Python 3.11+")
        db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1000)
        self.assertEqual(self.inflate(db, zlib.compress(b"a" * 1000)), ("a" * 1000, "text"))
        with self.assertRaisesRegex(sqlite3.Error, "too big"):
            self.inflate(db, zlib.compress(b"a" * 1001))

    def test_rejects_wrong_argument_counts(self):
        db = self.connect()
        for sql in ("SELECT zinflate()", "SELECT zinflate(1, 2)"):
            with self.subTest(sql), self.assertRaisesRegex(sqlite3.Error, "wrong number of arguments"):
                db.execute(sql)

    def test_usable_in_views_generated_columns_and_indexes(self):
        db = self.connect()
        db.execute("PRAGMA trusted_schema = OFF")
        db.execute("CREATE TABLE docs(id INTEGER PRIMARY KEY, payload BLOB,"
                   " doc TEXT GENERATED ALWAYS AS (zinflate(payload)) VIRTUAL)")
        db.execute("INSERT INTO docs(payload) VALUES (?)", (zlib.compress(b"hello"),))
        db.execute("CREATE INDEX docs_doc ON docs(zinflate(payload))")
        db.execute("CREATE VIEW docs_view AS SELECT id, zinflate(payload) AS doc FROM docs")
        self.assertEqual(db.execute("SELECT doc FROM docs").fetchall(), [("hello",)])
        self.assertEqual(db.execute("SELECT doc FROM docs_view").fetchall(), [("hello",)])

    def test_both_entry_points_work(self):
        for entry_point in ("sqlite3_zinflate_init", "sqlite3_extension_init"):
            with self.subTest(entry_point=entry_point):
                db = sqlite3.connect(":memory:")
                self.addCleanup(db.close)
                db.enable_load_extension(True)
                try:
                    db.load_extension(str(self.path), entrypoint=entry_point)
                except TypeError:
                    self.skipTest("load_extension(entrypoint=...) needs Python 3.12+")
                self.assertIsNone(db.execute("SELECT zinflate(NULL)").fetchone()[0])

    def test_matches_python_zlib_on_random_data(self):
        rng = random.Random(20260101)
        db = self.connect()
        for case in range(300):
            kind = rng.choice(("binary", "text", "repetitive"))
            length = rng.randrange(0, 20000)
            if kind == "binary":
                raw = rng.randbytes(length)
            elif kind == "text":
                raw = random_utf8(rng, length // 3)
            else:
                unit = rng.randbytes(rng.randrange(1, 40))
                raw = (unit * length)[:length]
            blob = zlib.compress(raw, rng.choice((0, 1, 6, 9)))
            try:
                expected = (raw, "blob") if b"\x00" in raw else (raw.decode("utf-8"), "text")
            except UnicodeDecodeError:
                expected = (raw, "blob")
            with self.subTest(case=case, kind=kind, length=length):
                self.assertEqual(self.inflate(db, blob), expected)


if __name__ == "__main__":
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        os.environ["ZINFLATE_PATH"] = sys.argv.pop(1)
    unittest.main()
