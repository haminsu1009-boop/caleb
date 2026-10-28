// Apps Script 코드를 Node 에서 검사하는 테스트: node shopee-gas/tests/run_tests.js
// Apps Script 전용 객체(Utilities 등)는 최소한의 가짜(shim)로 대신한다.
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const crypto = require('crypto');
const assert = require('assert');

const dir = path.join(__dirname, '..');
const sandbox = {
  console,
  Utilities: {
    // Apps Script 는 -128~127 범위의 바이트 배열을 돌려준다 → 그 동작까지 흉내 냄
    computeHmacSha256Signature: (value, key) =>
      Array.from(crypto.createHmac('sha256', key).update(value).digest()).map(b => (b > 127 ? b - 256 : b)),
  },
};
vm.createContext(sandbox);
fs.readdirSync(dir).filter(f => f.endsWith('.gs')).sort().forEach(f => {
  vm.runInContext(fs.readFileSync(path.join(dir, f), 'utf8'), sandbox, { filename: f });
});
const g = (code) => vm.runInContext(code, sandbox);

const market = {
  code: 'SG', currency: 'SGD', priceStep: 0.1, commission: 0.10, transactionFee: 0.03,
  serviceFee: 0, shipBase: 3000, shipPer100g: 700,
};
const pricing = { marginRate: 0.2, minProfitKrw: 3000, fxBufferRate: 0 };
sandbox.__m = market; sandbox.__p = pricing;

const tests = {
  '배송비는 100g 단위 올림': () => {
    assert.strictEqual(g('shippingKrw_(__m, 100)'), 3700);
    assert.strictEqual(g('shippingKrw_(__m, 101)'), 4400);
  },
  '가격 단위 올림': () => {
    assert.strictEqual(g('roundUp_(12.31, 0.1)'), 12.4);
    assert.strictEqual(g('roundUp_(12.3, 0.1)'), 12.3);
    assert.strictEqual(g('roundUp_(25001, 1000)'), 26000);
  },
  '목표 마진율 달성': () => {
    const r = g('calcPrice_(__m, __p, 1000, 10000, 0, 300)');
    assert.strictEqual(r.costKrw, 15100);
    assert.strictEqual(r.price, 22.6); // 15.1 / (1 - 0.13 - 0.2) = 22.54 → 22.6
    assert.ok(r.marginRate >= 0.2);
  },
  '싼 상품은 최소 이익 보장': () => {
    const r = g('calcPrice_(__m, __p, 1000, 1000, 0, 50)');
    assert.ok(r.profitKrw >= 3000, r.profitKrw);
  },
  '수수료+마진 100% 이상이면 오류': () => {
    assert.throws(() => g('calcPrice_(__m, {marginRate: 0.9, minProfitKrw: 0, fxBufferRate: 0}, 1000, 1000, 0, 10)'));
  },
  '기본 국가 설정 전부 정상 계산': () => {
    g('DEFAULT_MARKETS').forEach(row => {
      const m = { code: row[0], currency: row[2], priceStep: row[4], commission: row[5], transactionFee: row[6],
        serviceFee: row[7], shipBase: row[8], shipPer100g: row[9] };
      sandbox.__x = m;
      const r = g(`calcPrice_(__x, {marginRate: 0.2, minProfitKrw: 3000, fxBufferRate: 0.03}, ${row[10]}, 9800, 0, 320)`);
      assert.ok(r.profitKrw >= 2900, `${row[0]} ${r.profitKrw}`);
    });
  },
  '쇼피 서명 = HMAC-SHA256 hex': () => {
    const expected = crypto.createHmac('sha256', 'key').update('123/api/v2/x1700000000tok456').digest('hex');
    assert.strictEqual(g("shopeeSign_('key', [123, '/api/v2/x', 1700000000, 'tok', 456])"), expected);
  },
  '도매꾹 응답에서 상품 배열 찾기': () => {
    sandbox.__d = { domeggook: { header: {}, list: { item: [{ no: 1, title: 'a', price: '1,000' }] } } };
    assert.strictEqual(g('findItemArray_(__d)').length, 1);
  },
  '시트 헤더에 주문·상품 핵심 열 포함': () => {
    const h = g('sheetHeaders_()');
    ['SKU', '상태', '원가(원)', '소싱URL', 'AI결과'].forEach(k => assert.ok(h['상품'].includes(k), k));
    ['주문번호', '발주상태', '발송기한'].forEach(k => assert.ok(h['주문'].includes(k), k));
  },
  '요약 시트 수식의 열 문자가 실제 헤더 위치와 일치': () => {
    const h = g('sheetHeaders_()');
    const col = (sheet, name) => String.fromCharCode(65 + h[sheet].indexOf(name));
    assert.strictEqual(col('상품', '등록일'), 'R');
    assert.strictEqual(col('상품', '상태'), 'B');
    assert.strictEqual(col('주문', '주문시각'), 'C');
    assert.strictEqual(col('주문', '발주상태'), 'K');
    assert.strictEqual(col('채팅', '처리'), 'J');
    assert.strictEqual(col('채팅', '시각'), 'A');
  },
  '실행 버튼은 모두 실제 함수를 가리킴': () => {
    Object.values(g('RUN_BUTTONS')).forEach(fn => assert.strictEqual(typeof sandbox[fn], 'function', fn));
  },
  '큐텐 상세페이지 HTML: 이스케이프 + 발송일 + 이미지': () => {
    const html = g(`qoo10DetailHtml_({description: 'a<b>\\n줄', highlights: ['保湿']}, ['https://x/1.jpg'], 3)`);
    assert.ok(html.includes('a&lt;b&gt;<br>줄'), html);
    assert.ok(html.includes('通常3営業日'));
    assert.ok(html.includes('<img src="https://x/1.jpg"'));
    assert.ok(html.includes('<li style="margin:6px 0">保湿</li>'));
  },
  '시장가보다 많이 싸면 자동 인상하고 이익 재계산': () => {
    sandbox.__jp = { code: 'JP', currency: 'JPY', priceStep: 10, commission: 0.10, transactionFee: 0, serviceFee: 0, shipBase: 4000, shipPer100g: 500 };
    sandbox.__p0 = g('calcPrice_(__jp, {marginRate: 0.2, minProfitKrw: 3000, fxBufferRate: 0}, 9.3, 9800, 0, 320)');
    const before = sandbox.__p0.profitKrw;
    const v = g('judgePrice_(__jp, __p0, __p0.price * 2, __p0.price * 3, true)');
    assert.ok(v.startsWith('쌈→인상'), v);
    assert.ok(sandbox.__p0.profitKrw > before);
    assert.strictEqual(sandbox.__p0.price % 10, 0);
  },
  '시장가보다 많이 비싸면 비쌈 표시, 가격은 그대로': () => {
    sandbox.__p1 = g('calcPrice_(__jp, {marginRate: 0.2, minProfitKrw: 3000, fxBufferRate: 0}, 9.3, 9800, 0, 320)');
    const price = sandbox.__p1.price;
    assert.ok(g('judgePrice_(__jp, __p1, 100, 200, true)').startsWith('비쌈'));
    assert.strictEqual(sandbox.__p1.price, price);
  },
  '큐텐 날짜 파싱 실패해도 null': () => {
    assert.strictEqual(g("toDate_('잘못된날짜')"), null);
    assert.ok(g("toDate_('2026-10-28 10:00:00').getTime()") > 0);
  },
};

let failed = 0;
for (const [name, fn] of Object.entries(tests)) {
  try { fn(); console.log('✓', name); } catch (e) { failed++; console.log('✗', name, '-', e.message); }
}
console.log(failed ? `\n${failed}개 실패` : `\n전체 ${Object.keys(tests).length}개 통과`);
process.exit(failed ? 1 : 0);
