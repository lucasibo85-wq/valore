# Valore – statistiche, probabilità e scommesse di valore

App web per NBA e calcio. Gira gratis su GitHub e la apri dal telefono quando vuoi, senza tenere il PC acceso.

- **Ogni 3 ore** GitHub scarica statistiche e calendari (dati pubblici ESPN), calcola le proiezioni dei giocatori e aggiorna l'app.
- **NBA:** punti, rimbalzi, assist, triple, stoppate, rubate, palle perse, P+R+A, P+R, P+A, R+A, rubate+stoppate.
- **Calcio** (19 campionati, modificabili): tiri, tiri in porta, falli commessi e subiti, cartellino, gol, assist, gol+assist. Ci sono anche le probabilità 1X2, Over 2.5 e Goal delle partite.
- Inserisci linea e quota del tuo bookmaker e l'app ti dice probabilità, valore atteso (EV) e puntata consigliata (Kelly).
- Schedina, registro delle scommesse e ROI. Le scommesse sui giocatori si chiudono da sole quando arriva il tabellino.
- **NFL** (yard passate, corse e ricevute, ricezioni, passaggi, intercetti, touchdown), **MLB** (valide, H+R+RBI, fuoricampo, basi su ball; per i lanciatori partenti strikeout, eliminazioni, punti e valide concesse) e **tennis** ATP/WTA (vincente della partita con modello Elo).
- **Chicche** (stella in basso): le migliori occasioni del momento, in tre sezioni.
  - *Valore*: il modello dà più probabilità della quota.
  - *Errori quota*: un bookmaker paga più della quota giusta di mercato, cioè Pinnacle senza margine o la media dei bookmaker. Serve la chiave delle quote.
  - *Controlla*: proiezioni molto diverse dalla media recente, da confrontare con la linea del tuo bookmaker.
- **Multiple:** nella Schedina scegli «Multipla» per vedere quota totale, probabilità, valore e puntata consigliata. Se metti più selezioni della stessa partita compare un avviso.
- **Avviso EV troppo alto:** sopra il +15% la scommessa viene segnata «Da verificare» e la puntata consigliata scende all'1% del bankroll.
- **Quote gratuite ESPN:** per il calcio, quando non c'è la chiave, l'app usa le quote 1X2 pubblicate da ESPN, se presenti.
- **Calcio, tutti i mercati di squadra:** esito finale, doppia chance, draw no bet, Goal/No goal, Under/Over da 0.5 a 5.5, multigol, gol di casa e ospite, combo (es. 1 + Over 2.5), primo e secondo tempo (esito, over, goal, tempo con più gol), calci d'angolo, cartellini e risultato esatto. Accanto a ogni mercato scrivi la quota del tuo bookmaker e vedi subito il valore. Le scommesse si chiudono da sole quando arriva il risultato.
- **Coppe europee:** per Champions, Europa e Conference League il modello confronta squadre di campionati diversi usando tutte le partite dell'archivio.
- **NBA migliorata:** ridistribuisce i minuti dei giocatori assenti o in dubbio ai compagni, usa totale e handicap della partita (quote ESPN gratuite) per i punti attesi della squadra e tiene conto di back-to-back e rischio di partita a senso unico. Accanto a ogni giocatore trovi un'affidabilità (alta/media/bassa).
- **Autocalibrazione:** l'app confronta ogni giorno le sue proiezioni con i risultati veri e corregge da sola gli errori sistematici. Lo vedi nella pagina **Stato dati** (icona «i» in Partite), che mostra anche quali dati arrivano per ogni campionato.
- **NBA, NFL, MLB, mercati di squadra:** tocca una partita per vincente, handicap (o run line), totale punti/run e totale di ogni squadra, con la stima del modello e le linee ESPN a confronto.
- **NFL:** se un ricevitore o un running back è assente, bersagli e corse passano ai compagni; yard e touchdown seguono i punti attesi della squadra.
- **MLB:** il lanciatore partente cambia i run attesi; le prop dei battitori tengono conto di run attesi e lanciatore avversario.
- **Tennis:** Elo combinato con la superficie (terra, erba, cemento, riconosciuta dal nome del torneo), formato al meglio di 3 o 5 set, precedenti, risultato esatto in set, totale set e handicap set.
- **Classifica per categoria** (Giocatori → Classifica): scegli un mercato (es. Rimbalzi) e vedi i giocatori di oggi in ordine di proiezione, di probabilità di arrivare a una soglia (es. 10+), di frequenza nelle ultime 10 o di media stagionale.
- **Giocate del giorno** (Chicche → Oggi): le giocate più solide delle partite di oggi, anche senza quote. Per ognuna: probabilità del modello, conferme (ultime 10/20, stagione, H2H), la quota minima da cui conviene e il campo per scrivere la quota del tuo bookmaker. In alto la multipla del giorno con le 3 giocate più probabili di partite diverse.
- **Stile di gioco** (Schedina): Prudente, Equilibrato o Aggressivo. Decide quanto pesa il modello rispetto alla quota del bookmaker nel calcolo di EV e puntata, e quali quote sono giocabili (es. Equilibrato: fino a 4.00 e probabilità almeno 25%). Le giocate oltre i limiti restano visibili ma segnate «rischiosa» e non entrano nelle Chicche.
- **Precedenti (H2H):** (calcio: anche le ultime 5 stagioni, scaricate una volta sola) nella pagina di ogni partita (calcio, NBA, NFL, MLB, tennis) gli scontri diretti con vittorie, gol/punti medi e, nel calcio, Over 2.5, Goal, gol nel 1° tempo, angoli e cartellini. Per i giocatori: frequenza sopra la linea contro l'avversario di oggi (scheda del mercato e colonna H2H nella tabella «Tutti»).
- **NBA doppia doppia e tripla doppia:** probabilità dalle proiezioni di punti, rimbalzi, assist, rubate e stoppate, legate dai minuti giocati, corrette con la frequenza reale delle ultime 20 partite. Per le quote automatiche aggiungi `player_double_double` e `player_triple_double` a `odds.nba_prop_markets`.
- **Preferiti** (cuore in basso): tocca il cuore accanto a un mercato (scheda giocatore, tabella «Tutti», mercati della partita, Chicche) per salvarlo. Nella pagina Preferiti le giocate sono divise per partita, con probabilità e quote aggiornate e l'andamento live. Quando la partita finisce spariscono da sole.
- **Live:** risultato e statistiche delle partite in corso, letti da ESPN ogni 40 secondi direttamente dal telefono.
- **Codice d'accesso (facoltativo):** vedi sotto.
- **Cerca** (lente in alto): scrivi il nome di un giocatore e apri la scheda completa, con tutti i mercati, la linea, la probabilità e quante volte ha superato la linea nelle ultime 5, 10 e 20 partite e in stagione. Ci sono anche le partite contro l'avversario di stasera.
- **Linee alternative:** nella scheda di un mercato vedi la probabilità e la quota giusta per ogni linea vicina alla proiezione.
- **Incolla quote** (icona appunti nella pagina Giocatori): incolli più prop in una volta, una per riga, ad esempio `Tatum over 27.5 punti 1.87` o `Barella cartellino 3.75`, e l'app le valuta tutte.

---

## Installazione (una volta sola, circa 10 minuti)

### 1. Crea il repository
1. Su GitHub clicca **+** in alto a destra → **New repository**.
2. Nome: `valore`. Visibilità: **Public**, necessaria per pubblicare l'app gratis con GitHub Pages. Le tue scommesse restano sul tuo telefono, non su GitHub.
3. Clicca **Create repository**.

### 2. Carica i file
1. Nella pagina del repository vuoto clicca **uploading an existing file**.
2. Apri la cartella `valore` che hai estratto dallo zip, seleziona **tutto il contenuto** (comprese le cartelle `.github`, `docs`, `engine`, `tests`) e trascinalo nella pagina.
   - Se non vedi la cartella `.github`: in Esplora file attiva *Visualizza → Elementi nascosti*.
3. Clicca **Commit changes**.
4. Controlla che nel repository ci sia il file `.github/workflows/aggiorna.yml`. Se manca, vedi «Problemi frequenti» in fondo.

### 3. Attiva la pubblicazione
1. **Settings → Pages**: in *Build and deployment → Source* scegli **GitHub Actions**.
2. **Settings → Actions → General**: in fondo, *Workflow permissions* → **Read and write permissions** → **Save**.

### 4. (Facoltativo) Quote automatiche
1. Registrati gratis su [the-odds-api.com](https://the-odds-api.com) (500 crediti al mese) e copia la tua chiave (API key).
2. Su GitHub: **Settings → Secrets and variables → Actions → New repository secret**.
   Nome: `ODDS_API_KEY`, valore: la tua chiave → **Add secret**.

Senza chiave l'app funziona lo stesso: inserisci tu linea e quota nella scheda del giocatore.

### 5. Primo avvio
1. Scheda **Actions** → a sinistra **Aggiorna dati** → **Run workflow** → **Run workflow**.
2. Il primo giro scarica lo storico (circa 30–40 minuti). Lo storico completo (stagione NBA passata e circa 10 mesi di calcio) arriva in 2–3 giri. I giri successivi partono da soli ogni 3 ore; per fare prima puoi avviarli a mano.
3. Al termine l'app è online su **`https://TUO-NOME-UTENTE.github.io/valore/`**.

### 6. Sul telefono
Apri l'indirizzo con Safari (iPhone) o Chrome (Android) → *Condividi* / menu ⋮ → **Aggiungi a schermata Home**. Da lì si apre come un'app.

---

## Codice d'accesso (consigliato)
Senza codice chiunque conosca l'indirizzo può aprire l'app. Con il codice i dati vengono **cifrati**, quindi senza codice non si leggono, nemmeno scaricando i file.
1. Su GitHub: **Settings → Secrets and variables → Actions → New repository secret**.
2. Nome: `APP_PASSWORD`, valore: il codice che vuoi (almeno 8 caratteri) → **Add secret**.
3. Rilancia **Actions → Aggiorna dati**. Al primo accesso l'app chiede il codice e, se vuoi, lo ricorda su quel dispositivo.

Per cambiare il codice basta modificare il secret: dopo il prossimo aggiornamento serve quello nuovo.

## Personalizzare

Modifica `config.json` direttamente su GitHub (icona della matita):

| Voce | Cosa fa |
|---|---|
| `soccer.leagues` | Campionati di calcio, con i codici ESPN (es. `"ita.1": "Serie A"`). Altri codici: `ita.coppa_italia`, `esp.2`, `ger.2`, `fra.2`, `aut.1`, `sui.1`, `den.1`, `nor.1`, `swe.1`, `gre.1`, `jpn.1`, `ksa.1`, `fifa.world`… |
| `days_ahead` | Quanti giorni avanti mostrare le partite. |
| `nfl.enabled`, `mlb.enabled`, `tennis.enabled` | Attiva o disattiva NFL, MLB e tennis (`true`/`false`). |
| `nfl.days_ahead` | Per la NFL conviene 7: si gioca una volta a settimana. |
| `odds.daily_credit_budget` | Crediti di The Odds API da usare al giorno (15 × 30 = 450, sotto i 500 gratuiti). |
| `odds.nba_prop_markets` | Prop NBA da scaricare. Ogni mercato costa 1 credito per partita. Disponibili: `player_points`, `player_rebounds`, `player_assists`, `player_threes`, `player_blocks`, `player_steals`, `player_points_rebounds_assists`… |
| `odds.refresh_hours` | Ogni quante ore riscaricare le quote (24 con il piano gratuito). |
| `odds.soccer_prop_markets` | Prop dei calciatori da The Odds API (es. `player_shots_on_target`, `player_goal_scorer_anytime`). Vuoto = disattivate, perché consumano molti crediti. |

### Se un giorno passi a un piano quote a pagamento
Non serve cambiare codice. Basta modificare `config.json`: alza `daily_credit_budget` (ad esempio 600 con 20.000 crediti al mese), abbassa `refresh_hours` (ad esempio 3) e aggiungi i mercati che ti interessano in `nba_prop_markets` e `soccer_prop_markets`. Le quote arrivano in automatico nelle schede dei giocatori e il valore viene calcolato da solo.

## Come funziona il modello (in breve)

- **Giocatori:** tasso per minuto pesato sulle partite recenti, corretto verso la media del ruolo quando i dati sono pochi, moltiplicato per i minuti attesi. Poi entrano i fattori di contesto: quanto concede l'avversario in quella statistica, casa/trasferta e, nel calcio, l'arbitro per cartellini e falli. La distribuzione (binomiale negativa) tiene conto di quanto è variabile ogni giocatore.
- **Partite di calcio:** Poisson su forza d'attacco e di difesa, con più peso alle partite recenti.
- **Valore:** EV = probabilità × quota − 1. La puntata usa una frazione del criterio di Kelly, con un tetto del 5% del bankroll.
- NBA: gli infortunati segnati *Out* nell'anteprima ESPN vengono esclusi. Calcio: quando ESPN pubblica la formazione ufficiale, la probabilità da titolare diventa certa.

Il registro scommesse è salvato nel browser del dispositivo. Usa *Esporta/Importa* nella pagina ROI per spostarlo tra telefono e PC.

## Problemi frequenti

- **La pagina dice "Dati non ancora disponibili":** il primo aggiornamento non è finito, o è fallito. Guarda la scheda Actions: un pallino rosso indica un errore. Aprilo e copia le ultime righe del log.
- **Manca `.github/workflows/aggiorna.yml`:** crealo a mano con *Add file → Create new file*, nome `.github/workflows/aggiorna.yml`, e incolla il contenuto del file dallo zip.
- **"Nessuna statistica letta" nel log:** ESPN ha cambiato formato. Serve una piccola correzione a `engine/espn.py`.
- **Gli aggiornamenti automatici si fermano:** GitHub sospende le pianificazioni dopo 60 giorni senza attività nel repository. Riattivale da Actions → Aggiorna dati → *Enable workflow*.

---

Le probabilità sono stime, non certezze. Gioca solo ciò che puoi permetterti di perdere. Il gioco è vietato ai minori di 18 anni e può causare dipendenza.
