/**
 * 出張訪問 お礼メール 下書き作成ツール（GAS）
 * 差出人：手間いらず株式会社 徳原
 * ------------------------------------------------------------------
 * Eight の名刺CSVを取り込んだスプレッドシートから、訪問先へのお礼メールを
 * 差し込み生成し、Gmail に下書き（Draft）を作成します。※送信はしません。
 * CC には biz@temairazu.com を全件に付与します。
 *
 * テンプレは4種類（AH列「区分」で行ごとに選択）:
 *   新規     … TEMAIRAZU紹介＋オンライン説明の打診あり
 *   既存     … 日頃の御礼＋サポート姿勢（軽めの「ご連絡ください」のみ）
 *   お礼のみ … アポ打診の雰囲気を出さない純粋な御礼
 *   （空欄） … 汎用（軽くご説明の機会に触れる）
 *
 * 挨拶（昨日／先日）は AI列「挨拶」で手動指定でき、空欄なら
 * 名刺交換日（O列）から自動判定します（実行日の前日=昨日、それ以前=先日）。
 *
 * 使い方:
 *   1) Eight のCSVをスプレッドシートにインポート（1行目=見出し、2行目〜=データ）
 *   2) このコードを 拡張機能 → Apps Script に貼り付けて保存
 *   3) シートに戻って再読み込み → メニュー「お礼メール」が出る
 *   4) 「③ 作業列を準備」で 区分/挨拶/除外 のプルダウン列を自動作成
 *   5) 区分などを入力 → 「① プレビュー」で確認 → 「② Gmail下書きを作成」
 */

// ===== 設定 =====================================================
var CONFIG = {
  SHEET_NAME: '',            // 対象シート名。空なら「アクティブなシート」を使用
  DATA_START_ROW: 2,         // データ開始行（1行目はEightの見出し）
  CC: 'biz@temairazu.com',   // 全件に付与するCC
  SUBJECT: 'ご訪問御礼（手間いらず株式会社 徳原）',

  // 差出人（署名・挨拶文に使う）
  SENDER: {
    GREETING_NAME: '徳原',
    DEPARTMENT: '営業部',
    FULL_NAME: '徳原　啓也',
    EMAIL: 'keiya.tokuhara@temairazu.com',
    MOBILE: '090-6942-2135'
  },

  // 列の割り当て（EightのCSVレイアウト＋右端の作業列）
  COLS: {
    COMPANY:  'A',   // 会社名
    LAST:     'D',   // 姓
    FIRST:    'E',   // 名
    EMAIL:    'F',   // e-mail
    DATE:     'O',   // 名刺交換日
    TEMPLATE: 'AH',  // 区分（新規／既存／お礼のみ／空欄=汎用）
    GREETING: 'AI',  // 挨拶（昨日／先日／空欄=自動判定）
    EXCLUDE:  'AJ'   // 除外（何か入っていれば対象外）
  }
};

/** 列文字（'A','B',...,'AJ'）を 0 始まりの列番号に変換します。 */
function colIndex_(letter) {
  var s = String(letter).toUpperCase();
  var n = 0;
  for (var i = 0; i < s.length; i++) {
    n = n * 26 + (s.charCodeAt(i) - 64); // 'A'=1
  }
  return n - 1;
}

// ===== 本文テンプレート ==========================================
// {{会社名}}{{名前}}{{挨拶日}}{{署名}} を差し込みます。

var TPL_SHINKI =  // 新規顧客向け（オンライン説明の打診あり）
'{{会社名}}\n' +
'{{名前}} 様\n' +
'\n' +
'お世話になります。手間いらず株式会社の徳原です。\n' +
'{{挨拶日}}は突然の訪問にもかかわらず、貴重なお時間をいただき誠にありがとうございました。\n' +
'\n' +
'ご紹介いたしました宿泊予約サイトコントローラー「TEMAIRAZU」は、複数の予約サイトの客室・料金を一元管理し、販売機会の最大化と予約業務の省力化を実現するサービスです。\n' +
'導入効果や料金プランなど、改めて詳しくご説明の機会をいただけますと幸いです。\n' +
'オンラインでも30分ほどでご案内可能ですので、ご都合のよい日時をお知らせいただけますでしょうか。\n' +
'\n' +
'今後ともどうぞよろしくお願いいたします。\n' +
'\n' +
'{{署名}}';

var TPL_KISON =  // 既存顧客向け（アポ打診なし・サポート姿勢）
'{{会社名}}\n' +
'{{名前}} 様\n' +
'\n' +
'お世話になります。手間いらず株式会社の徳原です。\n' +
'{{挨拶日}}は訪問させていただき、誠にありがとうございました。\n' +
'日頃より「手間いらず」をご利用いただいておりますこと、重ねて御礼申し上げます。\n' +
'\n' +
'直接ご状況やご要望をお伺いでき、大変参考になりました。お伺いした内容は社内でも共有し、今後のサポートに活かしてまいります。\n' +
'操作のご不明点や追加のご要望などございましたら、いつでもお気軽にご連絡ください。\n' +
'\n' +
'引き続きどうぞよろしくお願いいたします。\n' +
'\n' +
'{{署名}}';

var TPL_OREINOMI =  // お礼のみ（アポ打診の雰囲気を出さない）
'{{会社名}}\n' +
'{{名前}} 様\n' +
'\n' +
'お世話になります。手間いらず株式会社の徳原です。\n' +
'{{挨拶日}}は訪問させていただき、誠にありがとうございました。\n' +
'直接ご挨拶ができ、また貴重なお話を伺うことができ、大変嬉しく思っております。\n' +
'\n' +
'またお目にかかれる機会を楽しみにしております。\n' +
'今後ともどうぞよろしくお願いいたします。\n' +
'\n' +
'{{署名}}';

var TPL_GENERIC =  // 汎用（区分未設定の行に使用）
'{{会社名}}\n' +
'{{名前}} 様\n' +
'\n' +
'お世話になります。手間いらず株式会社の徳原です。\n' +
'{{挨拶日}}は訪問させていただき、誠にありがとうございました。\n' +
'直接お話を伺うことができ、大変参考になりました。\n' +
'ご不明な点やご興味がございましたら、改めてオンライン等でご説明の機会をいただけますと幸いです。\n' +
'\n' +
'今後ともどうぞよろしくお願いいたします。\n' +
'\n' +
'{{署名}}';

/** 区分の値からテンプレを選びます。 */
function pickTemplate_(kubun) {
  var k = String(kubun || '').trim();
  if (k === '新規') return { name: '新規', body: TPL_SHINKI };
  if (k === '既存') return { name: '既存', body: TPL_KISON };
  if (k === 'お礼のみ') return { name: 'お礼のみ', body: TPL_OREINOMI };
  if (k === '') return { name: '汎用', body: TPL_GENERIC };
  return { name: '汎用（区分「' + k + '」は未定義）', body: TPL_GENERIC };
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
    .createMenu('お礼メール')
    .addItem('① プレビュー（下書きは作らない）', 'previewDrafts')
    .addItem('② Gmail下書きを作成', 'createDrafts')
    .addSeparator()
    .addItem('③ 作業列を準備（区分/挨拶/除外のプルダウン）', 'setupWorkColumns')
    .addToUi();
}

// ===== 作業列の準備 ==============================================
function setupWorkColumns() {
  var sheet = getSheet_();
  var lastRow = Math.max(sheet.getLastRow(), CONFIG.DATA_START_ROW);
  var defs = [
    { col: CONFIG.COLS.TEMPLATE, title: '区分',  list: ['新規', '既存', 'お礼のみ'] },
    { col: CONFIG.COLS.GREETING, title: '挨拶',  list: ['昨日', '先日'] },
    { col: CONFIG.COLS.EXCLUDE,  title: '除外',  list: ['除外'] }
  ];
  defs.forEach(function (d) {
    var c = colIndex_(d.col) + 1; // 1始まり
    sheet.getRange(1, c).setValue(d.title).setFontWeight('bold');
    var rule = SpreadsheetApp.newDataValidation()
      .requireValueInList(d.list, true)
      .setAllowInvalid(true)
      .build();
    sheet.getRange(CONFIG.DATA_START_ROW, c, lastRow - CONFIG.DATA_START_ROW + 1, 1)
      .setDataValidation(rule);
  });
  SpreadsheetApp.getUi().alert(
    '作業列を準備しました。\n' +
    CONFIG.COLS.TEMPLATE + '列「区分」: 新規／既存／お礼のみ（空欄=汎用）\n' +
    CONFIG.COLS.GREETING + '列「挨拶」: 昨日／先日（空欄=名刺交換日から自動判定）\n' +
    CONFIG.COLS.EXCLUDE + '列「除外」: 除外 と入れた行は対象外'
  );
}

// ===== メイン処理 =================================================
function previewDrafts() { run_(true); }
function createDrafts() { run_(false); }

function run_(previewOnly) {
  var rows = readContacts_();
  var targets = [];
  var skippedNoMail = [];
  var excluded = [];

  rows.forEach(function (r) {
    if (r.excluded) { excluded.push(r); }
    else if (!r.email) { skippedNoMail.push(r); }
    else { targets.push(r); }
  });

  // グループ別（挨拶×テンプレ）の件数
  var groups = {};
  targets.forEach(function (r) {
    var key = '【' + r.greeting + '・' + r.template.name + '】';
    groups[key] = (groups[key] || 0) + 1;
  });

  var log = [];
  log.push('=== ' + (previewOnly ? 'プレビュー' : '下書き作成') + ' ===');
  log.push('対象: ' + targets.length + ' 件 ／ メールなしスキップ: ' + skippedNoMail.length + ' 件 ／ 除外指定: ' + excluded.length + ' 件');
  log.push('差出人: ' + CONFIG.SENDER.FULL_NAME + ' ／ CC: ' + CONFIG.CC);
  log.push('件名: ' + CONFIG.SUBJECT);
  log.push('');
  Object.keys(groups).forEach(function (k) { log.push(k + ' ' + groups[k] + '件'); });
  log.push('');

  var created = 0;
  targets.forEach(function (r, i) {
    var body = renderBody_(r);
    var warn = [];
    if (!r.company) warn.push('⚠会社名空欄');
    if (r.greetingSource === '自動(日付なし)') warn.push('⚠名刺交換日なし→先日扱い');
    log.push(
      '[' + (i + 1) + '] To: ' + r.email +
      ' ／ ' + (r.company || '(会社名なし)') +
      ' ／ ' + r.name +
      ' ／ ' + r.template.name +
      ' ／ ' + r.greeting + '(' + r.greetingSource + ')' +
      (warn.length ? ' ' + warn.join(' ') : '')
    );
    if (!previewOnly) {
      GmailApp.createDraft(r.email, CONFIG.SUBJECT, body, { cc: CONFIG.CC });
      created++;
    }
  });

  if (skippedNoMail.length) {
    log.push('');
    log.push('--- スキップ（メールアドレス空欄） ---');
    skippedNoMail.forEach(function (r) {
      log.push('行' + r.rowNumber + ': ' + (r.company || '(会社名なし)') + ' ／ ' + (r.name || '(氏名なし)'));
    });
  }
  if (excluded.length) {
    log.push('');
    log.push('--- 除外指定 ---');
    excluded.forEach(function (r) {
      log.push('行' + r.rowNumber + ': ' + (r.company || '(会社名なし)') + ' ／ ' + (r.name || '(氏名なし)'));
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
  return r.template.body
    .replace('{{会社名}}', r.company)
    .replace('{{名前}}', r.name)
    .replace('{{挨拶日}}', r.greeting)
    .replace('{{署名}}', buildSignature_());
}

// ===== 挨拶（昨日／先日）の判定 ==================================

/** 名刺交換日セルの値を Date に変換します（Date型・'2026/08/03'形式に対応）。 */
function parseDate_(v) {
  if (v instanceof Date && !isNaN(v)) return v;
  var m = String(v || '').trim().match(/^(\d{4})[\/\-](\d{1,2})[\/\-](\d{1,2})$/);
  if (m) return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return null;
}

/**
 * 挨拶語を決めます。
 * 手動指定（昨日/先日）があれば最優先。なければ名刺交換日から自動判定：
 * 実行日の前日 → 昨日、それ以外（それ以前） → 先日。
 */
function decideGreeting_(manual, exchangeDateValue) {
  var m = String(manual || '').trim();
  if (m === '昨日' || m === '先日') return { greeting: m, source: '手動' };

  var d = parseDate_(exchangeDateValue);
  if (!d) return { greeting: '先日', source: '自動(日付なし)' };

  var today = new Date(); today.setHours(0, 0, 0, 0);
  var target = new Date(d); target.setHours(0, 0, 0, 0);
  var diffDays = Math.round((today - target) / 86400000);
  return { greeting: diffDays === 1 ? '昨日' : '先日', source: '自動' };
}

// ===== データ読み取り ============================================
function getSheet_() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = CONFIG.SHEET_NAME ? ss.getSheetByName(CONFIG.SHEET_NAME) : ss.getActiveSheet();
  if (!sheet) throw new Error('シートが見つかりません: ' + CONFIG.SHEET_NAME);
  return sheet;
}

function readContacts_() {
  var sheet = getSheet_();
  var lastRow = sheet.getLastRow();
  if (lastRow < CONFIG.DATA_START_ROW) return [];

  var C = CONFIG.COLS;
  var idx = {
    company:  colIndex_(C.COMPANY),
    last:     colIndex_(C.LAST),
    first:    colIndex_(C.FIRST),
    email:    colIndex_(C.EMAIL),
    date:     colIndex_(C.DATE),
    template: colIndex_(C.TEMPLATE),
    greeting: colIndex_(C.GREETING),
    exclude:  colIndex_(C.EXCLUDE)
  };
  var numCols = Math.max.apply(null, Object.keys(idx).map(function (k) { return idx[k]; })) + 1;
  var numRows = lastRow - CONFIG.DATA_START_ROW + 1;
  var values = sheet.getRange(CONFIG.DATA_START_ROW, 1, numRows, numCols).getValues();

  var contacts = [];
  values.forEach(function (row, i) {
    function get(k) {
      var v = row[idx[k]];
      return (v === null || v === undefined) ? '' : v;
    }
    var company = String(get('company')).trim();
    var last = String(get('last')).trim();
    var first = String(get('first')).trim();
    var email = String(get('email')).trim();
    var name = [last, first].filter(String).join(' ');

    // 会社名・氏名・メールがすべて空の行はデータ無しとみなしスキップ
    if (!company && !name && !email) return;

    var g = decideGreeting_(get('greeting'), get('date'));
    contacts.push({
      rowNumber: CONFIG.DATA_START_ROW + i,
      company: company,
      name: name,
      email: email,
      template: pickTemplate_(get('template')),
      greeting: g.greeting,
      greetingSource: g.source,
      excluded: String(get('exclude')).trim() !== ''
    });
  });

  return contacts;
}
