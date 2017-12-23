from conans import ConanFile
from conans import tools
import os, sys, re, pickle 

def boost_apply_modules(mods, opts):
    res = opts.copy()
    res.update({"without_" + x: [True, False] for x in mods})
    return res

class BoostConan(ConanFile):
    name = "Boost"
    version = "1.65.1"
    settings = "os", "arch", "compiler", "build_type"
    FOLDER_NAME = "boost_%s" % version.replace(".", "_")
    # The current python option requires the package to be built locally, to find default Python
    # implementation
    modules = (
            "atomic",
            "chrono",
            "container",
            "context",
            "coroutine",
            "coroutine2",
            "date_time",
            "exception",
            "fiber",
            "filesystem",
            "graph",
            "graph_parallel",
            "iostreams",
            "locale",
            "log",
            "math",
            "metaparse",
            "mpi",
            "program_options",
            "python",
            "random",
            "regex",
            "serialization",
            "signals",
            "system",
            "test",
            "thread",
            "timer",
            "type_erasure",
            "wave"
        )

    options = boost_apply_modules(modules, {
        "shared": [True, False],
        "header_only": [True, False],
        "fPIC": [True, False],
        "python": [True, False],  # Note: this variable does not have the 'without_' prefix to keep
        # the old shas
    })

    default_options = (
        "shared=False",
        "header_only=False", 
        "fPIC=False", 
        "python=False"
    ) + tuple("without_" + x + "=False" for x in modules)

    url="https://github.com/lasote/conan-boost"
    exports = ["FindBoost.cmake", "OriginalFindBoost*"]
    license="Boost Software License - Version 1.0. http://www.boost.org/LICENSE_1_0.txt"
    short_paths = True

    flags = []

    def config_options(self):
        """ First configuration step. Only settings are defined. Options can be removed
        according to these settings
        """
        if self.settings.compiler == "Visual Studio":
            self.options.remove("fPIC")

    def configure(self):
        """ Second configuration step. Both settings and options have values, in this case
        we can force static library if MT was specified as runtime
        """
        # TODO add support for an icu option that adds the icu dependency as needed

        if self.settings.compiler == "Visual Studio" and \
           self.options.shared and "MT" in str(self.settings.compiler.runtime):
            self.options.shared = False

        if self.options.header_only:
            # Should be doable in conan_info() but the UX is not ready
            self.options.remove("shared")
            self.options.remove("fPIC")
            self.options.remove("python")

        if not self.options.without_iostreams and not self.options.header_only:
            if self.settings.os == "Linux" or self.settings.os == "Macos":
                self.requires("bzip2/1.0.6@conan/stable")
                self.options["bzip2/1.0.6"].shared = self.options.shared
            self.requires("zlib/1.2.11@conan/stable")
            self.options["zlib"].shared = self.options.shared

    def package_id(self):
        if self.options.header_only:
            self.info.header_only()

    def source(self):
        zip_name = "%s.zip" % self.FOLDER_NAME if sys.platform == "win32" else "%s.tar.gz" % self.FOLDER_NAME
        url = "http://sourceforge.net/projects/boost/files/boost/%s/%s/download" % (self.version, zip_name)
        self.output.info("Downloading %s..." % url)
        tools.download(url, zip_name)
        tools.unzip(zip_name)
        os.unlink(zip_name)

    def build(self):
        if self.options.header_only:
            self.output.warn("Header only package, skipping build")
            return

        self.flags = self.boostrap()
        self.patch_project_jam()
        self.flags.extend(self.get_build_flags())

        # JOIN ALL FLAGS
        full_command = self.resolve_full_command()
        self.run("%s -o\"%s%sbuild_report.txt\"" % (full_command, self.build_folder, os.sep))

    def get_build_flags(self):
        flags = []
        if self.settings.compiler == "Visual Studio":
            flags.append("toolset=msvc-%s" % self._msvc_version())
        elif not self.settings.os == "Windows" and self.settings.compiler == "gcc" and \
                str(self.settings.compiler.version)[0] >= "5":
            # For GCC >= v5 we only need the major otherwise Boost doesn't find the compiler
            # The NOT windows check is necessary to exclude MinGW:
            flags.append("toolset=%s-%s" % (self.settings.compiler,
                                            str(self.settings.compiler.version)[0]))
        elif str(self.settings.compiler) in ["clang", "gcc"]:
            # For GCC < v5 and Clang we need to provide the entire version string
            flags.append("toolset=%s-%s" % (self.settings.compiler,
                                            str(self.settings.compiler.version)))

        flags.append("link=%s" % ("static" if not self.options.shared else "shared"))
        if self.settings.compiler == "Visual Studio" and self.settings.compiler.runtime:
            flags.append("runtime-link=%s" % ("static" if "MT" in str(self.settings.compiler.runtime) else "shared"))
        flags.append("variant=%s" % str(self.settings.build_type).lower())
        flags.append("address-model=%s" % ("32" if self.settings.arch == "x86" else "64"))

        for mod in self.modules:
            if getattr(self.options, "without_" + mod):
                flags.append("--without-" + mod)

        cxx_flags = []
        # fPIC DEFINITION
        if self.settings.compiler != "Visual Studio":
            if self.options.fPIC:
                cxx_flags.append("-fPIC")

        # LIBCXX DEFINITION FOR BOOST B2
        try:
            if str(self.settings.compiler.libcxx) == "libstdc++":
                flags.append("define=_GLIBCXX_USE_CXX11_ABI=0")
            elif str(self.settings.compiler.libcxx) == "libstdc++11":
                flags.append("define=_GLIBCXX_USE_CXX11_ABI=1")
            if "clang" in str(self.settings.compiler):
                if str(self.settings.compiler.libcxx) == "libc++":
                    cxx_flags.append("-stdlib=libc++")
                    cxx_flags.append("-std=c++11")
                    flags.append('linkflags="-stdlib=libc++"')
                else:
                    cxx_flags.append("-stdlib=libstdc++")
                    cxx_flags.append("-std=c++11")
        except:
            pass

        cxx_flags = 'cxxflags="%s"' % " ".join(cxx_flags) if cxx_flags else ""
        flags.append(cxx_flags)
        return flags

    def resolve_full_command(self):
        command = "b2" if self.settings.os == "Windows" else "./b2"
        b2_flags = " ".join(self.flags)
        without_python = "--without-python" if not self.options.python else ""
        full_command = "cd \"%s\" && %s %s -j%s --abbreviate-paths %s -d2" % (
            self.FOLDER_NAME,
            command,
            b2_flags,
            tools.cpu_count(),
            without_python)  # -d2 is to print more debug info and avoid travis timing out without output
        
        if self.settings.os == "Windows" and self.settings.compiler == "Visual Studio":
            full_command = "%s && %s" % (tools.vcvars_command(self.settings), full_command)
      
        return full_command

    def boostrap(self):
        with_toolset = {"apple-clang": "darwin"}.get(str(self.settings.compiler),
                                                     str(self.settings.compiler))
        command = "bootstrap" if self.settings.os == "Windows" \
                              else "./bootstrap.sh --with-toolset=%s" % with_toolset

        if self.settings.os == "Windows" and self.settings.compiler == "Visual Studio":
            command = "%s && %s" % (tools.vcvars_command(self.settings), command)

        flags = []
        if self.settings.os == "Windows" and self.settings.compiler == "gcc":
            command += " mingw"
            flags.append("--layout=system")

        try:
            self.run("cd %s && %s" % (self.FOLDER_NAME, command))
        except:
            self.run("cd %s && type bootstrap.log" % self.FOLDER_NAME
                     if self.settings.os == "Windows"
                     else "cd %s && cat bootstrap.log" % self.FOLDER_NAME)
            raise
        return flags

    def patch_project_jam(self):
        self.output.warn("Patching project-config.jam")
       
        if not self.options.without_iostreams and not self.options.header_only:
            contents = "\nusing zlib : %s : <include>%s <search>%s ;" % (
                self.requires["zlib"].conan_reference.version,
                self.deps_cpp_info["zlib"].include_paths[0].replace('\\', '/'),
                self.deps_cpp_info["zlib"].lib_paths[0].replace('\\', '/'))
            if self.settings.os == "Linux" or self.settings.os == "Macos":
                contents += "\nusing bzip2 : %s : <include>%s <search>%s ;" % (
                    self.requires["bzip2"].conan_reference.version,
                    self.deps_cpp_info["bzip2"].include_paths[0].replace('\\', '/'),
                    self.deps_cpp_info["bzip2"].lib_paths[0].replace('\\', '/'))

            filename = "%s/project-config.jam" % self.FOLDER_NAME
            tools.save(filename, tools.load(filename) + contents)

    def package(self):
        command = self.resolve_full_command()

        self.run("{1} install --prefix=\"{2}\" --exec-prefix=\"{2}{0}bin\" --libdir=\"{2}{0}lib\" --includedir=\"{2}{0}include\"".format(os.sep, command, self.package_folder))

        if not self.options.header_only and self.settings.compiler == "Visual Studio" and \
            self.options.shared == "False":
            # CMake findPackage help
            renames = []
            for libname in os.listdir(os.path.join(self.package_folder, "lib")):
                libpath = os.path.join(self.package_folder, "lib", libname)
                new_name = libname
                if new_name.startswith("lib"):
                    if os.path.isfile(libpath):
                        new_name =  libname[3:]
                if "-s-" in libname:
                    new_name = new_name.replace("-s-", "-")
                elif "-sgd-" in libname:
                    new_name = new_name.replace("-sgd-", "-gd-")

                renames.append([libpath, os.path.join(self.package_folder, "lib", new_name)])

            for original, new in renames:
                if original != new:
                    self.output.info("Rename: %s => %s" % (original, new))
                    os.rename(original, new)

        # save off the libs in a text file for package_info
        link_libs = self.collect_libs_from_build_log() 
        with open("%s%slink_library_list.pydata" % (self.package_folder, os.sep), 'wb') as lfile:
            pickle.dump(link_libs, lfile)

    def package_info(self):
        with open("%s%slink_library_list.pydata" % (self.package_folder, os.sep), 'rb') as lfile:
            self.cpp_info.libs = pickle.load(lfile)

        if not self.options.shared and self.settings.os == "Linux":
            self.cpp_info.libs.append("pthread")

        self.output.info("LIBRARIES: %s" % self.cpp_info.libs)

        if not self.options.header_only and self.options.shared:
            self.cpp_info.defines.append("BOOST_ALL_DYN_LINK")
        else:
            self.cpp_info.defines.append("BOOST_USE_STATIC_LIBS")

        if not self.options.header_only:
            if self.options.python:
                if not self.options.shared:
                    self.cpp_info.defines.append("BOOST_PYTHON_STATIC_LIB")

            if self.settings.compiler == "Visual Studio":
                # DISABLES AUTO LINKING! NO SMART AND MAGIC DECISIONS THANKS!
                self.cpp_info.defines.extend(["BOOST_ALL_NO_LIB"])

    def resolve_library(self, library_name):
        library_name = os.path.basename(library_name.strip())

        # special case for linux shared objects
        if self.settings.os != "Windows" and self.options.shared:
            numregex = re.compile(r'(.*)\.\d+$')
            while True:
                numsuffixmatch = numregex.match(library_name)
                if not numsuffixmatch:
                    break
                library_name = numsuffixmatch.group(1)

        name, ext = os.path.splitext(library_name)
        if ext in (".so", ".lib", ".a", ".dylib"):
            if ext != ".lib" and name.startswith("lib"):
                name = name[3:]
        return name

    def collect_libs_from_build_log(self):
        build_log = "%s%sbuild_report.txt" % (self.build_folder, os.sep)

        libregex = re.compile(r".*\{0}libs\{0}([^\{0}]*)\{0}".format(os.sep))
        foundlibs = {}
        foundmodules = set([])
        link_modules = []
        with open(build_log) as bf:
            for line in bf:
                # split the line
                first_space = line.find(" ")
                if first_space < 0:
                    continue

                command = line[0:first_space]
                parts = command.split('.')
                is_libline = False
                if self.options.shared:
                    if len(parts) < 3:
                        continue
                    if parts[1] != "link" or parts[2] != "dll":
                        continue
                else:
                    if len(parts) < 2:
                        continue
                    if parts[1] != "archive":
                        continue

                match = libregex.match(line[first_space+1:-1])
                if not match:
                    continue

                module = match.group(1)
                if not module in foundmodules:
                    try:
                        module_disabled = getattr(self.options, "without_" + module)
                        if module_disabled:
                            continue
                    except:
                        pass

                    foundmodules.add(module)
                    link_modules.append(module)

                library_name = self.resolve_library(line[first_space+1:-1])
                modlibs = None
                if not module in foundlibs:
                    modlibs = [library_name]
                else:
                    modlibs = foundlibs[module]
                    modlibs.append(library_name)

                foundlibs[module] = modlibs

        result = []
        for module in link_modules:
            result.extend(foundlibs[module])
        result.reverse()
        return result

    def _msvc_version(self):
        if self.settings.compiler.version == "15":
            return "14.1"
        else:
            return "%s.0" % self.settings.compiler.version
