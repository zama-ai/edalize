# Copyright edalize contributors
# Licensed under the 2-Clause BSD License, see LICENSE for details.
# SPDX-License-Identifier: BSD-2-Clause

import os
import logging

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
        (src_files, incdirs) = self._get_fileset_files()
        vlog_include_dirs = ["+incdir+" + d.replace("\\", "/") for d in incdirs]

        libs = []
        vlog_d = {}
        svlog_d = {}
        for f in src_files:
            if not f.logical_name:
                f.logical_name = "work"
            if not f.logical_name in libs:
                #bash_main.write("vlib {}\n".format(f.logical_name))
                libs.append(f.logical_name)
            if f.file_type.startswith("verilogSource") or f.file_type.startswith(
                "systemVerilogSource") or f.file_type.startswith(
                "SVASource"
            ) :
                # All the sv and verilog files are processed later.
                cmd = None
                if f.file_type.startswith("systemVerilogSource") or f.file_type.startswith(
                  "SVASource"):
                    if (f.logical_name not in svlog_d):
                        svlog_d[f.logical_name] = []
                    svlog_d[f.logical_name] += [f]
                elif f.file_type.startswith("verilogSource"):
                    if (f.logical_name not in vlog_d):
                        vlog_d[f.logical_name] = []
                    vlog_d[f.logical_name] += [f]
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
                tcl_main.write("do {}\n".format(f.name))
            elif f.file_type == "user":
                cmd = None
            else:
                _s = "{} has unknown file type '{}'"
                logger.warning(_s.format(f.name, f.file_type))
                cmd = None
            if cmd:
                args += ["-q"]
                args += ["-full64"]
                #args += ["-work", f.logical_name]
                args += [f.name.replace("\\", "/")]
                bash_main.write("{} {}\n".format(cmd, " ".join(args)))
        if (vlog_d | svlog_d):
                cmd = "vlogan"
                args = []

                args += self.tool_options.get("vlogan_options", [])
                if self.tool_options.get("uvm") is not None:
                    args+= [f'-ntb_opts {self.tool_options.get("uvm")}']

                for k, v in self.vlogdefine.items():
                    args += ["+define+{}={}".format(k, self._param_value_str(v))]

                args += vlog_include_dirs
                args += ["-q"]
                args += ["-full64"]

                for k in vlog_d.keys():
                    for f in vlog_d[k]:
                        vargs = args.copy()
                        vargs += [f.name.replace("\\", "/")]
                        bash_main.write("{} {}\n".format(cmd, " ".join(vargs)))
                # systemVerilog work library
                # Compile everything that belongs to the same
                # library under the same scope
                for k in svlog_d.keys():
                    vargs = args.copy()
                    vargs += ["-sverilog"]
                    for f in svlog_d[k]:
                        vargs += [f.name.replace("\\", "/")]
                    bash_main.write("{} {}\n".format(cmd, " ".join(vargs)))


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

        c_dpi_files = filter(lambda src: src.file_type == 'cSource', src_files)
        def extract_c_header(file):
          if file['is_include_file'] is True and file['file_type'] is 'cSource':
            return True

        c_hdr_files = filter(lambda f: f['is_include_file'] is True and f['file_type'] is 'cSource', self.files)
        c_dpi_dir = list(map(lambda f: os.path.dirname(f["name"]),c_hdr_files))


        template_vars = {
            "name": self.name,
            "vcs_options": vcs_options,
            "run_options": self.tool_options.get("run_options", []),
            "toplevel": self.toplevel,
            "plusargs": plusargs,
            "beforearg": beforearg,
            'c_dpi_files': c_dpi_files,
            'c_dpi_dir': c_dpi_dir,
            #"parameters": _parameters,
        }
        if self.tool_options.get("uvm") is not None:
            template_vars["uvm"] = self.tool_options.get("uvm")
            template_vars["test_name"] = self.tool_options.get("test_name", 'test_base')

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
