const SPREADSHEET_ID = '1xrFh5lok4XRiC8FrptHt-QR4sdWYfWaIWLVkjcjWaIA';
const SHEET_NAME = 'BMI30 Versions';
// Do not replace this with the token value.
// The Script Property name must be BMI30_SYNC_TOKEN; its value is the secret.
const TOKEN_PROPERTY = 'BMI30_SYNC_TOKEN';

function doGet() {
  return json_({
    ok: true,
    service: 'BMI30 version registry updater',
    sheetName: SHEET_NAME
  });
}

function doPost(e) {
  try {
    const expectedToken = PropertiesService.getScriptProperties().getProperty(TOKEN_PROPERTY);
    if (!expectedToken) {
      throw new Error('Sync token script property is not set. Expected property name: BMI30_SYNC_TOKEN');
    }

    const body = (e && e.postData && e.postData.contents) ? e.postData.contents : '{}';
    const payload = JSON.parse(body);
    if (!payload || payload.token !== expectedToken) {
      throw new Error('Unauthorized');
    }

    const headers = payload.headers || [];
    const rows = payload.rows || [];
    const keyColumn = payload.keyColumn || 'ID версии';
    const replace = payload.replace === true;
    if (!headers.length) {
      throw new Error('No headers provided');
    }
    if (!rows.length) {
      return json_({ok: true, updated: 0, appended: 0, message: 'No rows'});
    }

    const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
    const sheet = ss.getSheetByName(SHEET_NAME) || ss.insertSheet(SHEET_NAME);
    const result = replace ? replaceRows_(sheet, headers, rows) : upsertRows_(sheet, headers, rows, keyColumn);
    return json_({
      ok: true,
      sheetName: SHEET_NAME,
      mode: replace ? 'replace' : 'upsert',
      updated: result.updated,
      appended: result.appended,
      rowCount: rows.length
    });
  } catch (err) {
    return json_({
      ok: false,
      error: String(err && err.message ? err.message : err)
    });
  }
}

function replaceRows_(sheet, headers, rows) {
  sheet.clearContents();
  sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
  if (rows.length > 0) {
    const values = rows.map(function(obj) {
      return headers.map(function(header) {
        return Object.prototype.hasOwnProperty.call(obj, header) ? obj[header] : '';
      });
    });
    sheet.getRange(2, 1, values.length, headers.length).setValues(values);
  }
  sheet.setFrozenRows(1);
  sheet.getRange(1, 1, 1, headers.length).setFontWeight('bold');
  sheet.autoResizeColumns(1, headers.length);
  return {updated: 0, appended: rows.length};
}

function upsertRows_(sheet, incomingHeaders, rows, keyColumn) {
  const existingLastRow = sheet.getLastRow();
  const existingLastCol = sheet.getLastColumn();
  let headers = [];

  if (existingLastRow >= 1 && existingLastCol >= 1) {
    headers = sheet.getRange(1, 1, 1, existingLastCol).getValues()[0]
      .map(function(value) { return String(value || '').trim(); });
  }

  if (!headers.length || headers.every(function(value) { return value === ''; })) {
    headers = incomingHeaders.slice();
    sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
  } else {
    incomingHeaders.forEach(function(header) {
      if (headers.indexOf(header) < 0) {
        headers.push(header);
      }
    });
    sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
  }

  const keyIndex = headers.indexOf(keyColumn);
  if (keyIndex < 0) {
    throw new Error('Key column not found: ' + keyColumn);
  }

  const rowByKey = {};
  const dataLastRow = sheet.getLastRow();
  if (dataLastRow >= 2) {
    const values = sheet.getRange(2, 1, dataLastRow - 1, headers.length).getValues();
    values.forEach(function(row, idx) {
      const key = String(row[keyIndex] || '').trim();
      if (key) {
        rowByKey[key] = idx + 2;
      }
    });
  }

  let updated = 0;
  let appended = 0;
  rows.forEach(function(obj) {
    const key = String(obj[keyColumn] || '').trim();
    if (!key) {
      return;
    }
    const values = headers.map(function(header) {
      return Object.prototype.hasOwnProperty.call(obj, header) ? obj[header] : '';
    });
    if (rowByKey[key]) {
      sheet.getRange(rowByKey[key], 1, 1, headers.length).setValues([values]);
      updated += 1;
    } else {
      sheet.appendRow(values);
      appended += 1;
    }
  });

  sheet.setFrozenRows(1);
  sheet.getRange(1, 1, 1, headers.length).setFontWeight('bold');
  sheet.autoResizeColumns(1, headers.length);
  return {updated: updated, appended: appended};
}

function json_(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
