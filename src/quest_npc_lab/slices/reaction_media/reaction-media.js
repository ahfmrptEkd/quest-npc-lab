'use strict';

// The server selects the reaction. Raw model output never selects a portrait.
function createReactionMedia(media) {
  const node = document.createElement('figure');
  node.className = 'reaction-media';
  node.dataset.state = media.state;
  const frame = document.createElement('div');
  frame.className = 'portrait-frame';
  const image = document.createElement('img');
  image.src = media.image;
  image.alt = media.label;
  image.width = 272;
  image.height = 320;
  image.addEventListener('error', () => { image.hidden = true; });
  frame.append(image);
  const caption = document.createElement('figcaption');
  caption.textContent = media.label;
  node.append(frame, caption);
  let video = null;
  let failed = false;
  let motion = false;
  let disposed = false;
  function showStatic() {
    if (video) {
      video.pause();
      video.hidden = true;
    }
  }
  function fail() {
    failed = true;
    showStatic();
  }
  function setMotion(enabled) {
    motion = enabled;
    if (!enabled || !media.video || failed || disposed) {
      showStatic();
      return;
    }
    if (!video) {
      video = document.createElement('video');
      video.muted = true;
      video.loop = true;
      video.playsInline = true;
      video.hidden = true;
      video.setAttribute('aria-hidden', 'true');
      video.tabIndex = -1;
      video.addEventListener('error', fail);
      video.addEventListener('playing', () => {
        video.hidden = !motion || failed || disposed;
      });
      video.src = media.video;
      frame.append(video);
    }
    const playback = video.play();
    if (playback) playback.catch(fail);
  }
  return {
    node, setMotion,
    dispose() {
      disposed = true;
      showStatic();
      if (video) {
        video.removeAttribute('src');
        video.load();
      }
    },
  };
}
