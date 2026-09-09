# Demo-Dashboard-Daten

`demo_input.csv` + `demo_output.csv` sind ein zusammengehöriges Paar aus **einem** echten
Optimierungslauf – exakt das Format einer `provide_input_output_csv`-Antwort von shyft-power:

- `demo_input.csv`: das `input_csv`, das der Optimizer für den Lauf bekommen hat (Spalten wie in
  `optimizer_in.ftl` im `shyft`-Repo, `;`-getrennt).
- `demo_output.csv`: das dazugehörige `output_csv` (Optimizer-Ergebnis, `,`-getrennt).

Solange kein echter `shyft_access_key` hinterlegt ist (`is_demo_mode()` in `app.py`), ruft das
Addon nie Bubble/shyft-power auf – auch nicht für die Dashboard-Charts. Stattdessen liest
`sync_dashboard_chart_data()` → `_load_demo_dashboard_data()` diese beiden Dateien und schreibt sie
in denselben Cache (`DASHBOARD_CACHE_PATH`), den es sonst aus der echten Antwort befüllt.

`creation_date` wird beim Einlesen automatisch auf die aktuelle volle Stunde gesetzt – die
Beispieldaten müssen also nicht "frisch" gehalten werden.

**Live-Überlagerung:** `_overlay_live_demo_series()` ersetzt vor dem Cachen die Spalten
`Temperature`, `PV_generation` und `p_buy` durch Live-Werte (open-meteo-Wetter + Default-m²-
PV-Prognose + Awattar-Börsenpreis + fixer Anteil `DEMO_DYNAMIC_SURCHARGE_CENT`), damit die
Charts zur aktuellen Jahreszeit/Börsenlage passen. Das ist bewusst inkonsistent zum restlichen,
statischen Demo-Datensatz. Schlägt eine Live-Quelle fehl, bleibt die jeweilige Spalte statisch.

Die Dateien werden über das `Dockerfile` (`COPY demo_data /app/demo_data`) ins Image übernommen.
