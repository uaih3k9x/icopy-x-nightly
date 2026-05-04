#!/usr/bin/env python3

##########################################################################
# Required Notice: Copyright ETOILE401 SAS (http://www.lab401.com)
#
# Initial author: ETOILE401 SAS & https://github.com/quantum-x/ as of April 16, 2026
#
# Since this date, each contribution is under the copyright of its respective author.
#
# Copyright of each contribution is tracked by the Git history. See the output of git shortlog -nse for a full list or git log --pretty=short --follow <path/to/sourcefile> |git shortlog -ne to track a specific file.
#
# A mailmap is maintained to map author and committer names and email addresses to canonical names and email addresses.
# If by accident a copyright was removed from a file and is not directly deducible from the Git history, please submit a PR.
#
#
# This software is licensed under the PolyForm Noncommercial License 1.0.0.
# You may not use this software for commercial purposes.
#
# A copy of the license is available at:
# https://polyformproject.org/licenses/noncommercial/1.0.0
#
# This entire header "Required Notice" must remain in place.
##########################################################################

"""Lightweight i18n linter for iCopy-X.

Checks the parts of the localization surface that are structured enough to
validate safely:

* src/lib/resources.py: StringEN/StringZH key parity and placeholder parity.
* build/clients/factory/share/luascripts: Lua script display-name tables.

The tool is intentionally stdlib-only and Python 3.8 compatible so it can run
on developer machines, GitHub Actions, and small device-side diagnostic wrappers.
"""

import argparse
import importlib.util
import json
import os
import re
import sys


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_RESOURCES = os.path.join(REPO_ROOT, "src", "lib", "resources.py")
DEFAULT_LUA_DIR = os.path.join(
    REPO_ROOT, "build", "clients", "factory", "share", "luascripts"
)
DEFAULT_PLUGIN_DIR = os.path.join(REPO_ROOT, "plugins")

RESOURCE_CLASSES = {
    "en": "StringEN",
    "zh": "StringZH",
}

RESOURCE_DICTS = (
    "button",
    "title",
    "toastmsg",
    "tipsmsg",
    "procbarmsg",
    "itemmsg",
)

LUA_TRANSLATION_CANDIDATES = (
    "lua_script_manifest.%s.json",
    "lua_script_names.%s.json",
)

PLUGIN_MANIFEST_FIELDS = (
    "name",
    "description",
)

PLUGIN_UI_LOCALIZABLE_KEYS = (
    "name",
    "title",
    "page",
    "label",
    "text",
    "message",
    "header",
    "subheader",
)

BRACE_PLACEHOLDER_RE = re.compile(r"\{[^{}]*\}")
PERCENT_PLACEHOLDER_RE = re.compile(
    r"%(?:\([^)]+\))?[-+#0 ]*(?:\d+|\*)?(?:\.(?:\d+|\*))?[hlL]?[diouxXeEfFgGcrs%]"
)
SIMPLE_PLACEHOLDER_RE = re.compile(r"^\{[A-Za-z_][A-Za-z0-9_]*\}$")
ACTION_VALUE_RE = re.compile(r"^(run|set_state|push|scroll):")


class Report:
    def __init__(self):
        self.failures = []
        self.warnings = []
        self.passes = []

    def fail(self, message):
        self.failures.append(message)

    def warn(self, message):
        self.warnings.append(message)

    def passed(self, message):
        self.passes.append(message)

    @property
    def ok(self):
        return not self.failures

    def print_summary(self):
        for message in self.passes:
            print("[PASS] %s" % message)
        for message in self.warnings:
            print("[WARN] %s" % message)
        for message in self.failures:
            print("[FAIL] %s" % message)

        print()
        print(
            "i18n lint: %d pass, %d warning, %d failure"
            % (len(self.passes), len(self.warnings), len(self.failures))
        )


def _load_python_module(path):
    if not os.path.isfile(path):
        raise IOError("file not found: %s" % path)

    spec = importlib.util.spec_from_file_location("icopyx_lint_resources", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot import %s" % path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _short_list(items, limit=8):
    items = sorted(items)
    if len(items) <= limit:
        return ", ".join(items)
    return "%s, ... (+%d)" % (", ".join(items[:limit]), len(items) - limit)


def _format_key(category, key):
    return "%s.%s" % (category, key)


def _resource_class_name(lang):
    return RESOURCE_CLASSES.get(lang, "String%s" % lang.upper())


def _placeholders(value):
    """Return format placeholders that must remain compatible across locales."""
    brace_tokens = BRACE_PLACEHOLDER_RE.findall(value)
    percent_tokens = [
        token for token in PERCENT_PLACEHOLDER_RE.findall(value)
        if token != "%%"
    ]
    return tuple(brace_tokens), tuple(percent_tokens)


def _lint_resource_pair(report, resources, base_lang, target_lang):
    base_class_name = _resource_class_name(base_lang)
    target_class_name = _resource_class_name(target_lang)

    if not hasattr(resources, base_class_name):
        report.fail("missing resource class %s" % base_class_name)
        return
    if not hasattr(resources, target_class_name):
        report.fail("missing resource class %s" % target_class_name)
        return

    base_class = getattr(resources, base_class_name)
    target_class = getattr(resources, target_class_name)

    for category in RESOURCE_DICTS:
        base_dict = getattr(base_class, category, None)
        target_dict = getattr(target_class, category, None)
        if not isinstance(base_dict, dict):
            report.fail("%s.%s is not a dict" % (base_class_name, category))
            continue
        if not isinstance(target_dict, dict):
            report.fail("%s.%s is not a dict" % (target_class_name, category))
            continue

        base_keys = set(base_dict.keys())
        target_keys = set(target_dict.keys())

        missing = base_keys - target_keys
        extra = target_keys - base_keys
        if missing:
            report.fail(
                "%s missing %d key(s) from %s: %s"
                % (target_class_name, len(missing), category, _short_list(missing))
            )
        if extra:
            report.fail(
                "%s has %d extra key(s) in %s: %s"
                % (target_class_name, len(extra), category, _short_list(extra))
            )
        if not missing and not extra:
            report.passed(
                "%s/%s %s key parity (%d keys)"
                % (base_lang, target_lang, category, len(base_keys))
            )

        for key in sorted(base_keys & target_keys):
            base_value = base_dict[key]
            target_value = target_dict[key]

            if not isinstance(base_value, str):
                report.fail("%s value is not a string" % _format_key(category, key))
                continue
            if not isinstance(target_value, str):
                report.fail(
                    "%s %s value is not a string"
                    % (target_lang, _format_key(category, key))
                )
                continue
            if not target_value.strip():
                report.fail(
                    "%s %s value is empty"
                    % (target_lang, _format_key(category, key))
                )
                continue

            base_tokens = _placeholders(base_value)
            target_tokens = _placeholders(target_value)
            if base_tokens != target_tokens:
                report.fail(
                    "%s placeholder mismatch: %s has %r, %s has %r"
                    % (
                        _format_key(category, key),
                        base_lang,
                        base_tokens,
                        target_lang,
                        target_tokens,
                    )
                )


def lint_resources(report, resources_path, langs):
    try:
        resources = _load_python_module(resources_path)
    except Exception as exc:
        report.fail("cannot load resources.py: %s" % exc)
        return

    for lang in langs:
        if lang == "en":
            continue
        _lint_resource_pair(report, resources, "en", lang)


def _lua_script_names(lua_dir):
    names = []
    if not os.path.isdir(lua_dir):
        return names
    for filename in os.listdir(lua_dir):
        if filename.endswith(".lua"):
            names.append(filename[:-4])
    return sorted(names)


def _load_lua_translation(lua_dir, lang):
    for pattern in LUA_TRANSLATION_CANDIDATES:
        path = os.path.join(lua_dir, pattern % lang)
        if os.path.isfile(path):
            return path, _read_json(path)
    return None, None


def _normalize_lua_table(raw):
    """Return name_map, info_map, mode for supported Lua translation formats."""
    if isinstance(raw, dict) and isinstance(raw.get("scripts"), dict):
        raw = raw.get("scripts")

    if not isinstance(raw, dict):
        return None, None, None

    name_map = {}
    info_map = {}
    mode = "names"
    for key, value in raw.items():
        if isinstance(value, str):
            name_map[key] = value
        elif isinstance(value, dict):
            mode = "manifest"
            name = value.get("name")
            info = value.get("info")
            if isinstance(name, str):
                name_map[key] = name
            if isinstance(info, str):
                info_map[key] = info
        else:
            name_map[key] = value
    return name_map, info_map, mode


def lint_lua_translations(report, lua_dir, langs, require_lua_info):
    scripts = _lua_script_names(lua_dir)
    if not scripts:
        report.warn("Lua script directory has no .lua files: %s" % lua_dir)
        return

    script_set = set(scripts)
    report.passed("Lua script inventory (%d scripts)" % len(scripts))

    for lang in langs:
        if lang == "en":
            continue

        try:
            path, raw = _load_lua_translation(lua_dir, lang)
        except (OSError, ValueError) as exc:
            report.fail("cannot load Lua %s translation table: %s" % (lang, exc))
            continue

        if path is None:
            report.fail(
                "missing Lua %s translation table in %s"
                % (lang, lua_dir)
            )
            continue

        name_map, info_map, mode = _normalize_lua_table(raw)
        if name_map is None:
            report.fail("%s is not a supported Lua translation table" % path)
            continue

        key_set = set(name_map.keys())
        missing = script_set - key_set
        extra = key_set - script_set
        if missing:
            report.fail(
                "Lua %s table missing %d script label(s): %s"
                % (lang, len(missing), _short_list(missing))
            )
        if extra:
            report.fail(
                "Lua %s table has %d stale key(s): %s"
                % (lang, len(extra), _short_list(extra))
            )

        bad_values = []
        empty_values = []
        for key, value in name_map.items():
            if not isinstance(value, str):
                bad_values.append(key)
            elif not value.strip():
                empty_values.append(key)
        if bad_values:
            report.fail(
                "Lua %s table has non-string label(s): %s"
                % (lang, _short_list(bad_values))
            )
        if empty_values:
            report.fail(
                "Lua %s table has empty label(s): %s"
                % (lang, _short_list(empty_values))
            )

        if require_lua_info:
            if mode != "manifest":
                report.fail(
                    "Lua %s table has labels only; info requires manifest entries"
                    % lang
                )
            else:
                missing_info = [
                    key for key in scripts
                    if not isinstance(info_map.get(key), str)
                    or not info_map.get(key, "").strip()
                ]
                if missing_info:
                    report.fail(
                        "Lua %s table missing %d info field(s): %s"
                        % (lang, len(missing_info), _short_list(missing_info))
                    )

        if not missing and not extra and not bad_values and not empty_values:
            report.passed(
                "Lua %s labels covered by %s (%d labels)"
                % (lang, os.path.relpath(path, REPO_ROOT), len(scripts))
            )


def _plugin_dirs(plugin_dir):
    if not os.path.isdir(plugin_dir):
        return []
    result = []
    for name in sorted(os.listdir(plugin_dir)):
        if name.startswith(".") or name.startswith("_"):
            continue
        path = os.path.join(plugin_dir, name)
        if os.path.isdir(path):
            result.append(path)
    return result


def _is_localizable_plugin_string(value):
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text:
        return False
    if SIMPLE_PLACEHOLDER_RE.match(text):
        return False
    if ACTION_VALUE_RE.match(text) or text in ("finish", "select", "pop", "noop"):
        return False
    return True


def _collect_value(strings, value, path):
    if _is_localizable_plugin_string(value):
        strings.setdefault(value, []).append(path)


def _collect_button_strings(strings, buttons, path):
    if not isinstance(buttons, dict):
        return
    for key, value in buttons.items():
        item_path = "%s.%s" % (path, key)
        if isinstance(value, str):
            _collect_value(strings, value, item_path)
        elif isinstance(value, dict):
            _collect_value(strings, value.get("text"), item_path + ".text")


def _collect_plugin_ui_strings(obj, strings, path="ui", parent_key=None):
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "i18n":
                continue
            item_path = "%s.%s" % (path, key)
            if key == "buttons":
                _collect_button_strings(strings, value, item_path)
            elif key in PLUGIN_UI_LOCALIZABLE_KEYS:
                _collect_value(strings, value, item_path)
            else:
                _collect_plugin_ui_strings(value, strings, item_path, key)
        return

    if isinstance(obj, list):
        for index, value in enumerate(obj):
            _collect_plugin_ui_strings(
                value, strings, "%s[%d]" % (path, index), parent_key)
        return

    if parent_key in ("lines", "items"):
        _collect_value(strings, obj, path)


def _plugin_ui_translation_table(ui, lang):
    i18n = ui.get("i18n", {})
    if not isinstance(i18n, dict):
        return None
    table = i18n.get(lang)
    if not isinstance(table, dict):
        return None
    strings = table.get("strings", table)
    if not isinstance(strings, dict):
        return None
    return strings


def _lint_plugin_manifest_i18n(report, plugin_name, manifest, langs):
    i18n = manifest.get("i18n", {})
    if not isinstance(i18n, dict):
        i18n = {}

    for lang in langs:
        if lang == "en":
            continue

        table = i18n.get(lang)
        if not isinstance(table, dict):
            report.fail("%s manifest missing %s i18n table" % (plugin_name, lang))
            continue

        failures = []
        for field in PLUGIN_MANIFEST_FIELDS:
            source = manifest.get(field, "")
            if not _is_localizable_plugin_string(source):
                continue
            value = table.get(field)
            if not isinstance(value, str) or not value.strip():
                failures.append(field)
                continue
            if _placeholders(source) != _placeholders(value):
                report.fail(
                    "%s manifest %s.%s placeholder mismatch"
                    % (plugin_name, lang, field)
                )

        if failures:
            report.fail(
                "%s manifest %s missing field(s): %s"
                % (plugin_name, lang, _short_list(failures))
            )
        else:
            report.passed("%s manifest %s i18n covered" % (plugin_name, lang))


def _lint_plugin_ui_i18n(report, plugin_name, ui_path, ui, langs):
    strings = {}
    _collect_plugin_ui_strings(ui, strings)

    for lang in langs:
        if lang == "en":
            continue

        table = _plugin_ui_translation_table(ui, lang)
        if table is None:
            if strings:
                report.fail("%s ui.json missing %s strings table" % (plugin_name, lang))
            continue

        source_set = set(strings.keys())
        key_set = set(table.keys())
        missing = source_set - key_set
        extra = key_set - source_set
        if missing:
            report.fail(
                "%s ui.json %s missing %d string(s): %s"
                % (plugin_name, lang, len(missing), _short_list(missing))
            )
        if extra:
            report.fail(
                "%s ui.json %s has %d stale string(s): %s"
                % (plugin_name, lang, len(extra), _short_list(extra))
            )

        bad_values = []
        empty_values = []
        for key, value in table.items():
            if not isinstance(value, str):
                bad_values.append(key)
            elif not value.strip():
                empty_values.append(key)
        if bad_values:
            report.fail(
                "%s ui.json %s has non-string translation(s): %s"
                % (plugin_name, lang, _short_list(bad_values))
            )
        if empty_values:
            report.fail(
                "%s ui.json %s has empty translation(s): %s"
                % (plugin_name, lang, _short_list(empty_values))
            )

        for key in sorted(source_set & key_set):
            value = table.get(key)
            if isinstance(value, str) and _placeholders(key) != _placeholders(value):
                report.fail(
                    "%s ui.json %s placeholder mismatch for %r"
                    % (plugin_name, lang, key)
                )

        if not missing and not extra and not bad_values and not empty_values:
            report.passed(
                "%s ui.json %s strings covered by %s (%d strings)"
                % (
                    plugin_name,
                    lang,
                    os.path.relpath(ui_path, REPO_ROOT),
                    len(source_set),
                )
            )


def lint_plugin_translations(report, plugin_dir, langs):
    plugins = _plugin_dirs(plugin_dir)
    if not plugins:
        report.warn("Plugin directory has no plugins: %s" % plugin_dir)
        return

    for plugin_path in plugins:
        plugin_name = os.path.basename(plugin_path)
        manifest_path = os.path.join(plugin_path, "manifest.json")
        if not os.path.isfile(manifest_path):
            report.warn("%s has no manifest.json" % plugin_name)
            continue

        try:
            manifest = _read_json(manifest_path)
        except (OSError, ValueError) as exc:
            report.fail("%s manifest cannot be read: %s" % (plugin_name, exc))
            continue
        if not isinstance(manifest, dict):
            report.fail("%s manifest is not a JSON object" % plugin_name)
            continue

        _lint_plugin_manifest_i18n(report, plugin_name, manifest, langs)

        ui_path = os.path.join(plugin_path, "ui.json")
        if not os.path.isfile(ui_path):
            continue
        try:
            ui = _read_json(ui_path)
        except (OSError, ValueError) as exc:
            report.fail("%s ui.json cannot be read: %s" % (plugin_name, exc))
            continue
        if not isinstance(ui, dict):
            report.fail("%s ui.json is not a JSON object" % plugin_name)
            continue
        _lint_plugin_ui_i18n(report, plugin_name, ui_path, ui, langs)


def _parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Lint iCopy-X localization resources."
    )
    parser.add_argument(
        "--resources",
        default=DEFAULT_RESOURCES,
        help="Path to src/lib/resources.py",
    )
    parser.add_argument(
        "--lua-dir",
        default=DEFAULT_LUA_DIR,
        help="Directory containing factory Lua scripts and translation tables",
    )
    parser.add_argument(
        "--plugin-dir",
        default=DEFAULT_PLUGIN_DIR,
        help="Directory containing plugin subdirectories",
    )
    parser.add_argument(
        "--lang",
        action="append",
        default=None,
        help="Language code to check. Can be repeated. Default: zh",
    )
    parser.add_argument(
        "--require-lua-info",
        action="store_true",
        help="Require Lua translation manifest entries to include info text.",
    )
    parser.add_argument(
        "--skip-resources",
        action="store_true",
        help="Skip src/lib/resources.py checks.",
    )
    parser.add_argument(
        "--skip-lua",
        action="store_true",
        help="Skip Lua script translation checks.",
    )
    parser.add_argument(
        "--skip-plugins",
        action="store_true",
        help="Skip plugin manifest/ui translation checks.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv or sys.argv[1:])
    langs = args.lang or ["zh"]

    report = Report()
    if not args.skip_resources:
        lint_resources(report, args.resources, langs)
    if not args.skip_lua:
        lint_lua_translations(report, args.lua_dir, langs, args.require_lua_info)
    if not args.skip_plugins:
        lint_plugin_translations(report, args.plugin_dir, langs)

    report.print_summary()
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
