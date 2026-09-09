/**
 * 名刺一覧（32名） イベント御礼メール 下書き作成ツール（GAS）
 * 差出人：手間いらず株式会社 徳原
 * ------------------------------------------------------------------
 * 「名刺一覧」シートの名刺データを差し込み、Gmail に下書き（Draft）を
 * 作成します。※送信はしません。CC には biz@temairazu.com を全件に付与します。
 *
 * ★氏名は「姓 名」形式（例：塚本 勝）から【苗字のみ】を抽出して差し込みます。
 *   例：「塚本 勝」→「塚本」様
 *
 * ★★ SUBJECT / BODY_TEMPLATE の中身はまだ仮です。
 *    イベント名・候補日程が決まり次第、差し替えてください（下に印あり）。
 *
 * 使い方:
 *   1) このコードを対象スプレッドシートのスクリプトエディタに貼り付ける
 *      （拡張機能 → Apps Script）
 *   2) スプレッドシートを開き直すとメニュー「イベント御礼メール」が表示される
 *   3) 「① プレビュー（下書きは作らない）」で差し込み結果を確認
 *   4) 「② Gmail下書きを作成」で全件の下書きを作成
 */

// ===== 設定 =====================================================
var CONFIG = {
  SHEET_NAME: '名刺一覧',    // 対象シート名（空ならアクティブなシートを使用）
  DATA_START_ROW: 4,        // データ開始行（1〜3行目はタイトル・空行・見出し）
  CC: 'biz@temairazu.com',  // 全件に付与するCC

  // ★★ ここを実際のイベント名・件名に差し替えてください ★★
  SUBJECT: '【要差し替え】ご挨拶御礼（手間いらず株式会社 徳原）',

  // 差出人（署名・挨拶文に使う）
  SENDER: {
    GREETING_NAME: '徳原',
    DEPARTMENT: '営業部',
    FULL_NAME: '徳原　啓也',
    EMAIL: 'keiya.tokuhara@temairazu.com',
    MOBILE: '090-6942-2135'
  },

  // 列の割り当て（「名刺一覧」シートのレイアウト）
  COLS: {
    COMPANY: 'B',   // 会社・施設名
    NAME:    'C',   // 氏名（姓 名） ※ここから苗字だけを抽出します
    TITLE:   'D',   // 役職（未使用・将来の差し込み用に保持）
    EMAIL:   'E'    // メールアドレス
  }
};

/** 列文字（'A','B',...）を 0 始まりの列番号に変換します。 */
function colIndex_(letter) {
  var s = String(letter).toUpperCase();
  var n = 0;
  for (var i = 0; i < s.length; i++) {
    n = n * 26 + (s.charCodeAt(i) - 64); // 'A'=1
  }
  return n - 1;
}

/** 「姓 名」形式の氏名から苗字（先頭の語）だけを取り出します。全角/半角スペース両対応。 */
function extractSurname_(fullName) {
  var s = String(fullName || '').trim();
  if (!s) return '';
  return s.split(/[\s　]+/)[0];
}

// ===== 本文テンプレート ==========================================
// ★★ 本文もイベント名・候補日程が決まり次第、差し替えてください ★★
// {{会社名}}{{苗字}}{{署名}} を差し込みます。

var BODY_TEMPLATE =
'{{会社名}}\n' +
'{{苗字}} 様\n' +
'\n' +
'お世話になります。手間いらず株式会社の徳原です。\n' +
'先日は【要差し替え：イベント名】において、貴重なお時間をいただき誠にありがとうございました。\n' +
'\n' +
'改めて弊社サービスについてご説明の機会をいただけますと幸いです。\n' +
'【要差し替え：候補日程、または「オンラインでも対応可能です」等】\n' +
'\n' +
'今後ともどうぞよろしくお願いいたします。\n' +
'\n' +
'{{署名}}';

/** CONFIG.SENDER から署名ブロックを組み立てます。 */
function buildSignature_() {
  var s = CONFIG.SENDER;
  var telLine = 'TEL:03-3473-4345　　FAX:03-3473-4348' + (s.MOBILE ? '　M: ' + s.MOBILE : '');
  return [
    '***************************************************************************',
    '手間いらず 株式会社　　           https://www.temairazu.com',
    '----------------------------------------------------------------------------------------',
    s.DEPARTMENT + '　　　　　　　　　　　' + s.FULL_NAME,
    'Email　　　　　　　　　　  　' + s.EMAIL,
    '---------------------------------------------------------------------------------------',
    '==================================================',
    '〒564-0052　大阪府吹田市広芝町8-12 第3マイダビル',
    telLine,
    '***************************************************************************'
  ].join('\n');
}

// ===== メニュー ===================================================
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('イベント御礼メール')
    .addItem('① プレビュー（下書きは作らない）', 'previewDrafts')
    .addItem('② Gmail下書きを作成', 'createDrafts')
    .addToUi();
}

// ===== メイン処理 =================================================
function previewDrafts() { run_(true); }
function createDrafts() { run_(false); }

function run_(previewOnly) {
  var rows = readContacts_();
  var targets = [];
  var skipped = [];

  rows.forEach(function (r) {
    if (!r.email) { skipped.push(r); } else { targets.push(r); }
  });

  var log = [];
  log.push('=== ' + (previewOnly ? 'プレビュー' : '下書き作成') + ' ===');
  log.push('対象（メールあり）: ' + targets.length + ' 件 / スキップ（メール空欄）: ' + skipped.length + ' 件');
  log.push('差出人: ' + CONFIG.SENDER.FULL_NAME + ' ／ CC: ' + CONFIG.CC);
  log.push('件名: ' + CONFIG.SUBJECT);
  log.push('');

  var created = 0;
  targets.forEach(function (r, i) {
    var body = renderBody_(r);
    log.push('[' + (i + 1) + '] To: ' + r.email + ' ／ 会社名: ' + r.company + ' ／ 苗字: ' + r.surname + '（氏名: ' + r.fullName + '）');
    if (!previewOnly) {
      GmailApp.createDraft(r.email, CONFIG.SUBJECT, body, { cc: CONFIG.CC });
      created++;
    }
  });

  if (skipped.length) {
    log.push('');
    log.push('--- スキップ（メールアドレス空欄） ---');
    skipped.forEach(function (r) {
      log.push('行' + r.rowNumber + ': ' + (r.company || '(会社名なし)') + ' ／ ' + (r.fullName || '(氏名なし)'));
    });
  }

  if (!previewOnly) {
    log.push('');
    log.push('作成した下書き: ' + created + ' 件（Gmailの「下書き」フォルダをご確認ください）');
  }

  var message = log.join('\n');
  Logger.log(message);
  try { SpreadsheetApp.getUi().alert(message); } catch (e) {}
}

// ===== 差し込み ==================================================
function renderBody_(r) {
  return BODY_TEMPLATE
    .replace('{{会社名}}', r.company)
    .replace('{{苗字}}', r.surname)
    .replace('{{署名}}', buildSignature_());
}

// ===== データ読み取り ============================================
function readContacts_() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = CONFIG.SHEET_NAME ? ss.getSheetByName(CONFIG.SHEET_NAME) : ss.getActiveSheet();
  if (!sheet) throw new Error('シートが見つかりません: ' + CONFIG.SHEET_NAME);

  var lastRow = sheet.getLastRow();
  if (lastRow < CONFIG.DATA_START_ROW) return [];

  var C = CONFIG.COLS;
  var idx = {
    company: colIndex_(C.COMPANY),
    name:    colIndex_(C.NAME),
    email:   colIndex_(C.EMAIL)
  };
  var numCols = Math.max(idx.company, idx.name, idx.email) + 1;
  var numRows = lastRow - CONFIG.DATA_START_ROW + 1;
  var values = sheet.getRange(CONFIG.DATA_START_ROW, 1, numRows, numCols).getValues();

  var contacts = [];
  values.forEach(function (row, i) {
    var company = String(row[idx.company] || '').trim();
    var fullName = String(row[idx.name] || '').trim();
    var email = String(row[idx.email] || '').trim();

    // 会社名・氏名・メールがすべて空の行はデータ無しとみなしスキップ
    if (!company && !fullName && !email) return;

    contacts.push({
      rowNumber: CONFIG.DATA_START_ROW + i,
      company: company,
      fullName: fullName,
      surname: extractSurname_(fullName),
      email: email
    });
  });

  return contacts;
}
