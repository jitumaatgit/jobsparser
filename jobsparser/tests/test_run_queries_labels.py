"""run_queries.sh pairs each search term with its job family label.

The seam under test is the command line the script hands to the `jobsparser`
CLI: a stub executable records its argv, so `--search-term`/`--term-label`
pairing is observed exactly as the CLI receives it. A family label containing
spaces, commas or an ampersand either survives as one argument or it does not,
and nothing here needs the network.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "run_queries.sh"

# Stub standing in for the CLI: one line per argv entry, so a value that
# reaches the CLI as two arguments shows up as two lines.
STUB = """#!/usr/bin/env bash
for a in "$@"; do printf '%s\\n' "$a"; done
"""

# A term before any family header, a family whose label holds commas and an
# ampersand, a comment between header and term, and a commented-out term
# underneath a family header.
QUERIES = '''("entry-level" OR "no experience")

# --- Retail, Logistics & Specialized Trades ---
# Note: a comment between the header and the term must not reset the family.
("retail" OR cashier)

# --- IT, Office & Documentation ---
("help desk" OR "data entry")
#("database administrator" OR DBA)
'''

RETAIL = "Retail, Logistics & Specialized Trades"
IT = "IT, Office & Documentation"
COMMENTED_TERM = '("database administrator" OR DBA)'


def term_label_pairs(argv):
    """Return [(search term, term label)] in argv order.

    The label is ``None`` when the script passed no ``--term-label`` at all and
    ``''`` when it passed the flag with an empty value, which are different
    things: the ticket asks for the flag either way.
    """
    found = []
    i = 0
    while i < len(argv):
        if argv[i] == "--search-term":
            term = argv[i + 1]
            i += 2
            if i + 1 < len(argv) and argv[i] == "--term-label":
                found.append((term, argv[i + 1]))
                i += 2
            else:
                found.append((term, None))
        else:
            i += 1
    return found


class TermLabelTests(unittest.TestCase):
    def run_queries(self, queries=None, **env_extra):
        """Run the real script against a stub CLI in an isolated directory."""
        with tempfile.TemporaryDirectory(prefix="run-queries-") as tmp:
            root = Path(tmp)
            script = root / "run_queries.sh"
            shutil.copy2(SCRIPT, script)
            cli = root / ".venv" / "bin"
            cli.mkdir(parents=True)
            stub = cli / "jobsparser"
            stub.write_text(STUB)
            stub.chmod(0o755)
            (root / "queries.txt").write_text(
                QUERIES if queries is None else queries
            )

            env = dict(os.environ)
            # The script's own queries.txt lives in the copy's directory, so
            # an inherited value must not redirect it.
            env.pop("QUERIES_FILE", None)
            env.update({key: str(value) for key, value in env_extra.items()})

            return subprocess.run(
                [str(script)],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )

    def test_each_active_term_is_paired_with_the_family_above_it(self):
        proc = self.run_queries()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            term_label_pairs(proc.stdout.splitlines()),
            [
                ('("entry-level" OR "no experience")', ""),
                ('("retail" OR cashier)', RETAIL),
                ('("help desk" OR "data entry")', IT),
            ],
        )

    def test_a_family_label_with_commas_and_an_ampersand_stays_one_argument(self):
        argv = self.run_queries().stdout.splitlines()
        self.assertEqual(3, len(term_label_pairs(argv)))
        self.assertIn(RETAIL, argv)
        self.assertIn(IT, argv)
        # Word splitting would surface each fragment as its own argument.
        for fragment in (
            "Retail,",
            "Logistics",
            "&",
            "Specialized",
            "Trades",
            "IT,",
            "Office",
            "Documentation",
        ):
            self.assertNotIn(fragment, argv)

    def test_a_header_with_stray_trailing_whitespace_still_names_its_family(self):
        # A header ending in a stray space or a carriage return must not fall
        # through the comment branch: that would file the term beneath it under
        # the previous family and stamp wrong provenance onto its rows.
        for suffix in (" ", "\r"):
            with self.subTest(suffix=suffix):
                queries = (
                    "# --- Retail, Logistics & Specialized Trades ---\n"
                    '("retail" OR cashier)\n'
                    f"# --- IT, Office & Documentation ---{suffix}\n"
                    '("help desk" OR "data entry")\n'
                )
                argv = self.run_queries(queries).stdout.splitlines()
                self.assertEqual(
                    term_label_pairs(argv),
                    [
                        ('("retail" OR cashier)', RETAIL),
                        ('("help desk" OR "data entry")', IT),
                    ],
                )

    def test_a_commented_out_term_contributes_no_term_and_no_label(self):
        proc = self.run_queries()
        argv = proc.stdout.splitlines()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn(COMMENTED_TERM, argv)
        self.assertEqual(3, len(term_label_pairs(argv)))

    def test_a_queries_file_with_no_active_terms_still_exits_non_zero(self):
        proc = self.run_queries(
            "# --- Retail, Logistics & Specialized Trades ---\n"
            '#("retail" OR cashier)\n'
        )
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("No active search terms", proc.stderr)

    def test_the_estimated_time_banner_still_reports_the_run(self):
        proc = self.run_queries(RESULTS_WANTED=1)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Running 3 search term(s)", proc.stdout)
        self.assertIn("1 results each", proc.stdout)
        self.assertIn("Roughly", proc.stdout)
        self.assertIn("min minimum", proc.stdout)


if __name__ == "__main__":
    unittest.main()
