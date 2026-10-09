import sys
from setuptools import Extension, setup
setup(ext_modules=[Extension("rapidxmltodict._native", ["src/native.cpp"],
    include_dirs=["vendor"], language="c++",
    depends=["src/native_mapping.hpp", "src/rapidxml_events.hpp", "src/native_events_binding.hpp", "vendor/rapidxml/rapidxml.hpp", "vendor/rapidxml/rapidxml_lexical.hpp", "vendor/rapidxml/rapidxml_parse_core.hpp", "vendor/rapidxml/rapidxml_stream.hpp"],
    extra_compile_args=["/O2", "/std:c++17"] if sys.platform == "win32" else ["-O3", "-std=c++17", "-Wall", "-Wextra"],
)], package_dir={"": "src"}, packages=["rapidxmltodict"])
