"use strict";
const labels = {base_minimal: "Base · Minimal", base_improved: "Base · Improved", sft_improved: "SFT · Improved", grpo_improved: "SFT+GRPO · Improved"};
const $ = id => document.getElementById(id);
function node(tag, text, className) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (className) el.className = className;
  return el;
}
function cells(parent, values) {
  const row = node("tr");
  values.forEach(value => row.append(node("td", value)));
  parent.append(row);
}
function field(parent, label, value) { parent.append(node("dt", label), node("dd", value)); }
function details(parent, label, value) {
  const el = node("details");
  el.append(node("summary", label), node("pre", typeof value === "string" ? value : JSON.stringify(value, null, 2)));
  parent.append(el);
}
async function start() {
  const response = await fetch("results.json");
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const data = await response.json();
  for (const key of data.conditions) {
    const m = data.report.conditions[key];
    cells($("metrics"), [labels[key], `${m.correct} / ${m.count}`, `${(m.accuracy * 100).toFixed(1)}%`, `${m.format_errors} / ${m.count}`]);
    const option = node("option", labels[key]); option.value = key;
    $("analysis-condition").append(option);
  }
  $("delta").textContent = `SFT → GRPO: +${data.report.deltas.grpo.percentage_point_delta.toFixed(1)}%p (${data.report.conditions.grpo_improved.correct - data.report.conditions.sft_improved.correct}개 추가 정답).`;
  data.report.provenance.provenance_warnings.forEach(text => $("warnings").append(node("p", text)));
  for (const action of [...new Set(data.cases.map(c => c.expected))]) {
    const option = node("option", action); option.value = action; $("action").append(option);
  }
  let filtered = data.cases;
  function render() {
    const index = $("case").selectedIndex;
    const c = filtered[index];
    $("status").textContent = `${index + 1} / ${filtered.length} 사례 · ${c.id} · 저장된 실제 출력`;
    $("previous").disabled = index === 0; $("next").disabled = index === filtered.length - 1;
    $("input").replaceChildren(node("blockquote", c.utterance));
    const state = node("dl");
    field(state, "같은 시작 서버 상태", `${c.state.quest_name} · 처치 ${c.state.current_count} / ${c.state.target_count} · ${c.state.reward_description} · 수령 ${c.state.reward_claimed ? "완료" : "전"}`);
    field(state, "정답 행동 / 패턴", `${c.expected} / ${c.tags.join(", ")}`); $("input").append(state);
    $("comparison").replaceChildren();
    for (const key of data.conditions) {
      const {artifact: a, reaction: r} = c.responses[key];
      const card = node("article"); card.append(node("h3", labels[key]));
      const portrait = node("img"); portrait.src = r.image; portrait.alt = r.label; portrait.width = 240; portrait.height = 190;
      card.append(portrait, node("p", a.evaluation.is_action_correct ? "행동 정답" : "행동 오답", a.evaluation.is_action_correct ? "correct" : "incorrect"));
      const fields = node("dl");
      field(fields, "모델의 원래 행동", a.model_action || "파싱 불가");
      field(fields, "대사", a.parsed_output?.dialogue || "형식 오류로 대사 평가 불가");
      field(fields, "서버 처리", `${a.server_execution.approved ? "승인" : "미승인"} · 상태 ${a.server_execution.state_changed ? "변경" : "유지"}`);
      field(fields, "형식", a.evaluation.is_format_valid ? "유효" : "오류");
      if (a.error) field(fields, "오류 사유", a.error.reason);
      card.append(fields); details(card, "원시 응답 그대로 보기", a.raw_output);
      details(card, "최종 서버 상태", a.server_execution.final_state);
      $("comparison").append(card);
    }
  }
  function filter() {
    filtered = data.cases.filter(c => !$("action").value || c.expected === $("action").value);
    $("case").replaceChildren();
    filtered.forEach(c => { const option = node("option", `${c.id} · ${c.expected}`); option.value = c.id; $("case").append(option); });
    render();
  }
  $("action").addEventListener("change", filter); $("case").addEventListener("change", render);
  $("previous").addEventListener("click", () => { $("case").selectedIndex -= 1; render(); });
  $("next").addEventListener("click", () => { $("case").selectedIndex += 1; render(); });
  function analysis() {
    $("patterns").replaceChildren();
    Object.entries(data.report.conditions[$("analysis-condition").value].by_shortcut).forEach(([tag, m]) => cells($("patterns"), [tag, `${m.correct} / ${m.count}`, m.format_errors]));
  }
  $("analysis-condition").addEventListener("change", analysis);
  for (const [title, path] of Object.entries(data.links || {"원본 응답 240개": "artifacts/final_240_responses.jsonl", "전체 평가 보고서": "artifacts/final_evaluation_report.json"})) {
    const item = node("li"); const link = node("a", title); link.href = path; item.append(link); $("artifact-links").append(item);
  }
  filter(); analysis();
}
start().catch(error => { $("status").textContent = `결과를 불러오지 못했습니다: ${error.message}. 아래 원본 자료를 확인하세요.`; });
