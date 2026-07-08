/**
 * WG-Casting Tool – Backend (Google Apps Script)
 * =================================================
 *
 * Speichert Votes (Bewertungen der Mitbewohner:innen) und Verfügbarkeiten
 * (Terminfindung) in einem Google Sheet. Dient als kleines, kostenloses
 * Backend für die statische Tool-Seite (wg-tool.html).
 *
 * EINRICHTUNG – siehe SETUP.md. Kurz:
 *   1. Neues Google Sheet anlegen -> Erweiterungen -> Apps Script.
 *   2. Diesen Code komplett einfügen, speichern.
 *   3. ACCESS_CODE unten auf euren gemeinsamen Code setzen (gleich wie in wg-tool.html!).
 *   4. Bereitstellen -> Neue Bereitstellung -> Typ "Web-App":
 *        - "Ausführen als": Ich
 *        - "Zugriff": Jeder (bzw. "Jeder mit Google-Konto" wenn ihr das wollt)
 *   5. Die /exec-URL kopieren und in wg-tool.html als APPS_SCRIPT_URL eintragen.
 *
 * Datenmodell (Tabs werden automatisch angelegt):
 *   Votes:     applicant | voter | rating | comment | updated
 *   Avail:     applicant | voter | slotsJSON | updated
 *   Meetings:  applicant | state | proposedSlots | proposedAt | proposedBy | owner | responseSlots | confirmedSlot | updated
 * Votes/Avail: eine Zeile pro (applicant, voter). Meetings: eine Zeile pro applicant.
 */

// ====== KONFIG ======
var ACCESS_CODE = 'wg-casting';   // <-- ändern! Muss mit wg-tool.html übereinstimmen.
// ====================

var VOTES_SHEET = 'Votes';
var AVAIL_SHEET = 'Avail';
var MEETINGS_SHEET = 'Meetings';
var VOTES_HEADER = ['applicant', 'voter', 'rating', 'comment', 'updated'];
var AVAIL_HEADER = ['applicant', 'voter', 'slotsJSON', 'updated'];
var MEETINGS_HEADER = ['applicant', 'state', 'proposedSlots', 'proposedAt', 'proposedBy', 'owner', 'responseSlots', 'confirmedSlot', 'updated'];

function doGet(e) {
  return handle(e, (e && e.parameter) ? e.parameter : {});
}

function doPost(e) {
  var params = {};
  try {
    if (e && e.postData && e.postData.contents) {
      params = JSON.parse(e.postData.contents);
    }
  } catch (err) {
    params = (e && e.parameter) ? e.parameter : {};
  }
  return handle(e, params);
}

function handle(e, params) {
  var action = params.action || 'state';
  try {
    // 'state' (Lesen) ist bewusst ohne Code-Check, damit die Seite die
    // aktuellen Stände laden kann. Schreiben braucht den Code.
    if (action === 'state') {
      return json({
        ok: true,
        votes: readSheet(VOTES_SHEET, VOTES_HEADER),
        avail: readSheet(AVAIL_SHEET, AVAIL_HEADER),
        meetings: readSheet(MEETINGS_SHEET, MEETINGS_HEADER)
      });
    }

    if (params.code !== ACCESS_CODE) {
      return json({ ok: false, error: 'Falscher Zugangscode.' });
    }

    if (action === 'vote') {
      var voter = String(params.voter || '').trim();
      var applicant = String(params.applicant || '').trim();
      if (!voter || !applicant) return json({ ok: false, error: 'voter/applicant fehlt.' });
      upsert(VOTES_SHEET, VOTES_HEADER, applicant, voter, {
        rating: params.rating === '' || params.rating == null ? '' : Number(params.rating),
        comment: String(params.comment || '')
      });
      return json({ ok: true });
    }

    if (action === 'avail') {
      var v2 = String(params.voter || '').trim();
      var a2 = String(params.applicant || '').trim();
      if (!v2 || !a2) return json({ ok: false, error: 'voter/applicant fehlt.' });
      var slots = params.slots;
      if (typeof slots !== 'string') slots = JSON.stringify(slots || []);
      upsert(AVAIL_SHEET, AVAIL_HEADER, a2, v2, { slotsJSON: slots });
      return json({ ok: true });
    }

    if (action === 'meeting') {
      var app = String(params.applicant || '').trim();
      if (!app) return json({ ok: false, error: 'applicant fehlt.' });
      var fields = {};
      ['state', 'proposedSlots', 'proposedAt', 'proposedBy', 'owner', 'responseSlots', 'confirmedSlot'].forEach(function (k) {
        if (params[k] !== undefined && params[k] !== null) {
          fields[k] = (typeof params[k] === 'string') ? params[k] : JSON.stringify(params[k]);
        }
      });
      upsertMeeting(app, fields);
      return json({ ok: true });
    }

    return json({ ok: false, error: 'Unbekannte action: ' + action });
  } catch (err) {
    return json({ ok: false, error: String(err) });
  }
}

// ---- Sheet-Helfer ----

function getSheet(name, header) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sh = ss.getSheetByName(name);
  if (!sh) {
    sh = ss.insertSheet(name);
    sh.getRange(1, 1, 1, header.length).setValues([header]);
    sh.setFrozenRows(1);
  }
  return sh;
}

function readSheet(name, header) {
  var sh = getSheet(name, header);
  var last = sh.getLastRow();
  if (last < 2) return [];
  var values = sh.getRange(2, 1, last - 1, header.length).getValues();
  return values.map(function (row) {
    var obj = {};
    for (var i = 0; i < header.length; i++) obj[header[i]] = row[i];
    return obj;
  }).filter(function (o) { return o.applicant !== '' && o.voter !== ''; });
}

/**
 * Upsert: Zeile mit gleichem (applicant, voter) überschreiben, sonst anhängen.
 * fields enthält die zu setzenden Spalten (ohne applicant/voter/updated).
 */
function upsert(name, header, applicant, voter, fields) {
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    var sh = getSheet(name, header);
    var last = sh.getLastRow();
    var rowIndex = -1;
    if (last >= 2) {
      var keys = sh.getRange(2, 1, last - 1, 2).getValues(); // applicant, voter
      for (var i = 0; i < keys.length; i++) {
        if (String(keys[i][0]) === applicant && String(keys[i][1]) === voter) {
          rowIndex = i + 2;
          break;
        }
      }
    }
    var record = { applicant: applicant, voter: voter, updated: new Date().toISOString() };
    for (var k in fields) record[k] = fields[k];
    var rowValues = header.map(function (h) { return record[h] === undefined ? '' : record[h]; });
    if (rowIndex === -1) {
      sh.appendRow(rowValues);
    } else {
      sh.getRange(rowIndex, 1, 1, header.length).setValues([rowValues]);
    }
  } finally {
    lock.releaseLock();
  }
}

/**
 * Meeting-Upsert: eine Zeile pro applicant (Schlüssel = Spalte 1).
 * fields werden in eine bestehende Zeile gemergt (partielle Updates möglich).
 */
function upsertMeeting(applicant, fields) {
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    var sh = getSheet(MEETINGS_SHEET, MEETINGS_HEADER);
    var last = sh.getLastRow();
    var rowIndex = -1, existing = {};
    if (last >= 2) {
      var rows = sh.getRange(2, 1, last - 1, MEETINGS_HEADER.length).getValues();
      for (var i = 0; i < rows.length; i++) {
        if (String(rows[i][0]) === applicant) {
          rowIndex = i + 2;
          for (var j = 0; j < MEETINGS_HEADER.length; j++) existing[MEETINGS_HEADER[j]] = rows[i][j];
          break;
        }
      }
    }
    var record = {};
    for (var k in existing) record[k] = existing[k];
    for (var f in fields) record[f] = fields[f];
    record.applicant = applicant;
    record.updated = new Date().toISOString();
    var rowValues = MEETINGS_HEADER.map(function (h) { return record[h] === undefined ? '' : record[h]; });
    if (rowIndex === -1) sh.appendRow(rowValues);
    else sh.getRange(rowIndex, 1, 1, MEETINGS_HEADER.length).setValues([rowValues]);
  } finally {
    lock.releaseLock();
  }
}

function json(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
