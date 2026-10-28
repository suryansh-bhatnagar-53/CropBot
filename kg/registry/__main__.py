from . import RegistryError, read_registry


def main():
    try:
        entries = read_registry()
    except RegistryError as e:
        raise SystemExit("registry is invalid:\n  " + "\n  ".join(e.problems))
    for e in entries:
        approved = [r for r in e.default_scope if r.status == "approved"]
        print("%s  %s  (sha256 ok: %s)" % (e.id, e.file, e.sha256[:12]))
        print("  tier %d, edition %s, state %s, scope %s"
              % (e.authority_tier, e.edition_label, e.state_id, ", ".join(e.region_scope)))
        print("  default_scope: %d approved of %d" % (len(approved), len(e.default_scope)))
        for r in approved:
            print("    -", r.label())
        print("  section_scope: %d approved of %d"
              % (len(e.approved_section_scopes()), len(e.section_scope)))
    print("registry ok: %d entries" % len(entries))


main()
