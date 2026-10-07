# Limitless PTCGL Online Tournament Meta Analyzer

An unofficial, read-only Streamlit dashboard for descriptive analysis of public
Limitless Tournament Platform data. The deployed snapshot includes Standard,
online PTCGL tournaments from 2026-07-01 through 2026-10-07 with at least 60
players.

The dashboard can switch between the complete field, the full approved-player
cohort, and one approved player. The roster currently contains seven public
Play Limitless accounts: the original Azul Garcia Griego prototype plus six
`manual_decision=YES` players that also have a separately approved Play ID.
In cohort/player scope, deck representation uses only the selected population's
entries while matchup rates retain every opponent and count each match from the
selected population's perspective.

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

Production hides internal debug controls and detailed exception messages. To
enable the tournament-audit debug toggle during trusted local development, run:

```bash
LIMITLESS_ENABLE_DEBUG=1 .venv/bin/streamlit run dashboard/app.py
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

The dashboard reads only the bundled DuckDB snapshot and verified-player CSV.
It does not call the Limitless API when a visitor opens the app. Its sidebar
includes an optional [Buy Me a Coffee](https://buymeacoffee.com/qmi0000011)
support link.

## Refresh the data snapshot

Run the bundled updater locally with the new inclusive end date:

```bash
./scripts/update_data.sh YYYY-MM-DD
```

The script runs both `fetch` and `analyze`, reuses the local raw cache, rebuilds
`data/meta.duckdb`, and validates the result.

To keep only a rolling window, provide an optional start date as the second
argument:

```bash
./scripts/update_data.sh END_DATE START_DATE
```

After reviewing the dashboard, publish the new snapshot:

```bash
git add data/meta.duckdb
git commit -m "Update data through YYYY-MM-DD"
git push
```

Streamlit Community Cloud detects the GitHub update and redeploys the app.

## Maintain the verified player roster

Approved Play Limitless account mappings live in `data/verified_players.csv`.
Only rows with both `verification_status=YES` and `manual_decision=YES` appear
in the dashboard. Use the stable `play_limitless_player_id` as the analytics
key; social-media approval alone is not sufficient to add an account.

The identity-resolver project exports this guarded intersection and a complete
reason-coded audit:

```bash
cd ../ptcg-player-identity-resolver
.venv/bin/ptcg-resolver export-app-roster \
  --meta-db ../limitless-meta-streamlit/data/meta.duckdb \
  --existing-roster ../limitless-meta-streamlit/data/verified_players.csv \
  --worlds-2026-targets data/targets/worlds_2026_masters.csv \
  --output ../limitless-meta-streamlit/data/verified_players.csv \
  --audit-output data/review/manual_yes_app_roster_audit.csv
```

The resolver-local `data/review/manual_yes_app_roster_audit.csv` retains every
manual-YES target, including people still excluded because their Play ID is
not production-approved or is absent from the current App snapshot. It is not
part of the public Streamlit deployment.

After reviewing a new mapping, add one row and deploy it with the app:

```bash
git add data/verified_players.csv
git commit -m "Add verified player account"
git push
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
