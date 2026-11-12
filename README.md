# sqlite-zinflate

`zinflate(X)` is a small [SQLite loadable extension](https://www.sqlite.org/loadext.html) that inflates
zlib-compressed BLOBs, so compressed JSON, XML or text columns can be read straight from SQL and from
GUI tools such as [DB Browser for SQLite](https://sqlitebrowser.org/).

```sql
SELECT id, zinflate(payload) FROM documents;
SELECT json_extract(zinflate(payload), '$.name') FROM documents;
```

- **Self-contained.** The inflate half of zlib is compiled in. There is no zlib DLL to ship, and the Windows
  release needs no Visual C++ redistributable (static CRT).
- **Forgiving.** `NULL`, non-BLOB values and BLOBs that are not zlib streams come back unchanged, so you can
  apply it to a whole column.
- **Right type out.** UTF-8 text comes back as `TEXT` (so `json_extract()` and friends work on it), anything
  else as a `BLOB`.
- **Safe.** The output size is capped by SQLite's `SQLITE_LIMIT_LENGTH`. The function is registered as
  deterministic and innocuous, so it also works in views, generated columns and indexes when
  `trusted_schema` is off.

## Install

Download `zinflate.dll` (Windows, x64) from the
[latest release](https://github.com/umarinam/sqlite-zinflate/releases/latest) and keep it somewhere
permanent. Compare its hash with `SHA256SUMS.txt` from the same release:

```powershell
(Get-FileHash .\zinflate.dll -Algorithm SHA256).Hash.ToLower()
```

The library must match the program that loads it. This build is 64-bit, so use a 64-bit DB Browser for
SQLite, `sqlite3` or Python. For other platforms, or to build it yourself, see [Building](#building).

## Using it

### DB Browser for SQLite

Load the extension for every database you open:

1. Open **Edit → Preferences → Extensions**.
2. Under *Select extensions to load for every database*, click **Add extension** and pick `zinflate.dll`.
3. Click **OK**.

To load it for the current session only, use **Tools → Load Extension…**.

To see a compressed column decoded in **Browse Data**:

1. Right-click the column header and choose **Edit display format**.
2. Choose **Custom** and enter `zinflate("payload")`, replacing `payload` with the column name and keeping the
   double quotes.

A display format only changes what is shown; the stored data is untouched. In **Execute SQL**, call
`zinflate()` like any other function.

Note: DB Browser can also save the current filter, sort column and display formats as a *view*. That writes
a view into the database file, and because the view applies your display format it can only be queried where
the extension is loaded.

### sqlite3 shell

```
.load ./zinflate
SELECT zinflate(payload) FROM documents;
```

### Python

```python
import sqlite3

db = sqlite3.connect("example.db")
db.enable_load_extension(True)
db.load_extension("./zinflate")  # path to zinflate.dll / .so / .dylib; the suffix is optional
db.enable_load_extension(False)

print(db.execute("SELECT zinflate(payload) FROM documents").fetchall())
```

Some Python builds are compiled without extension support; there `enable_load_extension` does not exist.

### Other programs

Anything that can call `sqlite3_load_extension()` can use it. The library exports both
`sqlite3_extension_init` and `sqlite3_zinflate_init`, so it loads with or without an explicit entry point.

## Behaviour

| Input | Result |
| --- | --- |
| `NULL` | `NULL` |
| Anything that is not a BLOB (text, integer, real) | Returned unchanged |
| A BLOB that does not start with a zlib header: plain bytes, gzip, raw deflate, or a stream that needs a preset dictionary | Returned unchanged |
| A zlib stream that inflates to valid UTF-8 with no NUL bytes | `TEXT` |
| A zlib stream that inflates to anything else (binary, NUL bytes, invalid UTF-8) | `BLOB` |
| An empty zlib stream | `''` (empty `TEXT`) |
| A zlib header followed by corrupt or truncated data | Error: `zinflate: corrupt or truncated zlib data` |
| Inflated size above the connection's `SQLITE_LIMIT_LENGTH` | Error: `string or blob too big` |

A BLOB counts as a zlib stream when it is at least 6 bytes long and starts with a valid
[RFC 1950](https://www.rfc-editor.org/rfc/rfc1950) header: deflate method, window of at most 32 KiB, correct
check bits and no preset dictionary. About 1 in 2,000 random byte strings passes that test, so a non-zlib
BLOB that happens to begin with a valid header is reported as corrupt instead of being passed through. Keep
that in mind if a column mixes zlib streams with arbitrary binary data.

## Building

Only a C compiler is needed: the zlib inflate sources and the SQLite headers are vendored in
[`third_party/`](third_party), unmodified.

**Windows (MSVC).** Run `.\build.cmd` from any Command Prompt or PowerShell window. If the compiler is not on
`PATH`, it locates Visual Studio or the Build Tools with `vswhere` and sets up the x64 environment itself.

```
.\build.cmd
```

The result is `out\zinflate.dll` (x64, static CRT).

**CMake.**

```
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release
```

The result is `build/zinflate.dll`, `build/zinflate.so` or `build/zinflate.dylib`. Multi-config generators
such as Visual Studio put it in `build/Release/`.

## Testing

```
python tests/test_zinflate.py [path/to/zinflate.dll]
```

The tests use only the Python standard library (3.9 or newer; a few cases need 3.11 or 3.12 and are skipped on
older versions). Unless a path or the `ZINFLATE_PATH` environment variable is given, they look in `out/` and
`build/`. They cover the behaviour table above, large results, the length limit, views, generated columns and
indexes, both entry points, and a randomised comparison against Python's own `zlib`.

## Status

Tested on Windows x64: built with MSVC through `build.cmd` and through CMake (both the Ninja and the Visual
Studio generators), using zlib 1.3.2 and the SQLite 3.50.2 headers. The extension has been loaded into Python
3.14 (SQLite 3.50.4) and into the `sqlite3.dll` and `sqlcipher.dll` bundled with DB Browser for SQLite 3.13.1
(SQLite 3.46.1). The DB Browser steps above follow that version's own menus and behaviour; the GUI is not part
of the automated tests. Linux and macOS builds are supported by the CMake file but have not been tested yet.

## License

[MIT](LICENSE). The bundled third-party code (zlib, and the public-domain SQLite headers) is listed in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
