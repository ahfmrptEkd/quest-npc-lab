// Browser APIs are the external seam; execute the actual renderer without a GPU.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {test} = require('node:test');

class BrowserElement extends EventTarget {
  constructor(tag) {
    super();
    this.tagName = tag;
    this.children = [];
    this.dataset = {};
    this.hidden = false;
    this.paused = true;
  }
  append(...nodes) { this.children.push(...nodes); }
  setAttribute(name, value) { this[name] = value; }
  removeAttribute(name) { delete this[name]; }
  pause() { this.paused = true; }
  load() {}
  play() {
    if (this.rejectPlayback) return Promise.reject(new Error('Playback denied'));
    this.paused = false;
    this.dispatchEvent(new Event('playing'));
    return Promise.resolve();
  }
}
const context = vm.createContext({
  document: {createElement: tag => new BrowserElement(tag)},
});
vm.runInContext(fs.readFileSync(__dirname + '/reaction-media.js', 'utf8'), context);
const media = {
  state: 'firm', label: 'Guild receptionist: firm',
  image: '/media/firm.svg', video: '/media/firm.mp4',
};
function portrait(data = media) { return context.createReactionMedia(data); }

test('absent video and stopped motion retain an accessible static portrait', () => {
  for (const data of [media, {...media, video: null}]) {
    const view = portrait(data);
    view.setMotion(false);
    const [frame, caption] = view.node.children;
    assert.equal(frame.children.length, 1);
    assert.equal(frame.children[0].src, '/media/firm.svg');
    assert.equal(frame.children[0].alt, media.label);
    assert.equal(caption.textContent, media.label);
    assert.equal(frame.children[0].hidden, false);
  }
});

test('motion can start, stop and resume; disposal stops detached playback', () => {
  const view = portrait();
  view.setMotion(true);
  const [image, video] = view.node.children[0].children;
  assert.equal(video.hidden, false);
  assert.equal(video.paused, false);
  view.setMotion(false);
  assert.equal(video.hidden, true);
  assert.equal(video.paused, true);
  assert.equal(image.hidden, false);
  view.setMotion(true);
  assert.equal(video.hidden, false);
  view.dispose();
  assert.equal(video.paused, true);
  view.setMotion(true);
  assert.equal(video.hidden, true);
});

test('video load errors and rejected playback fall back to the portrait', async () => {
  for (const failure of ['error', 'reject']) {
    const view = portrait();
    view.setMotion(true);
    const [image, video] = view.node.children[0].children;
    if (failure === 'error') video.dispatchEvent(new Event('error'));
    else {
      view.setMotion(false);
      video.rejectPlayback = true;
      view.setMotion(true);
      await new Promise(resolve => setImmediate(resolve));
    }
    assert.equal(video.hidden, true);
    assert.equal(video.paused, true);
    assert.equal(image.hidden, false);
    view.setMotion(true);
    assert.equal(video.hidden, true);
  }
});

test('image failure retains a readable caption', () => {
  const view = portrait({...media, video: null});
  const [frame, caption] = view.node.children;
  frame.children[0].dispatchEvent(new Event('error'));
  assert.equal(frame.children[0].hidden, true);
  assert.equal(caption.textContent, media.label);
  assert.equal(caption.hidden, false);
});
