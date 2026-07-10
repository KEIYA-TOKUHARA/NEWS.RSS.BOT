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
  DATA_START_ROW: 6,         // データ開始行（テストデータ・注釈行の次から）
  CC: 'biz@temairazu.com',   // 全件に付与するCC
  SUBJECT: 'ホテル・レストラン・ショー御礼と打ち合わせのお願い',

  // 差出人（署名・挨拶文に使う）— ここだけ書き換えれば送信者を変更できます
  SENDER: {
    GREETING_NAME: '石束',                       // 挨拶「手間いらずの◯◯です」の◯◯（姓）
    DEPARTMENT: '営業部',                          // 部署
    FULL_NAME: '石束　□□',                        // ★署名の氏名（下の名前を記入してください）
    EMAIL: '□□@temairazu.com',                    // ★署名のメールアドレス（記入してください）
    MOBILE: ''                                     // 携帯番号（M:）。空なら M: 行を出しません
  },

  // 差し込みに使う列（★このリストの並びに合わせた「列文字」で指定）
  // ※ヘッダーではなく実データの入っている列を指定します。
  //   別レイアウトのシートに使う場合は、ここの列文字を変えるだけでOK。
  COL_FACILITY: 'B',   // 施設名
  COL_CORP:     'D',   // 法人名
  COL_LAST:     'H',   // 姓
  COL_FIRST:    'I',   // 名
  COL_EMAIL:    'O'    // メールアドレス
};

/** 列文字（'A','B',...,'AA'）を 0 始まりの列番号に変換します。 */
function colIndex_(letter) {
  var s = String(letter).toUpperCase();
  var n = 0;
  for (var i = 0; i < s.length; i++) {
    n = n * 26 + (s.charCodeAt(i) - 64); // 'A'=1
  }
  return n - 1;
}

// 本文テンプレート。{{会社名}}{{名前}}{{挨拶名}}{{署名}} を差し込みます。
var BODY_TEMPLATE =
'{{会社名}}\n' +
'{{名前}} 様\n' +
'お世話になります。手間いらずの{{挨拶名}}です。\n' +
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
    .replace('{{名前}}', r.name)
    .replace('{{挨拶名}}', CONFIG.SENDER.GREETING_NAME)
    .replace('{{署名}}', buildSignature_());
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

  // 列文字（B, D, H, I, O …）を 0 始まりの列番号に変換
  var idx = {
    facility: colIndex_(CONFIG.COL_FACILITY),
    corp:     colIndex_(CONFIG.COL_CORP),
    last:     colIndex_(CONFIG.COL_LAST),
    first:    colIndex_(CONFIG.COL_FIRST),
    email:    colIndex_(CONFIG.COL_EMAIL)
  };

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
