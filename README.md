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

1. Create an empty GitHub repository, then connect and push this local repository:

   ```bash
   git remote add origin https://github.com/YOUR_USERNAME/limitless-meta-streamlit.git
   git push -u origin main
   ```

2. The included
   `data/meta.duckdb` file must remain tracked; Git LFS is recommended for
   future database versions.
3. In Streamlit Community Cloud, create an app from the repository.
4. Set the branch to `main` and the entrypoint to `dashboard/app.py`.
5. Open Advanced settings and select Python 3.11.
6. Deploy. No secrets are required for this read-only snapshot.

The dashboard reads only the bundled DuckDB file. It does not call the
Limitless API when a visitor opens the app. Its sidebar includes an optional
[Buy Me a Coffee](https://buymeacoffee.com/qmi0000011) support link.

## Refresh the data snapshot

Run the bundled updater locally with the new inclusive end date:

```bash
./scripts/update_data.sh YYYY-MM-DD
```

The script runs both `fetch` and `analyze`, reuses the local raw cache, rebuilds
`data/meta.duckdb`, and validates the result. After reviewing the dashboard,
publish the new snapshot:

```bash
git add data/meta.duckdb
git commit -m "Update data through YYYY-MM-DD"
git push
```

Streamlit Community Cloud detects the GitHub update and redeploys the app.

Raw API cache and CSV analytics are intentionally excluded from the deployment
repository. Community Cloud local storage is not used as persistent storage.

## Notes

- Weighted Impact is descriptive and is not a forecast.
- Player names and decklists originate from public tournament standings.
- This project is independent and is not affiliated with or endorsed by
  Limitless or The Pokémon Company.
- Review third-party terms and obtain appropriate permission before commercial
  use.
