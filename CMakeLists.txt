cmake_minimum_required(VERSION 3.15)
project(zinflate VERSION 1.0.0 LANGUAGES C)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

add_library(zinflate MODULE
  src/zinflate.c
  third_party/zlib/adler32.c
  third_party/zlib/crc32.c
  third_party/zlib/inffast.c
  third_party/zlib/inflate.c
  third_party/zlib/inftrees.c
  third_party/zlib/zutil.c)

target_include_directories(zinflate PRIVATE third_party/sqlite third_party/zlib)

# Hidden symbols keep the bundled zlib from clashing with a zlib in the host process;
# only the two entry points in zinflate.c are exported.
set_target_properties(zinflate PROPERTIES
  PREFIX ""
  C_VISIBILITY_PRESET hidden)

if(APPLE)
  set_target_properties(zinflate PROPERTIES SUFFIX ".dylib")
endif()

if(MSVC)
  # Static C runtime: nothing to redistribute next to the DLL.
  set_property(TARGET zinflate PROPERTY MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
  target_compile_definitions(zinflate PRIVATE _CRT_SECURE_NO_DEPRECATE _CRT_NONSTDC_NO_DEPRECATE)
endif()
