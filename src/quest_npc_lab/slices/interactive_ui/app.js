'use strict';

const form = document.querySelector('#comparison');
const controls = document.querySelector('#controls');
const results = document.querySelector('#results');
const errorBox = document.querySelector('#error');
const progress = document.querySelector('#progress');
const utterance = document.querySelector('#utterance');
let busy = false;
const mediaViews = [];
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const pauseMedia = document.querySelector("#pause-media");
function syncMotion() {
  for (const view of mediaViews) view.setMotion(!reducedMotion.matches && !pauseMedia.checked);
}
reducedMotion.addEventListener("change", syncMotion);
pauseMedia.addEventListener("change", syncMotion);

function element(tag, text, className) {
  const node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  return node;
}

function showError(message) {
  errorBox.textContent = `입력 또는 요청 오류: ${message}`;
  errorBox.hidden = false;
  errorBox.focus();
}

function setBusy(value) {
  busy = value;
  controls.disabled = value;
  for (const button of results.querySelectorAll('button')) button.disabled = value;
  results.setAttribute('aria-busy', String(value));
}

async function request(path, body) {
  const response = await fetch(path, body === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

function render(data) {
  document.querySelector('#mode').textContent = data.mode === 'offline'
    ? 'OFFLINE / 결정적 테스트 대역 · 실제 모델 추론이 아닙니다. 기반 조건만 테스트 응답을 표시합니다.'
    : 'LIVE / 로컬 모델 추론 · 첫 요청은 모델 로딩으로 시간이 걸릴 수 있습니다.';
  for (const view of mediaViews) view.dispose();
  mediaViews.length = 0;
  results.replaceChildren();
  for (const condition of data.conditions) {
    const card = element('article', '', 'condition');
    card.append(element('h3', condition.label));
    const portrait = createReactionMedia(condition.reaction);
    mediaViews.push(portrait);
    card.append(portrait.node);
    card.append(element('p', condition.evaluation_label, 'unrated'));
    const ready = condition.status === 'ready';
    card.append(element('p', ready ? '실행 가능' : '미준비 / Checkpoint not ready', 'availability'));
    const model = condition.model;
    const details = element('details', '');
    details.append(element('summary', '모델 · 프롬프트 · 생성 설정'));
    details.append(element('pre', JSON.stringify(model, null, 2)));
    card.append(details);
    const artifact = condition.artifact;
    if (artifact) {
      card.append(element('h4', '모델 원시 출력'));
      card.append(element('pre', artifact.raw_output ?? '(출력 없음)', 'raw'));
      card.append(element('h4', '파싱된 행동 · 대사'));
      card.append(element('p', artifact.parsed_output?.action ?? '파싱 결과 없음', 'action'));
      card.append(element('p', artifact.parsed_output?.dialogue ?? '—'));
      if (artifact.error) {
        card.append(element('p', `${artifact.error.stage}: ${artifact.error.reason}`, 'failure'));
      }
      const execution = artifact.server_execution;
      card.append(element('h4', '서버 처리'));
      card.append(element('p', `${execution.approved ? '승인 / Approved' : '차단 / Blocked'} · ${execution.state_changed ? '상태 변경' : '상태 유지'}`));
    } else {
      card.append(element('p', ready ? '아직 실행하지 않았습니다.' : '준비된 학습 체크포인트가 없습니다. 대체 출력을 생성하지 않습니다.'));
    }
    card.append(element('h4', '현재 서버 상태'));
    card.append(element('pre', JSON.stringify(condition.state, null, 2), 'state'));
    if (ready) {
      const button = element('button', '이 상태로 다음 턴');
      button.type = 'button';
      button.setAttribute('aria-label', `${condition.label}: 이 상태로 다음 턴`);
      button.addEventListener('click', () => {
        if (!utterance.reportValidity()) return;
        run('/api/turn', {condition: condition.id, utterance: utterance.value});
      });
      card.append(button);
    }
    results.append(card);
  }
  syncMotion();
}

async function run(path, payload) {
  if (busy) return;
  errorBox.hidden = true;
  setBusy(true);
  progress.textContent = '요청 처리 중… 모델 로딩과 추론을 기다려 주세요. 자동 재시도는 하지 않습니다.';
  try {
    render(await request(path, payload));
    progress.textContent = '완료. 조건별 원시 출력과 서버 처리를 확인하세요.';
  } catch (error) {
    showError(error.message);
    progress.textContent = '요청 실패. 이전 결과를 유지합니다. 연결이 끊겼다면 새로고침으로 서버 상태를 확인하세요.';
  } finally {
    setBusy(false);
  }
}

form.addEventListener('submit', (event) => {
  event.preventDefault();
  const target = Number(document.querySelector('#target-count').value);
  const current = Number(document.querySelector('#current-count').value);
  const claimed = document.querySelector('#reward-claimed').checked;
  if (!Number.isSafeInteger(target) || !Number.isSafeInteger(current)) {
    showError('목표 수와 현재 수는 안전하게 표현 가능한 정수여야 합니다.');
    return;
  }
  if (claimed && current < target) {
    showError('목표 미달 상태에서는 보상 수령 완료를 선택할 수 없습니다.');
    return;
  }
  run('/api/compare', {
    state: {
      quest_name: document.querySelector('#quest-name').value,
      target_count: target, current_count: current,
      reward_description: document.querySelector('#reward-description').value,
      reward_claimed: claimed,
    },
    utterance: utterance.value,
  });
});

request('/api/session').then(data => {
  render(data);
  controls.disabled = false;
}).catch(error => showError(`${error.message} · 페이지를 새로고침하세요.`));
