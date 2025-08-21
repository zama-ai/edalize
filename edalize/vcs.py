# Copyright edalize contributors
# Licensed under the 2-Clause BSD License, see LICENSE for details.
# SPDX-License-Identifier: BSD-2-Clause

import os
import logging

from functools import reduce
from edalize.edatool import Edatool

logger = logging.getLogger(__name__)


class Vcs(Edatool):

    _description = """ Synopsys VCS Backend

VCS is one of the "Big 3" simulators.

Example snippet of a CAPI2 description file for VCS:

.. code:: yaml

   vcs:
     vcs_options:
       # Compile-time options passed to the vcs command
       - -debug_access+pp
       - -debug_access+all
     run_options:
       # Run-time options passed to the simulation itself
       - -licqueue
"""

    tool_options = {
        "lists": {
            "vlogan_options": "String",
            "vhdlan_options": "String",
            "vcs_options": "String",  # compile-time options (passed to VCS)
            "run_options": "String",  # runtime options (passed to simulation)
        }
    }

    argtypes = ["plusarg", "vlogdefine", "vlogparam"]

    def _filelist_has_filetype(self, file_list, string, match_type="prefix"):
        for f in file_list:
            if match_type == "prefix" and f.file_type.startswith(string):
                return True
            elif match_type == "exact" and f.file_type == string:
                return True
        return False

    def _write_build_rtl_analyze_file(self, bash_main):
        class CompilationUnit:
            def __init__(self, files, logical_name, file_type):
                self.files        = files
                self.logical_name = logical_name if logical_name is not None and \
                                                    len(logical_name) > 0 \
                                    else "work"
                self.file_type    = file_type

            @classmethod
            def from_file(cls, file):
                return cls(files=[file], logical_name=file.logical_name, file_type=file.file_type)

            def combine(self, other):
                if other in self:
                   return [CompilationUnit(files=self.files + other.files,
                                           logical_name=self.logical_name,
                                           file_type=self.file_type)]
                else:
                   return [self, other]

            def __contains__(self, other):
                return self.logical_name == other.logical_name and self.file_type == other.file_type

            def is_rtl(self):
                return self.file_type.startswith("verilogSource") or \
                       self.file_type.startswith("systemVerilogSource") or \
                       self.file_type.startswith("vhdlSource") or \
                       self.file_type.startswith( "SVASource")

            def __repr__(self):
                return f"logical_name: {self.logical_name}, file_type: {self.file_type}, " + \
                       f"files: {','.join((x.name for x in self.files))}"

            def __str__(self):
                return f"logical_name: {self.logical_name}, file_type: {self.file_type}, " + \
                       f"files: {len(self.files)}"

        bash_main.write(f"set -e\n")

        (src_files, incdirs) = self._get_fileset_files()

        # Combine files into compilation units
        units = [ CompilationUnit.from_file(file) for file in src_files ]
        libs = set(map(lambda x: x.logical_name, units))
        rtl_units = list(filter(lambda x: x.is_rtl(), units))
        units = [x for x in units if not x.is_rtl()] + \
                reduce(lambda acc, x: acc[:-1] + acc[-1].combine(x), rtl_units[1:], [rtl_units[0]])

        bash_main.write("#Compilation units: \n")
        bash_main.write("\n".join((f"#{x}" for x in units)) + "\n")

        vlog_include_dirs = ["+incdir+" + d.replace("\\", "/") for d in incdirs]
        vlog_defines      = ["+define+{}={}".format(k, self._param_value_str(v))
                             for k, v in self.vlogdefine.items()]

        for f in units:
            if f.file_type.startswith("verilogSource") or \
               f.file_type.startswith("systemVerilogSource") or \
               f.file_type.startswith( "SVASource"):
                cmd = "vlogan"
                args = list(self.tool_options.get("vlogan_options", []))
                args += vlog_defines
                args += vlog_include_dirs
                if f.file_type.startswith("systemVerilogSource"):
                    args += ["-sverilog"]
            elif f.file_type.startswith("vhdlSource"):
                cmd = "vhdlan"
                if f.file_type.endswith("-87"):
                    args = ["-87"]
                if f.file_type.endswith("-93"):
                    args = ["-93"]
                if f.file_type.endswith("-2008"):
                    args = ["-2008"]
                else:
                    args = []
                args += self.tool_options.get("vhdlan_options", [])
            elif f.file_type == "tclSource":
                cmd = None
                tcl_main.write("".join(("do {}\n".format(x.name) for x in f.files)))
            elif f.file_type == "user":
                cmd = None
            else:
                _s = "{} has unknown file type '{}'"
                logger.warning(_s.format(f, f.file_type))
                cmd = None
            if cmd:
                args += ["-q"]
                args += ["-full64"]
                args += ["-work", f.logical_name]
                args += [x.name.replace("\\", "/") for x in f.files]
                bash_main.write("{} {}\n".format(cmd, " ".join(args)))

    def configure_main(self):
        analyze_script = open(os.path.join(self.work_root, "analyze.bash"), "w")
        self._write_build_rtl_analyze_file(analyze_script)
        parameter_file = open(os.path.join(self.work_root, "parameters.snps"), "w")

        _parameters = []
        for key, value in self.vlogparam.items():
            # parameters are not given to Makefile and command line anymore but listed in a file
            #_parameters += ["{}.{}={}".format(self.toplevel, key, self._param_value_str(value))]
            parameter_file.write("assign {} {}/{}\n".format(self._param_value_str(value).replace('"', ''), self.toplevel, key))
        for key, value in self.generic.items():
            _parameters += [
                "{}.{}={}".format(self.toplevel, key, self._param_value_str(value, bool_is_str=True))
            ]
        plusargs = []
        beforearg = ""
        if self.plusarg:
            for key, value in self.plusarg.items():
                if key == "before":
                    beforearg = self._param_value_str(value)
                    continue
                plusarg = "+" + key
                if value != True:
                    plusarg += "=" + self._param_value_str(value)
                plusargs.append(plusarg)

        vcs_options = self.tool_options.get("vcs_options", [])

        (src_files, incdirs) = self._get_fileset_files(force_slash=True)
        if self._filelist_has_filetype(src_files, "systemVerilog", match_type="prefix"):
            vcs_options.append("-sverilog")

        if self._filelist_has_filetype(src_files, "verilog2001", match_type="exact"):
            vcs_options.append("+v2k")

        template_vars = {
            "name": self.name,
            "vcs_options": vcs_options,
            "run_options": self.tool_options.get("run_options", []),
            "toplevel": self.toplevel,
            "plusargs": plusargs,
            "beforearg": beforearg,
            "libraries": list(set(x.logical_name for x in src_files if len(x.logical_name))),
            #"parameters": _parameters,
        }

        self.render_template("Makefile.j2", "Makefile", template_vars)

    def run_main(self):
        args = ["run"]

        # Set plusargs
        if self.plusarg:
            plusargs = []
            for key, value in self.plusarg.items():
                plusargs += ["+{}={}".format(key, self._param_value_str(value))]
            args.append("EXTRA_OPTIONS=" + " ".join(plusargs))

        self._run_tool("make", args)
