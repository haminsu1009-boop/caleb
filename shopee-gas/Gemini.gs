/**
 * Gemini 무료 API 호출
 *
 * - schema 를 주면 정해진 JSON 형식으로만 답하게 강제한다 (파싱 실패 방지).
 * - search: true 면 구글 검색 결과를 근거로 답한다 (수요 조사용).
 *   검색과 JSON 강제는 같이 쓸 수 없어서, 수요 조사는 "검색 → 정리" 두 번 호출한다.
 * - 무료 등급은 분당 호출 수 제한이 있어 429 가 오면 기다렸다 다시 시도한다.
 */
function gemini_(prompt, opts) {
  opts = opts || {};
  const model = settings_()['Gemini모델'] || 'gemini-2.5-flash';
  const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent`;
  const body = { contents: [{ role: 'user', parts: [{ text: prompt }] }] };
  if (opts.system) body.systemInstruction = { parts: [{ text: opts.system }] };
  if (opts.schema) body.generationConfig = { responseMimeType: 'application/json', responseSchema: opts.schema };
  if (opts.search) body.tools = [{ google_search: {} }];

  for (let attempt = 1; attempt <= 4; attempt++) {
    const res = UrlFetchApp.fetch(url, {
      method: 'post',
      contentType: 'application/json',
      headers: { 'x-goog-api-key': secret_('GEMINI_API_KEY') },
      payload: JSON.stringify(body),
      muteHttpExceptions: true,
    });
    const code = res.getResponseCode();
    if (code === 429 || code >= 500) {
      Utilities.sleep(15000 * attempt);
      continue;
    }
    const data = JSON.parse(res.getContentText());
    if (code !== 200) throw new Error(`Gemini ${code}: ${JSON.stringify(data.error || data).slice(0, 300)}`);
    const cand = (data.candidates || [])[0];
    if (!cand || !cand.content) throw new Error(`Gemini 응답 없음 (${cand ? cand.finishReason : 'blocked'})`);
    const text = cand.content.parts.map(p => p.text || '').join('');
    return opts.schema ? JSON.parse(text) : text;
  }
  throw new Error('Gemini 호출 한도 초과 — 잠시 후 다시 실행됩니다');
}
