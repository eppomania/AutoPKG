#!/usr/bin/python
#
# 2022 Graham R Pugh
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Aangepast voor Pro Warehouse door Jeroen van Noort
#

"""See docstring for LastRecipeRunResult class"""

import os.path
import subprocess
import sys
from collections import OrderedDict
from plistlib import load as load_plist
from plistlib import dumps as write_plist
from autopkglib import Processor  # pylint: disable=import-error

try:
    from ruamel import yaml
    from ruamel.yaml import dump
    from ruamel.yaml import add_representer
    from ruamel.yaml.nodes import MappingNode
except ImportError:
    subprocess.check_call([sys.executable, "-m", "ensurepip"])
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "pip3",
            "install",
            "-U",
            "pip",
            "setuptools",
            "wheel",
            "ruamel.yaml",
            "--user",
        ]
    )
    from ruamel import yaml
    from ruamel.yaml import dump
    from ruamel.yaml import add_representer
    from ruamel.yaml.nodes import MappingNode


__all__ = ["PatchMasterRecipeMaker"]


class PatchMasterRecipeMaker(Processor):
    """An AutoPkg processor which will create a new recipe containing the package.
    Designed to be run as a post-processor of a .pkg or .jss recipe."""

    input_variables = {
        "RECIPE_CACHE_DIR": {"required": False, "description": ("RECIPE_CACHE_DIR.")},
        "RECIPE_OUTPUT_PATH": {
            "description": ("Path to output file."),
            "required": False,
            "default": ".",
        },
        "NAME": {"description": ("The NAME key."), "required": False},
        "POLICY_NAME": {
            "description": ("The desired policy name."),
            "required": False,
            "default": "%NAME% - Installer From AutoPKG",
        },
        "policy_template": {
            "description": ("The desired policy template."),
            "required": False,
            "default": "_Install_Policy.xml",
        },
        "GROUP_NAME": {
            "description": ("The desired smart group name."),
            "required": False,
            "default": "SW - Patch Management",
        },
        "group_template": {
            "description": ("The desired smart group template."),
            "required": False,
            "default": "_Smart_Group.xml",
        },
        "RECIPE_IDENTIFIER_PREFIX": {
            "description": "The identifier prefix.",
            "required": False,
            "default": "apple.prowarehouse.patch-management-recipes",
        },
        "CATEGORY": {
            "description": ("The package category in Jamf Pro."),
            "required": False,
            "default": "Software",
        },
        "SELF_SERVICE_DESCRIPTION": {
            "description": (
                "The Self Service Description in Jamf Pro - requires running against a jss recipe."
            ),
            "required": False,
            "default": "",
        },
        "make_categories": {
            "description": ("Add JamfCategoryUploader process if true."),
            "required": False,
            "default": False,
        },
        "add_regex": {
            "description": ("Add VersionRegexGenerator process if true."),
            "required": False,
            "default": False,
        },
        "make_policy": {
            "description": (
                "Add StopProcessingIf, JamfComputerGroupUploader, and "
                "JamfPolicyUploader processes if true."
            ),
            "required": False,
            "default": False,
        },
        "format": {
            "description": ("recipe output format (plist or yaml)."),
            "required": False,
            "default": "yaml",
        },
    }

    output_variables = {
        "CATEGORY": {"description": ("The package category.")},
        "NAME": {"description": ("The NAME.")},
    }

    description = __doc__

    def represent_ordereddict(self, dumper, data):
        value = []

        for item_key, item_value in data.items():
            node_key = dumper.represent_data(item_key)
            node_value = dumper.represent_data(item_value)

            value.append((node_key, node_value))

        return MappingNode("tag:yaml.org,2002:map", value)

    def convert_to_yaml(self, data):
        """Do the conversion."""
        add_representer(OrderedDict, self.represent_ordereddict)
        return dump(data, width=float("inf"), default_flow_style=False)

    def convert_to_plist(self, data):
        """Do the conversion."""
        lines = write_plist(data).decode("utf-8").splitlines()
        lines.append("")
        return "\n".join(lines)

    def optimise_yaml_recipes(self, recipe):
        """If input is an AutoPkg recipe, optimise the yaml output in 3 ways to aid
        human readability:

        1. Adjust the Processor dictionaries such that the Comment and Arguments keys are
        moved to the end, ensuring the Processor key is first.
        2. Ensure the NAME key is the first item in the Input dictionary.
        3. Order the items such that the Input and Process dictionaries are at the end.
        """

        if "Process" in recipe:
            process = recipe["Process"]
            new_process = []
            for processor in process:
                processor = OrderedDict(processor)
                if "Comment" in processor:
                    processor.move_to_end("Comment")
                if "Arguments" in processor:
                    processor.move_to_end("Arguments")
                new_process.append(processor)
            recipe["Process"] = new_process

        if "Input" in recipe:
            input = recipe["Input"]
            if "NAME" in input:
                input = OrderedDict(reversed(list(input.items())))
                input.move_to_end("NAME")
            recipe["Input"] = OrderedDict(reversed(list(input.items())))

        desired_order = [
            "Comment",
            "Description",
            "Identifier",
            "ParentRecipe",
            "MinimumVersion",
            "Input",
            "Process",
            "ParentRecipeTrustInfo",
        ]
        desired_list = [k for k in desired_order if k in recipe]
        reordered_recipe = {k: recipe[k] for k in desired_list}
        reordered_recipe = OrderedDict(reordered_recipe)
        return reordered_recipe

    def format_yaml_recipes(self, output):
        """Add lines between Input and Process, and between multiple processes.
        This aids readability of yaml recipes"""
        # add line before specific processors
        for item in ["Input:", "Process:", "- Processor:", "ParentRecipeTrustInfo:"]:
            output = output.replace(item, "\n" + item)

        # remove line before first process
        output = output.replace("Process:\n\n-", "Process:\n-")

        recipe = []
        lines = output.splitlines()
        for line in lines:
            # convert quoted strings with newlines in them to scalars
            if "\\n" in line:
                spaces = len(line) - len(line.lstrip()) + 2
                space = " "
                line = line.replace(': "', ": |\n{}".format(space * spaces))
                line = line.replace("\\t", "    ")
                line = line.replace('\\n"', "")
                line = line.replace("\\n", "\n{}".format(space * spaces))
                line = line.replace('\\"', '"')
                if line[-1] == '"':
                    line[:-1]
            # elif "%" in lines:
            # handle strings that have AutoPkg %percent% variables in them
            # (these need to be quoted)

            recipe.append(line)
        recipe.append("")
        return "\n".join(recipe)

    def main(self):
        """output the values to a file in the location provided"""

        # set variables
        output_file_path = self.env.get("RECIPE_OUTPUT_PATH")
        name = self.env.get("NAME")
        identifier_prefix = self.env.get("RECIPE_IDENTIFIER_PREFIX")
        category = self.env.get("CATEGORY")
        self_service_description = self.env.get("SELF_SERVICE_DESCRIPTION")
        group_name = self.env.get("GROUP_NAME")
        group_template = self.env.get("group_template")
        policy_name = self.env.get("POLICY_NAME")
        policy_template = self.env.get("policy_template")
        make_categories = self.env.get("make_categories")
        recipe_format = self.env.get("format")
        # handle setting make_categories in overrides
        if not make_categories or make_categories == "False":
            make_categories = False
        make_policy = self.env.get("make_policy")
        # handle setting make_policy in overrides
        if not make_policy or make_policy == "False":
            make_policy = False
        add_regex = self.env.get("add_regex")
        # handle setting add_regex in overrides
        if not add_regex or add_regex == "False":
            add_regex = False

        # parent recipes dependent on whether we are running a pkg or jss recipe
        # and if we're running an override
        run_recipe_identifier = os.path.basename(self.env.get("RECIPE_CACHE_DIR"))
        parent_recipe = ""
        if ".jss." in self.env.get("RECIPE_CACHE_DIR") or "local." in self.env.get(
            "RECIPE_CACHE_DIR"
        ):
            for recipe in self.env.get("PARENT_RECIPES"):
                if ".pkg.recipe" in recipe:
                    # is the parent recipe a yaml or plist recipe?
                    try:
                        if ".yaml" in recipe:
                            self.output("Parent is a YAML recipe", verbose_level=2)
                            with open(recipe, "r") as in_file:
                                parent_recipe_data = yaml.safe_load(in_file)
                        else:
                            self.output("Parent is a PLIST recipe", verbose_level=2)
                            with open(recipe, "rb") as in_file:
                                parent_recipe_data = load_plist(in_file)
                        parent_recipe = os.path.basename(
                            parent_recipe_data["Identifier"]
                        )
                    except IOError:
                        self.output(
                            (
                                "WARNING: could not find parent recipe identifier. "
                                f'Defaulting to {self.env.get("RECIPE_CACHE_DIR")} '
                                "which may need editing."
                            )
                        )
                        parent_recipe = os.path.basename(
                            self.env.get("RECIPE_CACHE_DIR")
                        )
            if not parent_recipe:
                self.output(
                    (
                        "WARNING: could not find parent recipe identifier. "
                        f'Defaulting to {self.env.get("RECIPE_CACHE_DIR")} '
                        "which may need editing."
                    )
                )
                parent_recipe = os.path.basename(self.env.get("RECIPE_CACHE_DIR"))
        else:
            parent_recipe = os.path.basename(self.env.get("RECIPE_CACHE_DIR"))

        # filename dependent on whether making policy or not
        if make_policy:
            output_file_name = name.replace(" ", "") + ".jamf.recipe"
        else:
            output_file_name = name.replace(" ", "") + "-pkg-upload.jamf.recipe"
        if recipe_format == "yaml":
            output_file_name = output_file_name + ".yaml"
        output_file = os.path.join(output_file_path, output_file_name)

        # write recipe data
        # common settings
        data = {
            "Comment": (
                f"Recipe automatically generated from {run_recipe_identifier} "
                "by JamfRecipeMaker"
            ),
            "Identifier": (
                identifier_prefix + ".jamf." + name.replace(" ", "") + "-pkg-upload"
            ),
            "ParentRecipe": parent_recipe,
            "MinimumVersion": "2.3",
            "Input": {"NAME": name, "CATEGORY": category},
            "Process": [],
        }
        if make_policy:
            data["Identifier"] = identifier_prefix + ".jamf." + name.replace(" ", "")
        else:
            data["Identifier"] = (
                identifier_prefix + ".jamf." + name.replace(" ", "") + "-pkg-upload"
            )

        # JamfCategoryUploader
        if make_categories:
            data["Process"].append(
                {
                    "Processor": (
                        "com.github.grahampugh.jamf-upload.processors/JamfCategoryUploader"
                    ),
                    "Arguments": {"category_name": "%CATEGORY%"},
                }
            )
        # JamfPackageUploader
        data["Process"].append(
            {
                "Processor": "com.github.grahampugh.jamf-upload.processors/JamfPackageUploader",
                "Arguments": {"pkg_category": "%CATEGORY%"},
            }
        )
        if make_policy:
            # JamfComputerGroupUploader
            data["Input"]["GROUP_NAME"] = group_name
            data["Input"]["GROUP_TEMPLATE"] = group_template
            data["Input"]["TESTING_GROUP_NAME"] = "Testing"
            data["Input"]["POLICY_CATEGORY"] = "Testing"
            data["Input"]["POLICY_NAME"] = policy_name
            data["Input"]["POLICY_TEMPLATE"] = policy_template
            data["Input"]["SELF_SERVICE_DISPLAY_NAME"] = policy_name
            data["Input"]["SELF_SERVICE_DESCRIPTION"] = self_service_description
            data["Input"]["SELF_SERVICE_ICON"] = "%NAME%.png"
            data["Input"]["UPDATE_PREDICATE"] = "pkg_uploaded == False"
            data["Process"].append(
                {
                    "Processor": "StopProcessingIf",
                    "Arguments": {"predicate": "%UPDATE_PREDICATE%"},
                }
            )
            if add_regex:
                data["Process"].append(
                    {
                        "Processor": (
                            "com.github.grahampugh.recipes.commonprocessors/VersionRegexGenerator"
                        ),
                    }
                )
            data["Process"].append(
                {
                    "Processor": (
                        "com.github.grahampugh.jamf-upload.processors/JamfComputerGroupUploader"
                    ),
                    "Arguments": {
                        "computergroup_name": "%GROUP_NAME%",
                        "computergroup_template": "%GROUP_TEMPLATE%",
                    },
                }
            )
            if make_categories:
                data["Process"].append(
                    {
                        "Processor": (
                            "com.github.grahampugh.jamf-upload.processors/JamfCategoryUploader"
                        ),
                        "Arguments": {"category_name": "%POLICY_CATEGORY%"},
                    }
                )
            data["Process"].append(
                {
                    "Processor": (
                        "com.github.grahampugh.jamf-upload.processors/JamfPolicyUploader"
                    ),
                    "Arguments": {
                        "policy_name": "%POLICY_NAME%",
                        "policy_template": "%POLICY_TEMPLATE%",
                        "icon": "%SELF_SERVICE_ICON%",
                    },
                }
            )

        if recipe_format == "plist":
            output = self.convert_to_plist(data)
        else:
            normalized = self.optimise_yaml_recipes(data)
            output = self.convert_to_yaml(normalized)
            output = self.format_yaml_recipes(output)
        out_file = open(output_file, "w")
        out_file.writelines(output)
        self.output("Wrote to : {}\n".format(output_file))


if __name__ == "__main__":
    PROCESSOR = PatchMasterRecipeMaker()
    PROCESSOR.execute_shell()
    