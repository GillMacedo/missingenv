# 0001: Names only, in one standard-library script

**Decision:** read only variable names, never open real `.env` files, and use one Python script with no dependencies.

**Why:** a config tool sits close to secrets, so the safest design can't print a value because it never keeps one. No dependencies means it works right after install.

**Alternatives:** a YAML parser would read manifests more exactly, but adds an install step and fails on Helm templates, which aren't valid YAML. Comparing real `.env` files would find more drift, but means opening secrets.
