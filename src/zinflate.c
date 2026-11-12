/*
** zinflate: a SQLite loadable extension that adds a zlib "inflate" SQL function.
**
**   zinflate(X)
**
** X is normally a BLOB holding a zlib stream (RFC 1950), such as the output of zlib's
** compress(), Python's zlib.compress() or Node's zlib.deflateSync().
**
**   - NULL returns NULL.
**   - A non-BLOB, or a BLOB that does not start with a zlib header, is returned
**     unchanged.
**   - Otherwise the inflated bytes are returned: TEXT if they are valid UTF-8 with no
**     NUL bytes (so json_*() and other text functions work on them), else BLOB.
**   - A BLOB with a zlib header that fails to inflate raises an SQL error.
**
** See README.md for build instructions and for using it from DB Browser for SQLite.
*/
#include <limits.h>
#include <string.h>
#include "sqlite3ext.h"
#include "zlib.h"
SQLITE_EXTENSION_INIT1

/* The entry points must stay visible when the library is built with hidden symbols. */
#if defined(_WIN32)
# define ZINFLATE_EXPORT __declspec(dllexport)
#elif defined(__GNUC__)
# define ZINFLATE_EXPORT __attribute__((visibility("default")))
#else
# define ZINFLATE_EXPORT
#endif

/* True if p starts with an RFC 1950 zlib header: deflate method, window <= 32K,
** valid check bits, and no preset dictionary. */
static int looksLikeZlib(const unsigned char *p, int n){
  return n>=6
      && (p[0]&0x0f)==8
      && (p[0]>>4)<=7
      && (((unsigned)p[0]<<8)|p[1])%31==0
      && (p[1]&0x20)==0;
}

/* True if s[0..n) is well-formed UTF-8 (no overlongs, surrogates or values above
** U+10FFFF) and contains no NUL byte. */
static int isUtf8NoNul(const unsigned char *s, size_t n){
  size_t i = 0;
  while( i<n ){
    unsigned char c = s[i];
    if( c==0 ) return 0;
    if( c<0x80 ){
      i++;
    }else if( c>=0xC2 && c<=0xDF ){
      if( i+1>=n || (s[i+1]&0xC0)!=0x80 ) return 0;
      i += 2;
    }else if( c>=0xE0 && c<=0xEF ){
      if( i+2>=n || (s[i+1]&0xC0)!=0x80 || (s[i+2]&0xC0)!=0x80 ) return 0;
      if( c==0xE0 && s[i+1]<0xA0 ) return 0;
      if( c==0xED && s[i+1]>=0xA0 ) return 0;
      i += 3;
    }else if( c>=0xF0 && c<=0xF4 ){
      if( i+3>=n || (s[i+1]&0xC0)!=0x80 || (s[i+2]&0xC0)!=0x80
       || (s[i+3]&0xC0)!=0x80 ) return 0;
      if( c==0xF0 && s[i+1]<0x90 ) return 0;
      if( c==0xF4 && s[i+1]>=0x90 ) return 0;
      i += 4;
    }else{
      return 0;
    }
  }
  return 1;
}

static void zinflateFunc(sqlite3_context *ctx, int argc, sqlite3_value **argv){
  sqlite3_value *pArg = argv[0];
  const unsigned char *pIn;
  int nIn;
  sqlite3_int64 mxLen;
  size_t hardCap, cap, nOut = 0;
  unsigned char *pOut;
  z_stream zs;
  int rc = Z_OK;
  int isTooBig = 0;
  int isNoMem = 0;
  (void)argc;

  if( sqlite3_value_type(pArg)==SQLITE_NULL ){
    sqlite3_result_null(ctx);
    return;
  }
  if( sqlite3_value_type(pArg)!=SQLITE_BLOB ){
    sqlite3_result_value(ctx, pArg);
    return;
  }
  pIn = (const unsigned char*)sqlite3_value_blob(pArg);
  nIn = sqlite3_value_bytes(pArg);
  if( !looksLikeZlib(pIn, nIn) ){
    sqlite3_result_value(ctx, pArg);
    return;
  }

  /* One byte past the SQL length limit is allowed so that a result of exactly the
  ** limit can still reach the end-of-stream marker. */
  mxLen = sqlite3_limit(sqlite3_context_db_handle(ctx), SQLITE_LIMIT_LENGTH, -1);
  hardCap = (size_t)mxLen + 1;
  cap = (size_t)nIn*4 + 256;
  if( cap>hardCap ) cap = hardCap;
  pOut = (unsigned char*)sqlite3_malloc64(cap);
  if( pOut==0 ){
    sqlite3_result_error_nomem(ctx);
    return;
  }

  memset(&zs, 0, sizeof(zs));
  if( inflateInit(&zs)!=Z_OK ){
    sqlite3_free(pOut);
    sqlite3_result_error_nomem(ctx);
    return;
  }
  zs.next_in = (Bytef*)pIn;
  zs.avail_in = (uInt)nIn;

  for(;;){
    size_t room = cap - nOut;
    uInt outBefore, inBefore;
    if( room==0 ){
      size_t nCap;
      unsigned char *pNew;
      if( cap>=hardCap ){
        isTooBig = 1;
        break;
      }
      nCap = cap*2;
      if( nCap<cap || nCap>hardCap ) nCap = hardCap;
      pNew = (unsigned char*)sqlite3_realloc64(pOut, nCap);
      if( pNew==0 ){
        isNoMem = 1;
        break;
      }
      pOut = pNew;
      cap = nCap;
      room = cap - nOut;
    }
    outBefore = room>UINT_MAX ? UINT_MAX : (uInt)room;
    inBefore = zs.avail_in;
    zs.next_out = pOut + nOut;
    zs.avail_out = outBefore;
    rc = inflate(&zs, Z_NO_FLUSH);
    nOut += outBefore - zs.avail_out;
    if( rc==Z_STREAM_END ) break;
    if( rc!=Z_OK && rc!=Z_BUF_ERROR ) break;
    if( zs.avail_out==outBefore && zs.avail_in==inBefore ){
      rc = Z_BUF_ERROR;
      break;
    }
    if( zs.avail_out>0 && zs.avail_in==0 ){
      /* Input ended before the end-of-stream marker. */
      rc = Z_BUF_ERROR;
      break;
    }
  }
  inflateEnd(&zs);

  if( isNoMem ){
    sqlite3_free(pOut);
    sqlite3_result_error_nomem(ctx);
  }else if( isTooBig || (rc==Z_STREAM_END && nOut>(size_t)mxLen) ){
    sqlite3_free(pOut);
    sqlite3_result_error_toobig(ctx);
  }else if( rc!=Z_STREAM_END ){
    sqlite3_free(pOut);
    sqlite3_result_error(ctx, "zinflate: corrupt or truncated zlib data", -1);
  }else if( nOut==0 ){
    sqlite3_free(pOut);
    sqlite3_result_text(ctx, "", 0, SQLITE_STATIC);
  }else if( isUtf8NoNul(pOut, nOut) ){
    sqlite3_result_text64(ctx, (const char*)pOut, nOut, sqlite3_free, SQLITE_UTF8);
  }else{
    sqlite3_result_blob64(ctx, pOut, nOut, sqlite3_free);
  }
}

ZINFLATE_EXPORT
int sqlite3_zinflate_init(
  sqlite3 *db,
  char **pzErrMsg,
  const sqlite3_api_routines *pApi
){
  (void)pzErrMsg;
  SQLITE_EXTENSION_INIT2(pApi);
  return sqlite3_create_function(db, "zinflate", 1,
                                 SQLITE_UTF8|SQLITE_DETERMINISTIC|SQLITE_INNOCUOUS,
                                 0, zinflateFunc, 0, 0);
}

/* Fallback entry point so the library still loads if it is renamed. */
ZINFLATE_EXPORT
int sqlite3_extension_init(
  sqlite3 *db,
  char **pzErrMsg,
  const sqlite3_api_routines *pApi
){
  return sqlite3_zinflate_init(db, pzErrMsg, pApi);
}
