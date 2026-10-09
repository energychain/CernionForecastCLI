# Cernion Forecast — Verbindlicher fachlicher Datenintegritätsvertrag

**Dokument-ID:** CET-FC-DIC-001  
**Version:** 0.1.0 — Entwurf  
**Stand:** 09.10.2026  
**Status:** Proposed / Nicht freigegeben  
**Geltungsbereich:** CernionForecastCLI, CET Forecast API und nachgelagerte Prognosevalidierung

---

## 1. Zweck und Verbindlichkeit

Dieser Vertrag beschreibt die fachlichen und technischen Mindestanforderungen an Daten, die von der CernionForecastCLI übernommen, normalisiert, an die CET Forecast API übertragen oder zur Bewertung von Prognoseergebnissen verwendet werden.

Ziel ist die Sicherstellung von:

- Eindeutiger Identität jeder Zeitreihe
- Korrekter zeitlicher Interpretation
- Nachweisbarer Herkunft und Messwertsemantik
- Kontrollierter Datenqualität und Vollständigkeit
- Reproduzierbarer Informationsverfügbarkeit zum Prognosezeitpunkt
- Ausschluss unzulässiger Informationsnutzung (*Data Leakage*)
- Vergleichbarkeit von Prognosen und Baselines
- Nachvollziehbarkeit aller transformations- und entscheidungsrelevanten Schritte

**Vertragsprinzip:**

> Ein technisch erfolgreicher Import ist kein Nachweis fachlicher Datenintegrität. Ein erfolgreiches Training ist kein Nachweis zulässiger Informationsverfügbarkeit. Ein erfolgreich erzeugter Forecast ist kein Nachweis prognostischer Eignung.

Die nachfolgenden Anforderungen verwenden die Normbegriffe:

- **MUSS:** zwingend einzuhalten
- **DARF NICHT:** verbindliches Verbot
- **SOLL:** begründete Regelanforderung; Abweichungen sind zu dokumentieren
- **KANN:** optionale Erweiterung

Eine MUSS-Verletzung führt zum Status `REJECTED`, sofern der Vertrag für den jeweiligen Schritt ausdrücklich keine kontrollierte Ausnahme definiert.

## 2. Vertragsparteien und Verantwortlichkeiten

### 2.1 Datenquelle / Integrationsadapter

Verantwortlich für die Bereitstellung und nachweisbare Interpretation der Quelldaten.

Hierzu gehören insbesondere:

- Originaldaten und Quellidentifikation
- Herkunftsformat und Formatversion
- Messwertsemantik und Einheit
- Zeitstempel und Quellzeitzone
- Datenqualitätskennzeichen
- Empfangs- und Verfügbarkeitsinformationen

### 2.2 CernionForecastCLI

Verantwortlich für:

- Formatprüfung und Normalisierung
- Eindeutige Serienselektion
- Zeitliche und semantische Validierung
- Berechnung und Dokumentation der Datenabdeckung
- Bildung der für den Forecast zulässigen Datenmenge
- Erstellung des Integrity Evidence Receipt
- Durchsetzung lokaler Integritätsregeln vor dem API-Aufruf

Die CLI DARF unklare Daten nicht durch stillschweigende Annahmen fachlich vervollständigen.

### 2.3 CET Forecast API

Verantwortlich für:

- Vertragskonforme Übernahme und serverseitige Validierung
- Durchsetzung der Mandantenzuordnung
- Nachvollziehbare Versionierung der importierten Daten
- Persistenz des bestätigten Informationsschnitts
- Bindung von Trainingsläufen und Modellversionen an die verwendeten Datenversionen
- Bereitstellung reproduzierbarer Forecast-Ergebnisse und Ausführungsnachweise

### 2.4 Forecast Evaluation

Verantwortlich für die unabhängige Prüfung von Prognosehorizont, Ist-Werten, Referenzverfahren, Prognosemetriken und fachlichen Qualitätsentscheidungen.

Sie MUSS unterscheiden zwischen einem gültigen Prognoseergebnis und einer für einen bestimmten Einsatzzweck akzeptierten Prognose.

---

## 3. Verbindliche Dateninvarianten

### INV-001 — Eindeutige Zeitreihenidentität

Jeder Datensatz MUSS eindeutig einem fachlichen Messobjekt oder einer explizit definierten Aggregation zugeordnet werden.

Erforderliche Identitätsmerkmale sind:

- `tenant_id`
- `series_id`
- `series_type`
- `measurement_semantics`
- `unit`

Bei MSCONS zusätzlich, soweit im jeweiligen Nachrichtenformat fachlich einschlägig:

- Messlokationskennung bzw. selektiertes Objekt
- OBIS-Kennzahl bzw. eindeutige fachliche Messgröße
- Nachrichtenreferenz
- Dokumentkennung

Ein frei definierter `series_id` DARF NICHT als Ersatz für eine eindeutige fachliche Selektion innerhalb einer mehrdeutigen Quelldatei verwendet werden.

**Akzeptanzregel:** Nach Anwendung der Selektionskriterien MUSS exakt eine fachliche Zeitreihe übrig bleiben.

Fehlercode: `AMBIGUOUS_SERIES_SELECTION`

### INV-002 — Zeitliche Eindeutigkeit

Jeder normalisierte Messwert MUSS einem eindeutigen Zeitpunkt oder eindeutig definierten Messintervall zugeordnet sein.

Der kanonische Zeitbezug ist UTC.

Zusätzlich MUSS die vertragliche lokale Zeitzone als IANA-Zeitzone dokumentiert werden.

Ein Zeitpunkt DARF NICHT allein aus einer mehrdeutigen lokalen Uhrzeit abgeleitet werden, sofern dadurch unterschiedliche reale Zeitpunkte möglich bleiben.

Die Normalisierung MUSS für jeden Wert den verwendeten Zeitzonen- und Konvertierungsmechanismus nachvollziehbar machen.

**Akzeptanzregel:** Innerhalb einer Zeitreihe DARF kein mehrfach belegter kanonischer Intervallschlüssel existieren.

Fehlercode: `DUPLICATE_INTERVAL`

### INV-003 — Explizite Messwertsemantik

Jeder Datensatz MUSS deklarieren, ob die Werte beispielsweise:

- Intervallenergie (`interval_energy`)
- Mittlere Wirkleistung (`average_power`)
- Zählerstands- oder Registerwerte (`cumulative_register`)

repräsentieren.

Die für Training und Scoring zugelassenen Semantiken MÜSSEN zum jeweiligen Prognosevertrag passen.

Zählerstände DÜRFEN NICHT ohne nachvollziehbare Differenzbildung und Validierung als Intervallenergiemengen verwendet werden.

Konvertierungen zwischen kW und kWh MÜSSEN die tatsächliche Intervalllänge berücksichtigen.

Fehlercode: `SEMANTICS_MISMATCH`

### INV-004 — Messwertqualität

Jeder Messwert MUSS einen nachvollziehbaren Qualitätsstatus besitzen.

Das kanonische Qualitätsmodell unterscheidet mindestens:

- `measured`
- `estimated`
- `provisional`
- `corrected`
- `unknown`

Quelle und Mappingregel MÜSSEN dokumentiert werden.

Unbekannte Quellstatus DÜRFEN NICHT automatisch als gemessen interpretiert werden.

Die Integritätsprüfung MUSS die Anteile der verschiedenen Qualitätsklassen separat ausweisen.

Fehlercode: `UNACCEPTABLE_VALUE_QUALITY`

### INV-005 — Vollständigkeit des Zeitrasters

Die erwartete Zahl von Intervallen MUSS unabhängig von der gelieferten Datenmenge bestimmt werden.

Bei lokaler Viertelstundenauflösung und `Europe/Berlin` ergeben sich für vollständige lokale Kalendertage üblicherweise:

| Kalendertag | Erwartete Intervalle |
|---|---:|
| Normaler Tag | 96 |
| Beginn der Sommerzeit | 92 |
| Ende der Sommerzeit | 100 |

Die konkrete Berechnung MUSS aus den tatsächlichen Grenzen des lokalen Kalendertags und der vereinbarten Intervallsemantik erfolgen.

Coverage ist definiert als:

`coverage = valid_expected_intervals / expected_intervals`

Dabei zählen nur gültige, dem erwarteten Raster zuordenbare Intervalle.

Zusätzliche Werte außerhalb des Rasters DÜRFEN die Coverage NICHT erhöhen.

Fehlercode: `INCOMPLETE_INTERVAL_GRID`

### INV-006 — Informationsverfügbarkeit

Für jede prognoserelevante Information MUSS dokumentiert sein, ab wann sie dem Prognoseverfahren zulässigerweise zur Verfügung stand.

Hierfür werden mindestens unterschieden:

- `event_time`: Zeitpunkt bzw. Intervall der fachlichen Beobachtung
- `available_at`: frühester nachweisbarer Zeitpunkt der Verfügbarkeit für den definierten Informationskanal
- `ingested_at`: Zeitpunkt der technischen Übernahme in CET
- `as_of`: verbindlicher Informationsschnitt des Prognoselaufs

`available_at` DARF NICHT allein aus `event_time` abgeleitet werden.

Fehlt ein belastbarer Verfügbarkeitsnachweis, MUSS für einen historischen Backtest eine ausdrücklich genehmigte, konservative Verfügbarkeitsregel verwendet werden. Diese MUSS im Evidence Receipt ausgewiesen werden.

Werte, deren Verfügbarkeit zum `as_of`-Zeitpunkt nicht belegt ist, DÜRFEN NICHT als zulässige historische Features verwendet werden.

Fehlercode: `INFORMATION_NOT_AVAILABLE_AS_OF`

### INV-007 — Verbindlicher Prognosehorizont

Jeder Prognoselauf MUSS den erwarteten Zielhorizont unabhängig von den gelieferten Prognosewerten definieren.

Erforderlich sind:

- `forecast_for` oder explizite Start-/Endzeit
- `forecast_timezone`
- `granularity`
- `horizon_start`
- `horizon_end`
- `expected_interval_count`

Der Forecast MUSS anhand dieses Rasters auf fehlende, doppelte oder unzulässige Zeitpunkte geprüft werden.

Eine Teilprognose DARF nur dann fachlich akzeptiert werden, wenn der entsprechende Anwendungsfall partielle Ergebnisse ausdrücklich erlaubt.

Fehlercode: `FORECAST_HORIZON_MISMATCH`

### INV-008 — Herkunft und Reproduzierbarkeit

Jeder Import MUSS die Herkunft der Daten dokumentieren.

Mindestens erforderlich:

- Quellenkennung
- Format und Formatversion
- Prüfsumme des Originalinputs
- Verwendete Selektionsparameter
- Normalisierungsversion
- Ergebnisprüfsumme der kanonischen Daten
- Zeitbezug und Einheiten
- Transformations- und Korrekturhinweise

Eine Korrektur MUSS als neue nachvollziehbare Datenversion erkennbar sein.

Eine bestehende Datenversion DARF NICHT stillschweigend überschrieben werden.

Fehlercode: `PROVENANCE_INCOMPLETE`

---

## 4. Zeitliche Zulässigkeit und D-2-Vertrag

### 4.1 Grundprinzip

Für eine Prognose des Liefertags D im D-2-Betriebsmodus MUSS ein verbindlicher Informationsschnitt festgelegt werden.

Die vertragliche D-2-Regel ist:

**Messwerte mit einem Beobachtungsintervall nach dem zulässigen historischen Grenzzeitpunkt von D-2 DÜRFEN NICHT als historische Trainingswerte verwendet werden.**

Zusätzlich MUSS jeder genutzte Messwert die `available_at <= as_of`-Bedingung erfüllen.

Die Tagesgrenze und der konkrete `as_of`-Zeitpunkt MÜSSEN separat definiert werden. Die bloße Bezeichnung „D-2“ ersetzt keinen nachprüfbaren Zeitstempel.

### 4.2 Unzulässige Datenverwendung

Ein Training MUSS abgelehnt oder mit einer ausdrücklich protokollierten, vertraglich erlaubten Einschränkung des Trainingsfensters durchgeführt werden, wenn:

- Beobachtungen aus D-1 oder D unzulässig im Training enthalten sind
- Featurewerte erst nach `as_of` verfügbar waren
- rückwirkend korrigierte Messwerte ohne Berücksichtigung ihres damaligen Verfügbarkeitsstands verwendet werden
- im Backtest spätere Ist-Werte zur Konstruktion historischer Features genutzt werden
- die Trainingshistorie eine unbemerkte zeitliche Überschneidung mit dem Bewertungszeitraum aufweist

Eine bloße Prüfung, ob mindestens 28 Beobachtungstage bis D-2 existieren, ist hierfür nicht ausreichend.

### 4.3 Historische Backtests

Für historische Backtests MUSS der damals verfügbare Informationsstand rekonstruiert oder mittels dokumentierter Verfügbarkeitsannahmen konservativ angenähert werden.

Die Backtest-Ergebnisse MÜSSEN ausweisen, ob sie auf:

- nachgewiesener historischer Verfügbarkeit,
- angenommener Verfügbarkeit oder
- einer rein retrospektiven Auswertung

beruhen.

Retrospektiv verfügbare Daten DÜRFEN NICHT ohne Kennzeichnung als Point-in-Time-Daten bezeichnet werden.

---

## 5. MSCONS-/EDIFACT-Integritätsvertrag

### 5.1 Nachrichtenvalidierung

Der Import MUSS vor der fachlichen Übernahme prüfen:

- unterstützter Nachrichtentyp und Version
- syntaktisch gültige Nachrichtenstruktur
- eindeutige Gruppenzuordnung der Messwerte
- erforderliche Referenzen und Qualifier
- gültige Zeitangaben
- zulässige Einheiten und Messwertsemantik
- fachlich passende Messwertstatus
- Integrität von Nachrichtenreferenzen und Segmentzählungen, soweit vorgeschrieben

Die Prüfung MUSS auf den tatsächlich unterstützten MSCONS-Anwendungsfällen und deren verbindlichen Formatvorgaben beruhen.

### 5.2 Eindeutige Auswahl

Nachrichten mit mehreren geeigneten Kandidaten MÜSSEN eine explizite Selektion oder eine anderweitig eindeutig nachgewiesene Zuordnung verlangen.

Die Auswahl des jeweils ersten Treffers ist verboten.

### 5.3 Fachliche Herkunft

Die Quellnachricht MUSS so referenzierbar bleiben, dass die Herkunft der übernommenen Messwerte nachvollzogen werden kann.

Ein produktiver Import MUSS die für seine Verarbeitung maßgeblichen Nachrichtendaten, Kennungen, Qualitätsinformationen und Selektionsregeln revisionsfähig dokumentieren.

Personen- oder geschäftsbezogene Identifikatoren DÜRFEN nur nach den geltenden Berechtigungs- und Schutzvorgaben persistiert werden.

### 5.4 DST-Sonderbehandlung

Bei mehrdeutigen lokalen Zeitangaben MUSS der Import entweder:

1. den tatsächlichen Zeitpunkt durch zusätzliche Nachrichteninformationen eindeutig bestimmen oder
2. den betreffenden Datensatz mit einem fachlichen Fehlerstatus zurückweisen.

Stillschweigende Standardannahmen sind nicht zulässig.

---

## 6. Qualitätsprofile und Entscheidungen

Der Vertrag unterscheidet Datenintegrität und Anwendungsqualität.

### 6.1 Integritätsprüfung

Die Integritätsprüfung ist unabhängig vom gewählten Prognosemodell.

Sie MUSS mindestens folgende Gates bereitstellen:

| Gate | Zweck |
|---|---|
| `identity_gate` | Eindeutige Messobjektzuordnung |
| `schema_gate` | Gültige Eingabestruktur |
| `temporal_gate` | Eindeutige Zeitstempel und Intervalle |
| `semantic_gate` | Gültige Einheit und Wertsemantik |
| `coverage_gate` | Abdeckung des erwarteten Zeitrasters |
| `availability_gate` | Zulässigkeit zum Informationsschnitt |
| `provenance_gate` | Nachvollziehbare Herkunft |
| `quality_gate` | Messwertqualitäts- und Grenzwertprüfung |

### 6.2 Integritätsstatus

Zulässige Zustände:

- `ACCEPTED`: Alle erforderlichen Integritätsprüfungen bestanden
- `ACCEPTED_WITH_WARNINGS`: Keine verbindliche Regel verletzt; dokumentierte nicht blockierende Warnungen
- `REJECTED`: Mindestens eine verbindliche Regel verletzt
- `NOT_EVALUABLE`: Eine notwendige Prüfung kann mangels Informationen nicht durchgeführt werden

`NOT_EVALUABLE` DARF NICHT als erfolgreich bestandene Integritätsprüfung gewertet werden.

### 6.3 Qualitätsprofile

Die Profile `monitoring`, `portfolio`, `system-load`, `household`, `industrial`, `volatile` und `strict` KÖNNEN anwendungsspezifische Qualitätsgrenzen definieren.

Diese Profile DÜRFEN jedoch keine grundlegenden Identitäts-, Zeit-, Semantik- oder Verfügbarkeitsinvarianten deaktivieren.

Schwellwerte für WAPE, Bias, MAE oder RMSE gehören zur Prognoseabnahme, nicht zur vorgelagerten strukturellen Datenintegrität.

---

## 7. Forecast- und Baseline-Integrität

### 7.1 Forecast-Validierung

Vor der Berechnung fachlicher Metriken MUSS geprüft werden:

- Prognose gehört zur richtigen Serie und zum richtigen Mandanten
- Vorhersagehorizont entspricht dem angeforderten Zielraster
- Keine doppelten Prognoseintervalle
- Prognosewerte sind numerisch gültig
- Prognose- und Ist-Werte besitzen vergleichbare Einheiten und Semantik
- Bewertungs-Ist-Werte werden nicht als Trainings- oder Prognosefeatures verwendet

### 7.2 Baseline-Verfahren

Baselines MÜSSEN denselben Informationsschnitt wie das Modell respektieren.

Dies gilt insbesondere für:

- Previous Day
- Previous Week
- Rolling Mean
- saisonale oder kalendertagsbezogene Referenzverfahren

Eine Baseline DARF NICHT bessere Informationen als das zu bewertende Modell verwenden.

Wenn ein Referenzverfahren wegen des Informationsschnitts nicht vollständig berechenbar ist, MUSS das Ergebnis `INSUFFICIENT_AVAILABLE_HISTORY` ausweisen.

### 7.3 Metriken

Metriken MÜSSEN mathematisch korrekt und hinsichtlich ihrer Definitionsbedingungen dokumentiert sein.

Für den WAPE gilt:

`WAPE = 100 × Summe(|Forecast - Actual|) / Summe(|Actual|)`

Ist die Summe der absoluten Ist-Werte null, MUSS WAPE als nicht definiert gekennzeichnet werden.

Ein undefinierter WAPE DARF NICHT automatisch als null oder als bestandener Qualitätsnachweis interpretiert werden.

Die Prognoseabnahme MUSS festlegen, wie mit undefinierten Pflichtmetriken umzugehen ist.

---

## 8. Integrity Evidence Receipt

Jeder produktive Verarbeitungs- oder Prognoselauf MUSS ein maschinenlesbares Evidence Receipt erzeugen.

Das Receipt dokumentiert die fachliche Integrität des Datenstands zum Zeitpunkt der Verarbeitung.

### 8.1 Mindestumfang

- Vertrags-ID und Vertragsversion
- Client-Version und verwendete Transformationsversion
- Tenant- und Serienidentität
- Quellen- und Dataset-Prüfsummen
- Datenversion
- Prognosehorizont
- Zeitraster und Zeitzone
- Informationsschnitt
- Nachweis der Datenverfügbarkeit
- Ergebnis sämtlicher Integritäts-Gates
- Fehler und Warnungen
- Referenz auf Trainingslauf bzw. Modellversion, sofern vorhanden

### 8.2 Unveränderlichkeit

Das Receipt MUSS nach Abschluss des zugehörigen Laufs unverändert reproduzierbar sein.

Spätere Korrekturen erzeugen ein neues Receipt mit Referenz auf die vorherige Version.

### 8.3 Verknüpfung

Forecast-Ergebnisse und Qualitätsberichte MÜSSEN auf die für sie maßgebliche Datenintegritätsprüfung referenzieren können.

Ein Qualitätsbericht ohne eindeutig zuordenbaren Informationsstand DARF NICHT als vollständig reproduzierbarer Prognosenachweis gelten.

---

## 9. Ausführungs- und Fehlervertrag

### 9.1 Vorbedingungen

Vor einem produktiven API-Schreibaufruf MUSS die lokale Integritätsprüfung erfolgreich abgeschlossen sein.

Der CET-Server MUSS die für ihn verbindlichen Integritätsprüfungen unabhängig vom Client erneut durchführen.

### 9.2 Fehlerklassifikation

Fehler MÜSSEN mindestens unterscheiden zwischen:

- `SCHEMA_ERROR`
- `IDENTITY_ERROR`
- `TEMPORAL_ERROR`
- `SEMANTIC_ERROR`
- `COVERAGE_ERROR`
- `AVAILABILITY_ERROR`
- `PROVENANCE_ERROR`
- `API_CONTRACT_ERROR`
- `TRANSPORT_ERROR`
- `FORECAST_QUALITY_FAILURE`

### 9.3 Verarbeitungsergebnis

Jeder Lauf MUSS einen eindeutigen maschinenlesbaren Status besitzen.

Ein API-Transporterfolg DARF NICHT automatisch als fachlicher Verarbeitungserfolg gelten.

Bei unterbrochener Kommunikation MUSS der Ausführungsstatus als unbekannt behandelt werden, bis er über einen serverseitigen Status- oder Idempotenznachweis geklärt wurde.

### 9.4 Batch-Verarbeitung

Für jedes Batch-Element MUSS separat dokumentiert werden:

- Eingabereferenz
- Verarbeitungsstatus
- Fehlercode und Fehlerursache
- Integritätsprüfung
- Ergebnisversion
- Idempotenz- und Wiederaufnahmereferenz

Fehler einzelner Elemente DÜRFEN NICHT durch eine aggregierte Batch-Erfolgsmeldung verdeckt werden.

---

## 10. Sicherheit und Schutzbedürftigkeit

Die Übertragung mandantenbezogener Daten MUSS über einen zugelassenen verschlüsselten Transportkanal erfolgen.

Produktive Datenübertragungen über unverschlüsseltes HTTP sind nicht zulässig.

Zugangstokens DÜRFEN NICHT in Ergebnisartefakten, Protokollen oder Fehlermeldungen persistiert werden.

Messlokations- und Marktteilnehmerkennungen sowie gegebenenfalls personenbeziehbare Verbrauchsdaten MÜSSEN dem festgelegten Berechtigungs- und Datenschutzkonzept unterliegen.

Eine Pseudonymisierung MUSS ausdrücklich definieren, welche Identifier geschützt werden und welche für betriebliche Rückverfolgbarkeit erhalten bleiben müssen.

Eine bloße Hashbildung ist nicht automatisch eine hinreichende Anonymisierung.

---

## 11. Versionierung und Kompatibilität

Jede Datenübertragung MUSS einer eindeutig identifizierbaren Vertragsversion zugeordnet werden können.

Breaking Changes erfordern eine neue Major-Version des fachlichen Vertrags.

Zu Breaking Changes gehören insbesondere:

- veränderte Messwertsemantik
- geänderte Zeitstempelinterpretation
- geänderte Vollständigkeitsdefinition
- geänderte Bedeutung von Qualitätsstatus
- veränderte Pflichtinformationen für Verfügbarkeitsnachweise

Client und Server MÜSSEN inkompatible Vertragsversionen ablehnen oder über eine ausdrücklich spezifizierte, nachvollziehbare Migration behandeln.

---

## 12. Verbindliche Abnahmetests

Vor Freigabe einer Implementierung dieses Vertrags MÜSSEN mindestens folgende Tests erfolgreich sein:

**AT-001 — Mehrdeutige MSCONS-Auswahl**  
Zwei gleich geeignete Zeitreihen ohne eindeutige Selektionsparameter führen zur Zurückweisung.

**AT-002 — Sommerzeitumstellung**  
Ein vollständiger lokaler Umstellungstag wird mit genau 92 Intervallen validiert.

**AT-003 — Winterzeitumstellung**  
Ein vollständiger lokaler Umstellungstag wird mit genau 100 eindeutig zugeordneten Intervallen validiert.

**AT-004 — Unvollständiger Prognosehorizont**  
80 von 96 gültigen Intervallen ergeben 83,33 % Coverage und bestehen keine vollständige 100-%-Abnahme.

**AT-005 — D-2-Datenverfügbarkeit**  
Ein Trainingsdatensatz mit unzulässigen D-1-Werten wird zurückgewiesen oder vor dem Training ausdrücklich und nachweisbar auf den zulässigen Datenstand begrenzt.

**AT-006 — Historische Korrektur**  
Ein erst nach `as_of` verfügbarer Korrekturwert darf einen Point-in-Time-Backtest nicht nachträglich verbessern.

**AT-007 — Referenzprognose**  
Ein Previous-Day-Verfahren darf keine zum Informationsschnitt unbekannten Werte verwenden.

**AT-008 — Nullverbrauch**  
Ein Bewertungsdatensatz mit vollständig null betragenden Ist-Werten führt zu einem definierten Metrikstatus und keinem unbehandelten Laufzeitfehler.

**AT-009 — Reproduzierbarkeit**  
Identische kanonische Eingangsdaten, Transformationsversionen, Informationsschnitte und Bewertungsregeln führen zu identisch interpretierbaren Integritätsentscheidungen.

**AT-010 — Serverseitige Durchsetzung**  
Ein API-Aufruf, der lokale Prüfungen umgeht und gegen eine verbindliche Invariante verstößt, wird serverseitig zurückgewiesen.

**AT-011 — Batch-Fehlernachweis**  
Fehler eines einzelnen Importelements bleiben einschließlich Ursache und Elementidentität nachvollziehbar.

**AT-012 — Mandantenisolierung**  
Datensätze und Integritätsnachweise können nicht über nicht autorisierte Tenant-Grenzen hinweg verwendet werden.

---

## 13. Definition of Done

Der fachliche Datenintegritätsvertrag gilt als technisch umgesetzt, wenn:

1. Die verbindlichen Invarianten durch ausführbare Validierungsregeln abgebildet sind.
2. Jeder produktive Import den notwendigen Integritätsprüfungen unterliegt.
3. Informationsverfügbarkeit und Trainingsgrenzen nachweisbar geprüft werden.
4. Jeder Forecast gegen den unabhängig festgelegten Zielhorizont validiert wird.
5. Baselines denselben Informationsschnitt wie das Modell einhalten.
6. Ein versioniertes Integrity Evidence Receipt erzeugt und persistiert wird.
7. Alle verpflichtenden Abnahmetests erfolgreich sind.
8. CLI und CET API dieselben Vertragssemantiken unterstützen.
9. Verstöße durch maschinenlesbare Fehlercodes erkennbar sind.
10. Eine fachliche Freigabe der Vertragsversion dokumentiert wurde.

---

## 14. Offene Festlegungen vor Freigabe

Folgende Punkte sind vor der Überführung dieses Entwurfs in einen verbindlich freigegebenen Standard abschließend festzulegen:

- Welche Serienarten und Messwertsemantiken unterstützt CET verbindlich?
- Welche konkreten D-2-Abgabe- und Verfügbarkeitszeitpunkte gelten pro Betriebsfall?
- Welche Zeitintervallkonvention gilt: Intervallbeginn, Intervallende oder beides?
- Welche MSCONS-Anwendungsfälle und Formatversionen werden verbindlich unterstützt?
- Welches Mapping der EDIFACT-Qualitätskennzeichen ist für diese Formate zulässig?
- Welche Mindestabdeckung gilt je operativem Anwendungsfall?
- Welche Verfügbarkeitsnachweise sind für historische Backtests akzeptabel?
- Wie werden nicht verfügbare Baselines in der Qualitätsentscheidung behandelt?
- Welche Teile des Evidence Receipts persistiert CET zentral und welche die CLI lokal?
- Welche Aufbewahrungsfristen und Zugriffsrechte gelten für Rohdaten und Integritätsnachweise?

**Freigabebedingung:** Der Vertrag darf erst dann als `APPROVED` geführt werden, wenn diese Festlegungen getroffen und durch entsprechende Konformitätstests überprüfbar gemacht wurden.

---

**Leitprinzip des Vertrags**

*Jede Prognose muss nicht nur rechnerisch erzeugbar, sondern hinsichtlich ihrer Datenbasis, ihres damaligen Informationsstands und ihrer fachlichen Bedeutung überprüfbar sein.*
