#!/usr/bin/env python3
#
# Generates strings.xml files from the gettext files. This script is run automatically by the
# Gradle task `generateStrings`.
#
# This script requires the package `polib`. It also runs contrib/make_locale, which requires
# the package `requests`, and the external commands `xgettext` and `msgfmt`.

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import os
from os.path import abspath, basename, dirname, isdir, join
import re
from subprocess import run
import sys

# We use polib because we need msgid_plural, which the standard library gettext module discards
# during parsing of .mo files.
import polib


SCRIPT_NAME = basename(__file__)
EC_ROOT = abspath(join(dirname(__file__), "../.."))


JAVA_KEYWORDS = set([
    "abstract", "assert", "boolean", "break", "byte", "case", "catch", "char", "class",
    "const", "continue", "default", "do", "double ", "else", "enum", "extends", "final",
    "finally", "float", "for", "goto", "if", "implements", "import", "instanceof", "int",
    "interface ", "long", "native", "new", "package", "private", "protected", "public",
    "return", "short", "static", "strictfp", "super", "switch ", "synchronized", "this",
    "throw", "throws", "transient", "try", "void", "volatile", "while"])

KOTLIN_KEYWORDS = set([  # "Hard" keywords only.
    "as", "break", "class", "continue", "do", "else", "false", "for", "fun", "if", "in",
    "interface", "is", "null", "object", "package", "return", "super", "this", "throw",
    "true", "try", "typealias", "typeof" "val", "var", "when", "while"])

KEYWORDS = JAVA_KEYWORDS | KOTLIN_KEYWORDS


# Map from gettext plural formula to Android quantity keywords. This will have to be extended
# as plural translations are added in more languages. Android uses the CLDR rules from
# http://www.unicode.org/cldr/charts/25/supplemental/language_plural_rules.html.
QUANTITIES = {
    # e.g. zh
    "0": {
        0: "other"
    },

    # e.g. de
    "(n != 1)": {
        0: "one",
        1: "other"
    },

    # e.g. fr
    "(n > 1)": {
        0: "one",   # For these languages, "one" includes zero (see CLDR link above).
        1: "other"
    },

    # e.g. ro
    "(n==1 ? 0 : (n==0 || (n%100>0 && n%100<20)) ? 1 : 2)": {
        0: "one",
        1: "few",
        2: "other"
    },
}


def main():
    args = parse_args()
    if not args.no_download:
        log("Running make_locale")
        run([sys.executable, join(EC_ROOT, "contrib/make_locale")], check=True)

    locale_dir = join(EC_ROOT, "lib/locale")
    lang_strings = defaultdict(list)
    for lang_region in [name for name in os.listdir(locale_dir)
                        if isdir(join(locale_dir, name)) and name != '__pycache__']:
        lang, region = lang_region.split("_")
        catalog = read_catalog(join(locale_dir, lang_region, "LC_MESSAGES",
                                    "electron-cash.mo"))
        lang_strings[lang].append((region, catalog))

    src_strings = read_catalog(join(locale_dir, "messages.pot"))
    ids = make_ids(src_strings)
    for lang, region_strings in lang_strings.items():
        region_strings.sort(key=region_order, reverse=True)
        for i, (region, strings) in enumerate(region_strings):
            write_xml(lang if i == 0 else "{}-r{}".format(lang, region),
                      strings, ids)

    # The main strings.xml should be generated last, because this script will only be
    # automatically run if it's missing.
    write_xml("", src_strings, ids)


def read_catalog(filename):
    try:
        is_pot = filename.endswith(".pot")
        f = (polib.mofile if filename.endswith(".mo") else polib.pofile)(filename)
        pf = f.metadata.get("Plural-Forms")
        if pf is None:
            quantities = None
        else:
            match = re.search(r"plural=(.+?);", pf)
            if not match:
                raise Exception("Failed to parse Plural-Forms")
            formula = match.group(1)
            quantities = QUANTITIES.get(formula)

        catalog = {}
        for entry in f:
            try:
                msgid = entry.msgid
                if is_excluded(msgid):
                    continue

                # Replace Python str.format syntax with Java String.format syntax.
                keywords = re.findall(r"\{(\w+)\}", msgid)
                def fix_format(s):
                    s = s.replace("{}", "%s")
                    for k in keywords:
                        s = s.replace("{" + k + "}",
                                      "%{}$s".format(keywords.index(k) + 1))
                    return s

                msgid = fix_format(msgid)
                if entry.msgid_plural:
                    if is_pot:
                        catalog[msgid] = {"one": msgid,
                                          "other": fix_format(entry.msgid_plural)}
                    else:
                        if quantities is None:
                            raise Exception(
                                "Unknown plural formula '{}': add it to QUANTITIES in {}"
                                .format(formula, SCRIPT_NAME))
                        catalog[msgid] = {quantities[i]: fix_format(s)
                                          for i, s in entry.msgstr_plural.items()}
                else:
                    catalog[msgid] = msgid if is_pot else fix_format(entry.msgstr)
            except Exception:
                raise Exception("Failed to process entry '{}'".format(entry.msgid))
        return catalog

    except Exception:
        raise Exception("Failed to process '{}'".format(filename))


# The region with the most translations is output without a country code so it will act as
# a fallback for the others.
#
# Apparently Android 7 and later treats traditional and simplified Chinese as unrelated
# languages. Since it interprets "zh" as being simplified, it will never use it in any
# traditional locale, preferring English instead
# (https://gist.github.com/amake/0ac7724681ac1c178c6f95a5b09f03ce). We work around this by
# giving priority to zh_CN (simplified Chinese), so it is always output as values-zh,
# irrespective of how many translations it contains.
def region_order(item):
    region, strings = item
    return (region == "CN",   # "zh" must always be simplified Chinese: see comment above.
            len(strings))


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-download", action="store_true")
    return ap.parse_args()


def is_excluded(src_str):
    return (re.search(r"^\W*$", src_str) or         # Empty or only punctuation.
            src_str in ["Auto connect"])            # Clashes with "Auto-connect".


# Returns a dict {s: id} where each `s` is a string in `strings`, and `id` is a unique
# Java/Kotlin identifier generated from it.
def make_ids(strings):
    ids_out = {}
    for id_options in [dict(lower=True, squash=True),
                       dict(lower=True, squash=False),
                       dict(lower=False, squash=False)]:
        ids_in = {s: tuple(str_to_id(s, **id_options).split("_"))
                  for s in strings}
        try:
            make_ids_inner(ids_in, ids_out)
            return {s: "_".join(id) for s, id in ids_out.items()}
        except DuplicateStringError:
            strings = list(ids_in)

    # The remaining strings differ only in equal-length sequences of space or punctuation. We
    # could handle this by generating unique suffixes for the ID, but that could cause the ID
    # to get a different value when the string set changes. So it's safer to just list the
    # undesired string in is_excluded.
    raise Exception("Failed to make unique IDs for the following strings:\n" +
                    "\n".join(repr(s) for s in sorted(strings, key=case_insensitive)))


def make_ids_inner(ids_in, ids_out):
    max_words = 2
    existing_ids = list(ids_out.values())
    prev_counts = None
    while ids_in:
        counts = Counter(existing_ids)
        counts.update([id[:max_words] for id in ids_in.values()])
        if counts == prev_counts:
            raise DuplicateStringError()

        strings_done = []
        for s, id in ids_in.items():
            short_id = id[:max_words]
            if counts[short_id] == 1:
                ids_out[s] = short_id
                strings_done.append(s)
        for s in strings_done:
            del ids_in[s]

        prev_counts = counts
        max_words += 1


class DuplicateStringError(Exception):
    pass


# Returns an identifier generated from every word in the given string.
def str_to_id(s, *, lower, squash):
    s = s.replace("'", "")  # Combine contractions.
    if lower:
        s = s.lower()

    if squash:
        s = re.sub(r"%\S+", "", s)  # Remove placeholders.
        pattern = r"\W+"
        lstrip = "0123456789_"
        rstrip = "_"
    else:
        pattern = r"\W"
        lstrip = "0123456789"
        rstrip = ""
    id = (re.sub(pattern, "_", s, flags=re.ASCII)  # Remove invalid characters.
          .lstrip(lstrip)
          .rstrip(rstrip))
    if id in KEYWORDS:
        id += "_"
    return id


def write_xml(res_suffix, strings, ids):
    dir_name = "values" + ("-" + res_suffix if res_suffix else "")
    base_name = "strings.xml"
    log("Generating {}/{}: ".format(dir_name, base_name), end="")

    abs_dir_name = join(EC_ROOT, "android/app/src/main/res", dir_name)
    os.makedirs(abs_dir_name, exist_ok=True)

    timestamp = datetime.utcnow().isoformat()
    output = sorted(((ids[src_str], tgt)
                     for src_str, tgt in strings.items()
                     if src_str in ids),  # Crowdin strings may not be in our local source.
                    key=lambda x: case_insensitive(x[0]))
    with open(join(abs_dir_name, base_name), "w", encoding="UTF-8") as f:
        print('<?xml version="1.0" encoding="utf-8"?>', file=f)
        print('<!-- Generated by {} at {} -->'.format(SCRIPT_NAME, timestamp), file=f)
        print('<!-- DO NOT EDIT: edit the source Python files instead. -->', file=f)
        print('<resources>', file=f)
        for id, tgt in output:
            if isinstance(tgt, dict):
                print('    <plurals name="{}">'.format(id), file=f)
                for quantity, s in tgt.items():
                    print('        <item quantity="{}">{}</item>'
                          .format(quantity, str_for_xml(s)), file=f)
                print('    </plurals>', file=f)
            else:
                print('    <string name="{}">{}</string>'.format(id, str_for_xml(tgt)), file=f)
        print('</resources>', file=f)

    log("{} items".format(len(output)))


XML_REPLACEMENTS = [
    # Generic XML syntax
    ("&", "&amp;"),
    ("<", "&lt;"),
    (">", "&gt;"),

    # Android-specific syntax
    # (https://developer.android.com/guide/topics/resources/string-resource#escaping_quotes)
    (re.compile(r"^([@?])"), r"\1"),
    ("'", r"\'"),
    ('"', r'\"'),
    ("\n", r"\n"),
]

def str_for_xml(s):
    for old, new in XML_REPLACEMENTS:
        if isinstance(old, str):
            s = s.replace(old, new)
        else:
            s = re.sub(old, new, s)
    return s


def log(*args, **kwargs):
    print(*args, **kwargs)
    kwargs.get("file", sys.stdout).flush()


def case_insensitive(s):
    return (s.lower(), s)


if __name__ == "__main__":
    main()
