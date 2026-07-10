/**
 * ホテル・レストラン・ショー フォローメール 下書き作成ツール（GAS）
 * ------------------------------------------------------------------
 * スプレッドシートの名刺データ（社名・氏名・メールアドレス）を差し込み、
 * Gmail に下書き（Draft）を作成します。※送信はしません。
 *
 * 使い方:
 *   1) このコードを対象スプレッドシートのスクリプトエディタに貼り付ける
 *      （拡張機能 → Apps Script）
 *   2) スプレッドシートを開き直すとメニュー「メール下書き」が表示される
 *   3) 「① プレビュー（下書きは作らない）」で差し込み結果を確認
 *   4) 「② Gmail下書きを作成」で全件の下書きを作成
 *
 * CC には biz@temairazu.com を全件に付与します。
 */

// ===== 設定 =====================================================
var CONFIG = {
  SHEET_NAME: '',            // 対象シート名。空なら「アクティブなシート」を使用
  HEADER_ROW: 3,             // 見出し行（kintoneフォーム→ の行）
  DATA_START_ROW: 6,         // データ開始行（テストデータ・注釈行の次から）
  CC: 'biz@temairazu.com',   // 全件に付与するCC
  SUBJECT: 'ホテル・レストラン・ショー御礼と打ち合わせのお願い',

  // 見出し行の列名（HEADER_ROW のセル文字列と一致させる）
  COL_FACILITY: '施設名',       // B列
  COL_CORP:     '法人名',       // D列
  COL_LAST:     '姓',           // I列
  COL_FIRST:    '名',           // J列
  COL_EMAIL:    'メールアドレス' // P列
};

// 本文テンプレート。{{会社名}} と {{名前}} を差し込みます。
var BODY_TEMPLATE =
'{{会社名}}\n' +
'{{名前}} 様\n' +
'お世話になります。手間いらずの徳原です。\n' +
'先日は「ホテル・レストラン・ショー＆FOODEX JAPAN in 関西 2026」において、当社ブースへお立ち寄りいただき、誠にありがとうございました。\n' +
'短いお時間ではございましたが、直接ご挨拶できたことを大変嬉しく思っております。\n' +
'会場でも簡単にご紹介いたしましたが、改めてご説明の機会をいただけますと幸いです。\n' +
'つきましては、一度お打ち合わせのお時間をいただけますでしょうか。\n' +
'以下の日程でご都合はいかがでしょうか。\n' +
'━━━━━━━━━━━━━━━\n' +
'候補日時\n' +
'━━━━━━━━━━━━━━━\n' +
'7月29日（火）10:00〜18:00\n' +
'7月30日（水）10:00〜18:00\n' +
'8月 5日（火）10:00〜18:00\n' +
'8月 6日（水）10:00〜18:00\n' +
'━━━━━━━━━━━━━━━\n' +
'ご都合のよい日時をお知らせいただけますと幸いです。\n' +
'なお、オンライン・対面どちらでも対応可能でございます。\n' +
'どうぞよろしくお願いいたします。\n' +
'\n' +
'***************************************************************************\n' +
'手間いらず 株式会社　　           https://www.temairazu.com\n' +
'----------------------------------------------------------------------------------------\n' +
'営業部　　　　　　　　　　　徳原　啓也\n' +
'Email　　　　　　　　　　  　keiya.tokuhara@temairazu.com\n' +
'---------------------------------------------------------------------------------------\n' +
'==================================================\n' +
'〒564-0052　大阪府吹田市広芝町8-12 第3マイダビル\n' +
'TEL:03-3473-4345　　FAX:03-3473-4348　M: 090-6942-2135\n' +
'***************************************************************************';

// ===== メニュー ===================================================
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('メール下書き')
    .addItem('① プレビュー（下書きは作らない）', 'previewDrafts')
    .addItem('② Gmail下書きを作成', 'createDrafts')
    .addToUi();
}

// ===== メイン処理 =================================================

/** 下書きは作らず、差し込み結果と対象/スキップ件数をログ表示します。 */
function previewDrafts() {
  run_(true);
}

/** Gmail に下書きを作成します。 */
function createDrafts() {
  run_(false);
}

function run_(previewOnly) {
  var rows = readContacts_();
  var targets = [];
  var skipped = [];

  rows.forEach(function (r) {
    if (!r.email) {
      skipped.push(r);
    } else {
      targets.push(r);
    }
  });

  var log = [];
  log.push('=== ' + (previewOnly ? 'プレビュー' : '下書き作成') + ' ===');
  log.push('対象（メールあり）: ' + targets.length + ' 件 / スキップ（メール空欄）: ' + skipped.length + ' 件');
  log.push('CC: ' + CONFIG.CC);
  log.push('件名: ' + CONFIG.SUBJECT);
  log.push('');

  var created = 0;
  targets.forEach(function (r, i) {
    var subject = CONFIG.SUBJECT;
    var body = renderBody_(r);
    log.push('[' + (i + 1) + '] To: ' + r.email + ' ／ 会社名: ' + r.company + ' ／ 名前: ' + r.name);

    if (!previewOnly) {
      GmailApp.createDraft(r.email, subject, body, { cc: CONFIG.CC });
      created++;
    }
  });

  if (skipped.length) {
    log.push('');
    log.push('--- スキップ（メールアドレス空欄） ---');
    skipped.forEach(function (r) {
      log.push('行' + r.rowNumber + ': ' + (r.company || '(会社名なし)') + ' ／ ' + (r.name || '(氏名なし)'));
    });
  }

  if (!previewOnly) {
    log.push('');
    log.push('作成した下書き: ' + created + ' 件（Gmailの「下書き」フォルダをご確認ください）');
  }

  var message = log.join('\n');
  Logger.log(message);
  try {
    SpreadsheetApp.getUi().alert(message);
  } catch (e) {
    // UIが無いコンテキスト（手動実行など）ではログのみ
  }
}

// ===== 差し込み ==================================================

/** テンプレートに会社名・名前を差し込んで本文を生成します。 */
function renderBody_(r) {
  return BODY_TEMPLATE
    .replace('{{会社名}}', r.company)
    .replace('{{名前}}', r.name);
}

// ===== データ読み取り ============================================

/**
 * シートから連絡先を読み取ります。
 * 会社名 = 法人名を優先、なければ施設名。
 * 名前   = 姓 + 名（間に半角スペース）。
 */
function readContacts_() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = CONFIG.SHEET_NAME ? ss.getSheetByName(CONFIG.SHEET_NAME) : ss.getActiveSheet();
  if (!sheet) throw new Error('シートが見つかりません: ' + CONFIG.SHEET_NAME);

  var lastRow = sheet.getLastRow();
  var lastCol = sheet.getLastColumn();
  if (lastRow < CONFIG.DATA_START_ROW) return [];

  var header = sheet.getRange(CONFIG.HEADER_ROW, 1, 1, lastCol).getValues()[0];
  var idx = {
    facility: findCol_(header, CONFIG.COL_FACILITY),
    corp:     findCol_(header, CONFIG.COL_CORP),
    last:     findCol_(header, CONFIG.COL_LAST),
    first:    findCol_(header, CONFIG.COL_FIRST),
    email:    findCol_(header, CONFIG.COL_EMAIL)
  };
  Object.keys(idx).forEach(function (k) {
    if (idx[k] < 0) throw new Error('見出し行に列が見つかりません: ' + k + '（' + CONFIG.HEADER_ROW + '行目を確認）');
  });

  var numRows = lastRow - CONFIG.DATA_START_ROW + 1;
  var values = sheet.getRange(CONFIG.DATA_START_ROW, 1, numRows, lastCol).getValues();

  var contacts = [];
  values.forEach(function (row, i) {
    var corp = String(row[idx.corp] || '').trim();
    var facility = String(row[idx.facility] || '').trim();
    var last = String(row[idx.last] || '').trim();
    var first = String(row[idx.first] || '').trim();
    var email = String(row[idx.email] || '').trim();

    var company = corp || facility;           // 法人名優先、なければ施設名
    var name = [last, first].filter(String).join(' '); // 姓 名

    // 会社名・氏名・メールがすべて空の行はデータ無しとみなしスキップ
    if (!company && !name && !email) return;

    contacts.push({
      rowNumber: CONFIG.DATA_START_ROW + i,
      company: company,
      name: name,
      email: email
    });
  });

  return contacts;
}

/** 見出し配列から列名の位置（0始まり）を返す。見つからなければ -1。 */
function findCol_(header, name) {
  for (var i = 0; i < header.length; i++) {
    if (String(header[i]).trim() === name) return i;
  }
  return -1;
}
