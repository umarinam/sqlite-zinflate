# Third-party notices

sqlite-zinflate bundles the following third-party files, unmodified, under `third_party/`.

## zlib 1.3.2

- Location: `third_party/zlib/`
- Source: <https://github.com/madler/zlib>, tag `v1.3.2` (only the files needed for inflate, plus `LICENSE`)
- License: the zlib license, see `third_party/zlib/LICENSE`
- Copyright (C) 1995-2026 Jean-loup Gailly and Mark Adler

The prebuilt `zinflate.dll` statically links this code.

## SQLite 3.50.2 headers

- Location: `third_party/sqlite/` (`sqlite3.h` and `sqlite3ext.h`)
- Source: the official 3.50.2 amalgamation, <https://www.sqlite.org/2025/sqlite-amalgamation-3500200.zip>
- License: public domain, see <https://www.sqlite.org/copyright.html>
