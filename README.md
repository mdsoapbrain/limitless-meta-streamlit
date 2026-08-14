# Limitless PTCGL Online Tournament Meta Analyzer

An unofficial, read-only Streamlit dashboard for descriptive analysis of public
Limitless Tournament Platform data. The deployed snapshot includes Standard,
online PTCGL tournaments from 2026-07-01 through 2026-08-13 with at least 60
players.

## Run locally

Python 3.11 is recommended.

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python scripts/verify_deploy.py
.venv/bin/python -m pytest -q
.venv/bin/streamlit run dashboard/app.py
```

## Deploy to Streamlit Community Cloud

1. Push this directory to a GitHub repository. The included
   `data/meta.duckdb` file must remain tracked; Git LFS is recommended for
   future database versions.
2. In Streamlit Community Cloud, create an app from the repository.
3. Set the entrypoint to `dashboard/app.py`.
4. Open Advanced settings and select Python 3.11.
5. Deploy. No secrets are required for this read-only snapshot.

The dashboard reads only the bundled DuckDB file. It does not call the
Limitless API when a visitor opens the app. Its sidebar includes an optional
[Buy Me a Coffee](https://buymeacoffee.com/qmi0000011) support link.

## Refresh the data snapshot

Run the analysis pipeline outside Streamlit Community Cloud, verify the new
database, then commit the updated `data/meta.duckdb` file:

```bash
.venv/bin/python -m limitless_meta analyze \
  --start 2026-07-01 \
  --end YYYY-MM-DD \
  --min-players 60 \
  --match-scope all

.venv/bin/python scripts/verify_deploy.py
```

Raw API cache and CSV analytics are intentionally excluded from the deployment
repository. Community Cloud local storage is not used as persistent storage.

## Notes

- Weighted Impact is descriptive and is not a forecast.
- Player names and decklists originate from public tournament standings.
- This project is independent and is not affiliated with or endorsed by
  Limitless or The Pokémon Company.
- Review third-party terms and obtain appropriate permission before commercial
  use.
