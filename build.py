import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
import tomllib

PYTHON_MAX_MINOR = 14

CUSTOM_CFLAGS = [
    "-DNDEBUG",
    "-g0",
    "-O2",
    "-mtune=generic",
    "-fno-semantic-interposition",
    "-fno-strict-overflow",
    "-fvisibility=hidden",
    # "-flto=thin",
]
CUSTOM_CXXFLAGS = CUSTOM_CFLAGS
CUSTOM_LDFLAGS = [
    "-Wl,-s",
    "-Wl,-O1",
    "-Wl,--sort-common",
    "-Wl,--as-needed",
    "-Wl,-z,pack-relative-relocs",
    "-Wl,--exclude-libs,ALL",
    # "-flto=thin",
]
UNSAFE_FLAGS = [   # unsafe to use when building some libraries
    "-fvisibility=hidden",
]
CFLAGS_OLD = os.environ.get("CFLAGS", "")
CXXFLAGS_OLD = os.environ.get("CFLAGS", "")
LDFLAGS_OLD = os.environ.get("CFLAGS", "")

RED = "\033[1;31m"
PURPLE = "\033[1;35m"


def get_app_name():
    """Get app name from pyproject.toml"""
    if os.path.exists("pyproject.toml"):
        with open("pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        if "project" in data and "version" in data["project"]:
            return str(data["project"]["name"])
        print("App name not specified in pyproject.toml", file=sys.stderr)
        sys.exit(1)
    print("pyproject.toml file not found", file=sys.stderr)
    sys.exit(1)


def get_version_number():
    """Get version number from pyproject.toml"""
    if os.path.exists("pyproject.toml"):
        with open("pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        if "project" in data and "version" in data["project"]:
            return str(data["project"]["version"])
        print("Version not specified in pyproject.toml", file=sys.stderr)
        sys.exit(1)
    print("pyproject.toml file not found", file=sys.stderr)
    sys.exit(1)


def supports_color():
    """Return True if the running terminal supports ANSI colors"""
    if sys.platform == "win32":
        return (os.getenv("ANSICON") is not None or
            os.getenv("WT_SESSION") is not None or
            os.getenv("TERM_PROGRAM") == "vscode" or
            os.getenv("TERM") in ("xterm", "xterm-color", "xterm-256color")
        )
    if not sys.stdout.isatty():
        return False
    return os.getenv("TERM", "") != "dumb"


def is_gil_enabled():
    """Safely check if GIL is enabled"""
    try:
        return sys._is_gil_enabled()
    except AttributeError:
        return True


def get_python_version():
    """Get python major and minor versions"""
    if shutil.which("uv"):
        try:
            version_result = subprocess.run(["uv", "run", "--no-sync", "python", "-VV"], capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as e:
            print(f"uv error: {e}", color_code=RED, prefix="", file=sys.stderr)
            return sys.version_info.major, sys.version_info.minor, not is_gil_enabled()
        all_parts = version_result.stdout.strip().split(" ")
        version_parts = all_parts[1].split(".")
        if len(version_parts) < 2:
            return sys.version_info.major, sys.version_info.minor, not is_gil_enabled()
        return int(version_parts[0]), int(version_parts[1]), "free-threading" in all_parts[2]
    return sys.version_info.major, sys.version_info.minor, not is_gil_enabled()


PKGNAME = get_app_name()
PKGVER = get_version_number()
USE_COLOR = supports_color()


def fprint(text, color="\033[1;35m", prefix=f"[{PKGNAME.capitalize()} Build Script]: ", file=sys.stdout):
    """Print colored text prefixed with text, default is light purple"""
    if USE_COLOR and color:
        print(f"{color}{prefix}{text}\033[0m", file=file, flush=True)
    else:
        print(f"{prefix}{text}", file=file, flush=True)


def iprint(text, indent=2, color=None):
    """Print inented low importance text belonging to build step"""
    if color:
        fprint(text, prefix=(indent * " "), color=color)
    else:
        print(f"{indent * " "}{text}", flush=True)


def check_python():
    """Check python version and print warning, and return True if running inside pure python (no uv)"""
    if sys.version_info.major != 3:
        fprint(f"Python {sys.version_info.major} is not supported. Only Python 3 is supported.", color=RED, prefix="", file=sys.stderr)
        sys.exit(1)

    if os.environ.get("UV", ""):
        if sys.version_info.minor < 12 or sys.version_info.minor > PYTHON_MAX_MINOR:
            fprint(f'WARNING: Python {sys.version_info.major}.{sys.version_info.minor} is not supported but build may succeed. Run "python build.py" to let uv download and setup recommended temporary python interpreter.', color=RED)
        if not is_gil_enabled():
            fprint("WARNING: Freethreaded build may fail or built binary may crash.", color=RED)
        return False

    try:
        subprocess.run(["uv", "--version"], capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        fprint(f"uv error: {e}", color=RED, prefix="", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        fprint("uv command not found, please ensure uv is installed and in PATH", color=RED, prefix="", file=sys.stderr)
        sys.exit(1)
    return True


def ensure_python():
    """Check current python and download correct python if needed"""
    _, minor, _ = get_python_version()
    if minor == PYTHON_MAX_MINOR:
        return None

    version = f"3.{PYTHON_MAX_MINOR}"
    # ensure there is no same-name freethreaded python
    subprocess.run(["uv", "python", "uninstall", f"3.{minor}+freethreaded"], check=False)

    fprint(f"Setting up python {version} for this project")
    subprocess.run(["uv", "python", "install", version], check=True)

    return version


def check_dev():
    """Check if its dev environment and set it up"""
    if importlib.util.find_spec("PyInstaller") is None or importlib.util.find_spec("nuitka") is None:
        subprocess.run(["uv", "sync", "--group", "build"], check=True)


def setup_compiler(clang, clear=False, overwrite=False, cflags=[], ldflags=[], cxxflags=[], safe=False, lld=True, exclude=True):
    """Set compiler and its flags in environment variables"""
    if clang:
        os.environ["CC"] = "clang"
        os.environ["CXX"] = "clang++"
        if shutil.which("lld") and clang and lld:
            os.environ["LD"] = "lld"
    if clear:
        os.environ["CFLAGS"] = CFLAGS_OLD
        os.environ["CXXFLAGS"] = CXXFLAGS_OLD
        os.environ["LDFLAGS"] = LDFLAGS_OLD
        return [], [], []
    unsafe_flags = UNSAFE_FLAGS
    if sys.platform == "win32" and not clang:   # unsupported flags in cl
        unsafe_flags += ["-g0", "-O3", "-mtune=generic", "-fno-semantic-interposition", "-fno-strict-overflow"]
        safe = True
    skip_mtune = "-mtune=" in CFLAGS_OLD
    custom_cflags = [item for item in CUSTOM_CFLAGS if item not in unsafe_flags and not (skip_mtune and item.starswith("-mtune"))] if safe else CUSTOM_CFLAGS
    custom_ldflgs = [item for item in CUSTOM_LDFLAGS if "exclude-libs" not in item] if not exclude else CUSTOM_LDFLAGS
    cflags = ([] if overwrite else CFLAGS_OLD.split(" ")) + custom_cflags + cflags
    cxxflags = ([] if overwrite else CXXFLAGS_OLD.split(" ")) + CUSTOM_CXXFLAGS + cxxflags
    ldflags = ([] if overwrite else LDFLAGS_OLD.split(" ")) + custom_ldflgs + ldflags
    if shutil.which("lld") and clang and lld:
        ldflags.append("-fuse-ld=lld")
    os.environ["CFLAGS"] = " ".join(cflags)
    os.environ["CXXFLAGS"] = " ".join(cxxflags)
    os.environ["LDFLAGS"] = " ".join(ldflags)
    if not lld:
        os.environ["LD"] = ""
    return cflags, cxxflags, ldflags



def build_with_pyinstaller(onedir):
    """Build with pyinstaller"""
    pkgname = get_app_name()
    mode = "--onedir" if onedir else "--onefile"
    hidden_imports = []
    exclude_imports = []
    package_data = []

    # platform-specific
    if sys.platform == "linux":
        options = []
    elif sys.platform == "win32":
        options = ["--console"]
    elif sys.platform == "darwin":
        options = []


    # prepare command and run it
    cmd = [
        "uv", "run", "python", "-m", "PyInstaller",
        mode,
        *hidden_imports,
        *exclude_imports,
        *package_data,
        *options,
        "--noconfirm",
        "--clean",
        f"--name={pkgname}",
        "main.py",
    ]
    cmd = [arg for arg in cmd if arg != ""]
    fprint("Starting pyinstaller")
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Build failed: {e}")
        sys.exit(e.returncode)

    # cleanup
    fprint("Cleaning up")
    try:
        os.remove(f"{pkgname}.spec")
        shutil.rmtree("build")
    except FileNotFoundError:
        pass
    fprint(f"Finished building {pkgname}")


def build_with_nuitka(onedir, clang, mingw, print_cmd=False):
    """Build with nuitka"""
    clang = clang or os.environ.get("CC") == "clang"
    pkgname = get_app_name()
    static_python = False

    mode = "--standalone" if onedir else "--onefile"
    compiler = ""
    if clang:
        compiler = "--clang"
    elif mingw:
        compiler = "--mingw64"
    python_flags = [
        "--python-flag=no_asserts",
        "--python-flag=no_docstrings",
        "--python-flag=no_site",
    ]
    hidden_imports = []
    exclude_imports = []
    package_data = []

    setup_compiler(clang, exclude=False)

    # options
    if clang:
        os.environ["CFLAGS"] = "-Wno-macro-redefined"

    # platform-specific
    if sys.platform == "linux":
        options = []
    elif sys.platform == "win32" and not print_cmd:
        options = ["--assume-yes-for-downloads"]
    elif sys.platform == "darwin":
        options = [
            f"--macos-app-name={get_app_name()}",
            f"--macos-app-version={get_version_number()}",
            "--macos-app-protected-resource=NSMicrophoneUsageDescription:Microphone access for recording voice message.",
        ]

    # prepare command and run it
    cmd = [
        "uv", "run", "python", "-m", "nuitka",
        mode,
        compiler,
        *python_flags,
        *hidden_imports,
        *exclude_imports,
        *package_data,
        *options,
        "--static-libpython=yes" if static_python else "",
        "--no-prefer-source-code",
        "--onefile-tempdir-spec={TEMP}/cmus-rpc-py_{PID}",
        "--company-name=SparkLost",
        f"--product-name={PKGNAME}",
        "--remove-output",
        "--output-dir=dist",
        f"--output-filename={pkgname}",
        "main.py",
    ]
    cmd = [arg for arg in cmd if arg != ""]
    if print_cmd:
        print(" ".join(cmd))
        sys.exit(0)
    fprint("Starting nuitka")
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Build failed: {e}")
        sys.exit(e.returncode)

    # cleanup
    fprint("Cleaning up")
    try:
        os.remove(f"{pkgname}.spec")
        shutil.rmtree("build")
    except FileNotFoundError:
        pass
    fprint(f"Finished building {pkgname}")


def parser():
    """Setup argument parser for CLI"""
    parser = argparse.ArgumentParser(
        prog="build.py",
        description=f"build script for {PKGNAME}",
    )
    parser._positionals.title = "arguments"
    parser.add_argument(
        "--nuitka",
        action="store_true",
        help="build with nuitka instead of pyinstaller, needs compiler but produces more optimized executable",
    )
    parser.add_argument(
        "--noclang",
        action="store_true",
        help="script prefers clang if its installed, set this to not use it, or change CC and LD env vars",
    )
    parser.add_argument(
        "--onedir",
        action="store_true",
        help="build into directory instead single executable",
    )
    parser.add_argument(
        "--mingw",
        action="store_true",
        help="use mingw instead msvc on windows, has no effect on Linux and macOS",
    )
    parser.add_argument(
        "--nobuild",
        action="store_true",
        help="only configure environment, but dont build",
    )
    parser.add_argument(
        "--print-cmd",
        action="store_true",
        help="print build command for nuitka or pyinstaller and exit",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parser()
    clang = not (args.noclang or args.mingw)

    if args.print_cmd:
        if args.nuitka:
            build_with_nuitka(args.onedir, clang, args.mingw, args.nosoundcard, print_cmd=True)
        else:
            build_with_pyinstaller(args.onedir, args.nosoundcard, print_cmd=True)
        sys.exit(0)

    if check_python():
        version = ensure_python()
        if version:
            os.execvp("uv", ["uv", "run", "-p", version, *sys.argv])
        else:
            os.execvp("uv", ["uv", "run", *sys.argv])
        sys.exit(0)

    if args.nobuild:
        sys.exit(0)

    if sys.platform not in ("linux", "win32", "darwin"):
        print(f"This platform is not supported: {sys.platform}", file=sys.stderr)
        sys.exit(1)

    check_dev()
    if args.nuitka:
        build_with_nuitka(args.onedir, clang, args.mingw)
    else:
        build_with_pyinstaller(args.onedir)

    sys.exit(0)
