/**
 * 名刺一覧（32名） イベント御礼メール 下書き作成ツール（GAS）
 * 差出人：手間いらず株式会社 徳原
 * ------------------------------------------------------------------
 * 「名刺一覧」シートの名刺データを差し込み、Gmail に下書き（Draft）を
 * 作成します。※送信はしません。CC には biz@temairazu.com を全件・
 * 全テンプレート共通で自動的に付与します（下記 CONFIG.CC）。
 *
 * ★件名・本文は【「テンプレート設定」シート】に複数パターン書けます。
 *   1行 = 1テンプレート（テンプレート名／件名／本文）。4つに限らず自由に増減可。
 *   コードは書き換えなくてOKです。差し込みタグは {{会社名}} と {{苗字}} が使えます。
 *   末尾には署名が自動で付きます（本文に署名を書く必要はありません）。
 *
 * ★「名刺一覧」シートの F列「テンプレート」で、行（担当者）ごとに
 *   どのテンプレートを送るかをプルダウンで選びます。
 *
 * ★氏名は「姓 名」形式（例：塚本 勝）から【苗字のみ】を抽出して差し込みます。
 *
 * 使い方:
 *   1) このコードを対象スプレッドシートのスクリプトエディタに貼り付ける
 *      （拡張機能 → Apps Script）
 *   2) スプレッドシートを開き直すとメニュー「イベント御礼メール」が表示される
 *   3) 「③ テンプレート・選択列を準備」を実行
 *      → 「テンプレート設定」シート（4行の例入り）と、
 *        「名刺一覧」シートの F列にプルダウンが自動でできる
 *   4) 「テンプレート設定」シートに件名・本文を書く（複数パターンOK）
 *   5) 「名刺一覧」シートの各行で、F列から送るテンプレートを選ぶ
 *   6) 「① プレビュー（下書きは作らない）」で差し込み結果を確認
 *   7) 「② Gmail下書きを作成」で全件の下書きを作成
 */

// ===== 設定 =====================================================
var CONFIG = {
  SHEET_NAME: '名刺一覧',              // 名刺データのシート名
  TEMPLATES_SHEET_NAME: 'テンプレート設定', // テンプレートを書き込むシート名
  DATA_START_ROW: 4,                  // データ開始行（1〜3行目はタイトル・空行・見出し）
  CC: 'biz@temairazu.com',            // ★全件・全テンプレート共通で付与するCC

  // 差出人（署名・挨拶文に使う）
  SENDER: {
    DEPARTMENT: '営業部',
    FULL_NAME: '徳原　啓也',
    EMAIL: 'keiya.tokuhara@temairazu.com',
    MOBILE: '090-6942-2135'
  },

  // 列の割り当て（「名刺一覧」シートのレイアウト）
  COLS: {
    COMPANY:  'B',   // 会社・施設名
    NAME:     'C',   // 氏名（姓 名） ※ここから苗字だけを抽出します
    TITLE:    'D',   // 役職（未使用・将来の差し込み用に保持）
    EMAIL:    'E',   // メールアドレス
    TEMPLATE: 'F'    // 送るテンプレート名（プルダウン）
  },

  // 「テンプレート設定」シートの列（A=テンプレート名, B=件名, C=本文。2行目からデータ）
  TEMPLATE_COLS: { NAME: 'A', SUBJECT: 'B', BODY: 'C' },
  TEMPLATE_HEADER_ROW: 1,
  TEMPLATE_DATA_START_ROW: 2,

  // 初回セットアップ時に「テンプレート設定」シートへ入れる例（空欄の行にだけ入ります）
  DEFAULT_TEMPLATE_NAMES: ['新規', '既存', 'お礼のみ', '汎用']
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

/** テンプレート文字列に {{会社名}}{{苗字}} を差し込みます。 */
function fillTags_(text, r) {
  return String(text || '')
    .replace(/\{\{会社名\}\}/g, r.company)
    .replace(/\{\{苗字\}\}/g, r.surname);
}

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
    .addSeparator()
    .addItem('③ テンプレート・選択列を準備', 'setupTemplatesAndColumn')
    .addToUi();
}

// ===== テンプレートシート・選択列の準備 ============================
function setupTemplatesAndColumn() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();

  // --- 「テンプレート設定」シート ---
  var tSheet = ss.getSheetByName(CONFIG.TEMPLATES_SHEET_NAME);
  if (!tSheet) tSheet = ss.insertSheet(CONFIG.TEMPLATES_SHEET_NAME);

  var tc = CONFIG.TEMPLATE_COLS;
  tSheet.getRange(CONFIG.TEMPLATE_HEADER_ROW, colIndex_(tc.NAME) + 1).setValue('テンプレート名').setFontWeight('bold');
  tSheet.getRange(CONFIG.TEMPLATE_HEADER_ROW, colIndex_(tc.SUBJECT) + 1).setValue('件名').setFontWeight('bold');
  tSheet.getRange(CONFIG.TEMPLATE_HEADER_ROW, colIndex_(tc.BODY) + 1).setValue('本文').setFontWeight('bold');
  tSheet.getRange(CONFIG.TEMPLATE_HEADER_ROW, colIndex_(tc.BODY) + 2)
    .setValue('※差し込みタグ: {{会社名}} {{苗字}}／署名とCC(' + CONFIG.CC + ')は自動付与、本文に書く必要なし');

  CONFIG.DEFAULT_TEMPLATE_NAMES.forEach(function (name, i) {
    var row = CONFIG.TEMPLATE_DATA_START_ROW + i;
    var nameCell = tSheet.getRange(row, colIndex_(tc.NAME) + 1);
    var bodyCell = tSheet.getRange(row, colIndex_(tc.BODY) + 1);
    if (!nameCell.getValue()) nameCell.setValue(name);
    if (!bodyCell.getValue()) bodyCell.setValue('{{会社名}}\n{{苗字}} 様\n\n（「' + name + '」向けの本文をここに書いてください）');
  });

  tSheet.getRange(CONFIG.TEMPLATE_DATA_START_ROW, colIndex_(tc.BODY) + 1, CONFIG.DEFAULT_TEMPLATE_NAMES.length, 1).setWrap(true);
  tSheet.setColumnWidth(colIndex_(tc.NAME) + 1, 120);
  tSheet.setColumnWidth(colIndex_(tc.SUBJECT) + 1, 260);
  tSheet.setColumnWidth(colIndex_(tc.BODY) + 1, 480);

  // --- 「名刺一覧」シートに テンプレート選択列（プルダウン）を追加 ---
  var cSheet = ss.getSheetByName(CONFIG.SHEET_NAME);
  if (!cSheet) throw new Error('シートが見つかりません: ' + CONFIG.SHEET_NAME);

  var col = colIndex_(CONFIG.COLS.TEMPLATE) + 1;
  cSheet.getRange(3, col).setValue('テンプレート').setFontWeight('bold'); // 見出し行(3行目)に合わせる

  var lastRow = Math.max(cSheet.getLastRow(), CONFIG.DATA_START_ROW);
  var templateNameRange = tSheet.getRange(
    CONFIG.TEMPLATE_DATA_START_ROW, colIndex_(tc.NAME) + 1, 200, 1
  ); // テンプレート名の一覧を範囲参照 → 後から行を増やしても自動でプルダウンに反映
  var rule = SpreadsheetApp.newDataValidation()
    .requireValueInRange(templateNameRange, true)
    .setAllowInvalid(true)
    .build();
  cSheet.getRange(CONFIG.DATA_START_ROW, col, lastRow - CONFIG.DATA_START_ROW + 1, 1).setDataValidation(rule);

  SpreadsheetApp.getUi().alert(
    '準備できました。\n\n' +
    '① 「' + CONFIG.TEMPLATES_SHEET_NAME + '」シートに件名・本文を書いてください（行を増やせばテンプレートも増やせます）\n' +
    '② 「' + CONFIG.SHEET_NAME + '」シートの F列で、担当者ごとに送るテンプレートをプルダウンから選んでください\n' +
    'CCは全件 ' + CONFIG.CC + ' が自動で付きます。'
  );
}

/** 「テンプレート設定」シートからテンプレート一覧を { 名前: {subject, body} } の形で読み込みます。 */
function readTemplates_() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(CONFIG.TEMPLATES_SHEET_NAME);
  if (!sheet) {
    throw new Error(
      '「' + CONFIG.TEMPLATES_SHEET_NAME + '」シートが見つかりません。\n' +
      'メニューの「③ テンプレート・選択列を準備」を先に実行してください。'
    );
  }
  var tc = CONFIG.TEMPLATE_COLS;
  var lastRow = sheet.getLastRow();
  var map = {};
  for (var row = CONFIG.TEMPLATE_DATA_START_ROW; row <= lastRow; row++) {
    var name = String(sheet.getRange(row, colIndex_(tc.NAME) + 1).getValue() || '').trim();
    if (!name) continue;
    var subject = String(sheet.getRange(row, colIndex_(tc.SUBJECT) + 1).getValue() || '').trim();
    var body = String(sheet.getRange(row, colIndex_(tc.BODY) + 1).getValue() || '').trim();
    map[name] = { subject: subject, body: body };
  }
  return map;
}

// ===== メイン処理 =================================================
function previewDrafts() { run_(true); }
function createDrafts() { run_(false); }

function run_(previewOnly) {
  var templates = readTemplates_();
  var rows = readContacts_();
  var targets = [];
  var skippedNoMail = [];
  var skippedNoTemplate = [];

  rows.forEach(function (r) {
    if (!r.email) { skippedNoMail.push(r); return; }
    var t = templates[r.templateName];
    if (!t || !t.subject || !t.body) { skippedNoTemplate.push(r); return; }
    r.resolvedTemplate = t;
    targets.push(r);
  });

  // テンプレート別の件数集計
  var groups = {};
  targets.forEach(function (r) {
    groups[r.templateName] = (groups[r.templateName] || 0) + 1;
  });

  var log = [];
  log.push('=== ' + (previewOnly ? 'プレビュー' : '下書き作成') + ' ===');
  log.push('対象: ' + targets.length + ' 件 ／ メールなしスキップ: ' + skippedNoMail.length +
    ' 件 ／ テンプレート未選択・未定義スキップ: ' + skippedNoTemplate.length + ' 件');
  log.push('差出人: ' + CONFIG.SENDER.FULL_NAME + ' ／ CC: ' + CONFIG.CC);
  log.push('');
  Object.keys(groups).forEach(function (k) { log.push('【' + k + '】 ' + groups[k] + '件'); });
  log.push('');

  var created = 0;
  targets.forEach(function (r, i) {
    var subject = fillTags_(r.resolvedTemplate.subject, r);
    var body = fillTags_(r.resolvedTemplate.body, r) + '\n\n' + buildSignature_();
    log.push('[' + (i + 1) + '] To: ' + r.email + ' ／ ' + r.company + ' ／ ' + r.surname + '様 ／ テンプレート: ' + r.templateName);
    if (!previewOnly) {
      GmailApp.createDraft(r.email, subject, body, { cc: CONFIG.CC });
      created++;
    }
  });

  if (skippedNoMail.length) {
    log.push('');
    log.push('--- スキップ（メールアドレス空欄） ---');
    skippedNoMail.forEach(function (r) {
      log.push('行' + r.rowNumber + ': ' + (r.company || '(会社名なし)') + ' ／ ' + (r.fullName || '(氏名なし)'));
    });
  }
  if (skippedNoTemplate.length) {
    log.push('');
    log.push('--- スキップ（テンプレート未選択／未定義） ---');
    skippedNoTemplate.forEach(function (r) {
      log.push('行' + r.rowNumber + ': ' + (r.company || '(会社名なし)') + ' ／ ' + (r.fullName || '(氏名なし)') +
        ' ／ 選択値: ' + (r.templateName || '(空欄)'));
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

// ===== データ読み取り ============================================
function readContacts_() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(CONFIG.SHEET_NAME);
  if (!sheet) throw new Error('シートが見つかりません: ' + CONFIG.SHEET_NAME);

  var lastRow = sheet.getLastRow();
  if (lastRow < CONFIG.DATA_START_ROW) return [];

  var C = CONFIG.COLS;
  var idx = {
    company:  colIndex_(C.COMPANY),
    name:     colIndex_(C.NAME),
    email:    colIndex_(C.EMAIL),
    template: colIndex_(C.TEMPLATE)
  };
  var numCols = Math.max(idx.company, idx.name, idx.email, idx.template) + 1;
  var numRows = lastRow - CONFIG.DATA_START_ROW + 1;
  var values = sheet.getRange(CONFIG.DATA_START_ROW, 1, numRows, numCols).getValues();

  var contacts = [];
  values.forEach(function (row, i) {
    var company = String(row[idx.company] || '').trim();
    var fullName = String(row[idx.name] || '').trim();
    var email = String(row[idx.email] || '').trim();
    var templateName = String(row[idx.template] || '').trim();

    // 会社名・氏名・メールがすべて空の行はデータ無しとみなしスキップ
    if (!company && !fullName && !email) return;

    contacts.push({
      rowNumber: CONFIG.DATA_START_ROW + i,
      company: company,
      fullName: fullName,
      surname: extractSurname_(fullName),
      email: email,
      templateName: templateName
    });
  });

  return contacts;
}
